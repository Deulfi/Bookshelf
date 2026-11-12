"""Database engine setup and schema migrations (SQLite + Alembic)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_REVISION = re.compile(r"^revision\b[^=\n]*=\s*['\"]([^'\"]+)['\"]", re.M)
_DOWN_REVISION = re.compile(r"^down_revision\b[^=\n]*=(.*)$", re.M)


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Naive UTC timestamp. SQLite has no timezone support, so all datetimes are stored as UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


def _casefold(value: str | None) -> str | None:
    return value.casefold() if value is not None else None


def make_engine(url: str) -> Engine:
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
        # Unicode-aware case folding for search and sorting (SQLite's LOWER() is ASCII-only).
        dbapi_connection.create_function("casefold", 1, _casefold, deterministic=True)

    return engine


def _head_revision() -> str | None:
    """The newest migration, read from the files in ``migrations/versions`` without Alembic.
    None when that isn't clear-cut (no files, branches); Alembic then decides."""
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in (MIGRATIONS_DIR / "versions").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        revision = _REVISION.search(source)
        down = _DOWN_REVISION.search(source)
        if revision is None or down is None:
            return None
        revisions.add(revision.group(1))
        parents.update(re.findall(r"['\"]([^'\"]+)['\"]", down.group(1)))
    heads = revisions - parents
    return heads.pop() if len(heads) == 1 else None


def _schema_is_current(engine: Engine) -> bool:
    head = _head_revision()
    if head is None:
        return False
    try:
        with engine.connect() as connection:
            versions = connection.scalars(text("SELECT version_num FROM alembic_version")).all()
    except DatabaseError:  # a new database has no alembic_version table yet
        return False
    return versions == [head]


def run_migrations(engine: Engine) -> None:
    """Upgrade the database schema to the latest Alembic revision.

    Alembic takes about 11 MB of memory once imported, and most starts have nothing to migrate,
    so it is only loaded when the database isn't at the newest revision yet."""
    if _schema_is_current(engine):
        return
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def init_database(url: str) -> sessionmaker[Session]:
    engine = make_engine(url)
    run_migrations(engine)
    return sessionmaker(engine, expire_on_commit=False)
