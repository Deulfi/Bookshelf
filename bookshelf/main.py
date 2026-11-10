"""Application factory: wires settings, database, storage, routers and error handling."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .config import Settings
from .db import init_database
from .deps import LoginRequired
from .routers import account, admin, auth, kosync, library, opds, reader, stats, webdav
from .services.scanner import LibraryScanner
from .storage import Storage
from .templating import render

STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    storage = Storage(settings.data_dir, settings.ingest_dir)
    storage.ensure_dirs()

    app = FastAPI(title="Bookshelf", version=__version__, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.storage = storage
    app.state.sessionmaker = init_database(settings.database_url)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    for module in (auth, library, reader, stats, account, admin, kosync, opds, webdav):
        app.include_router(module.router)

    app.add_exception_handler(kosync.KosyncError, kosync.kosync_error_handler)
    app.add_exception_handler(LoginRequired, _login_required_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    scanner = LibraryScanner(app.state.sessionmaker, storage, settings.data_dir / "scan.json")
    app.state.scanner = scanner
    scanner.start()  # scans once now, then on the interval chosen in the settings
    return app


async def _login_required_handler(request: Request, _exc: Exception) -> Response:
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": "Not logged in."}, status_code=401)
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
