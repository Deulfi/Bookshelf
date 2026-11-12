"""The book library: importing, listing, searching, editing and deleting books."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePath
from typing import BinaryIO

from sqlalchemy import Select, and_, case, func, select
from sqlalchemy.orm import Session, aliased

from ..db import utcnow
from ..formats import detect_format
from ..models import Book, ReadingProgress, User
from ..storage import Storage
from . import covers
from .hashing import filename_md5, partial_md5
from .metadata import extract_metadata

STATUSES = ("all", "reading", "unread", "finished")
SORTS = ("recent", "title", "author", "last_read")
FINISHED_THRESHOLD = 0.98
CONTINUE_READING_LIMIT = 8
_COPY_CHUNK = 1024 * 1024
# Files modified more recently than this are still being written (sync tools, copies).
SETTLE_SECONDS = 10


class LibraryError(Exception):
    """An import/edit error with a user-facing message."""


class DuplicateBookError(LibraryError):
    def __init__(self, book: Book) -> None:
        super().__init__(f"Already in your library as “{book.title}”.")
        self.book = book


@dataclass(frozen=True)
class BookEntry:
    """A book together with its (optional) KOReader reading progress."""

    book: Book
    progress: ReadingProgress | None = None

    @property
    def percent(self) -> int:
        return round(self.progress.percentage * 100) if self.progress else 0

    @property
    def status(self) -> str:
        if self.progress is None or self.progress.percentage <= 0:
            return "unread"
        return "finished" if self.progress.percentage >= FINISHED_THRESHOLD else "reading"

    @property
    def last_read(self) -> datetime | None:
        if self.progress is None:
            return None
        return datetime.fromtimestamp(self.progress.timestamp, UTC).replace(tzinfo=None)


# --- Import -----------------------------------------------------------------------------------


def import_book(
    db: Session,
    storage: Storage,
    user: User,
    filename: str,
    source: BinaryIO,
    *,
    max_bytes: int,
) -> Book:
    filename = PurePath(filename.replace("\\", "/")).name[:500] or "upload"
    fmt = detect_format(filename)
    if fmt is None:
        raise LibraryError(f"Unsupported file type: {filename}")

    temp_path = storage.new_temp_path()
    stored_path: str | None = None
    try:
        size = _copy_limited(source, temp_path, max_bytes)
        if size == 0:
            raise LibraryError("The file is empty.")

        document_hash = partial_md5(temp_path)
        existing = db.scalar(
            select(Book).where(Book.user_id == user.id, Book.partial_md5 == document_hash)
        )
        if existing is not None:
            raise DuplicateBookError(existing)

        metadata = extract_metadata(temp_path, fmt, filename)
        root = storage.library_root(user.id)
        relative = storage.schema_relative_path(
            metadata.author, metadata.series, metadata.title or PurePath(filename).stem, fmt
        )
        stored_path = storage.store_book(temp_path, root, relative)
        book = Book(
            user_id=user.id,
            title=metadata.title or filename,
            author=metadata.author,
            series=metadata.series,
            series_index=metadata.series_index,
            description=metadata.description,
            language=metadata.language,
            publisher=metadata.publisher,
            format=fmt,
            original_filename=filename,
            file_path=stored_path,
            file_size=size,
            partial_md5=document_hash,
            filename_md5=filename_md5(filename),
        )
        db.add(book)
        db.flush()  # assigns book.id for the cover file name
        if metadata.cover:
            book.has_cover = covers.save_cover(metadata.cover, storage.cover_path(book.id))
        db.commit()
        return book
    except BaseException:
        db.rollback()
        if stored_path is not None:
            (storage.library_root(user.id) / stored_path).unlink(missing_ok=True)
        raise
    finally:
        temp_path.unlink(missing_ok=True)


def _duplicate_scope(storage: Storage, user: User) -> Select:
    """Books a scanned file is compared with. The shared ingest folder holds every user's
    uploads, so there any user's copy counts; a per-user folder only knows its owner's books."""
    statement = select(Book)
    if storage.ingest_dir is None:
        statement = statement.where(Book.user_id == user.id)
    return statement


def import_from_disk(db: Session, storage: Storage, user: User, path: Path) -> Book:
    """Register a book file that already lives in the user's library folder (no copy)."""
    root = storage.library_root(user.id)
    fmt = detect_format(path.name)
    if fmt is None:
        raise LibraryError(f"Unsupported file type: {path.name}")
    relative = path.relative_to(root).as_posix()

    document_hash = partial_md5(path)
    existing = db.scalar(
        _duplicate_scope(storage, user).where(Book.partial_md5 == document_hash).limit(1)
    )
    if existing is not None:
        if existing.file_path != relative and storage.find_book_file(existing) is None:
            # The file was moved or renamed outside Bookshelf: follow it instead of leaving
            # a broken entry behind.
            existing.file_path = relative
            db.commit()
        raise DuplicateBookError(existing)

    metadata = extract_metadata(path, fmt, path.name)
    book = Book(
        user_id=user.id,
        title=metadata.title or path.name,
        author=metadata.author,
        series=metadata.series,
        series_index=metadata.series_index,
        description=metadata.description,
        language=metadata.language,
        publisher=metadata.publisher,
        format=fmt,
        original_filename=path.name,
        file_path=relative,
        file_size=path.stat().st_size,
        partial_md5=document_hash,
        filename_md5=filename_md5(path.name),
    )
    db.add(book)
    db.flush()
    if metadata.cover:
        book.has_cover = covers.save_cover(metadata.cover, storage.cover_path(book.id))
    db.commit()
    return book


