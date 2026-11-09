"""File storage layout below the data directory.

<data_dir>/books/<user_id>/...   uploaded book files (legacy)
<data_dir>/covers/<book_id>.jpg  cover thumbnails
<data_dir>/tmp/                 in-progress uploads
<data_dir>/files/<user_id>/     WebDAV files (e.g. KOReader statistics)

When ingest_dir is set (the user's library folder, e.g. a NAS share), new
books are stored there under <Author>/<Series>/<Title>.<ext> and are never
copied or renamed on import. Book.file_path is always relative to the
library root the file lives in (ingest_dir or books_dir).
"""

from __future__ import annotations

import contextlib
import re
import shutil
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Book

# Characters that cannot appear in a Windows file or directory name.
_INVALID_SEGMENT_CHARS = re.compile(r"[\\/:*?\"<>|]")


class Storage:
    def __init__(self, root: Path, ingest_dir: Path | None = None) -> None:
        self.root = root
        self.books_dir = root / "books"
        self.covers_dir = root / "covers"
        self.tmp_dir = root / "tmp"
        self.files_dir = root / "files"
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

    def upload_root(self, user_id: int) -> Path:
        if self.ingest_dir is not None:
            return self.ingest_dir
        return self.books_dir / str(user_id)

    @staticmethod
    def _clean_segment(value: str | None, limit: int = 100) -> str:
        value = _INVALID_SEGMENT_CHARS.sub(" ", value or "")
        return " ".join(value.split())[:limit].strip()

    def schema_relative_path(
        self, author: str | None, series: str | None, title: str | None, fmt: str
    ) -> str:
        name = self._clean_segment(title) or "book"
        segments = [s for s in (self._clean_segment(author), self._clean_segment(series)) if s]
        return "/".join([*segments, f"{name}.{fmt}"])

    def new_temp_path(self) -> Path:
        return self.tmp_dir / uuid.uuid4().hex

    def store_book(self, source: Path, root: Path, relative: str) -> str:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return relative

    def find_book_file(self, book: Book) -> Path | None:
        located = self._locate(book)
        return located[1] if located else None

    def move_book(self, book: Book, relative: str) -> bool:
        located = self._locate(book)
        if located is None:
            return False
        root, source = located
        target = root / relative
        if target.exists() and target.resolve() != source.resolve():
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        return True

    def cleanup_old_covers_and_dirs(self, db: Session) -> None:
        for cover in self.covers_dir.glob("*.jpg"):
            if self.find_book_for_cover(db, int(cover.stem)) is None:
                cover.unlink(missing_ok=True)

        for root in self.library_roots():
            if not root.is_dir():
                continue
            # Deepest first: a parent emptied by its child's removal is pruned in the same pass.
            for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                if path.is_dir() and not any(path.iterdir()):
                    with contextlib.suppress(OSError):
                        path.rmdir()

    def find_book_for_cover(self, db: Session, book_id: int) -> Book | None:
        return db.scalar(select(Book).where(Book.id == book_id))

    def library_roots(self) -> tuple[Path, ...]:
        if self.ingest_dir is not None:
            return (self.ingest_dir, self.books_dir)
        return (self.books_dir,)

    def cover_path(self, book_id: int) -> Path:
        return self.covers_dir / f"{book_id}.jpg"

    def delete_book_files(self, book: Book) -> None:
        path = self.find_book_file(book)
        if path is not None:
            path.unlink(missing_ok=True)
        self.cover_path(book.id).unlink(missing_ok=True)

    def user_files_dir(self, user_id: int) -> Path:
        return self.files_dir / str(user_id)

    def delete_user_dir(self, user_id: int) -> None:
        shutil.rmtree(self.books_dir / str(user_id), ignore_errors=True)
        shutil.rmtree(self.user_files_dir(user_id), ignore_errors=True)
