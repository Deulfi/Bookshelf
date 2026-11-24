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
from enum import IntEnum
from pathlib import Path
from typing import Any

import httpx

from ..config import Settings


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
    """A thin, synchronous REST client for one lncrawl server and one API token.

    Holds an :class:`httpx.Client` (a connection pool), so close it when done —
    use it as a context manager, or keep one on ``app.state`` for the app's life.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        verify_tls: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self._token = token
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            verify=verify_tls,
            timeout=timeout,
            follow_redirects=True,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> WebnovelClient | None:
        """Build a client from configuration, or None when the feature is unconfigured."""
        if not settings.lncrawl_url or not settings.lncrawl_token:
            return None
        return cls(
            settings.lncrawl_url,
            settings.lncrawl_token,
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

    def download_epub(self, artifact: Artifact, dest: Path) -> Path:
        """Stream the EPUB to ``dest``. The /static guard reads the token from the query
        string (the Authorization header is ignored there), so it is passed as a param."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._http.stream(
                "GET", f"/static/{artifact.output_file}", params={"token": self._token}
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


def mint_token(base_url: str, email: str, password: str, *, verify_tls: bool = True) -> str:
    """One-off helper to obtain an API token for BOOKSHELF_LNCRAWL_TOKEN from a login.

    Run this once (or create a token in lncrawl's web UI) so Bookshelf stores a token
    rather than the account password.
    """
    with httpx.Client(base_url=base_url.rstrip("/"), verify=verify_tls, timeout=30.0) as http:
        login = http.post("/api/auth/login", json={"email": email, "password": password})
        login.raise_for_status()
        token = login.json()["token"]
        created = http.post(
            "/api/auth/me/create-token",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )
        created.raise_for_status()
        return created.json()["token"]
