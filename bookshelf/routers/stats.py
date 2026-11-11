"""Reading statistics page (KOReader's statistics synced via WebDAV, plus the web reader)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ..deps import DB, AppSettings, AppStorage, CurrentUser
from ..services import library, reading_stats
from ..templating import render

router = APIRouter()


@router.get("/stats")
def stats_page(
    request: Request, db: DB, user: CurrentUser, storage: AppStorage, settings: AppSettings
) -> Response:
    path = reading_stats.statistics_path(storage, user.id)
    stats = reading_stats.load_stats(path, settings.tzinfo, db=db, user_id=user.id)
    books = {}
    if stats:
        books = library.books_by_document(db, user, [b.md5 for b in stats.books if b.md5])
    return render(
        request,
        "stats.html",
        user=user,
        nav="stats",
        stats=stats,
        synced_at=reading_stats.last_synced(path),
        library_books=books,
        webdav_url=str(request.base_url).rstrip("/") + "/webdav",
    )