def sync_library(
    db: Session, storage: Storage, user: User, log: Callable[[str], None] | None = None
) -> int:
    """Scan ``user``'s library folder: register new book files in place, move books with
    legacy random file names to Author/Series/Title, and drop entries whose file is gone."""
    root = storage.library_root(user.id)
    shared = storage.ingest_dir is not None
    if shared and not root.is_dir():
        return 0  # the shared folder is not mounted: never touch the database then
    root.mkdir(parents=True, exist_ok=True)
    reorganize_legacy_files(db, storage, user, log=log)
    known_paths = set(db.scalars(_duplicate_scope(storage, user).with_only_columns(Book.file_path)))
    imported = 0
    seen_files = 0
    now = time.time()
    for path in storage.library_files(root):
        if detect_format(path.name) is None:
            continue
        seen_files += 1
        relative = path.relative_to(root).as_posix()
        if relative in known_paths:
            continue
        try:
            if now - path.stat().st_mtime < SETTLE_SECONDS:
                continue  # still being written; picked up on the next scan
            book = import_from_disk(db, storage, user, path)
        except DuplicateBookError:
            continue
        except (LibraryError, OSError) as error:
            db.rollback()
            if log:
                log(f"skipped {relative}: {error}")
            continue
        imported += 1
        known_paths.add(relative)
        if log:
            log(f"imported {relative} as #{book.id}")
    # An empty shared folder usually means an unmounted share, not a deleted library: never
    # prune then. A per-user folder lives in the data dir, so an empty one really is empty.
    if seen_files or not shared:
        prune_missing(db, storage, log=log, user=None if shared else user)
    return imported


_LEGACY_NAME = re.compile(r"^[0-9a-f]{32}$")


def reorganize_legacy_files(
    db: Session, storage: Storage, user: User, log: Callable[[str], None] | None = None
) -> int:
    """Move uploads stored under random names (older versions) to Author/Series/Title.ext."""
    moved = 0
    # Legacy files sit directly in the library root, so only path-less entries are candidates.
    candidates = select(Book).where(Book.user_id == user.id, ~Book.file_path.contains("/"))
    for book in db.scalars(candidates).all():
        path = PurePath(book.file_path)
        if len(path.parts) != 1 or not _LEGACY_NAME.match(path.stem):
            continue
        wanted = storage.schema_relative_path(book.author, book.series, book.title, book.format)
        final = storage.move_book(book, wanted)
        if final is None:
            continue  # file missing: prune_missing deals with it
        book.file_path = final
        db.commit()
        moved += 1
        if log:
            log(f"renamed #{book.id} to {final}")
    return moved


