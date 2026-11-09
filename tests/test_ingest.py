"""Tests for library-folder ingestion: in-place import, sync, and cleanup."""

from __future__ import annotations

import os
import time
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


def _drop(ingest: Path, relative: str, data: bytes, *, age: float = 60) -> Path:
    """Write a file; ``age`` seconds old so the sync does not treat it as half-written."""
    path = ingest / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))
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


def test_orphan_cover_removed_and_live_cover_kept(env):
    db, storage, user, ingest = env
    path = _drop(ingest, "Kept Author/Kept.epub", make_epub(title="Kept", series=None))
    book = library_service.import_from_disk(db, storage, user, path)
    storage.cover_path(book.id).write_bytes(b"cover")
    orphan = storage.cover_path(9999)
    orphan.write_bytes(b"orphan")
    storage.remove_orphan_covers(db)
    assert not orphan.exists()
    assert storage.cover_path(book.id).exists()


def test_sync_does_not_delete_unrelated_empty_folders(env):
    db, storage, user, ingest = env
    _drop(ingest, "A/Book.epub", make_epub(title="A", series=None))
    keep = ingest / "My empty folder"
    keep.mkdir()
    library_service.sync_library(db, storage, user)
    assert keep.exists()


def test_sync_prunes_books_whose_file_is_gone(env):
    db, storage, user, ingest = env
    gone = _drop(ingest, "Gone/Gone.epub", make_epub(title="Gone", author="Gone", series=None))
    stay = _drop(ingest, "Stay/Stay.epub", make_epub(title="Stay", author="Stay", series=None))
    book = library_service.import_from_disk(db, storage, user, gone)
    library_service.import_from_disk(db, storage, user, stay)
    storage.cover_path(book.id).write_bytes(b"cover")
    gone.unlink()
    assert library_service.prune_missing(db, storage) == 1
    assert not storage.cover_path(book.id).exists()
    assert library_service.find_books(db, user).entries[0].book.title == "Stay"


def test_prune_is_skipped_when_library_folder_is_empty(env):
    db, storage, user, ingest = env
    path = _drop(ingest, "A/Book.epub", make_epub(title="A", series=None))
    library_service.import_from_disk(db, storage, user, path)
    path.unlink()  # looks like an unmounted share: nothing left at all
    assert library_service.prune_missing(db, storage) == 0
    assert len(library_service.find_books(db, user).entries) == 1


def test_renamed_file_is_relinked_instead_of_left_broken(env):
    db, storage, user, ingest = env
    path = _drop(ingest, "Old/Book.epub", make_epub(title="Moved", series=None))
    book = library_service.import_from_disk(db, storage, user, path)
    new = ingest / "New" / "Book.epub"
    new.parent.mkdir()
    path.rename(new)
    os.utime(new, (time.time() - 60,) * 2)
    library_service.sync_library(db, storage, user)
    db.refresh(book)
    assert book.file_path == "New/Book.epub"
    assert storage.find_book_file(book) is not None


def test_metadata_move_never_overwrites_another_book(env):
    db, storage, user, ingest = env
    a = _drop(ingest, "X/Same.epub", make_epub(title="Same", author="X", series=None))
    b = _drop(ingest, "Y/B.epub", make_epub(title="Other", author="Y", series=None))
    book_a = library_service.import_from_disk(db, storage, user, a)
    book_b = library_service.import_from_disk(db, storage, user, b)
    library_service.update_metadata(db, storage, book_b, title="Same", author="X")
    assert book_b.file_path == "X/Same (2).epub"
    assert (ingest / book_a.file_path).is_file()
    assert (ingest / book_b.file_path).is_file()


def test_path_segments_cannot_escape_the_library(env):
    _, storage, _, _ = env
    relative = storage.schema_relative_path("..", ".", "../../evil", "epub")
    assert ".." not in relative.split("/")
    assert not relative.startswith("/")


def test_sync_skips_files_that_are_still_being_written(env):
    db, storage, user, ingest = env
    _drop(ingest, "A/Fresh.epub", make_epub(title="Fresh", series=None), age=0)
    assert library_service.sync_library(db, storage, user) == 0
    os.utime(ingest / "A/Fresh.epub", (time.time() - 60,) * 2)
    assert library_service.sync_library(db, storage, user) == 1
