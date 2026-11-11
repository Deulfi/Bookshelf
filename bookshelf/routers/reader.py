"""Browser reader (foliate-js): the reader page, reading position and reader preferences."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from ..deps import DB, AppStorage, CurrentUser
from ..formats import READABLE_FORMATS
from ..icons import icon
from ..models import ReadingProgress, User
from ..services import library, progress, reader_config, reading_stats
from ..services.library import BookEntry
from ..templating import render

router = APIRouter()


# Icons the reader's bar elements may use; rendered into the page for the scripts to clone.
READER_ICONS = (
    "arrow-left",
    "arrow-right",
    "chevron-left",
    "chevron-right",
    "list",
    "settings",
    "x",
    "sun",
    "maximize",
    "book",
)


def _entry_or_404(db: DB, user: User, book_id: int) -> BookEntry:
    entry = library.get_entry(db, user, book_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Book not found.")
    return entry


@router.get("/read/{book_id}")
def read_book(
    request: Request, db: DB, user: CurrentUser, storage: AppStorage, book_id: int
) -> Response:
    """Read a book in the browser. Everything the reader needs is inlined as JSON."""
    entry = _entry_or_404(db, user, book_id)
    book = entry.book
    if book.format not in READABLE_FORMATS:
        raise HTTPException(status_code=404, detail="This format can't be read in the browser.")
    bootstrap = {
        "book": {
            "id": book.id,
            "document": book.partial_md5,
            "title": book.title,
            "author": book.author,
            "fileUrl": f"/books/{book.id}/file",
            "exitUrl": f"/books/{book.id}",
            "format": book.format,
            "positionUrl": f"/api/books/{book.id}/position",
        },
        "prefsUrl": "/api/reader/prefs",
        "fontsUrl": "/reader/fonts/",
        "config": reader_config.effective_config(storage, user),
        "prefs": reader_config.get_prefs(db, user),
        "plugins": reader_config.plugin_urls(storage),
    }
    return render(
        request,
        "read.html",
        user=user,
        book=book,
        bootstrap=bootstrap,
        reader_icons={name: icon(name, 20) for name in READER_ICONS},
    )


class PositionBody(BaseModel):
    """Position reported by the browser reader. ``progress`` is a KOReader XPointer for EPUBs
    (so KOReader and Readest can open it) or a foliate CFI; ``cfi`` is the older field name."""

    progress: str = Field(default="", max_length=4000)
    cfi: str = Field(default="", max_length=4000)
    fraction: float
    device: str = "Web reader"
    device_id: str = ""
    # Active reading time since the last successful update, for the reading statistics.
    seconds: float = 0


def _position(record: ReadingProgress | None) -> dict[str, Any]:
    if record is None:
        return {"progress": None, "cfi": None, "percentage": None}
    return {
        "progress": record.progress,
        "cfi": record.progress,  # older reader scripts
        "percentage": record.percentage,
        "device": record.device,
        "device_id": record.device_id,
        "timestamp": record.timestamp,
    }


@router.get("/api/books/{book_id}/position")
def get_position(db: DB, user: CurrentUser, book_id: int) -> JSONResponse:
    """Saved reading position for the browser reader, if any."""
    entry = _entry_or_404(db, user, book_id)
    return JSONResponse(_position(progress.get_progress(db, user.id, entry.book.partial_md5)))


@router.put("/api/books/{book_id}/position")
def put_position(body: PositionBody, db: DB, user: CurrentUser, book_id: int) -> JSONResponse:
    """Save the reader position into the KOReader sync record. Foliate's 0–1 fraction becomes
    the record's percentage, in the same units the KOReader sync protocol uses."""
    entry = _entry_or_404(db, user, book_id)
    position = body.progress or body.cfi
    if not position:
        return JSONResponse({"error": "No position given."}, status_code=422)
    record = progress.save_progress(
        db,
        user.id,
        entry.book.partial_md5,
        progress=position,
        percentage=body.fraction,
        device=body.device.strip() or "Web reader",
        device_id=body.device_id.strip(),
    )
    reading_stats.add_web_time(db, user.id, entry.book.partial_md5, body.seconds)
    return JSONResponse(_position(record))


@router.put("/api/reader/prefs")
def put_prefs(db: DB, user: CurrentUser, prefs: Any = Body()) -> JSONResponse:
    """Save the values chosen in the reader's settings panel."""
    try:
        saved = reader_config.save_prefs(db, user, prefs)
    except reader_config.ReaderConfigError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    return JSONResponse(saved)


@router.get("/api/reader/layout")
def layout_editor_data(user: CurrentUser, storage: AppStorage) -> JSONResponse:
    """Everything the bar editor on the settings page needs."""
    return JSONResponse(
        {
            "layout": reader_config.effective_config(storage, user)["layout"],
            "defaultLayout": reader_config.effective_config(storage, None)["layout"],
            "plugins": reader_config.plugin_urls(storage),
            "limits": reader_config.LAYOUT_NUMBERS,
        }
    )


@router.get("/reader/plugins/{name}")
def reader_plugin(_user: CurrentUser, storage: AppStorage, name: str) -> Response:
    """Bar element plugins the server owner placed in ``<data_dir>/reader/plugins/``."""
    path = reader_config.plugin_file(storage, name)
    if path is None:
        raise HTTPException(status_code=404, detail="Plugin not found.")
    return FileResponse(
        path, media_type="text/javascript", headers={"Cache-Control": "private, max-age=86400"}
    )


@router.get("/reader/fonts/{name}")
def reader_font(_user: CurrentUser, storage: AppStorage, name: str) -> Response:
    """Fonts the server owner placed in ``<data_dir>/reader/fonts/`` for use in the config."""
    path = reader_config.font_file(storage, name)
    if path is None:
        raise HTTPException(status_code=404, detail="Font not found.")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})
