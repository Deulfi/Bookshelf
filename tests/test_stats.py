"""Reading statistics parsed from KOReader's statistics database."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import func, select

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


# --- Reading sessions --------------------------------------------------------------------------


def test_web_reader_sessions(admin_client: TestClient) -> None:
    from bookshelf.models import ReadingSession
    from bookshelf.services.reading_stats import SESSION_GAP, add_web_time

    book_id = upload(admin_client, "a.epub", make_epub(title="Dracula")).json()["id"]
    page = admin_client.get(f"/books/{book_id}").text
    assert "Reading sessions" not in page
    md5 = page.split('KOReader document ID</dt><dd class="mono">')[1][:32]
    user_id = _admin_id(admin_client)
    t0 = 1_800_000_000
    with admin_client.app.state.sessionmaker() as db:
        add_web_time(db, user_id, md5, 60, t0, fraction=0.12, previous_fraction=0.10, device_id="a")
        add_web_time(
            db, user_id, md5, 60, t0 + 120, fraction=0.15, previous_fraction=0.12, device_id="a"
        )
        # a long pause, then another sitting; another browser has its own session
        add_web_time(db, user_id, md5, 30, t0 + 120 + SESSION_GAP + 1, fraction=0.2, device_id="a")
        add_web_time(
            db, user_id, md5, 45, t0 + 200, fraction=0.5, previous_fraction=0.15, device_id="b"
        )
        rows = db.scalars(select(ReadingSession).order_by(ReadingSession.id)).all()
    assert [(r.device_id, r.seconds, r.start_fraction, r.end_fraction) for r in rows] == [
        ("a", 120, 0.10, 0.15),
        ("a", 30, 0.2, 0.2),  # without an earlier position, the session starts where it ends
        ("b", 45, 0.15, 0.5),
    ]
    assert rows[0].started_at == t0 - 60 and rows[0].ended_at == t0 + 120

    page = admin_client.get(f"/books/{book_id}").text
    assert "Reading sessions" in page
    assert "10% → 15%" in page and "15% → 50%" in page
    assert "Show more" not in page


def test_reader_position_updates_create_a_session(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "a.epub", make_epub(title="Dracula")).json()["id"]
    _put_position(admin_client, book_id, 0)  # position only: no session
    assert "Reading sessions" not in admin_client.get(f"/books/{book_id}").text
    _put_position(admin_client, book_id, 90)
    page = admin_client.get(f"/books/{book_id}").text
    assert "Reading sessions" in page and "Web reader" in page and "2 min" in page


def test_koreader_sessions_and_paging(admin_client: TestClient, tmp_path: Path) -> None:
    book_id = upload(admin_client, "a.epub", make_epub(title="Dracula")).json()["id"]
    page = admin_client.get(f"/books/{book_id}").text
    md5 = page.split('KOReader document ID</dt><dd class="mono">')[1][:32]
    start = ts(2026, 10, 1, 8)
    reads = []
    for sitting in range(12):  # 12 sittings, a day apart, 3 pages of a minute each
        base = start + sitting * 86400
        reads += [(base + i * 60, sitting * 3 + i + 1, 60) for i in range(3)]
    data = make_statistics_db(
        tmp_path / "statistics.sqlite3",
        [{"title": "Dracula", "md5": md5, "pages": 100, "reads": reads}],
    )
    assert (
        admin_client.put("/webdav/statistics.sqlite3", content=data, auth=ADMIN).status_code == 201
    )

    page = admin_client.get(f"/books/{book_id}").text
    assert page.count('class="session"') == 10
    assert "pages 34–36 of 100" in page  # the newest sitting comes first
    assert "pages 1–3" not in page
    assert f"/books/{book_id}/sessions?offset=10" in page

    more = admin_client.get(f"/books/{book_id}/sessions?offset=10").text
    assert more.count('class="session"') == 2
    assert "pages 1–3 of 100" in more and "Show more" not in more

    admin_client.post("/admin/users", data={"username": "bob", "password": "bobpass1"})
    admin_client.post("/logout")
    admin_client.post("/login", data={"username": "bob", "password": "bobpass1"})
    assert admin_client.get(f"/books/{book_id}/sessions").status_code == 404


def test_session_resume_links(admin_client: TestClient, tmp_path: Path) -> None:
    book_id = upload(admin_client, "a.epub", make_epub(title="Dracula")).json()["id"]
    _put_position(admin_client, book_id, 90)  # web reader: ends at its XPointer, 10%
    page = admin_client.get(f"/books/{book_id}").text
    md5 = page.split('KOReader document ID</dt><dd class="mono">')[1][:32]
    link = (
        f'href="/read/{book_id}?at=%2Fbody%2FDocFragment%5B1%5D%2Fbody%2Fp%5B1%5D'
        f'&amp;fraction=0.100000"'
    )
    assert link in page
    assert "Delete this session" in page

    # KOReader: resume at the last page read / the page count KOReader had then
    reads = [(ts(2026, 10, 1, 8) + i * 60, page_no, 60) for i, page_no in enumerate((5, 6, 30))]
    data = make_statistics_db(
        tmp_path / "statistics.sqlite3",
        [{"title": "Dracula", "md5": md5, "pages": 120, "reads": reads}],
    )
    admin_client.put("/webdav/statistics.sqlite3", content=data, auth=ADMIN)
    page = admin_client.get(f"/books/{book_id}").text
    assert "pages 5–30 of 120" in page
    assert f'href="/read/{book_id}?fraction=0.250000"' in page
    assert page.count('session-delete"') == 1  # KOReader's sessions can't be deleted here

    # The reader opens there and gets the resume target in its bootstrap.
    def bootstrap(url: str) -> dict:
        html = admin_client.get(url).text
        return json.loads(
            html.split('id="reader-bootstrap"')[1].split(">", 1)[1].split("</script>")[0]
        )

    assert bootstrap(f"/read/{book_id}?fraction=0.25")["resume"] == {
        "progress": "",
        "percentage": 0.25,
    }
    assert "resume" not in bootstrap(f"/read/{book_id}")
    assert bootstrap(f"/read/{book_id}?fraction=7")["resume"]["percentage"] == 1.0


def test_delete_web_session_removes_its_time(admin_client: TestClient, client: TestClient) -> None:
    from bookshelf.models import ReadingSession

    book_id = upload(admin_client, "a.epub", make_epub(title="Dracula")).json()["id"]
    _put_position(admin_client, book_id, 25 * 60)
    assert "25 min" in admin_client.get("/stats").text
    with admin_client.app.state.sessionmaker() as db:
        session_id = db.scalar(select(ReadingSession.id))

    # Another user can't delete it, and a session of another book doesn't match this one.
    other = upload(admin_client, "b.epub", make_epub(title="Other")).json()["id"]
    response = admin_client.post(f"/books/{other}/sessions/{session_id}/delete")
    assert response.status_code == 404
    admin_client.post("/admin/users", data={"username": "bob", "password": "bobpass1"})
    client.post("/logout")
    client.post("/login", data={"username": "bob", "password": "bobpass1"})
    assert client.post(f"/books/{book_id}/sessions/{session_id}/delete").status_code == 404
    client.post("/logout")
    client.post("/login", data={"username": ADMIN[0], "password": ADMIN[1]})

    response = admin_client.post(
        f"/books/{book_id}/sessions/{session_id}/delete", follow_redirects=False
    )
    assert response.status_code == 303
    assert "Reading sessions" not in admin_client.get(f"/books/{book_id}").text
    assert "No statistics yet" in admin_client.get("/stats").text  # its time is gone too
    with admin_client.app.state.sessionmaker() as db:
        assert db.scalar(select(func.count()).select_from(WebReadingTime)) == 0
