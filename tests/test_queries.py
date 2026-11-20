"""Library queries: SQL-side search, filters, sorting and pagination."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from bookshelf.models import Book, ReadingProgress, author_sort_key
from bookshelf.routers.library import PAGE_SIZE

from .conftest import ADMIN


def add_books(client: TestClient, books: list[dict]) -> None:
    """Insert book rows directly (no files needed for listing tests)."""
    with client.app.state.sessionmaker() as db:
        for i, fields in enumerate(books):
            digest = f"{i:032x}"
            db.add(
                Book(
                    user_id=1,
                    format="epub",
                    original_filename=f"{i}.epub",
                    file_path=f"1/{i}.epub",
                    file_size=1,
                    partial_md5=fields.pop("partial_md5", digest),
                    filename_md5=fields.pop("filename_md5", digest[::-1]),
                    **fields,
                )
            )
        db.commit()


def add_progress(client: TestClient, document: str, percentage: float, timestamp: int) -> None:
    with client.app.state.sessionmaker() as db:
        db.add(
            ReadingProgress(
                user_id=1,
                document=document,
                progress="x",
                percentage=percentage,
                device="Kobo",
                device_id="k",
                timestamp=timestamp,
            )
        )
        db.commit()


def card_titles(html: str) -> list[str]:
    return [chunk.split("</div>")[0] for chunk in html.split('<div class="book-title">')[1:]]


def test_infinite_scroll_pages(admin_client: TestClient) -> None:
    total = PAGE_SIZE * 2 + 5
    add_books(admin_client, [{"title": f"Book {i:03d}"} for i in range(total)])

    first = admin_client.get("/?sort=title")
    assert len(card_titles(first.text)) == PAGE_SIZE
    assert 'class="load-more"' in first.text
    assert "page=2" in first.text

    last = admin_client.get("/?sort=title&page=3", headers={"HX-Request": "true"})
    titles = card_titles(last.text)
    assert titles == [f"Book {i:03d}" for i in range(PAGE_SIZE * 2, total)]
    assert "load-more" not in last.text
    assert "<html" not in last.text


def test_search_is_unicode_case_insensitive(admin_client: TestClient) -> None:
    add_books(
        admin_client,
        [
            {"title": "Jane Eyre", "author": "Charlotte BRONTË"},
            {"title": "Emma", "author": "Jane Austen"},
            {"title": "100% Pure", "author": "Someone"},
        ],
    )
    assert card_titles(admin_client.get("/?q=brontë").text) == ["Jane Eyre"]
    assert card_titles(admin_client.get("/?q=jane eyre").text) == ["Jane Eyre"]
    # LIKE wildcards in the query are matched literally.
    assert card_titles(admin_client.get("/?q=100%").text) == ["100% Pure"]
    assert card_titles(admin_client.get("/?q=%25").text) == ["100% Pure"]


def test_sort_by_author_uses_surname(admin_client: TestClient) -> None:
    add_books(
        admin_client,
        [
            {"title": "Walden", "author": "Henry David Thoreau"},
            {"title": "Emma", "author": "Jane Austen"},
            {"title": "Untitled", "author": None},
            {"title": "Persuasion", "author": "Austen, Jane"},
        ],
    )
    assert card_titles(admin_client.get("/?sort=author").text) == [
        "Emma",
        "Persuasion",
        "Walden",
        "Untitled",
    ]


def test_author_sort_key() -> None:
    assert author_sort_key("Ursula K. Le Guin") == "guin, ursula k. le"
    assert author_sort_key("Austen, Jane") == "austen, jane"
    assert author_sort_key("Homer") == "homer"
    assert author_sort_key("Neil Gaiman & Terry Pratchett") == "gaiman, neil"
    assert author_sort_key(None) is None


def test_status_filters_counts_and_shelf(admin_client: TestClient) -> None:
    add_books(admin_client, [{"title": t} for t in ("Unread", "Reading", "Finished", "ByName")])
    add_progress(admin_client, f"{1:032x}", 0.4, 100)
    add_progress(admin_client, f"{2:032x}", 1.0, 200)
    # Progress reported under the filename hash counts too, and the newest record wins.
    add_progress(admin_client, f"{3:032x}", 0.1, 300)
    add_progress(admin_client, f"{3:032x}"[::-1], 0.5, 400)

    page = admin_client.get("/")
    assert "All <small>4</small>" in page.text
    assert "Reading <small>2</small>" in page.text
    assert "Finished <small>1</small>" in page.text
    assert "Unread <small>1</small>" in page.text

    assert card_titles(admin_client.get("/?status=reading&sort=last_read").text) == [
        "ByName",
        "Reading",
    ]
    assert card_titles(admin_client.get("/?status=finished").text) == ["Finished"]
    assert card_titles(admin_client.get("/?status=unread").text) == ["Unread"]

    book_page = admin_client.get("/books/4")
    assert "50%" in book_page.text


def test_status_filter_is_remembered(admin_client: TestClient) -> None:
    add_books(admin_client, [{"title": t} for t in ("Unread", "Reading")])
    add_progress(admin_client, f"{1:032x}", 0.4, 100)

    def checked(html: str) -> str:
        return re.search(r'name="status" value="(\w+)" checked', html).group(1)

    assert checked(admin_client.get("/").text) == "all"
    admin_client.get("/?status=unread", headers={"HX-Request": "true"})
    # the next visit without a filter shows the one chosen last
    page = admin_client.get("/").text
    assert checked(page) == "unread" and card_titles(page) == ["Unread"]
    assert checked(admin_client.get("/?status=all").text) == "all"
    assert checked(admin_client.get("/").text) == "all"


def test_opds_pagination(admin_client: TestClient) -> None:
    add_books(admin_client, [{"title": f"Book {i:03d}"} for i in range(55)])
    first = admin_client.get("/opds/books?sort=title", auth=ADMIN)
    assert first.text.count("<entry>") == 50
    assert 'rel="next"' in first.text
    second = admin_client.get("/opds/books?sort=title&page=2", auth=ADMIN)
    assert second.text.count("<entry>") == 5
    assert 'rel="next"' not in second.text
