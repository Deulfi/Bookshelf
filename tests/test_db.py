"""Startup migrations: Alembic is only loaded when the schema is behind."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from bookshelf import db


def test_head_revision_matches_alembic() -> None:
    config = Config()
    config.set_main_option("script_location", str(db.MIGRATIONS_DIR))
    assert db._head_revision() == ScriptDirectory.from_config(config).get_current_head()


def test_schema_is_current_only_after_migrating(tmp_path: Path) -> None:
    engine = db.make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    assert not db._schema_is_current(engine)  # new database: no alembic_version table

    db.run_migrations(engine)
    assert db._schema_is_current(engine)

    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '0001'"))
    assert not db._schema_is_current(engine)  # an older database still gets migrated
