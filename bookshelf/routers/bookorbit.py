"""The part of BookOrbit's KOReader plugin API that Readest uses for reading statistics.

Readest's BookOrbit integration talks to ``{server}/api/v1/koreader`` with the same
``x-auth-user``/``x-auth-key`` headers as KOReader sync. With only "Sync stats" switched on it
calls ``users/auth`` (when connecting), ``plugin/match-check`` (for each open book) and
``plugin/page-stats`` (page views, like KOReader's ``page_stat_data``). Everything else it may
call (``plugin/version``, annotation and bookmark exchange, book states) is answered with 404,
which Readest treats as a server without that feature. The progress routes are mounted here as
well, so the integration also works with "Sync progress" on.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import DB
from ..models import Book
from ..services import reading_stats
from . import kosync
from .kosync import SyncUser

router = APIRouter(prefix="/api/v1/koreader", tags=["bookorbit"])

MAX_BOOKS_PER_REQUEST = 50  # BookOrbit's limits, which Readest chunks its uploads to
MAX_EVENTS_PER_REQUEST = 500
_HASH = re.compile(r"[0-9a-f]{32}")

router.add_api_route("/users/auth", kosync.authorize, methods=["GET"])
router.add_api_route("/syncs/progress", kosync.update_progress, methods=["PUT"])
router.add_api_route("/syncs/progress/{document}", kosync.get_progress, methods=["GET"])


class DeviceFields(BaseModel):
    deviceId: str = ""  # BookOrbit's field names (camelCase)
    deviceModel: str = ""
    pluginVersion: str = ""


class MatchCheckRequest(DeviceFields):
    hashes: list[str] = Field(default_factory=list, max_length=MAX_BOOKS_PER_REQUEST)


class PageStatsEvent(BaseModel):
    page: int
    startTime: int
    durationSeconds: int
    totalPages: int


class PageStatsBook(BaseModel):
    hash: str
    events: list[PageStatsEvent] = Field(default_factory=list)


class PageStatsRequest(DeviceFields):
    books: list[PageStatsBook] = Field(default_factory=list, max_length=MAX_BOOKS_PER_REQUEST)


def _device_name(payload: DeviceFields) -> str:
    """The session log's source: "Readest" plus the device name the user gave it."""
    model = payload.deviceModel.strip()
    if not payload.pluginVersion.lower().startswith("readest"):
        return model or "BookOrbit client"
    if not model or model.lower() == "readest":
        return "Readest"
    return model if "readest" in model.lower() else f"Readest ({model})"


@router.post("/plugin/match-check")
def match_check(payload: MatchCheckRequest, user: SyncUser, db: DB) -> dict:
    """Every well-formed hash counts as matched: like KOReader's statistics, time is kept for
    books that are not in the library (yet), so Readest never asks to link a book by hand."""
    hashes = [h for h in dict.fromkeys(h.lower() for h in payload.hashes) if _HASH.fullmatch(h)]
    rows = db.execute(
        select(Book.partial_md5, Book.id).where(
            Book.user_id == user.id, Book.partial_md5.in_(hashes)
        )
    )
    book_ids = {md5: book_id for md5, book_id in rows}
    return {
        "matches": [
            {"hash": h, "bookId": book_ids.get(h, 0), "bookFileId": book_ids.get(h, 0)}
            for h in hashes
        ],
        "libraryVersion": "",
    }


@router.post("/plugin/page-stats")
def page_stats(payload: PageStatsRequest, user: SyncUser, db: DB) -> dict:
    if sum(len(book.events) for book in payload.books) > MAX_EVENTS_PER_REQUEST:
        raise HTTPException(400, f"At most {MAX_EVENTS_PER_REQUEST} events per request")
    device = _device_name(payload)
    results, unmatched = [], []
    for book in payload.books:
        document = book.hash.lower()
        if not _HASH.fullmatch(document):
            unmatched.append(book.hash)
            continue
        events = [
            reading_stats.PageEvent(e.startTime, e.page, e.durationSeconds, e.totalPages)
            for e in book.events
        ]
        added = reading_stats.add_page_events(
            db, user.id, document, events, device=device, device_id=payload.deviceId
        )
        results.append({"hash": document, "accepted": added})
    return {"results": results, "unmatched": unmatched}
