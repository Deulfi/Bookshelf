"""Reading position shared between the web reader, KOReader and Readest (KOReader sync)."""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from bookshelf.services import chapters
from bookshelf.services.chapters import Outline

from .conftest import ADMIN, make_chapter_epub, upload


def _document(client: TestClient, book_id: int) -> str:
    page = client.get(f"/books/{book_id}").text
    return page.split('KOReader document ID</dt><dd class="mono">')[1][:32]


def _sync_headers() -> dict[str, str]:
    username, password = ADMIN
    return {"x-auth-user": username, "x-auth-key": hashlib.md5(password.encode()).hexdigest()}


def test_spine_index_from_xpointer_and_cfi() -> None:
    assert chapters.spine_index("/body/DocFragment[152]/body/h1") == 151
    assert chapters.spine_index("/body/DocFragment[3]/body/div/p[2]/text().4") == 2
    assert chapters.spine_index("epubcfi(/6/8!/4,/2,/4/8/17:158)") == 3
    assert chapters.spine_index("42") is None
    assert chapters.spine_index("") is None
    assert chapters.spine_index(None) is None


def test_chapter_in_outline() -> None:
    outline = Outline(6, ((1, "One"), (2, "Two"), (2, "Two, part 2"), (4, "Three")))
    assert chapters.chapter_in(outline, 0) is None  # the cover, before the first chapter
    assert chapters.chapter_in(outline, 1) == chapters.Chapter(1, 4, "One")
    assert chapters.chapter_in(outline, 2) == chapters.Chapter(2, 4, "Two")
    assert chapters.chapter_in(outline, 3) == chapters.Chapter(3, 4, "Two, part 2")
    assert chapters.chapter_in(outline, 5) == chapters.Chapter(4, 4, "Three")
    assert chapters.chapter_in(outline, 6) is None
    assert chapters.chapter_in(Outline(3, ()), 1) == chapters.Chapter(2, 3, None, "Section")


def test_web_reader_sends_xpointer_and_device(admin_client: TestClient) -> None:
    book = upload(admin_client, "c.epub", make_chapter_epub(chapters=5)).json()
    xpointer = "/body/DocFragment[2]/body/p[10]"
    put = admin_client.put(
        f"/api/books/{book['id']}/position",
        json={"progress": xpointer, "fraction": 0.3, "device_id": "browser-1"},
    )
    assert put.status_code == 200

    # KOReader / Readest read the same record
    record = admin_client.get(
        f"/syncs/progress/{_document(admin_client, book['id'])}", headers=_sync_headers()
    ).json()
    assert record["progress"] == xpointer
    assert record["device"] == "Web reader"
    assert record["device_id"] == "browser-1"


def test_position_needs_a_value(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "c.epub", make_chapter_epub()).json()["id"]
    response = admin_client.put(f"/api/books/{book_id}/position", json={"fraction": 0.3})
    assert response.status_code == 422


def test_readest_progress_reaches_web_reader_and_book_page(admin_client: TestClient) -> None:
    book = upload(admin_client, "c.epub", make_chapter_epub(chapters=5)).json()
    pushed = admin_client.put(
        "/syncs/progress",
        headers=_sync_headers(),
        json={
            "document": _document(admin_client, book["id"]),
            "progress": "/body/DocFragment[4]/body/h1",
            "percentage": 0.65,
            "device": "Readest (Windows)",
            "device_id": "f598",
        },
    )
    assert pushed.status_code == 200

    position = admin_client.get(f"/api/books/{book['id']}/position").json()
    assert position["progress"] == "/body/DocFragment[4]/body/h1"
    assert position["device"] == "Readest (Windows)"
    assert position["device_id"] == "f598"
    assert isinstance(position["timestamp"], int)

    page = admin_client.get(f"/books/{book['id']}").text
    assert "Chapter 4</span>" in page and "4/5" in page


def test_book_page_chapter_from_web_reader_cfi(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "c.epub", make_chapter_epub(chapters=3)).json()["id"]
    admin_client.put(
        f"/api/books/{book_id}/position",
        json={"progress": "epubcfi(/6/4!/4/2,/1:0,/1:5)", "fraction": 0.5},
    )
    assert "2/3</span>" in admin_client.get(f"/books/{book_id}").text


