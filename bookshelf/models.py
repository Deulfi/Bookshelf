"""SQLAlchemy ORM models. Schema changes require a new Alembic migration (see CLAUDE.md)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from .db import Base, utcnow


def author_sort_key(author: str | None) -> str | None:
    """Sort key for the first author: "Jane Austen" -> "austen, jane".

    Names already written as "Last, First" are kept. Multiple authors are joined with " & ".
    """
    first = (author or "").split(" & ")[0].strip()
    if not first:
        return None
    if "," not in first and " " in first:
        given, surname = first.rsplit(" ", 1)
        first = f"{surname}, {given}"
    return first.casefold()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    # bcrypt(md5(password)) – verifies both web logins and KOReader's md5-based sync key.
    password_hash: Mapped[str] = mapped_column(String(100))
    is_admin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    books: Mapped[list[Book]] = relationship(
        back_populates="owner", cascade="all, delete-orphan", passive_deletes=True
    )


class AuthSession(Base):
    """A browser login session. Only a SHA-256 digest of the cookie token is stored."""

    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]

    user: Mapped[User] = relationship()


class Book(Base):
    __tablename__ = "books"
    __table_args__ = (
        UniqueConstraint("user_id", "partial_md5"),
        Index("ix_books_user_recent", "user_id", "created_at", "id"),  # default library order
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    title: Mapped[str] = mapped_column(String(500))
    author: Mapped[str | None] = mapped_column(String(500))
    # Derived from ``author`` (see ``author_sort_key``), kept in sync automatically.
    author_sort: Mapped[str | None] = mapped_column(String(500))
    series: Mapped[str | None] = mapped_column(String(500))
    series_index: Mapped[float | None]
    description: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(20))
    publisher: Mapped[str | None] = mapped_column(String(300))

    format: Mapped[str] = mapped_column(String(10))
    original_filename: Mapped[str] = mapped_column(String(500))
    file_path: Mapped[str] = mapped_column(String(500))  # relative to the library root
    file_size: Mapped[int]
    # KOReader document identifiers: "binary" (partial MD5 of the file) and "filename" (MD5).
    partial_md5: Mapped[str] = mapped_column(String(32), index=True)
    filename_md5: Mapped[str] = mapped_column(String(32), index=True)
    has_cover: Mapped[bool] = mapped_column(default=False)
    # When the book was marked for syncing to e-readers (OPDS /opds/sync); None = not marked.
    device_sync_at: Mapped[datetime | None]

    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    owner: Mapped[User] = relationship(back_populates="books")

    @validates("author")
    def _sync_author_sort(self, _key: str, author: str | None) -> str | None:
        self.author_sort = author_sort_key(author)
        return author


class ReaderProfile(Base):
    """Values chosen in the browser reader's settings panel (see ``services/reader_config.py``).
    The user's configuration override is a file: ``<data_dir>/reader/users/<username>.json``."""

    __tablename__ = "reader_profiles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # JSON object: the values chosen in the reader's settings panel (theme, font size, ...).
    prefs: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class WebReadingTime(Base):
    """Seconds read in the browser reader, per book and hour. Merged with KOReader's
    ``statistics.sqlite3`` on the stats pages (see ``services/reading_stats.py``)."""

    __tablename__ = "web_reading_time"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # The book's partial MD5, like ReadingProgress.document and KOReader's ``book.md5``.
    document: Mapped[str] = mapped_column(String(32), primary_key=True)
    hour: Mapped[int] = mapped_column(primary_key=True)  # unix seconds, start of the hour
    seconds: Mapped[int] = mapped_column(default=0)
    last_read: Mapped[int] = mapped_column(default=0)  # unix seconds of the latest addition


class ReadingProgress(Base):
    """Progress as reported by KOReader, keyed by its document hash (not by book id)."""

    __tablename__ = "reading_progress"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    document: Mapped[str] = mapped_column(String(128), primary_key=True)
    progress: Mapped[str] = mapped_column(Text, default="")
    percentage: Mapped[float] = mapped_column(default=0.0)
    device: Mapped[str] = mapped_column(String(200), default="")
    device_id: Mapped[str] = mapped_column(String(200), default="")
    timestamp: Mapped[int]  # unix seconds, as KOReader expects
