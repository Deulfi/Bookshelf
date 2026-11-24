"""Web-novel ingestion through a remote lncrawl server (lightnovel-crawler >= 4.x).

Bookshelf treats a web novel as a file like any other: it asks an lncrawl instance
to crawl a source URL and render an EPUB, downloads that EPUB, then hands it to
``library.import_book`` (new novel) or ``library.replace_file`` (refresh with new
chapters) exactly as an upload would be. Nothing about Bookshelf's file-based model,
KOReader sync or OPDS changes — the novel is just another EPUB once it lands.

This service owns ONLY the conversation with lncrawl. It never touches the database
or FastAPI, in keeping with the service layer. It talks to lncrawl's REST API over
httpx and raises :class:`WebnovelError` (user-facing message) for the router to turn
into a response.

A crawl runs for minutes on the lncrawl side, so the flow is submit-then-poll:

    client = WebnovelClient.from_settings(settings)      # None if not configured
    job_id = client.submit_fetch(url)                    # returns immediately
    job = client.wait_for_job(job_id)                    # BACKGROUND worker only
    novel_id = job.novel_id
    client.wait_for_job(client.submit_make_epub(novel_id))
    art = client.latest_epub(novel_id)
    client.download_epub(art, dest_path)                 # -> hand to library.import_book

``wait_for_job`` blocks; never call it from a request handler. Drive it from a
background thread/worker and store ``novel_id`` on the book so the refresh button can
call ``submit_fetch_latest(novel_id)`` later.

Contract verified live against lncrawl 4.14.0; see scripts/lncrawl_client.py for a
standalone probe of the same endpoints.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import IntEnum
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Book, User, WebnovelImport
from ..storage import Storage
from . import library


class WebnovelError(Exception):
    """A web-novel import error carrying a user-facing message."""


class WebnovelJobError(WebnovelError):
    """An lncrawl job did not reach SUCCESS (often: the source blocked the crawl)."""


class JobStatus(IntEnum):
    PENDING = 0
    RUNNING = 1
    SUCCESS = 2
    FAILED = 3
    CANCELED = 4
    PAUSED = 5


@dataclass(frozen=True)
class Job:
    """A crawl/render job. ``novel_id`` is only set once a fetch job has succeeded."""

    id: str
    status: JobStatus
    progress: int
    done: bool
    error: str
    title: str
    novel_id: str | None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Job:
        extra = data.get("extra") or {}
        try:
            status = JobStatus(data["status"])
        except (KeyError, ValueError):
            status = JobStatus.FAILED
        return cls(
            id=data.get("id", ""),
            status=status,
            progress=int(data.get("progress", 0)),
            done=bool(data.get("is_done")),
            error=data.get("error") or extra.get("failure_detail") or "",
            title=data.get("job_title", ""),
            novel_id=extra.get("novel_id"),
        )


@dataclass(frozen=True)
class Artifact:
    """A produced file for a novel. ``output_file`` is the path under ``/static/``."""

    novel_id: str
    fmt: str
    file_name: str
    file_size: int
    output_file: str
    created_at: int

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Artifact:
        return cls(
            novel_id=data.get("novel_id", ""),
            fmt=data.get("format", ""),
            file_name=data.get("file_name", ""),
            file_size=int(data.get("file_size", 0)),
            output_file=data.get("output_file", ""),
            created_at=int(data.get("created_at", 0)),
        )


ProgressHook = Callable[[Job], None]


class WebnovelClient:
    """A thin, synchronous REST client for one lncrawl server and one account.

    lncrawl authenticates API calls with HTTP Basic (the account's username/email and
    password); its short-lived "API tokens" are not accepted as bearer credentials. The
    EPUB download is the exception: ``/static`` ignores the Authorization header and wants
    a login token in the query string, so the client logs in for that one call.

    Holds an :class:`httpx.Client` (a connection pool), so close it when done —
    use it as a context manager, or keep one on ``app.state`` for the app's life.
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        verify_tls: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self._username = username
        self._password = password
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            auth=httpx.BasicAuth(username, password),
            verify=verify_tls,
            timeout=timeout,
            follow_redirects=True,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> WebnovelClient | None:
        """Build a client from configuration, or None when the feature is unconfigured."""
        if not (settings.lncrawl_url and settings.lncrawl_username and settings.lncrawl_password):
            return None
        return cls(
            settings.lncrawl_url,
            settings.lncrawl_username,
            settings.lncrawl_password,
            verify_tls=settings.lncrawl_verify_tls,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> WebnovelClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- low level ----------------------------------------------------------------------------

    def _json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        try:
            resp = self._http.request(method, path, json=payload)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise WebnovelError(
                f"The web-novel server rejected the request ({exc.response.status_code})."
            ) from exc
        except httpx.HTTPError as exc:
            raise WebnovelError(f"Could not reach the web-novel server: {exc}.") from exc

    # -- submitting jobs ----------------------------------------------------------------------

    def submit_fetch(self, url: str) -> str:
        """Start crawling a novel and its chapters. Returns the job id to poll."""
        job = self._json("POST", "/api/job/create/fetch-novels", {"urls": [url], "full": True})
        return job["id"]

    def submit_make_epub(self, novel_id: str) -> str:
        """Start rendering a crawled novel to EPUB. Returns the job id to poll."""
        payload = {"novel_id": novel_id, "formats": ["epub"]}
        return self._json("POST", "/api/job/create/make-artifacts", payload)["id"]

    def submit_fetch_latest(self, novel_id: str) -> str:
        """Refresh metadata, pull new chapters and re-render, in one job (the refresh button)."""
        payload = {"novel_id": novel_id}
        return self._json("POST", "/api/job/create/fetch-latest", payload)["id"]

    # -- polling ------------------------------------------------------------------------------

    def job(self, job_id: str) -> Job:
        return Job.from_json(self._json("GET", f"/api/job/{job_id}"))

    def cancel_job(self, job_id: str) -> None:
        self._json("POST", f"/api/job/{job_id}/cancel")

    def wait_for_job(
        self,
        job_id: str,
        *,
        interval: float = 3.0,
        on_progress: ProgressHook | None = None,
    ) -> Job:
        """Poll until the job finishes. Returns it on SUCCESS, else raises WebnovelJobError.

        Blocks for the length of the crawl — call this from a background worker, never
        from a request handler.
        """
        while True:
            job = self.job(job_id)
            if on_progress is not None:
                on_progress(job)
            if job.done:
                if job.status is JobStatus.SUCCESS:
                    return job
                raise WebnovelJobError(
                    job.error or f"The crawl did not finish ({job.status.name.lower()})."
                )
            time.sleep(interval)

    # -- artifacts ----------------------------------------------------------------------------

    def latest_epub(self, novel_id: str) -> Artifact:
        """The newest EPUB for a novel. Look up by novel_id — not by the submitted job id,
        whose artifacts are produced by a child job."""
        data = self._json("GET", f"/api/novel/{novel_id}/artifacts")
        epubs = [
            Artifact.from_json(a)
            for a in data
            if a.get("format") == "epub" and a.get("is_available")
        ]
        if not epubs:
            raise WebnovelError("The web-novel server produced no EPUB for this novel.")
        return max(epubs, key=lambda a: a.created_at)

    def _login_token(self) -> str:
        """A short-lived login token for the one endpoint (``/static``) that needs it."""
        try:
            resp = self._http.post(
                "/api/auth/login", json={"email": self._username, "password": self._password}
            )
            resp.raise_for_status()
            return resp.json()["token"]
        except httpx.HTTPError as exc:
            raise WebnovelError(f"Could not sign in to the web-novel server: {exc}.") from exc

    def download_epub(self, artifact: Artifact, dest: Path) -> Path:
        """Stream the EPUB to ``dest``. The /static guard reads the token from the query
        string (the Authorization header is ignored there), so a login token is passed."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        token = self._login_token()
        try:
            with self._http.stream(
                "GET", f"/static/{artifact.output_file}", params={"token": token}
            ) as resp:
                resp.raise_for_status()
                with dest.open("wb") as fh:
                    for chunk in resp.iter_bytes(1024 * 64):
                        fh.write(chunk)
        except httpx.HTTPError as exc:
            dest.unlink(missing_ok=True)
            raise WebnovelError(f"Could not download the EPUB: {exc}.") from exc
        if artifact.file_size and dest.stat().st_size != artifact.file_size:
            dest.unlink(missing_ok=True)
            raise WebnovelError("The downloaded EPUB was incomplete; try again.")
        return dest


# --- Orchestration (DB-backed; drives the two-step import and the refresh) ------------------
#
# A web novel runs through its lncrawl jobs entirely in that server; Bookshelf tracks one
# WebnovelImport row and advances it a step at a time, driven by the Webnovels tab polling
# ``advance`` every 30s. No background threads: each poll is a quick request that checks the
# current job and, when it finishes, either starts the next one or imports the finished EPUB.

_LOG_LINES = 50


def list_imports(db: Session, user: User) -> list[WebnovelImport]:
    return list(
        db.scalars(
            select(WebnovelImport)
            .where(WebnovelImport.user_id == user.id)
            .order_by(WebnovelImport.created_at.desc(), WebnovelImport.id.desc())
        )
    )


def get_import(db: Session, user: User, import_id: int) -> WebnovelImport | None:
    return db.scalar(
        select(WebnovelImport).where(
            WebnovelImport.id == import_id, WebnovelImport.user_id == user.id
        )
    )


def for_book(db: Session, user: User, book_id: int) -> WebnovelImport | None:
    return db.scalar(
        select(WebnovelImport).where(
            WebnovelImport.book_id == book_id, WebnovelImport.user_id == user.id
        )
    )


def delete_import(db: Session, record: WebnovelImport) -> None:
    """Remove the tracking row only; the imported book, if any, stays in the library."""
    db.delete(record)
    db.commit()


def cancel_import(
    db: Session, settings: Settings, user: User, record: WebnovelImport
) -> WebnovelImport:
    """Stop a running fetch. Tells lncrawl to cancel the job (best effort) and marks it here."""
    if record.state != "running":
        return record
    client = WebnovelClient.from_settings(settings)
    if client is not None and record.job_id:
        try:
            with client:
                client.cancel_job(record.job_id)
        except WebnovelError:
            pass  # cancel is best effort; mark it canceled locally regardless
    record.state = "canceled"
    record.job_id = None
    _log(record, "Canceled.")
    db.commit()
    return record


def start_import(db: Session, settings: Settings, user: User, url: str) -> WebnovelImport:
    """Submit a crawl for ``url`` and create the tracking row (state=running, stage=fetch)."""
    url = (url or "").strip()
    if not url:
        raise WebnovelError("Enter a novel URL.")
    client = _client_or_error(settings)
    with client:
        job_id = client.submit_fetch(url)
    record = WebnovelImport(
        user_id=user.id,
        source_url=url,
        title=url,
        job_id=job_id,
        state="running",
        stage="fetch",
    )
    _log(record, "Queued the crawl.")
    db.add(record)
    db.commit()
    return record


def link_book(db: Session, settings: Settings, user: User, book: Book, url: str) -> WebnovelImport:
    """Link an existing book to a web source so it can be updated. Submits a crawl; when it
    finishes, the book's file is replaced with lncrawl's EPUB (or left as-is if identical), and
    the book gains a novel id for future refreshes. Transferred web novels resume this way."""
    url = (url or "").strip()
    if not url:
        raise WebnovelError("Enter a novel URL.")
    if for_book(db, user, book.id) is not None:
        raise WebnovelError("This book is already linked to a web source.")
    client = _client_or_error(settings)
    with client:
        job_id = client.submit_fetch(url)
    record = WebnovelImport(
        user_id=user.id,
        book_id=book.id,
        source_url=url,
        title=book.title,
        job_id=job_id,
        state="running",
        stage="fetch",
    )
    _log(record, "Linking to the web source.")
    db.add(record)
    db.commit()
    return record


def start_refresh(
    db: Session, settings: Settings, user: User, record: WebnovelImport
) -> WebnovelImport:
    """Re-run the novel through lncrawl's fetch-latest (new chapters, then a fresh EPUB)."""
    if record.state == "running":
        return record
    if not record.novel_id:
        raise WebnovelError("This novel can't be refreshed yet.")
    client = _client_or_error(settings)
    with client:
        job_id = client.submit_fetch_latest(record.novel_id)
    record.job_id = job_id
    record.state = "running"
    record.stage = "render"
    _log(record, "Checking for new chapters.")
    db.commit()
    return record


def advance(
    db: Session, storage: Storage, settings: Settings, user: User, record: WebnovelImport
) -> WebnovelImport:
    """Move a running import forward by one lncrawl job; a no-op once it is ready or failed."""
    if record.state != "running" or not record.job_id:
        return record
    client = WebnovelClient.from_settings(settings)
    if client is None:
        _fail(db, record, "Web-novel fetching is not configured.")
        return record
    try:
        with client:
            job = client.job(record.job_id)
            if not job.done:
                record.message = _running_message(record, job)
                db.commit()
                return record
            if job.status is not JobStatus.SUCCESS:
                _fail(db, record, job.error or "The crawl did not finish.")
                return record
            if record.stage == "fetch":
                _after_fetch(db, record, client, job)
            else:
                _ingest(db, storage, settings, user, record, client)
    except WebnovelError as exc:
        _fail(db, record, str(exc))
    return record


def catch_up(db: Session, storage: Storage, settings: Settings, user: User) -> None:
    """Advance every running import as far as it can go now. Called when the Web novels tab
    loads, so a crawl that finished on lncrawl while the tab was closed is picked up at once
    instead of waiting for the next poll (polling only runs while the tab is open)."""
    for record in list_imports(db, user):
        if record.state != "running":
            continue
        for _ in range(6):  # fetch -> render -> download is a few steps; bounded for safety
            before = (record.state, record.stage, record.job_id)
            advance(db, storage, settings, user, record)
            if record.state != "running" or (record.state, record.stage, record.job_id) == before:
                break


def _client_or_error(settings: Settings) -> WebnovelClient:
    client = WebnovelClient.from_settings(settings)
    if client is None:
        raise WebnovelError("Web-novel fetching is not configured.")
    return client


def _after_fetch(db: Session, record: WebnovelImport, client: WebnovelClient, job: Job) -> None:
    novel_id = job.novel_id or record.novel_id
    if not novel_id:
        _fail(db, record, "The crawl finished without a novel id.")
        return
    record.novel_id = novel_id
    record.job_id = client.submit_make_epub(novel_id)
    record.stage = "render"
    _log(record, "Crawl finished; building the EPUB.")
    db.commit()


def _ingest(
    db: Session,
    storage: Storage,
    settings: Settings,
    user: User,
    record: WebnovelImport,
    client: WebnovelClient,
) -> None:
    artifact = client.latest_epub(record.novel_id or "")
    temp = storage.new_temp_path()
    try:
        client.download_epub(artifact, temp)
        with temp.open("rb") as handle:
            if record.book_id is None:
                _create_book(db, storage, settings, user, record, artifact.file_name, handle)
            else:
                _replace_book(db, storage, settings, record, artifact.file_name, handle)
    finally:
        temp.unlink(missing_ok=True)


def _create_book(
    db: Session,
    storage: Storage,
    settings: Settings,
    user: User,
    record: WebnovelImport,
    filename: str,
    handle: Any,
) -> None:
    try:
        book = library.import_book(
            db, storage, user, filename, handle, max_bytes=settings.max_upload_bytes
        )
    except library.DuplicateBookError as exc:
        record.book_id = exc.book.id
        record.title = exc.book.title
        _finish(db, record, "This novel is already in your library.")
        return
    except library.LibraryError as exc:
        _fail(db, record, str(exc))
        return
    record.book_id = book.id
    record.title = book.title
    _finish(db, record, "Imported the EPUB.")


def _replace_book(
    db: Session,
    storage: Storage,
    settings: Settings,
    record: WebnovelImport,
    filename: str,
    handle: Any,
) -> None:
    book = db.get(Book, record.book_id)
    if book is None:
        _fail(db, record, "The book is no longer in your library.")
        return
    try:
        library.replace_file(
            db, storage, book, filename, handle, max_bytes=settings.max_upload_bytes
        )
    except library.LibraryError as exc:
        # The fresh EPUB may be identical (no new chapters) — not a failure.
        record.title = book.title
        _finish(db, record, str(exc))
        return
    record.title = book.title
    _finish(db, record, "Updated with the latest chapters.")


def _running_message(record: WebnovelImport, job: Job) -> str:
    what = "Crawling chapters" if record.stage == "fetch" else "Building the EPUB"
    return f"{what}… {job.progress}%"[:500]


def _finish(db: Session, record: WebnovelImport, message: str) -> None:
    record.state = "ready"
    record.stage = "done"
    record.job_id = None
    _log(record, message)
    db.commit()


def _fail(db: Session, record: WebnovelImport, message: str) -> None:
    record.state = "failed"
    record.job_id = None
    _log(record, message)
    db.commit()


def _log(record: WebnovelImport, message: str) -> None:
    record.message = message[:500]
    stamp = datetime.now(UTC).strftime("%H:%M")
    lines = record.log.splitlines() if record.log else []
    lines.append(f"{stamp} {message}")
    record.log = "\n".join(lines[-_LOG_LINES:])[:4000]
