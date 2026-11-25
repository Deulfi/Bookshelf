"""The Web novels tab: fetching and refreshing novels through lncrawl.

The lncrawl client is replaced with a scripted fake, so these never touch the network; the
state machine, the real EPUB ingest (import_book / replace_file) and the templates all run.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bookshelf.config import Settings
from bookshelf.main import create_app
from bookshelf.models import Book, User, WebnovelImport
from bookshelf.services import webnovels
from bookshelf.services.webnovels import Artifact, Job, JobStatus

from .conftest import make_chapter_epub, make_epub, upload

URL = "https://novels.test/series/demo"


# --- scripted fake lncrawl client -----------------------------------------------------------


def _running(job_id: str, progress: int) -> Job:
    return Job(
        id=job_id,
        status=JobStatus.RUNNING,
        progress=progress,
        done=False,
        error="",
        title="",
        novel_id=None,
    )


def _done(job_id: str, *, novel_id: str | None = None, title: str = "") -> Job:
    return Job(
        id=job_id,
        status=JobStatus.SUCCESS,
        progress=100,
        done=True,
        error="",
        title=title,
        novel_id=novel_id,
    )


def _failed(job_id: str, error: str) -> Job:
    return Job(
        id=job_id,
        status=JobStatus.FAILED,
        progress=100,
        done=True,
        error=error,
        title="",
        novel_id=None,
    )


class FakeClient:
    """Returns pre-set Job objects per job id and writes ``epub`` as the downloaded EPUB."""

    def __init__(self, epub: bytes, jobs: dict[str, Job], *, novel_id: str = "nv1") -> None:
        self.epub = epub
        self.jobs = jobs
        self.novel_id = novel_id
        self.submitted: list[tuple[str, str]] = []

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def submit_fetch(self, url: str) -> str:
        self.submitted.append(("fetch", url))
        return "job-fetch"

    def submit_make_epub(self, novel_id: str) -> str:
        self.submitted.append(("make", novel_id))
        return "job-render"

    def submit_fetch_latest(self, novel_id: str) -> str:
        self.submitted.append(("latest", novel_id))
        return "job-latest"

    def job(self, job_id: str) -> Job:
        return self.jobs[job_id]

    def cancel_job(self, job_id: str) -> None:
        self.submitted.append(("cancel", job_id))

    def latest_epub(self, novel_id: str) -> Artifact:
        return Artifact(
            novel_id=novel_id,
            fmt="epub",
            file_name="Fetched Novel.epub",
            file_size=len(self.epub),
            output_file=f"novels/{novel_id}/artifacts/Fetched Novel.epub",
            created_at=1,
        )

    def download_epub(self, artifact: Artifact, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.epub)
        return dest


def _use(monkeypatch: pytest.MonkeyPatch, fake: FakeClient) -> None:
    monkeypatch.setattr(
        webnovels.WebnovelClient, "from_settings", classmethod(lambda cls, settings: fake)
    )


# --- fixtures ------------------------------------------------------------------------------


@pytest.fixture
def configured_client(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        lncrawl_url="https://lncrawl.test",
        lncrawl_username="admin",
        lncrawl_password="secret",
    )
    with TestClient(create_app(settings)) as client:
        client.post(
            "/setup",
            data={"username": "admin", "password": "secret123", "password_confirm": "secret123"},
            follow_redirects=False,
        )
        yield client


def _advance_to_done(client: TestClient, record_id: int, *, limit: int = 6) -> WebnovelImport:
    app = client.app
    with app.state.sessionmaker() as db:
        user = db.scalar(select(User))
        record = db.get(WebnovelImport, record_id)
        for _ in range(limit):
            if record.state != "running":
                break
            webnovels.advance(db, app.state.storage, app.state.settings, user, record)
        db.refresh(record)
        db.expunge(record)
        return record


# --- the two-step import -------------------------------------------------------------------


def test_import_creates_a_book_from_the_fetched_epub(
    configured_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClient(
        make_epub(title="Fetched Novel", series=None),
        {"job-fetch": _done("job-fetch", novel_id="nv1"), "job-render": _done("job-render")},
    )
    _use(monkeypatch, fake)
    app = configured_client.app
    with app.state.sessionmaker() as db:
        user = db.scalar(select(User))
        record = webnovels.start_import(db, app.state.settings, user, URL)
        rid = record.id
    assert fake.submitted == [("fetch", URL)]

    record = _advance_to_done(configured_client, rid)
    assert record.state == "ready"
    assert record.novel_id == "nv1"
    assert record.book_id is not None
    assert fake.submitted == [("fetch", URL), ("make", "nv1")]

    with app.state.sessionmaker() as db:
        book = db.get(Book, record.book_id)
        assert book is not None
        assert book.title == "Fetched Novel"
        assert book.format == "epub"
    assert record.title == "Fetched Novel"


def test_a_running_crawl_reports_progress_and_submits_nothing_more(
    configured_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClient(make_epub(), {"job-fetch": _running("job-fetch", 42)})
    _use(monkeypatch, fake)
    app = configured_client.app
    with app.state.sessionmaker() as db:
        user = db.scalar(select(User))
        record = webnovels.start_import(db, app.state.settings, user, URL)
        webnovels.advance(db, app.state.storage, app.state.settings, user, record)
        assert record.state == "running"
        assert record.stage == "fetch"
        assert "42%" in record.message
    assert fake.submitted == [("fetch", URL)]


def test_a_transient_timeout_keeps_the_import_running(
    configured_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A busy/unreachable lncrawl must not fail a crawl it is finishing fine — it retries."""

    class FlakyClient(FakeClient):
        def job(self, job_id: str) -> Job:
            raise webnovels.WebnovelUnavailable("the read operation timed out")

    fake = FlakyClient(make_epub(), {})
    _use(monkeypatch, fake)
    app = configured_client.app
    with app.state.sessionmaker() as db:
        user = db.scalar(select(User))
        record = webnovels.start_import(db, app.state.settings, user, URL)
        webnovels.advance(db, app.state.storage, app.state.settings, user, record)
        assert record.state == "running"  # not failed
        assert "retry" in record.message.lower()


