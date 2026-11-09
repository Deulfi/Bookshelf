"""Tests for library-folder ingestion: in-place import, sync, and cleanup."""

from __future__ import annotations

from pathlib import Path

import pytest

from bookshelf.config import Settings
from bookshelf.db import init_database
from bookshelf.models import User
from bookshelf.services import library as library_service
from bookshelf.storage import Storage

from .conftest import make_epub


@pytest.fixture
def env(tmp_path: Path):
    """Data dir, library folder, database session, and one user."""
    settings = Settings(data_dir=tmp_path / "data")
    ingest = tmp_path / "library"
    ingest.mkdir()
    storage = Storage(settings.data_dir, ingest)
    storage.ensure_dirs()
    sessionmaker = init_database(settings.database_url)
    with sessionmaker() as db:
        user = User(username="admin", password_hash="x", is_admin=True)
        db.add(user)
        db.commit()
        yield db, storage, user, ingest


def _drop(ingest: Path, relative: str, data: bytes) -> Path:
    path = ingest / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_import_from_disk_registers_in_place(env):
    db, storage, user, ingest = env
    path = _drop(ingest, "Ada Lovelace/Engines/The Test Book.epub", make_epub())
    book = library_service.import_from_disk(db, storage, user, path)
    assert book.file_path == "Ada Lovelace/Engines/The Test Book.epub"
    assert path.is_file()  # registered in place, not copied
    assert not (storage.books_dir / str(user.id) / book.file_path).exists()


def test_sync_library_imports_new_and_skips_known(env):
    db, storage, user, ingest = env
    emma = make_epub(title="Emma")
    _drop(ingest, "Ada Lovelace/Engines/Emma.epub", emma)
    dune = make_epub(title="Dune", author="Frank Herbert", series=None)
    _drop(ingest, "Frank Herbert/Dune.epub", dune)
    assert library_service.sync_library(db, storage, user) == 2
    assert library_service.sync_library(db, storage, user) == 0
    # Same content under a new name: duplicate hash, skipped.
    _drop(ingest, "Nobody/Emma-copy.epub", emma)
    assert library_service.sync_library(db, storage, user) == 0
    # Unsupported files are ignored, not errors.
    _drop(ingest, "notes.bin", b"hello")
    assert library_service.sync_library(db, storage, user) == 0


def test_update_metadata_moves_file_and_prunes_empty_dirs(env):
    db, storage, user, ingest = env
    path = _drop(ingest, "Ada Lovelace/Engines/The Test Book.epub", make_epub())
    book = library_service.import_from_disk(db, storage, user, path)
    library_service.update_metadata(db, storage, book, author="Someone New", series="")
    assert book.file_path == "Someone New/The Test Book.epub"
    assert (ingest / book.file_path).is_file()
    assert not path.exists()
    assert not (ingest / "Ada Lovelace").exists()  # empty author + series chain pruned


def test_cleanup_removes_orphan_cover_and_empty_chain(env):
    db, storage, user, ingest = env
    kept = make_epub(title="Kept", author="Kept Author", series=None)
    path = _drop(ingest, "Kept Author/Kept.epub", kept)
    book = library_service.import_from_disk(db, storage, user, path)
    storage.cover_path(book.id).write_bytes(b"cover")
    orphan = storage.cover_path(9999)
    orphan.write_bytes(b"orphan")
    chain = ingest / "Gone Author" / "Gone Series"
    chain.mkdir(parents=True)
    storage.cleanup_old_covers_and_dirs(db)
    assert not orphan.exists()
    assert not chain.exists()  # parent and child both removed
    assert storage.cover_path(book.id).exists()  # live book's cover kept