def prune_missing(
    db: Session,
    storage: Storage,
    log: Callable[[str], None] | None = None,
    user: User | None = None,
) -> int:
    """Delete database entries (and covers) whose book file no longer exists on disk;
    only ``user``'s books when given."""
    shared = storage.ingest_dir
    if user is None and shared is not None and not _has_books(storage, shared):
        return 0  # library folder missing or empty: could be an unmounted share
    # Libraries can be large: stream only the columns needed to find the file (plain rows, no
    # ORM objects), then delete the few missing entries by id.
    statement = select(Book.id, Book.user_id, Book.title, Book.file_path)
    if user is not None:
        statement = statement.where(Book.user_id == user.id)
    missing: list[int] = []
    for row in db.execute(statement.execution_options(yield_per=500)):
        if storage.is_ignored(row.file_path):  # e.g. imported before .stfolder was skipped
            if log:
                log(f"removed #{row.id} “{row.title}”: ignored folder ({row.file_path})")
            missing.append(row.id)
        elif storage.find_book_file(row) is None:  # only reads user_id and file_path
            if log:
                log(f"removed #{row.id} “{row.title}”: file is gone ({row.file_path})")
            missing.append(row.id)
    removed = 0
    for book_id in missing:
        book = db.get(Book, book_id)
        if book is None:
            continue
        storage.cover_path(book.id).unlink(missing_ok=True)
        db.delete(book)
        removed += 1
    if removed:
        db.commit()
    storage.remove_orphan_covers(db)
    return removed


def _has_books(storage: Storage, folder: Path) -> bool:
    if not folder.is_dir():
        return False
    return any(detect_format(p.name) is not None for p in storage.library_files(folder))


def _copy_limited(source: BinaryIO, target: Path, max_bytes: int) -> int:
    size = 0
    with target.open("wb") as out:
        while chunk := source.read(_COPY_CHUNK):
            size += len(chunk)
            if size > max_bytes:
                raise LibraryError(f"File is larger than {max_bytes // (1024 * 1024)} MB.")
            out.write(chunk)
    return size


# --- Queries ----------------------------------------------------------------------------------
#
# All filtering, sorting and paging happens in SQL, so the cost of a page stays constant no
# matter how large the library is. KOReader may report progress under the content hash or the
# file name hash of a book, so both are joined and the most recent record wins.

_by_hash = aliased(ReadingProgress, name="progress_by_hash")
_by_name = aliased(ReadingProgress, name="progress_by_name")
_name_is_newer = _by_name.timestamp > func.coalesce(_by_hash.timestamp, -1)
_percentage = case((_name_is_newer, _by_name.percentage), else_=_by_hash.percentage)
_last_read = case((_name_is_newer, _by_name.timestamp), else_=_by_hash.timestamp)
_status = case(
    (func.coalesce(_percentage, 0) <= 0, "unread"),
    (_percentage >= FINISHED_THRESHOLD, "finished"),
    else_="reading",
)
_search_text = func.casefold(
    Book.title + " " + func.coalesce(Book.author, "") + " " + func.coalesce(Book.series, "")
)
_ORDER_BY = {
    "recent": (Book.created_at.desc(), Book.id.desc()),
    "title": (func.casefold(Book.title), Book.id),
    "author": (
        Book.author_sort.is_(None),
        Book.author_sort,
        func.casefold(func.coalesce(Book.series, "")),
        func.coalesce(Book.series_index, 0),
        func.casefold(Book.title),
        Book.id,
    ),
    "last_read": (_last_read.desc().nulls_last(), Book.created_at.desc(), Book.id.desc()),
    # Most recently marked first: KOReader's OPDS sync expects the newest entry at the top.
    "device": (Book.device_sync_at.desc().nulls_last(), Book.id.desc()),
}


@dataclass(frozen=True)
class BookPage:
    entries: list[BookEntry]
    has_more: bool


def _scoped(statement: Select, user: User, text: str = "") -> Select:
    """Join reading progress, restrict to ``user``'s books and apply the search ``text``."""
    statement = (
        statement.outerjoin(
            _by_hash, and_(_by_hash.user_id == Book.user_id, _by_hash.document == Book.partial_md5)
        )
        .outerjoin(
            _by_name, and_(_by_name.user_id == Book.user_id, _by_name.document == Book.filename_md5)
        )
        .where(Book.user_id == user.id)
    )
    for term in text.casefold().split():
        statement = statement.where(_search_text.contains(term, autoescape=True))
    return statement


def _entries(db: Session, statement: Select) -> list[BookEntry]:
    entries = []
    for book, by_hash, by_name in db.execute(statement):
        records = [record for record in (by_hash, by_name) if record is not None]
        latest = max(records, key=lambda record: record.timestamp) if records else None
        entries.append(BookEntry(book, latest))
    return entries


