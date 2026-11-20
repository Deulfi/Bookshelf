"""Schema migrations must keep existing data (SQLite batch mode recreates tables)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from bookshelf.db import MIGRATIONS_DIR, foreign_keys_off, make_engine, run_migrations


def _upgrade_to(engine, revision: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with foreign_keys_off(engine) as connection, connection.begin():
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


def test_migrating_keeps_rows_that_reference_users(tmp_path: Path) -> None:
    # 0008 recreates ``users``; with foreign keys on, its DROP TABLE cascaded to every row
    # that references a user (books, progress, reading time, ...).
    engine = make_engine(f"sqlite:///{(tmp_path / 'bookshelf.db').as_posix()}")
    _upgrade_to(engine, "0007")
    with engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO users (id, username, password_hash, is_admin, created_at) "
                "VALUES (1, 'ada', 'x', 1, '2026-11-01')"
            )
        )
        db.execute(
            text(
                "INSERT INTO books (user_id, title, format, original_filename, file_path, file_size, "
                "partial_md5, filename_md5, has_cover, device_sync_at, created_at, updated_at) "
                "VALUES (1, 'Emma', 'epub', 'e.epub', 'e.epub', 1, 'a', 'b', 0, '2026-11-02', "
                "'2026-11-01', '2026-11-01')"
            )
        )
        db.execute(
            text(
                "INSERT INTO reading_progress (user_id, document, progress, percentage, "
                "device, device_id, timestamp) VALUES (1, 'a', 'x', 0.5, 'Kobo', 'k', 1)"
            )
        )

    run_migrations(engine)

    with engine.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM books WHERE device_sync_at IS NOT NULL")) == 1
        assert db.scalar(text("SELECT count(*) FROM reading_progress")) == 1
        assert db.scalar(text("PRAGMA foreign_keys")) == 1  # back on for the app's connections
    backups = list((tmp_path / "backups").glob("bookshelf-0007-*.db"))
    assert len(backups) == 1


def test_migrating_works_when_backups_folder_is_unusable(tmp_path: Path) -> None:
    # e.g. backups/ created by root: the copy goes next to the database, startup goes on
    engine = make_engine(f"sqlite:///{(tmp_path / 'bookshelf.db').as_posix()}")
    _upgrade_to(engine, "0007")
    (tmp_path / "backups").write_text("not a folder")

    run_migrations(engine)

    with engine.connect() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) != "0007"
    assert len(list(tmp_path.glob("bookshelf-0007-*.db"))) == 1
