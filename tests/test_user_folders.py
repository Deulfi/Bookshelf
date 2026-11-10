"""Per-user library folders (no BOOKSHELF_INGEST_DIR): layout, scanning and legacy files."""

from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from bookshelf.models import Book, User
from bookshelf.services import library as library_service

from .conftest import make_epub, upload


def _wait_for_scanner(client: TestClient) -> None:
    scanner = client.app.state.scanner
    deadline = time.time() + 10
    while scanner.running and time.time() < deadline:
        time.sleep(0.02)


def _user(client: TestClient, username: str) -> User:
    with client.app.state.sessionmaker() as db:
        user = db.query(User).filter_by(username=username).one()
        db.expunge(user)
        return user


def _drop(folder: Path, relative: str, data: bytes) -> Path:
    path = folder / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (time.time() - 60,) * 2)
    return path


def test_upload_is_stored_as_author_series_title(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "whatever.epub", make_epub()).json()["id"]
    storage = admin_client.app.state.storage
    with admin_client.app.state.sessionmaker() as db:
        book = db.get(Book, book_id)
        assert book.file_path == "Ada Lovelace/Engines/The Test Book.epub"
        assert (storage.books_dir / str(book.user_id) / book.file_path).is_file()
    assert admin_client.get(f"/books/{book_id}/file").status_code == 200


def test_scan_imports_files_dropped_into_the_users_folder(admin_client: TestClient) -> None:
    _wait_for_scanner(admin_client)
    admin = _user(admin_client, "admin")
    folder = admin_client.app.state.storage.library_root(admin.id)
    _drop(folder, "Mary Shelley/Frankenstein.epub", make_epub(title="Frankenstein", series=None))

    result = admin_client.app.state.scanner.run_scan(admin.id)
    assert result is not None and result.imported == 1
    assert result.error is None
    page = admin_client.get("/").text
    assert "Frankenstein" in page


def test_scan_is_per_user(admin_client: TestClient) -> None:
    _wait_for_scanner(admin_client)
    admin_client.post("/admin/users", data={"username": "bob", "password": "bobpass1"})
    bob = _user(admin_client, "bob")
    folder = admin_client.app.state.storage.library_root(bob.id)
    _drop(folder, "Bob Author/Bobs Book.epub", make_epub(title="Bob's Book", series=None))

    scanner = admin_client.app.state.scanner
    assert scanner.run_scan(_user(admin_client, "admin").id).imported == 0  # not admin's folder
    assert scanner.run_scan(bob.id).imported == 1
    with admin_client.app.state.sessionmaker() as db:
        assert db.query(Book).filter_by(user_id=bob.id).count() == 1
        assert db.query(Book).filter(Book.user_id != bob.id).count() == 0


def test_same_file_in_two_users_folders_is_imported_for_both(admin_client: TestClient) -> None:
    _wait_for_scanner(admin_client)
    admin_client.post("/admin/users", data={"username": "bob", "password": "bobpass1"})
    storage = admin_client.app.state.storage
    data = make_epub(title="Shared", series=None)
    for name in ("admin", "bob"):
        _drop(storage.library_root(_user(admin_client, name).id), "A/Shared.epub", data)
    result = admin_client.app.state.scanner.run_scan()
    assert result.imported == 2


def test_legacy_random_names_are_reorganized(admin_client: TestClient) -> None:
    _wait_for_scanner(admin_client)
    book_id = upload(admin_client, "a.epub", make_epub()).json()["id"]
    storage = admin_client.app.state.storage
    with admin_client.app.state.sessionmaker() as db:
        book = db.get(Book, book_id)
        root = storage.library_root(book.user_id)
        legacy = "0123456789abcdef0123456789abcdef.epub"
        (root / book.file_path).rename(root / legacy)
        storage.prune_empty_parents((root / book.file_path).parent, root)
        book.file_path = legacy
        db.commit()
        user = db.get(User, book.user_id)
        assert library_service.reorganize_legacy_files(db, storage, user) == 1
        db.refresh(book)
        assert book.file_path == "Ada Lovelace/Engines/The Test Book.epub"
        assert (root / book.file_path).is_file()
        assert not (root / legacy).exists()
    assert admin_client.get(f"/books/{book_id}/file").status_code == 200


def test_scan_prunes_deleted_files(admin_client: TestClient) -> None:
    _wait_for_scanner(admin_client)
    book_id = upload(admin_client, "a.epub", make_epub()).json()["id"]
    storage = admin_client.app.state.storage
    with admin_client.app.state.sessionmaker() as db:
        book = db.get(Book, book_id)
        (storage.library_root(book.user_id) / book.file_path).unlink()
        user_id = book.user_id
    result = admin_client.app.state.scanner.run_scan(user_id)
    assert result.removed == 1


def test_scan_api(admin_client: TestClient, client: TestClient) -> None:
    _wait_for_scanner(admin_client)
    response = admin_client.post("/api/library/scan")
    assert response.status_code == 202
    _wait_for_scanner(admin_client)
    status = admin_client.get("/api/library/scan").json()
    assert status["running"] is False and status["error"] is None
    admin_client.post("/logout")
    assert client.post("/api/library/scan").status_code == 401
