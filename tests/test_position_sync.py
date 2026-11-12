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
    # Equal chapters: 60% is 40% into chapter 3, which has an h1 and 300 paragraphs.
    assert position["progress"] == "/body/DocFragment[3]/body/p[120]"
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
        {"mode": "percent", "percent": "abc"},
        {"mode": "chapter", "chapter": ""},
        {"mode": "chapter", "chapter": "x"},
    ],
)
def test_set_progress_rejects_non_numbers(admin_client: TestClient, data: dict) -> None:
    book_id = upload(admin_client, "c.epub", make_chapter_epub(chapters=4)).json()["id"]
    response = admin_client.post(f"/books/{book_id}/progress", data=data)
    assert response.status_code == 422
    assert "data-open" in response.text  # the dialog opens again with the error
    assert admin_client.get(f"/api/books/{book_id}/position").json()["progress"] is None


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"mode": "percent", "percent": "120"}, 1.0),
        ({"mode": "percent", "percent": "-5"}, 0.0),
        ({"mode": "chapter", "chapter": "9"}, 1.0),  # 9 of 4: capped to the last = finished
        ({"mode": "chapter", "chapter": "4"}, 1.0),  # the last chapter means finished
        ({"mode": "chapter", "chapter": "0"}, 0.0),  # nothing read yet
        ({"mode": "chapter", "chapter": "-3"}, 0.0),
        # the other tab's field is ignored, even when it is out of range or not a number
        ({"mode": "chapter", "chapter": "2", "percent": "120"}, None),
        ({"mode": "percent", "percent": "50", "chapter": "abc"}, 0.5),
    ],
)
def test_set_progress_caps_values(admin_client: TestClient, data: dict, expected) -> None:
    book_id = upload(admin_client, "c.epub", make_chapter_epub(chapters=4)).json()["id"]
    response = admin_client.post(f"/books/{book_id}/progress", data=data, follow_redirects=False)
    assert response.status_code == 303
    percentage = admin_client.get(f"/api/books/{book_id}/position").json()["percentage"]
    if expected is None:
        assert 0.2 < percentage < 0.3  # chapter 2 of 4
    else:
        assert percentage == expected


def test_progress_dialog_defaults_to_chapter_0_when_not_started(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "c.epub", make_chapter_epub(chapters=4)).json()["id"]
    page = admin_client.get(f"/books/{book_id}").text
    assert 'name="chapter" type="number" step="1" inputmode="numeric" value="0"' in page
    assert "novalidate" in page and 'max="' not in page.split("progress-form")[1][:3000]
    admin_client.post(f"/books/{book_id}/progress", data={"mode": "chapter", "chapter": "4"})
    page = admin_client.get(f"/books/{book_id}").text
    assert "100%" in page and "4/4</span>" in page and 'value="4"' in page


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


def test_chapters_at_anchors_inside_one_file(admin_client: TestClient) -> None:
    """Calibre-style books keep several chapters per file; the TOC points at anchors."""
    epub = make_chapter_epub(chapters=6, lines=50, per_file=3)
    book = upload(admin_client, "a.epub", epub).json()
    for number in (2, 3, 5, 6):
        admin_client.post(
            f"/books/{book['id']}/progress", data={"mode": "chapter", "chapter": str(number)}
        )
        page = admin_client.get(f"/books/{book['id']}").text
        assert f"{number}/6</span>" in page, number
    position = admin_client.get(f"/api/books/{book['id']}/position").json()
    assert position["percentage"] == 1.0  # the last chapter means finished
    admin_client.post(f"/books/{book['id']}/progress", data={"mode": "chapter", "chapter": "5"})
    position = admin_client.get(f"/api/books/{book['id']}/position").json()
    # Chapter 5 is the second in file 2: its heading is the second <h2> there.
    assert position["progress"] == "/body/DocFragment[2]/body/div/h2[2]"
    assert 0.65 < position["percentage"] < 0.7


def test_chapter_of_a_paragraph_position_between_anchors(admin_client: TestClient) -> None:
    book = upload(
        admin_client, "a.epub", make_chapter_epub(chapters=6, lines=50, per_file=3)
    ).json()
    admin_client.put(
        "/syncs/progress",
        headers=_sync_headers(),
        json={
            "document": _document(admin_client, book["id"]),
            "progress": "/body/DocFragment[1]/body/div/p[60]/text().3",  # in chapter 2
            "percentage": 0.2,
            "device": "Kobo",
            "device_id": "k",
        },
    )
    assert "2/6</span>" in admin_client.get(f"/books/{book['id']}").text


def test_mark_as_finished(admin_client: TestClient) -> None:
    book = upload(
        admin_client, "a.epub", make_chapter_epub(chapters=6, lines=50, per_file=3)
    ).json()
    response = admin_client.post(
        f"/books/{book['id']}/progress",
        data={"mode": "percent", "percent": "3", "finished": "1"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    position = admin_client.get(f"/api/books/{book['id']}/position").json()
    assert position["percentage"] == 1.0
    assert position["progress"] == "/body/DocFragment[2]/body/div/p[150]"  # the last block
    page = admin_client.get(f"/books/{book['id']}").text
    assert "100%" in page and "6/6</span>" in page and "Finished" in page
