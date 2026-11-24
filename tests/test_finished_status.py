"""The "finished" reading status: percentage for normal books, chapter position for long ones."""

from __future__ import annotations

from fastapi.testclient import TestClient

from bookshelf.models import Book, ReadingProgress
from bookshelf.services.library import BookEntry

from .conftest import make_chapter_epub, upload


def _entry(spine_length: int | None, docfragment: int, percentage: float) -> BookEntry:
    book = Book(title="t", spine_length=spine_length)
    progress = ReadingProgress(
        user_id=1,
        document="d",
        progress=f"/body/DocFragment[{docfragment}]/body/p[1]",
        percentage=percentage,
        timestamp=0,
    )
    return BookEntry(book=book, progress=progress)


def test_long_book_is_not_finished_before_its_last_chapter() -> None:
    # 421/426 chapters is 98.8% — past the percentage threshold, but not the last chapter.
    assert _entry(426, 421, 0.988).status == "reading"


def test_long_book_is_finished_in_its_last_chapter() -> None:
    assert _entry(426, 426, 0.99).status == "finished"


def test_short_book_uses_the_percentage_threshold() -> None:
    assert _entry(10, 9, 0.985).status == "finished"
    assert _entry(10, 5, 0.5).status == "reading"


def test_book_without_a_spine_length_uses_percentage() -> None:
    assert _entry(None, 300, 0.99).status == "finished"


def test_unread_when_no_progress() -> None:
    assert _entry(426, 1, 0.0).status == "unread"


def test_library_filter_keeps_a_long_mid_book_out_of_finished(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "web.epub", make_chapter_epub("LongSerial", 3)).json()["id"]
    with admin_client.app.state.sessionmaker() as db:
        book = db.get(Book, book_id)
        book.spine_length = 426  # pretend it is a long web novel
        db.add(
            ReadingProgress(
                user_id=book.user_id,
                document=book.partial_md5,
                progress="/body/DocFragment[421]/body",
                percentage=0.988,
                timestamp=1,
            )
        )
        db.commit()
    assert "LongSerial" in admin_client.get("/?status=reading").text
    assert "LongSerial" not in admin_client.get("/?status=finished").text
