"""Database engine setup and schema migrations (SQLite + Alembic)."""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Connection, Engine, create_engine, event, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

log = logging.getLogger(__name__)
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


# 0-based spine item of a KOReader XPointer or EPUB CFI, mirroring
# ``services.chapters.spine_index`` for use in SQL (the library's "finished" status).
_XPOINTER_SPINE = re.compile(r"^/body/DocFragment\[(\d+)\]")
_CFI_SPINE = re.compile(r"^epubcfi\(/6/(\d+)")


def _spine_index(progress: str | None) -> int | None:
    if not progress:
        return None
    if match := _XPOINTER_SPINE.match(progress):
        return int(match.group(1)) - 1
    if match := _CFI_SPINE.match(progress):
        return int(match.group(1)) // 2 - 1
    return None


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
        # Spine item of a reading position, for the chapter-aware "finished" status.
        dbapi_connection.create_function("spine_index", 1, _spine_index, deterministic=True)

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

    _backup_before_migrating(engine)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with foreign_keys_off(engine) as connection, connection.begin():
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        _check_foreign_keys(connection)


@contextmanager
def foreign_keys_off(engine: Engine) -> Iterator[Connection]:
    """A connection without foreign key enforcement, for migrations.

    SQLite can't change a table's columns in place, so Alembic's batch mode copies the table and
    runs ``DROP TABLE`` on the old one. With foreign keys on, that drop deletes every row that
    references the table through ``ON DELETE CASCADE``: recreating ``users`` (0008) erased all
    books, progress and reading time. The pragma only works outside a transaction, and the
    connection gets it back before it returns to the pool."""
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        enforced = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
        connection.commit()
        if enforced != 0:
            raise RuntimeError("Could not turn off foreign keys for the migration.")
        try:
            yield connection
        finally:
            connection.rollback()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()


def _check_foreign_keys(connection: Connection) -> None:
    problems = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if problems:
        raise RuntimeError(f"The migration broke foreign keys: {problems[:5]}")


def _backup_before_migrating(engine: Engine) -> None:
    """Copy an existing database to ``backups/`` next to it before its schema changes.

    A copy that can't be written (say ``backups/`` belongs to root) goes next to the database
    instead; if that fails too, a warning is logged and the migration runs anyway."""
    path = engine.url.database
    if not path or path == ":memory:" or not Path(path).exists():
        return
    with engine.connect() as connection:
        try:
            version = connection.scalar(text("SELECT version_num FROM alembic_version"))
        except DatabaseError:
            return  # a new database: nothing to keep
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        name = f"bookshelf-{version}-{stamp}.db"
        raw = connection.connection.driver_connection
        folder = Path(path).parent
        errors = []
        for target in (folder / "backups" / name, folder / name):
            try:
                target.parent.mkdir(exist_ok=True)
                copy = sqlite3.connect(target)
                try:
                    raw.backup(copy)
                finally:
                    copy.close()
                log.info("Database copied to %s before migrating.", target)
                return
            except (OSError, sqlite3.Error) as exc:
                errors.append(f"{target}: {exc}")
        log.warning("No backup before migrating (%s).", "; ".join(errors))


def init_database(url: str) -> sessionmaker[Session]:
    engine = make_engine(url)
    run_migrations(engine)
    return sessionmaker(engine, expire_on_commit=False)