def find_books(
    db: Session,
    user: User,
    *,
    text: str = "",
    status: str = "all",
    sort: str = "recent",
    device_only: bool = False,
    limit: int = 60,
    offset: int = 0,
) -> BookPage:
    """One page of ``user``'s books matching the search ``text`` and reading ``status``.

    ``device_only`` restricts the result to books marked for syncing to e-readers.
    """
    statement = _scoped(select(Book, _by_hash, _by_name), user, text)
    if status in STATUSES and status != "all":
        statement = statement.where(_status == status)
    if device_only:
        statement = statement.where(Book.device_sync_at.is_not(None))
    statement = statement.order_by(*_ORDER_BY.get(sort, _ORDER_BY["recent"]))
    # Fetch one extra row to know whether another page exists without a COUNT query.
    entries = _entries(db, statement.limit(limit + 1).offset(offset))
    return BookPage(entries[:limit], has_more=len(entries) > limit)


def count_by_status(db: Session, user: User, text: str = "") -> dict[str, int]:
    statement = _scoped(select(_status, func.count(Book.id)).select_from(Book), user, text)
    counts = dict.fromkeys(STATUSES, 0)
    for status, count in db.execute(statement.group_by(_status)):
        counts[status] = count
        counts["all"] += count
    return counts


def count_device_books(db: Session, user: User, text: str = "") -> int:
    """Number of books marked for e-reader sync (matching the search ``text``)."""
    statement = _scoped(select(func.count(Book.id)).select_from(Book), user, text)
    return db.scalar(statement.where(Book.device_sync_at.is_not(None))) or 0


def continue_reading(db: Session, user: User) -> list[BookEntry]:
    return find_books(
        db, user, status="reading", sort="last_read", limit=CONTINUE_READING_LIMIT
    ).entries


def books_by_document(db: Session, user: User, documents: list[str]) -> dict[str, Book]:
    """``user``'s books keyed by partial MD5 (KOReader's document id), for the given ids."""
    if not documents:
        return {}
    books = db.scalars(
        select(Book).where(Book.user_id == user.id, Book.partial_md5.in_(set(documents)))
    )
    return {book.partial_md5: book for book in books}


def get_entry(db: Session, user: User, book_id: int) -> BookEntry | None:
    statement = _scoped(select(Book, _by_hash, _by_name), user).where(Book.id == book_id)
    entries = _entries(db, statement)
    return entries[0] if entries else None


# --- Mutations --------------------------------------------------------------------------------


def update_metadata(db: Session, storage: Storage, book: Book, **changes: object) -> None:
    title = str(changes.pop("title", "") or "").strip()
    if title:
        book.title = title[:500]
    for field in ("author", "series", "language", "publisher", "description"):
        if field in changes:
            value = str(changes[field] or "").strip()
            setattr(book, field, value or None)
    if "series_index" in changes:
        book.series_index = changes["series_index"]  # type: ignore[assignment]
    old_path = book.file_path
    final: str | None = None
    if storage.find_book_file(book) is not None:
        wanted = storage.schema_relative_path(book.author, book.series, book.title, book.format)
        if wanted != old_path:
            final = storage.move_book(book, wanted)
            if final is not None:
                book.file_path = final
    try:
        db.commit()
    except BaseException:
        db.rollback()
        if final is not None and final != old_path:
            book.file_path = final  # in memory only: lets move_book find the moved file
            storage.move_book(book, old_path)
            db.rollback()
        raise


def replace_cover(db: Session, storage: Storage, book: Book, data: bytes) -> None:
    if not covers.save_cover(data, storage.cover_path(book.id)):
        raise LibraryError("The cover image could not be read.")
    book.has_cover = True
    book.updated_at = utcnow()  # changes the cover URL, so browsers fetch the new image
    db.commit()


def set_device_sync(db: Session, book: Book, enabled: bool) -> None:
    """Mark or unmark a book for syncing to e-readers via the OPDS sync feed."""
    if enabled and book.device_sync_at is None:
        book.device_sync_at = utcnow()
    elif not enabled:
        book.device_sync_at = None
    db.commit()


def delete_book(db: Session, storage: Storage, book: Book) -> None:
    storage.delete_book_files(book)
    db.delete(book)
    db.commit()
