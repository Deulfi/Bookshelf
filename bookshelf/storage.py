"""File storage layout below the data directory.

<data_dir>/books/<user_id>/...   each user's library folder (Author/Series/Title.ext)
<data_dir>/covers/<book_id>.jpg  cover thumbnails
<data_dir>/tmp/                 in-progress uploads
<data_dir>/files/<user_id>/     WebDAV files (e.g. KOReader statistics)
<data_dir>/reader/              optional web reader overrides (*.json) and fonts/

Books are stored as <Author>/<Series>/<Title>.<ext> below the user's library root:
books/<user_id>/ by default, or the shared ingest_dir (e.g. a NAS share) when it is set.
Files already in a library root are registered in place by a scan. Book.file_path is
always relative to the library root the file lives in.
"""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Book

# Characters that cannot appear in a Windows file or directory name.
_INVALID_SEGMENT_CHARS = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")
# Usernames as allowed by services/users.py; safe to use as a file name.
_SAFE_FILE_NAME = re.compile(r"^[a-z0-9][a-z0-9._@-]{0,63}$")


class Storage:
    def __init__(self, root: Path, ingest_dir: Path | None = None) -> None:
        self.root = root
        self.books_dir = root / "books"
        self.covers_dir = root / "covers"
        self.tmp_dir = root / "tmp"
        self.files_dir = root / "files"
        self.reader_dir = root / "reader"  # optional web reader config and fonts
        self.ingest_dir = ingest_dir

    def ensure_dirs(self) -> None:
        for directory in (self.books_dir, self.covers_dir, self.tmp_dir, self.files_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def _locate(self, book: Book) -> tuple[Path, Path] | None:
        if self.ingest_dir is not None:
            path = self.ingest_dir / book.file_path
            if path.is_file():
                return self.ingest_dir, path
        root = self.books_dir / str(book.user_id)
        path = root / book.file_path
        if path.is_file():
            return root, path
        return None

    def library_root(self, user_id: int) -> Path:
        """Where a user's books live: the shared ingest folder, or ``books/<user_id>/``."""
        if self.ingest_dir is not None:
            return self.ingest_dir
        return self.books_dir / str(user_id)

    upload_root = library_root

    @staticmethod
    def _clean_segment(value: str | None, limit: int = 100) -> str:
        value = _INVALID_SEGMENT_CHARS.sub(" ", value or "")
        value = " ".join(value.split())[:limit]
        # Windows/SMB shares reject names ending in a dot or space; "." and ".." must never
        # survive, or an author called ".." would escape the library folder.
        return value.strip(" .")

    def schema_relative_path(
        self, author: str | None, series: str | None, title: str | None, fmt: str
    ) -> str:
        name = self._clean_segment(title) or "book"
        segments = [s for s in (self._clean_segment(author), self._clean_segment(series)) if s]
        return "/".join([*segments, f"{name}.{fmt}"])

    def new_temp_path(self) -> Path:
        return self.tmp_dir / uuid.uuid4().hex

    def unique_relative(self, root: Path, relative: str, own: Path | None = None) -> str:
        """``relative`` or, if that name is taken, "Name (2).ext", "Name (3).ext", ...

        ``own`` is the file being renamed; it does not count as a collision with itself.
        """
        candidate = Path(relative)
        number = 1
        while True:
            target = root / candidate
            if not target.exists() or (own is not None and _same_file(target, own)):
                return candidate.as_posix()
            number += 1
            candidate = Path(relative).with_name(
                f"{Path(relative).stem} ({number}){Path(relative).suffix}"
            )

    def store_book(self, source: Path, root: Path, relative: str) -> str:
        """Copy a temp file into ``root`` without overwriting; returns the path used."""
        relative = self.unique_relative(root, relative)
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return relative

    def find_book_file(self, book: Book) -> Path | None:
        located = self._locate(book)
        return located[1] if located else None

    def move_book(self, book: Book, relative: str) -> str | None:
        """Move a book to ``relative`` below its library root; returns the final path or None."""
        located = self._locate(book)
        if located is None:
            return None
        root, source = located
        relative = self.unique_relative(root, relative, own=source)
        target = root / relative
        if _same_file(target, source):
            return relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        self.prune_empty_parents(source.parent, root)
        return relative

    def prune_empty_parents(self, directory: Path, root: Path) -> None:
        """Remove ``directory`` and its parents while they are empty, never ``root`` itself."""
        root = root.resolve()
        directory = directory.resolve()
        while directory != root and root in directory.parents:
            try:
                directory.rmdir()  # fails (and we stop) as soon as a directory is not empty
            except OSError:
                return
            directory = directory.parent

    def remove_orphan_covers(self, db: Session) -> int:
        """Delete cover files whose book no longer exists (one query, not one per cover)."""
        live = set(db.scalars(select(Book.id)))
        removed = 0
        for cover in self.covers_dir.glob("*.jpg"):
            if not cover.stem.isdigit() or int(cover.stem) not in live:
                cover.unlink(missing_ok=True)
                removed += 1
        return removed

    def library_roots(self) -> tuple[Path, ...]:
        if self.ingest_dir is not None:
            return (self.ingest_dir, self.books_dir)
        return (self.books_dir,)

    def cover_path(self, book_id: int) -> Path:
        return self.covers_dir / f"{book_id}.jpg"

    def delete_book_files(self, book: Book) -> None:
        located = self._locate(book)
        if located is not None:
            root, path = located
            path.unlink(missing_ok=True)
            self.prune_empty_parents(path.parent, root)
        self.cover_path(book.id).unlink(missing_ok=True)

    def user_files_dir(self, user_id: int) -> Path:
        return self.files_dir / str(user_id)

    def user_reader_config(self, user_id: int, username: str) -> Path:
        """A user's web reader override file, named after the user (falls back to the id
        for a name that is not a safe file name)."""
        safe = bool(_SAFE_FILE_NAME.match(username))
        return self.reader_dir / "users" / (f"{username}.json" if safe else f"user-{user_id}.json")

    def delete_user_dir(self, user_id: int) -> None:
        shutil.rmtree(self.books_dir / str(user_id), ignore_errors=True)
        shutil.rmtree(self.user_files_dir(user_id), ignore_errors=True)


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False