def test_a_blocked_source_marks_the_import_failed(
    configured_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClient(make_epub(), {"job-fetch": _failed("job-fetch", "the site refused")})
    _use(monkeypatch, fake)
    app = configured_client.app
    with app.state.sessionmaker() as db:
        user = db.scalar(select(User))
        record = webnovels.start_import(db, app.state.settings, user, URL)
        rid = record.id
    record = _advance_to_done(configured_client, rid)
    assert record.state == "failed"
    assert "the site refused" in record.message
    assert record.book_id is None


def test_empty_url_is_rejected(configured_client: TestClient) -> None:
    app = configured_client.app
    with app.state.sessionmaker() as db:
        user = db.scalar(select(User))
        with pytest.raises(webnovels.WebnovelError):
            webnovels.start_import(db, app.state.settings, user, "   ")


# --- refresh (fetch-latest) ----------------------------------------------------------------


def _import_one(client: TestClient, monkeypatch: pytest.MonkeyPatch, epub: bytes) -> int:
    fake = FakeClient(
        epub, {"job-fetch": _done("job-fetch", novel_id="nv1"), "job-render": _done("job-render")}
    )
    _use(monkeypatch, fake)
    app = client.app
    with app.state.sessionmaker() as db:
        user = db.scalar(select(User))
        rid = webnovels.start_import(db, app.state.settings, user, URL).id
    _advance_to_done(client, rid)
    return rid


def test_refresh_replaces_the_file_with_new_chapters(
    configured_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    rid = _import_one(configured_client, monkeypatch, make_chapter_epub("Serial", chapters=3))
    app = configured_client.app
    with app.state.sessionmaker() as db:
        book_id = db.get(WebnovelImport, rid).book_id
        before = db.get(Book, book_id).partial_md5

    fake = FakeClient(make_chapter_epub("Serial", chapters=6), {"job-latest": _done("job-latest")})
    _use(monkeypatch, fake)
    with app.state.sessionmaker() as db:
        user = db.scalar(select(User))
        webnovels.start_refresh(db, app.state.settings, user, db.get(WebnovelImport, rid))
    record = _advance_to_done(configured_client, rid)

    assert record.state == "ready"
    assert ("latest", "nv1") in fake.submitted
    with app.state.sessionmaker() as db:
        after = db.get(Book, book_id)
        assert after.partial_md5 != before
        assert after.file_size == len(make_chapter_epub("Serial", chapters=6))


def test_refresh_with_no_new_chapters_is_not_a_failure(
    configured_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    epub = make_chapter_epub("Serial", chapters=3)
    rid = _import_one(configured_client, monkeypatch, epub)
    app = configured_client.app

    fake = FakeClient(epub, {"job-latest": _done("job-latest")})  # identical EPUB
    _use(monkeypatch, fake)
    with app.state.sessionmaker() as db:
        user = db.scalar(select(User))
        webnovels.start_refresh(db, app.state.settings, user, db.get(WebnovelImport, rid))
    record = _advance_to_done(configured_client, rid)
    assert record.state == "ready"
    assert "same file" in record.message


# --- the tab, router and templates ---------------------------------------------------------


def test_tab_hidden_until_configured(admin_client: TestClient) -> None:
    assert "/webnovels" not in admin_client.get("/").text
    page = admin_client.get("/webnovels")
    assert page.status_code == 200
    assert "Not set up yet" in page.text


def test_tab_shown_when_configured(configured_client: TestClient) -> None:
    assert "/webnovels" in configured_client.get("/").text
    page = configured_client.get("/webnovels")
    assert "Add web novel" in page.text


def test_tab_load_catches_up_a_finished_import(
    configured_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClient(
        make_epub(title="CaughtUp", series=None),
        {"job-fetch": _done("job-fetch", novel_id="nv1"), "job-render": _done("job-render")},
    )
    _use(monkeypatch, fake)
    app = configured_client.app
    with app.state.sessionmaker() as db:
        user = db.scalar(select(User))
        rid = webnovels.start_import(db, app.state.settings, user, URL).id

    # Load the tab without ever hitting the status poll — as if returning after leaving.
    configured_client.get("/webnovels")
    with app.state.sessionmaker() as db:
        record = db.get(WebnovelImport, rid)
        assert record.state == "ready"
        assert db.get(Book, record.book_id).title == "CaughtUp"


def test_add_then_poll_renders_cards_and_imports(
    configured_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The crawl is still running when the tab first loads, so the card shows "Working".
    fake = FakeClient(
        make_epub(title="Polled Novel", series=None), {"job-fetch": _running("job-fetch", 10)}
    )
    _use(monkeypatch, fake)

    added = configured_client.post("/webnovels", data={"url": URL}, follow_redirects=False)
    assert added.status_code == 303
    listing = configured_client.get("/webnovels").text
    assert URL in listing and "Working" in listing

    with configured_client.app.state.sessionmaker() as db:
        rid = db.scalar(select(WebnovelImport.id))

    # The crawl and render finish on lncrawl; each poll advances one step.
    fake.jobs["job-fetch"] = _done("job-fetch", novel_id="nv1")
    fake.jobs["job-render"] = _done("job-render")
    first = configured_client.get(f"/webnovels/{rid}/status").text
    assert "hx-get" in first  # fetch done -> rendering; still polling
    second = configured_client.get(f"/webnovels/{rid}/status").text
    assert "hx-get" not in second  # imported: polling stops

    with configured_client.app.state.sessionmaker() as db:
        record = db.get(WebnovelImport, rid)
        assert record.state == "ready"
        assert db.get(Book, record.book_id).title == "Polled Novel"


def test_cancel_stops_a_running_import(
    configured_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClient(make_epub(), {"job-fetch": _running("job-fetch", 10)})
    _use(monkeypatch, fake)
    app = configured_client.app
    with app.state.sessionmaker() as db:
        user = db.scalar(select(User))
        rid = webnovels.start_import(db, app.state.settings, user, URL).id

    resp = configured_client.post(f"/webnovels/{rid}/cancel", follow_redirects=False)
    assert resp.status_code == 303
    assert ("cancel", "job-fetch") in fake.submitted
    with app.state.sessionmaker() as db:
        record = db.get(WebnovelImport, rid)
        assert record.state == "canceled"
        assert record.job_id is None


def test_add_empty_url_shows_an_error(configured_client: TestClient) -> None:
    response = configured_client.post("/webnovels", data={"url": ""}, follow_redirects=False)
    assert response.status_code == 422
    assert "Enter a novel URL" in response.text


def test_delete_removes_the_record_but_keeps_the_book(
    configured_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    rid = _import_one(configured_client, monkeypatch, make_epub(series=None))
    with configured_client.app.state.sessionmaker() as db:
        book_id = db.get(WebnovelImport, rid).book_id

    assert (
        configured_client.post(f"/webnovels/{rid}/delete", follow_redirects=False).status_code
        == 303
    )
    with configured_client.app.state.sessionmaker() as db:
        assert db.get(WebnovelImport, rid) is None
        assert db.get(Book, book_id) is not None


def test_link_existing_book_enables_updates(
    configured_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    book_id = upload(configured_client, "local.epub", make_epub(title="Local", series=None)).json()[
        "id"
    ]
    fake = FakeClient(
        make_chapter_epub("Local", 4),
        {"job-fetch": _done("job-fetch", novel_id="nv9"), "job-render": _done("job-render")},
    )
    _use(monkeypatch, fake)

    resp = configured_client.post(
        f"/books/{book_id}/link", data={"url": URL}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/webnovels"

    with configured_client.app.state.sessionmaker() as db:
        rid = db.scalar(select(WebnovelImport.id).where(WebnovelImport.book_id == book_id))
    record = _advance_to_done(configured_client, rid)
    assert record.state == "ready"
    assert record.book_id == book_id
    assert record.novel_id == "nv9"
    page = configured_client.get(f"/books/{book_id}").text
    assert f"/webnovels/{rid}/refresh" in page


def test_link_rejects_an_already_linked_book(
    configured_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    book_id = upload(configured_client, "local.epub", make_epub(series=None)).json()["id"]
    fake = FakeClient(make_epub(), {"job-fetch": _done("job-fetch", novel_id="nv1")})
    _use(monkeypatch, fake)
    first = configured_client.post(
        f"/books/{book_id}/link", data={"url": URL}, follow_redirects=False
    )
    assert first.status_code == 303
    second = configured_client.post(
        f"/books/{book_id}/link", data={"url": URL}, follow_redirects=False
    )
    assert second.status_code == 422
    assert "already linked" in second.text


def test_link_empty_url_errors(configured_client: TestClient) -> None:
    book_id = upload(configured_client, "local.epub", make_epub(series=None)).json()["id"]
    resp = configured_client.post(
        f"/books/{book_id}/link", data={"url": ""}, follow_redirects=False
    )
    assert resp.status_code == 422
    assert "Enter a novel URL" in resp.text


def test_book_page_offers_link_when_configured(configured_client: TestClient) -> None:
    book_id = upload(configured_client, "local.epub", make_epub(series=None)).json()["id"]
    assert 'data-dialog-open="link-dialog"' in configured_client.get(f"/books/{book_id}").text


def test_book_page_shows_the_refresh_button(
    configured_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    rid = _import_one(configured_client, monkeypatch, make_epub(series=None))
    with configured_client.app.state.sessionmaker() as db:
        book_id = db.get(WebnovelImport, rid).book_id
    page = configured_client.get(f"/books/{book_id}").text
    assert f"/webnovels/{rid}/refresh" in page
    assert "Check for new chapters" in page
