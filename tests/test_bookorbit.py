"""The BookOrbit-compatible routes Readest uses to push reading statistics."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from bookshelf.models import ReadingSession, WebReadingTime
from bookshelf.security import md5_hex
from bookshelf.services.reading_stats import SESSION_GAP

from .conftest import ADMIN, make_epub, upload

BASE = "/api/v1/koreader"
HEADERS = {"x-auth-user": ADMIN[0], "x-auth-key": md5_hex(ADMIN[1])}
DEVICE = {"deviceId": "dev-1", "deviceModel": "Pixel", "pluginVersion": "readest-0.9.1"}
T0 = 1_800_000_000  # the start of an hour


def _md5(client: TestClient, book_id: int) -> str:
    page = client.get(f"/books/{book_id}").text
    return page.split('KOReader document ID</dt><dd class="mono">')[1][:32]


def _push(client: TestClient, books: list[dict], headers: dict = HEADERS):
    return client.post(
        f"{BASE}/plugin/page-stats", json={**DEVICE, "books": books}, headers=headers
    )


def _event(start: int, page: int, seconds: int = 60, total: int = 100) -> dict:
    return {"page": page, "startTime": start, "durationSeconds": seconds, "totalPages": total}


def test_auth_and_progress_under_the_bookorbit_prefix(admin_client: TestClient) -> None:
    assert admin_client.get(f"{BASE}/users/auth", headers=HEADERS).json() == {"authorized": "OK"}
    assert admin_client.get(f"{BASE}/users/auth").status_code == 401
    body = {"document": "a" * 32, "progress": "/body/DocFragment[2]", "percentage": 0.4}
    assert admin_client.put(f"{BASE}/syncs/progress", json=body, headers=HEADERS).status_code == 200
    got = admin_client.get(f"{BASE}/syncs/progress/{'a' * 32}", headers=HEADERS).json()
    assert got["percentage"] == 0.4
    # Features Bookshelf doesn't have answer 404, which Readest reads as "not supported".
    assert admin_client.get(f"{BASE}/plugin/version", headers=HEADERS).status_code == 404


def test_match_check_matches_every_hash(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "a.epub", make_epub(title="Dracula")).json()["id"]
    md5 = _md5(admin_client, book_id)
    response = admin_client.post(
        f"{BASE}/plugin/match-check",
        json={**DEVICE, "hashes": [md5.upper(), "b" * 32, "not-a-hash"], "books": []},
        headers=HEADERS,
    )
    assert response.status_code == 200
    matches = response.json()["matches"]
    assert [(m["hash"], m["bookId"]) for m in matches] == [(md5, book_id), ("b" * 32, 0)]
    no_auth = admin_client.post(f"{BASE}/plugin/match-check", json={"hashes": []})
    assert no_auth.status_code == 401


def test_page_stats_become_reading_time_and_sessions(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "a.epub", make_epub(title="Dracula")).json()["id"]
    md5 = _md5(admin_client, book_id)
    first = [_event(T0, 10), _event(T0 + 60, 11), _event(T0 + 120, 12)]
    later = [_event(T0 + 240 + SESSION_GAP + 1, 30, 90)]
    response = _push(admin_client, [{"hash": md5, "events": first + later}])
    assert response.status_code == 200
    assert response.json() == {"results": [{"hash": md5, "accepted": 4}], "unmatched": []}

    # Re-sent events (a retried chunk) are not counted twice; a page that arrives late joins
    # the sitting it belongs to, not the newest one.
    again = _push(admin_client, [{"hash": md5, "events": first[1:] + [_event(T0 + 180, 13)]}])
    assert again.json()["results"][0]["accepted"] == 1

    with admin_client.app.state.sessionmaker() as db:
        hours = db.scalars(select(WebReadingTime)).all()
        sessions = db.scalars(select(ReadingSession).order_by(ReadingSession.started_at)).all()
    assert sum(h.seconds for h in hours) == 4 * 60 + 90
    assert [(s.device, s.device_id, s.seconds) for s in sessions] == [
        ("Readest (Pixel)", "dev-1", 4 * 60),  # the late page joined its sitting
        ("Readest (Pixel)", "dev-1", 90),
    ]
    assert (sessions[0].start_fraction, sessions[0].end_fraction) == (0.10, 0.13)
    assert (sessions[0].started_at, sessions[0].ended_at) == (T0, T0 + 240)

    page = admin_client.get(f"/books/{book_id}").text
    assert "Readest (Pixel)" in page
    assert "10% → 13%" in page


def test_page_stats_skip_bad_events_and_hashes(admin_client: TestClient) -> None:
    response = _push(
        admin_client,
        [
            {"hash": "c" * 32, "events": [_event(0, 1), _event(T0, 1, 0), _event(T0, 2, total=0)]},
            {"hash": "nope", "events": [_event(T0, 1)]},
        ],
    )
    assert response.json() == {
        "results": [{"hash": "c" * 32, "accepted": 0}],
        "unmatched": ["nope"],
    }
    too_many = [{"hash": "c" * 32, "events": [_event(T0 + i, i) for i in range(501)]}]
    assert _push(admin_client, too_many).status_code == 400
    assert _push(admin_client, [], headers={}).status_code == 401


def test_page_stats_are_per_user(admin_client: TestClient) -> None:
    _push(admin_client, [{"hash": "d" * 32, "events": [_event(T0, 1)]}])
    with admin_client.app.state.sessionmaker() as db:
        users = {row.user_id for row in db.scalars(select(WebReadingTime))}
    assert len(users) == 1
