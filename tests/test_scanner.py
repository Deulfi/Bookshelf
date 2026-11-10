"""Tests for the library scanner: manual scan, interval setting and the settings page."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bookshelf.config import Settings
from bookshelf.main import create_app
from bookshelf.models import Book

from .conftest import ADMIN, make_epub


@pytest.fixture
def library_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "library"
    folder.mkdir()
    return folder


@pytest.fixture
def app_client(tmp_path: Path, library_dir: Path):
    app = create_app(Settings(data_dir=tmp_path / "data", ingest_dir=library_dir))
    with TestClient(app) as client:
        username, password = ADMIN
        client.post(
            "/setup",
            data={"username": username, "password": password, "password_confirm": password},
        )
        yield client, app


def _add_book(folder: Path, name: str = "Book.epub") -> Path:
    path = folder / "Ada" / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(make_epub())
    os.utime(path, (time.time() - 60,) * 2)
    return path


def test_manual_scan_adds_and_removes(app_client, library_dir):
    _client, app = app_client
    scanner = app.state.scanner
    book_file = _add_book(library_dir)
    scanner.last_result = None
    # Wait for any startup scan to finish, then scan on demand.
    while scanner.running:
        time.sleep(0.01)
    result = scanner.run_scan()
    assert result is not None and result.imported == 1
    book_file.unlink()
    _add_book(library_dir, "Other.epub").write_bytes(make_epub(title="Other", author="O"))
    os.utime(library_dir / "Ada" / "Other.epub", (time.time() - 60,) * 2)
    result = scanner.run_scan()
    assert result is not None and result.removed == 1
    with app.state.sessionmaker() as db:
        assert db.query(Book).count() == 1


def test_interval_is_saved_and_validated(app_client):
    client, app = app_client
    assert app.state.scanner.interval_minutes == 0
    assert client.post("/settings/scan-interval", data={"minutes": "60"}).status_code in (200, 303)
    assert app.state.scanner.interval_minutes == 60
    assert client.post("/settings/scan-interval", data={"minutes": "7"}).status_code == 422
    assert app.state.scanner.interval_minutes == 60


def test_settings_page_shows_scan_card_and_button_works(app_client):
    client, _app = app_client
    page = client.get("/settings")
    assert "Scan now" in page.text
    response = client.post("/settings/scan", follow_redirects=False)
    assert response.status_code == 303


def test_scan_card_covers_user_folders_without_ingest_dir(admin_client: TestClient):
    page = admin_client.get("/settings").text
    assert "Scan all folders now" in page
    assert "data-scan-trigger" in admin_client.get("/").text


def test_scan_button_is_for_admins_with_a_shared_folder(app_client):
    client, _app = app_client
    assert "data-scan-trigger" in client.get("/").text
    client.post("/admin/users", data={"username": "bob", "password": "bobpass1"})
    client.post("/logout")
    client.post("/login", data={"username": "bob", "password": "bobpass1"})
    assert "data-scan-trigger" not in client.get("/").text
    assert client.post("/api/library/scan").status_code == 403
