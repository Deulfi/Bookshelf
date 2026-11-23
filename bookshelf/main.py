"""Application factory: wires settings, database, storage, routers and error handling."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from . import __version__
from .config import Settings
from .db import init_database
from .deps import PEER_KEY, LoginRequired
from .routers import (
    account,
    admin,
    auth,
    bookorbit,
    kosync,
    library,
    opds,
    reader,
    stats,
    webdav,
)
from .services.scanner import LibraryScanner
from .storage import Storage
from .templating import render

STATIC_DIR = Path(__file__).parent / "static"


class VersionedStaticFiles(StaticFiles):
    """Static files. URLs with ``?v=<content hash>`` (see ``templating.static_url``) never change
    their content, so browsers may keep them without asking again."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code == 200 and b"v=" in scope.get("query_string", b""):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


class KeepPeer:
    """Remembers the connection's own address before uvicorn's proxy middleware replaces
    ``client`` with ``X-Forwarded-For``: header logins must come from a listed proxy."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            client = scope.get("client")
            scope[PEER_KEY] = client[0] if client else ""
        await self.app(scope, receive, send)


def create_server() -> ASGIApp:
    """The app as ``python -m bookshelf serve`` runs it: proxy headers are handled here (as
    uvicorn would, trusting ``FORWARDED_ALLOW_IPS``), after keeping the connection address."""
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    trusted = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
    return KeepPeer(ProxyHeadersMiddleware(create_app(), trusted_hosts=trusted))


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _cross_site(request: Request) -> bool:
    """A browser request started by another site. Device clients send neither header."""
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site:
        return fetch_site not in ("same-origin", "none")
    origin = request.headers.get("origin")
    if not origin:
        return False
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    return origin == "null" or urlsplit(origin).netloc != host.split(",")[0].strip()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    storage = Storage(settings.data_dir, settings.ingest_dir, settings.scan_ignore)
    storage.ensure_dirs()

    app = FastAPI(title="Bookshelf", version=__version__, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.storage = storage
    app.state.sessionmaker = init_database(settings.database_url)

    static = VersionedStaticFiles(directory=STATIC_DIR)
    app.mount("/static", GZipMiddleware(static, minimum_size=1024), name="static")
    for module in (auth, library, reader, stats, account, admin, kosync, bookorbit, opds, webdav):
        app.include_router(module.router)

    app.add_exception_handler(kosync.KosyncError, kosync.kosync_error_handler)
    app.add_exception_handler(LoginRequired, _login_required_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)

    if settings.auth != "password":
        # Without a login cookie (SameSite=Lax), nothing else stops another website from
        # posting forms to Bookshelf in the user's browser.
        @app.middleware("http")
        async def reject_cross_site(request: Request, call_next):
            if request.method not in SAFE_METHODS and _cross_site(request):
                return JSONResponse({"error": "Cross-site request refused."}, status_code=403)
            return await call_next(request)

    scanner = LibraryScanner(app.state.sessionmaker, storage, settings.data_dir / "scan.json")
    app.state.scanner = scanner
    scanner.start()  # scans once now, then on the interval chosen in the settings
    return app


async def _login_required_handler(request: Request, _exc: Exception) -> Response:
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": "Not logged in."}, status_code=401)
    settings: Settings = request.app.state.settings
    if settings.auth == "header":  # there is no login page; the proxy signs people in
        detail = f"Not signed in: the request has no {settings.auth_header} header from the proxy."
        return await _http_error_handler(request, StarletteHTTPException(401, detail))
    target = "/login"
    if request.method == "GET" and request.url.path != "/":
        target += "?next=" + quote(
            request.url.path + (f"?{request.url.query}" if request.url.query else "")
        )
    if request.headers.get("HX-Request") == "true":
        return Response(status_code=204, headers={"HX-Redirect": target})
    return RedirectResponse(target, status_code=303)


async def _http_error_handler(request: Request, exc: StarletteHTTPException) -> Response:
    """Friendly HTML error pages for browsers; JSON for everything else."""
    if "text/html" in request.headers.get("accept", ""):
        return render(
            request,
            "error.html",
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
            status=exc.status_code,
            message=exc.detail,
        )
    return await http_exception_handler(request, exc)
