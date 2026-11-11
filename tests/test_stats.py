"""Reading statistics parsed from KOReader's statistics database."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select

from bookshelf.models import User, WebReadingTime
from bookshelf.security import md5_hex
from bookshelf.services.reading_stats import (
    MAX_WEB_SECONDS,
    CalendarDay,
    book_stats,
    build_calendar,
    load_stats,
)

from .conftest import ADMIN, make_epub, upload
from .koreader_stats import make_statistics_db

BERLIN = ZoneInfo("Europe/Berlin")


def ts(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=UTC).timestamp())


def test_load_stats_totals_streak_and_timezone(tmp_path: Path) -> None:
    path = tmp_path / "statistics.sqlite3"
    make_statistics_db(
        path,
        [
            {
                "title": "Dracula",
                "authors": "Bram Stoker",
                "md5": "a" * 32,
                "pages": 400,
                "reads": [
                    (ts(2026, 10, 12, 8), 1, 600),
                    (ts(2026, 10, 11, 8), 2, 1200),
                    (ts(2026, 10, 10, 8), 3, 300),
                    # 23:30 UTC on Oct 8 is already Oct 9 in Berlin.
                    (ts(2026, 10, 8, 23, 30), 4, 60),
                    (ts(2025, 12, 31, 8), 5, 120),
                ],
            }
        ],
    )
    stats = load_stats(path, BERLIN, today=date(2026, 10, 12))
    assert stats is not None
    assert stats.total_seconds == 600 + 1200 + 300 + 60 + 120
    assert stats.year_seconds == 600 + 1200 + 300 + 60
    assert stats.week_seconds == 600  # the week starts on Monday, Oct 12
    assert stats.pages_read == 5
    assert stats.days_read == 5
    assert stats.streak_days == 4  # Oct 9–12 in Berlin time
    assert stats.books[0].title == "Dracula"
    assert stats.books[0].seconds_left(0.5) == round(2280 / 5 * 200)

    days = {d.day: d.seconds for week in stats.calendar for d in week.days if d}
    assert days[date(2026, 10, 9)] == 60


def test_streak_continues_from_yesterday(tmp_path: Path) -> None:
    path = tmp_path / "statistics.sqlite3"
    make_statistics_db(
        path,
        [{"title": "X", "reads": [(ts(2026, 10, 11), 1, 60), (ts(2026, 10, 10), 2, 60)]}],
    )
    assert load_stats(path, ZoneInfo("UTC"), today=date(2026, 10, 12)).streak_days == 2


def test_calendar_shape_and_levels() -> None:
    today = date(2026, 10, 14)  # a Wednesday
    calendar = build_calendar({today: 45 * 60}, today, weeks=4)
    assert len(calendar) == 4
    assert all(len(week.days) == 7 for week in calendar)
    assert calendar[0].days[0].day.weekday() == 0
    last_week = calendar[-1].days
    assert last_week[2].day == today and last_week[2].level == 3
    assert last_week[3] is None  # Thursday is in the future
    assert [CalendarDay(today, s).level for s in (0, 60, 20 * 60, 40 * 60, 90 * 60)] == [
        0,
        1,
        2,
        3,
        4,
    ]


def test_corrupt_file_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "statistics.sqlite3"
    path.write_bytes(b"this is not a database")
    assert load_stats(path, ZoneInfo("UTC")) is None


def test_stats_page_and_book_page(admin_client: TestClient, tmp_path: Path) -> None:
    empty = admin_client.get("/stats")
    assert empty.status_code == 200
    assert "No statistics yet" in empty.text
    assert "/webdav" in empty.text

    book_id = upload(admin_client, "a.epub", make_epub(title="Dracula")).json()["id"]
    page = admin_client.get(f"/books/{book_id}").text
    md5 = page.split('KOReader document ID</dt><dd class="mono">')[1][:32]

    now = int(datetime.now(UTC).timestamp())
    data = make_statistics_db(
        tmp_path / "statistics.sqlite3",
        [
            {
                "title": "Dracula",
                "authors": "Ada Lovelace",
                "md5": md5,
                "pages": 100,
                "reads": [(now - 7200 + i * 60, i, 60) for i in range(1, 41)],
            },
            {"title": "Not in library", "md5": "f" * 32, "pages": 10, "reads": [(now, 1, 30)]},
        ],
    )
    response = admin_client.put("/webdav/statistics.sqlite3", content=data, auth=ADMIN)
    assert response.status_code == 201
    admin_client.put(
        "/syncs/progress",
        headers={
            "x-auth-user": "admin",
            "x-auth-key": md5_hex(ADMIN[1]),
        },
        json={
            "document": md5,
            "progress": "x",
            "percentage": 0.4,
            "device": "Kobo",
            "device_id": "k",
        },
    )

    stats_page = admin_client.get("/stats").text
    assert "Total reading time" in stats_page
    assert "40 min" in stats_page
    assert f'href="/books/{book_id}"' in stats_page
    assert "Not in library" in stats_page

    book_page = admin_client.get(f"/books/{book_id}").text
    assert "40 min read" in book_page
    assert "about 1 h left" in book_page  # 60 s/page × 60 remaining pages


# --- Web reader time ---------------------------------------------------------------------------


def _admin_id(client: TestClient) -> int:
    with client.app.state.sessionmaker() as db:
        return db.scalar(select(User.id).where(User.username == ADMIN[0]))


def _put_position(client: TestClient, book_id: int, seconds: float) -> None:
    response = client.put(
        f"/api/books/{book_id}/position",
        json={"progress": "/body/DocFragment[1]/body/p[1]", "fraction": 0.1, "seconds": seconds},
    )
    assert response.status_code == 200


def test_web_time_is_recorded_per_hour_and_clamped(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "a.epub", make_epub(title="Dracula")).json()["id"]
    _put_position(admin_client, book_id, 30)
    _put_position(admin_client, book_id, 45.4)
    _put_position(admin_client, book_id, -100)  # ignored
    _put_position(admin_client, book_id, 999_999)  # clamped to an hour
    with admin_client.app.state.sessionmaker() as db:
        rows = db.scalars(select(WebReadingTime)).all()
    assert len(rows) == 1
    assert rows[0].seconds == 30 + 45 + MAX_WEB_SECONDS
    assert rows[0].last_read > 0


def test_web_time_only(admin_client: TestClient, tmp_path: Path) -> None:
    book_id = upload(admin_client, "a.epub", make_epub(title="Dracula")).json()["id"]
    _put_position(admin_client, book_id, 25 * 60)

    stats_page = admin_client.get("/stats").text
    assert "No statistics yet" not in stats_page
    assert "25 min" in stats_page
    assert f'href="/books/{book_id}"' in stats_page
    assert "0 pages" not in stats_page
    assert "1 day" in stats_page  # streak

    book_page = admin_client.get(f"/books/{book_id}").text
    assert "25 min read" in book_page
    assert " left" not in book_page.split("reading-time")[1][:200]  # no pages, no estimate

    # Another user sees none of it.
    with admin_client.app.state.sessionmaker() as db:
        stats = load_stats(tmp_path / "missing", ZoneInfo("UTC"), db=db, user_id=999)
    assert stats is None


def test_web_time_merges_with_koreader(admin_client: TestClient, tmp_path: Path) -> None:
    book_id = upload(admin_client, "a.epub", make_epub(title="Dracula")).json()["id"]
    page = admin_client.get(f"/books/{book_id}").text
    md5 = page.split('KOReader document ID</dt><dd class="mono">')[1][:32]
    now = int(datetime.now(UTC).timestamp())
    path = tmp_path / "statistics.sqlite3"
    make_statistics_db(
        path,
        [
            {
                "title": "Dracula",
                "md5": md5,
                "pages": 100,
                "reads": [(now - 7200 + i * 60, i, 60) for i in range(1, 11)],
            },
            {"title": "Other", "md5": "f" * 32, "pages": 10, "reads": [(now - 3600, 1, 300)]},
        ],
    )
    _put_position(admin_client, book_id, 20 * 60)

    with admin_client.app.state.sessionmaker() as db:
        user_id = _admin_id(admin_client)
        stats = load_stats(path, ZoneInfo("UTC"), db=db, user_id=user_id)
        book = book_stats(path, md5, db=db, user_id=user_id)
    assert stats.total_seconds == 10 * 60 + 300 + 20 * 60
    assert stats.pages_read == 11  # pages come from KOReader only
    assert [b.title for b in stats.books] == ["Dracula", "Other"]  # one row per book, newest first
    assert stats.books[0].seconds == 30 * 60
    assert stats.books[0].pages_read == 10
    assert book.seconds == 30 * 60
    assert book.seconds_left(0.5) == 60 * 50  # KOReader's 60 s/page, web time left out

    # Without a database the KOReader numbers are unchanged.
    assert load_stats(path, ZoneInfo("UTC")).total_seconds == 10 * 60 + 300
