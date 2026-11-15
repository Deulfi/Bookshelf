"""Series grouped into one library card, and the series row on book pages."""

from __future__ import annotations

from fastapi.testclient import TestClient

from bookshelf.models import Book, User

from .test_queries import add_books, add_progress, card_titles


def _series_library(client: TestClient) -> None:
    add_books(
        client,
        [
            {"title": "Foundation", "series": "foundation", "series_index": 1.0},
            {"title": "Foundation and Empire", "series": "Foundation", "series_index": 2.0},
            {"title": "Second Foundation", "series": "Foundation", "series_index": 3.0},
            {"title": "Dune"},
            {"title": "Emma"},
        ],
    )


def test_grouping_shows_one_card_per_series(admin_client: TestClient) -> None:
    _series_library(admin_client)
    assert len(card_titles(admin_client.get("/?sort=title").text)) == 5

    page = admin_client.get("/?sort=title&group_set=true&group=true").text
    # The series card is named after the series; series names match case-insensitively.
    assert card_titles(page) == ["Dune", "Emma", "Foundation"]
    assert 'class="badge-series"' in page and ">3</span>" in page
    assert "3 books" in page
    assert page.count('class="stack-layer') == 2  # the two volumes before the newest one
    assert 'href="/books/3"' in page  # the card opens the newest volume (number 3)
    assert "All <small>5</small>" in page  # the counts still count books


def test_grouping_is_remembered_until_switched_off(admin_client: TestClient) -> None:
    _series_library(admin_client)
    admin_client.get("/?group_set=true&group=true")
    with admin_client.app.state.sessionmaker() as db:
        assert db.query(User).filter_by(username="admin").one().group_series is True
    assert len(card_titles(admin_client.get("/").text)) == 3  # a bare visit keeps grouping

    admin_client.get("/?group_set=true")  # the switch sent unchecked
    assert len(card_titles(admin_client.get("/").text)) == 5


def test_grouping_applies_filters_to_books_first(admin_client: TestClient) -> None:
    _series_library(admin_client)
    add_progress(admin_client, f"{0:032x}", 0.5, 100)  # Foundation (number 1) is being read
    page = admin_client.get("/?status=reading&group_set=true&group=true").text
    assert card_titles(page) == ["Foundation"]
    assert 'class="badge-series"' not in page  # only one matching book: a plain card


def test_grouped_infinite_scroll(admin_client: TestClient) -> None:
    from bookshelf.routers.library import PAGE_SIZE

    add_books(
        admin_client,
        [{"title": f"Book {i:03d}", "series": f"S{i:03d}"} for i in range(PAGE_SIZE + 3)]
        + [{"title": "Extra", "series": "S000", "series_index": 2.0}],
    )
    first = admin_client.get("/?sort=title&group_set=true&group=true")
    assert len(card_titles(first.text)) == PAGE_SIZE and 'class="load-more"' in first.text
    last = admin_client.get(
        "/?sort=title&group_set=true&group=true&page=2", headers={"HX-Request": "true"}
    )
    assert len(card_titles(last.text)) == 3


def test_book_page_lists_the_series(admin_client: TestClient) -> None:
    _series_library(admin_client)
    page = admin_client.get("/books/2").text
    assert "Foundation · 3 books" in page
    assert page.count('<a class="series-card') == 3
    assert 'class="series-card is-current" href="/books/2"' in page
    assert "series-strip" not in admin_client.get("/books/4").text  # no series


def test_series_of_another_user_stay_private(admin_client: TestClient) -> None:
    _series_library(admin_client)
    admin_client.post("/admin/users", data={"username": "bob", "password": "bobpass1"})
    with admin_client.app.state.sessionmaker() as db:
        bob = db.query(User).filter_by(username="bob").one()
        db.add(
            Book(
                user_id=bob.id,
                title="Bob's Foundation",
                series="Foundation",
                series_index=9.0,
                format="epub",
                original_filename="b.epub",
                file_path="b.epub",
                file_size=1,
                partial_md5="b" * 32,
                filename_md5="c" * 32,
            )
        )
        db.commit()
    page = admin_client.get("/books/1").text
    assert "Bob's Foundation" not in page and "3 books" in page