def test_book_page_without_chapter_info(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "c.epub", make_chapter_epub(chapters=3)).json()["id"]
    admin_client.put(f"/api/books/{book_id}/position", json={"progress": "17", "fraction": 0.5})
    page = admin_client.get(f"/books/{book_id}").text
    assert "50%" in page
    assert 'class="progress-chapter"' not in page


def test_continue_reading_cover_opens_reader(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "c.epub", make_chapter_epub()).json()["id"]
    admin_client.put(
        f"/api/books/{book_id}/position", json={"progress": "epubcfi(/6/2!)", "fraction": 0.2}
    )
    page = admin_client.get("/").text
    assert f'class="continue-cover cover-frame" href="/read/{book_id}"' in page
    assert f'class="continue-info" href="/books/{book_id}"' in page


def test_set_progress_by_percentage_writes_xpointer(admin_client: TestClient) -> None:
    book = upload(admin_client, "c.epub", make_chapter_epub(chapters=4)).json()
    response = admin_client.post(
        f"/books/{book['id']}/progress",
        data={"mode": "percent", "percent": "60"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    position = admin_client.get(f"/api/books/{book['id']}/position").json()
    assert position["percentage"] == 0.6
    assert position["progress"] == "/body/DocFragment[3]/body"  # equal chapters: 60% is in #3
    assert position["device"] == "Bookshelf (edited)"
    page = admin_client.get(f"/books/{book['id']}").text
    assert "60%" in page
    assert "3/4</span>" in page


def test_set_progress_by_chapter(admin_client: TestClient) -> None:
    book = upload(admin_client, "c.epub", make_chapter_epub(chapters=4)).json()
    admin_client.post(f"/books/{book['id']}/progress", data={"mode": "chapter", "chapter": "2"})
    position = admin_client.get(f"/api/books/{book['id']}/position").json()
    assert position["progress"] == "/body/DocFragment[2]/body"
    assert 0.2 < position["percentage"] < 0.3  # chapter 2 of 4 equal chapters starts at 25%


@pytest.mark.parametrize(
    "data",
    [
        {"mode": "percent", "percent": "120"},
        {"mode": "percent", "percent": "abc"},
        {"mode": "chapter", "chapter": "9"},
        {"mode": "chapter", "chapter": ""},
    ],
)
def test_set_progress_rejects_bad_input(admin_client: TestClient, data: dict) -> None:
    book_id = upload(admin_client, "c.epub", make_chapter_epub(chapters=4)).json()["id"]
    response = admin_client.post(f"/books/{book_id}/progress", data=data)
    assert response.status_code == 422
    assert "data-open" in response.text  # the dialog opens again with the error
    assert admin_client.get(f"/api/books/{book_id}/position").json()["progress"] is None


def test_set_progress_other_formats_percentage_only(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "notes.txt", b"hello world").json()["id"]
    page = admin_client.get(f"/books/{book_id}").text
    assert 'id="mode-chapter"' not in page
    admin_client.post(f"/books/{book_id}/progress", data={"mode": "percent", "percent": "12.5"})
    position = admin_client.get(f"/api/books/{book_id}/position").json()
    assert position["percentage"] == 0.125
    assert position["progress"] == ""


def test_reset_progress(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "c.epub", make_chapter_epub()).json()["id"]
    admin_client.post(f"/books/{book_id}/progress", data={"mode": "percent", "percent": "50"})
    response = admin_client.post(f"/books/{book_id}/progress/delete", follow_redirects=False)
    assert response.status_code == 303
    assert admin_client.get(f"/api/books/{book_id}/position").json()["progress"] is None
    assert "Not started yet" in admin_client.get(f"/books/{book_id}").text


def test_progress_edit_is_private(admin_client: TestClient, client: TestClient) -> None:
    book_id = upload(admin_client, "c.epub", make_chapter_epub()).json()["id"]
    admin_client.post("/admin/users", data={"username": "bob", "password": "bobpass1"})
    admin_client.post("/logout")
    client.post("/login", data={"username": "bob", "password": "bobpass1"})
    assert client.post(f"/books/{book_id}/progress", data={"percent": "5"}).status_code == 404
    assert client.post(f"/books/{book_id}/progress/delete").status_code == 404
