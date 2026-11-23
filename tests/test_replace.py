"""Replacing a book's file with a new version (web novels that gain chapters)."""

from __future__ import annotations

import os
import time

from fastapi.testclient import TestClient
from sqlalchemy import select

from bookshelf.models import Book, ReadingProgress, ReadingSession, User, WebReadingTime
from bookshelf.security import md5_hex
from bookshelf.services import library
from bookshelf.services.reading_stats import add_web_time

from .conftest import ADMIN, make_chapter_epub, make_epub, upload

SYNC = {"x-auth-user": ADMIN[0], "x-auth-key": md5_hex(ADMIN[1])}
POSITION = "/body/DocFragment[3]/body/p[12]"


def _book(client: TestClient, book_id: int) -> Book:
    with client.app.state.sessionmaker() as db:
        book = db.get(Book, book_id)
        db.expunge(book)
        return book


def _replace(client: TestClient, book_id: int, filename: str, data: bytes):
    return client.post(
        f"/books/{book_id}/file",
        files={"file": (filename, data, "application/octet-stream")},
        follow_redirects=False,
    )


def _read_old_version(client: TestClient, book: Book) -> None:
    """A position from KOReader and some web reader time, all under the old document ID."""
    body = {"document": book.partial_md5, "progress": POSITION, "percentage": 0.6}
    assert client.put("/syncs/progress", json=body, headers=SYNC).status_code == 200
    with client.app.state.sessionmaker() as db:
        user_id = db.scalar(select(User.id))
        add_web_time(db, user_id, book.partial_md5, 300, 1_800_000_000, fraction=0.6)


def test_replace_keeps_the_book_and_moves_progress_and_time(admin_client: TestClient) -> None:
    v1 = make_chapter_epub(title="Web Novel", chapters=3)
    book_id = upload(admin_client, "novel.epub", v1).json()["id"]
    old = _book(admin_client, book_id)
    _read_old_version(admin_client, old)

    response = _replace(admin_client, book_id, "novel-ch1-5.epub", make_chapter_epub("X", 5))
    assert response.status_code == 303
    new = _book(admin_client, book_id)
    assert new.partial_md5 != old.partial_md5
    assert new.title == "Web Novel"  # metadata stays
    assert new.original_filename == "novel-ch1-5.epub"
    assert new.file_path == old.file_path
    assert new.file_size > old.file_size
    assert admin_client.get(f"/books/{book_id}/file").content == make_chapter_epub("X", 5)

    # KOReader opening the new file finds the old position under the new document ID.
    synced = admin_client.get(f"/syncs/progress/{new.partial_md5}", headers=SYNC).json()
    assert synced["progress"] == POSITION and synced["percentage"] == 0.6
    assert admin_client.get(f"/syncs/progress/{old.partial_md5}", headers=SYNC).json() == {}
    with admin_client.app.state.sessionmaker() as db:
        assert {r.document for r in db.scalars(select(WebReadingTime))} == {new.partial_md5}
        assert {r.document for r in db.scalars(select(ReadingSession))} == {new.partial_md5}
    page = admin_client.get(f"/books/{book_id}").text
    assert "5 min read" in page
    assert "Reading sessions" in page


def test_a_newer_position_on_the_new_file_wins(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "novel.epub", make_chapter_epub("N", 3)).json()["id"]
    old = _book(admin_client, book_id)
    _read_old_version(admin_client, old)
    v2 = make_chapter_epub("N", 4)
    # Read on the device already, before the book was replaced here.
    with admin_client.app.state.sessionmaker() as db:
        from bookshelf.services.hashing import partial_md5

        path = admin_client.app.state.storage.tmp_dir / "v2.epub"
        path.write_bytes(v2)
        new_hash = partial_md5(path)
        path.unlink()
        db.add(
            ReadingProgress(
                user_id=db.scalar(select(User.id)),
                document=new_hash,
                progress="/body/DocFragment[4]",
                percentage=0.9,
                timestamp=int(time.time()) + 60,
            )
        )
        db.commit()
    assert _replace(admin_client, book_id, "novel.epub", v2).status_code == 303
    synced = admin_client.get(f"/syncs/progress/{new_hash}", headers=SYNC).json()
    assert synced["percentage"] == 0.9


def test_replace_errors(admin_client: TestClient) -> None:
    v1 = make_epub(title="One")
    book_id = upload(admin_client, "one.epub", v1).json()["id"]
    other = make_epub(title="Two")
    upload(admin_client, "two.epub", other)

    same = _replace(admin_client, book_id, "one.epub", v1)
    assert same.status_code == 422
    assert "same file" in same.text
    assert (
        'id="replace-dialog" class="dialog dialog-sm" aria-labelledby="replace-title" data-open'
        in same.text
    )

    taken = _replace(admin_client, book_id, "two.epub", other)
    assert taken.status_code == 422
    assert "Already in your library as “Two”" in taken.text

    assert _replace(admin_client, book_id, "setup.exe", b"MZ").status_code == 422
    assert _replace(admin_client, 9999, "one.epub", v1).status_code == 404
    assert _book(admin_client, book_id).original_filename == "one.epub"


def test_replace_with_another_format_renames_the_file(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "novel.epub", make_epub(title="Novel")).json()["id"]
    old = _book(admin_client, book_id)
    storage = admin_client.app.state.storage
    old_path = storage.find_book_file(old)
    fb2 = b"<?xml version='1.0'?><FictionBook><body><p>Hi</p></body></FictionBook>"
    assert _replace(admin_client, book_id, "novel.fb2", fb2).status_code == 303
    new = _book(admin_client, book_id)
    assert new.format == "fb2"
    assert new.file_path == old.file_path.removesuffix(".epub") + ".fb2"
    assert storage.find_book_file(new).read_bytes() == fb2
    assert not old_path.exists()
    assert [p.name for p in old_path.parent.iterdir()] == ["Novel.fb2"]  # no staging leftovers


def test_scan_picks_up_a_file_replaced_in_the_library_folder(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "novel.epub", make_chapter_epub("S", 3)).json()["id"]
    old = _book(admin_client, book_id)
    _read_old_version(admin_client, old)
    storage = admin_client.app.state.storage
    path = storage.find_book_file(old)
    path.write_bytes(make_chapter_epub("S", 6))
    os.utime(path, (time.time() - 60,) * 2)

    logs: list[str] = []
    with admin_client.app.state.sessionmaker() as db:
        user = db.scalar(select(User))
        assert library.sync_library(db, storage, user, log=logs.append) == 0
    new = _book(admin_client, book_id)
    assert new.partial_md5 != old.partial_md5
    assert new.file_size == path.stat().st_size
    assert any("the file changed" in line for line in logs)
    synced = admin_client.get(f"/syncs/progress/{new.partial_md5}", headers=SYNC).json()
    assert synced["progress"] == POSITION

    # A file still being written is left for the next scan.
    path.write_bytes(make_chapter_epub("S", 7))
    with admin_client.app.state.sessionmaker() as db:
        library.sync_library(db, storage, db.scalar(select(User)))
    assert _book(admin_client, book_id).partial_md5 == new.partial_md5


def test_book_page_has_the_replace_dialog(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "a.epub", make_epub()).json()["id"]
    page = admin_client.get(f"/books/{book_id}").text
    assert 'data-dialog-open="replace-dialog"' in page
    assert f'action="/books/{book_id}/file"' in page
