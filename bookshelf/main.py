"""Application factory: wires settings, database, storage, routers and error handling."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .config import Settings
from .db import init_database
from .deps import LoginRequired
from .models import User
from .routers import account, admin, auth, kosync, library, opds, stats, webdav
from .services import library as library_service
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
    for module in (auth, library, stats, account, admin, kosync, opds, webdav):
        app.include_router(module.router)

    app.add_exception_handler(kosync.KosyncError, kosync.kosync_error_handler)
    app.add_exception_handler(LoginRequired, _login_required_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    start_ingest_worker(app, settings, storage)
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


# --- Background ingest worker ---------------------------------------------------------------


class IngestWorker:
    """Background thread that keeps the library folder in sync with the database."""

    def __init__(self, app: FastAPI, storage: Storage) -> None:
        self.app = app
        self.storage = storage
        self.interval = 60.0
        self._thread: threading.Thread | None = None

    def _log(self, message: str) -> None:
        print(f"[ingest] {message}", flush=True)

    def _sync_once(self) -> None:
        with self.app.state.sessionmaker() as db:
            user = db.scalar(select(User).order_by(User.id).limit(1))
            if user is None:
                return
            try:
                count = library_service.sync_library(db, self.storage, user, log=self._log)
            except Exception as error:  # the worker must never take the server down
                self._log(f"error: {error}")
                return
            if count:
                self._log(f"synced {count} new book(s)")

    def _loop(self) -> None:
        while True:
            self._sync_once()
            time.sleep(self.interval)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()


def start_ingest_worker(app: FastAPI, settings: Settings, storage: Storage) -> None:
    if not settings.ingest_dir:
        return  # feature disabled by default
    IngestWorker(app, storage).start()
