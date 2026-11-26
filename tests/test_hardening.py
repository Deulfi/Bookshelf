"""Input limits and malformed-input handling (from the 2026-11-26 code review)."""

from __future__ import annotations

import io
import threading
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from bookshelf.models import Book
from bookshelf.routers import library as library_router
from bookshelf.security import md5_hex
from bookshelf.services import chapters, webnovels
from bookshelf.services.files import FileStore, PreconditionFailed
from bookshelf.services.metadata.base import read_member
from bookshelf.services.webnovels import Artifact, WebnovelClient, WebnovelError

from .conftest import ADMIN, make_epub, upload

HEADERS = {"x-auth-user": ADMIN[0], "x-auth-key": md5_hex(ADMIN[1])}


# --- cover upload ----------------------------------------------------------------------------


def test_oversized_cover_is_rejected(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(library_router, "MAX_COVER_UPLOAD_BYTES", 1024)
    book_id = upload(admin_client, "a.epub", make_epub()).json()["id"]
    response = admin_client.post(
        f"/books/{book_id}",
        data={"title": "Changed"},
        files={"cover": ("cover.jpg", b"x" * 2048, "image/jpeg")},
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert "too large" in response.text


# --- KOSync field lengths --------------------------------------------------------------------


def test_kosync_rejects_oversized_fields(admin_client: TestClient) -> None:
    body = {"document": "d" * 129, "progress": "p", "percentage": 0.5}
    response = admin_client.put("/syncs/progress", json=body, headers=HEADERS)
    assert response.status_code == 403
    assert response.json()["code"] == 2003

    body = {"document": "d" * 32, "progress": "p" * 5000, "percentage": 0.5}
    assert admin_client.put("/syncs/progress", json=body, headers=HEADERS).status_code == 403

    body = {"document": "d" * 128, "progress": "p" * 100, "percentage": 0.5}
    assert admin_client.put("/syncs/progress", json=body, headers=HEADERS).status_code == 200


# --- blank form fields -----------------------------------------------------------------------


def test_blank_login_and_setup_rerender_the_page(client: TestClient) -> None:
    setup = client.post("/setup", data={"username": "", "password": "", "password_confirm": ""})
    assert setup.status_code == 422
    assert "text/html" in setup.headers["content-type"]

    client.post(
        "/setup",
        data={"username": "admin", "password": "secret123", "password_confirm": "secret123"},
    )
    client.cookies.clear()
    login = client.post("/login", data={"username": "", "password": ""})
    assert login.status_code == 401
    assert "text/html" in login.headers["content-type"]


# --- chapters: nesting and oversized members -------------------------------------------------


def _nested_epub(depth: int) -> bytes:
    """make_epub's book with a chapter nested deeper than the recursion limit allows."""
    source = zipfile.ZipFile(io.BytesIO(make_epub()))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for info in source.infolist():
            data = source.read(info)
            if info.filename == "OEBPS/text.xhtml":
                nested = "<div>" * depth + "<p>text</p>" + "</div>" * depth
                data = f"<html><body>{nested}</body></html>".encode()
            archive.writestr(info.filename, data)
    return buffer.getvalue()


def test_deeply_nested_chapter_reads_as_unavailable(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "deep.epub", _nested_epub(3000)).json()["id"]
    assert admin_client.get(f"/books/{book_id}").status_code == 200
    with admin_client.app.state.sessionmaker() as db:
        book = db.get(Book, book_id)
        outline = chapters.outline_of(admin_client.app.state.storage, book)
    assert outline is not None
    assert outline.section(0) is None  # RecursionError in the walk is handled, not raised


def test_read_member_refuses_oversized_member() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("big.xml", b"a" * 5000)
        archive.writestr("small.xml", b"<a/>")
    with zipfile.ZipFile(buffer) as archive:
        assert read_member(archive, "small.xml", limit=100) == b"<a/>"
        with pytest.raises(ValueError):
            read_member(archive, "big.xml", limit=100)


# --- WebDAV commit ---------------------------------------------------------------------------


def test_concurrent_if_match_commits_only_one_wins(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    first = store.new_temp_path()
    first.write_bytes(b"v1")
    store.commit(first, "a.sqlite3")
    etag = store.get("a.sqlite3").etag

    results: list[str] = []

    def put(content: bytes) -> None:
        temp = store.new_temp_path()
        temp.write_bytes(content)
        try:
            store.commit(temp, "a.sqlite3", if_match=etag)
            results.append("ok")
        except PreconditionFailed:
            results.append("412")

    threads = [threading.Thread(target=put, args=(b"v%d" % i,)) for i in range(2, 8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count("ok") == 1
    assert results.count("412") == len(threads) - 1


# --- web-novel client ------------------------------------------------------------------------


def _client(handler, **kwargs) -> WebnovelClient:
    client = WebnovelClient("https://lncrawl.test", "u", "p", **kwargs)
    client._http = httpx.Client(
        base_url="https://lncrawl.test", transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.parametrize("url", ["ftp://x.test/a", "javascript:alert(1)", "novel", "http://"])
def test_novel_url_must_be_http(url: str) -> None:
    with pytest.raises(WebnovelError):
        webnovels._clean_url(url)


def test_novel_url_length_and_trim() -> None:
    assert webnovels._clean_url("  https://x.test/n  ") == "https://x.test/n"
    with pytest.raises(WebnovelError):
        webnovels._clean_url("https://x.test/" + "a" * 600)


def test_unexpected_lncrawl_replies_become_webnovel_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/api/job/create"):
            return httpx.Response(200, json={"detail": "nope"})  # no "id"
        if request.url.path.endswith("/artifacts"):
            return httpx.Response(200, json={"detail": "nope"})  # not a list
        return httpx.Response(200, text="<html>not json</html>")

    client = _client(handler)
    with pytest.raises(WebnovelError):
        client.submit_fetch("https://x.test/n")
    with pytest.raises(WebnovelError):
        client.latest_epub("nv")
    with pytest.raises(WebnovelError):
        client.job("j1")


def test_job_with_garbage_progress_parses() -> None:
    job = webnovels.Job.from_json({"id": "j", "status": 1, "progress": "n/a"})
    assert job.progress == 0


def test_download_stops_at_the_size_cap(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"token": "t"})
        return httpx.Response(200, content=b"x" * 10_000)

    artifact = Artifact("nv", "epub", "a.epub", 0, "novels/a.epub", 1)  # size unknown
    dest = tmp_path / "out.epub"
    with pytest.raises(WebnovelError):
        _client(handler, max_download_bytes=1000).download_epub(artifact, dest)
    assert not dest.exists()

    _client(handler, max_download_bytes=20_000).download_epub(artifact, dest)
    assert dest.stat().st_size == 10_000
