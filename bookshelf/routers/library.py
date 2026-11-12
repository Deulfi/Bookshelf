"""Library pages (grid, book details) and the upload API used by the web UI."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response

from ..deps import DB, AppSettings, AppStorage, CurrentUser
from ..formats import READABLE_FORMATS
from ..models import Book, User
from ..services import chapters, library, progress, reading_stats
from ..services.library import BookEntry
from ..services.metadata.base import parse_float
from ..templating import render
from ._files import book_file_response, cover_response

router = APIRouter()

PAGE_SIZE = 60  # books per page; more are loaded while scrolling


def _entry_or_404(db: DB, user: User, book_id: int) -> BookEntry:
    entry = library.get_entry(db, user, book_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Book not found.")
    return entry


@router.get("/")
def library_page(
    request: Request,
    db: DB,
    user: CurrentUser,
    q: str = "",
    status: str = "all",
    sort: str = "recent",
    device: bool = False,
    page: int = 1,
) -> Response:
    status = status if status in library.STATUSES else "all"
    sort = sort if sort in library.SORTS else "recent"
    page = max(page, 1)
    result = library.find_books(
        db,
        user,
        text=q,
        status=status,
        sort=sort,
        device_only=device,
        limit=PAGE_SIZE,
        offset=(page - 1) * PAGE_SIZE,
    )
    next_url = None
    if result.has_more:
        url = request.url.include_query_params(page=page + 1)
        next_url = f"{url.path}?{url.query}"

    is_htmx = (
        request.headers.get("HX-Request") == "true"
        and request.headers.get("HX-History-Restore-Request") != "true"
    )
    headers = {"Vary": "HX-Request"}
    if is_htmx and page > 1:  # infinite scroll: just the next batch of cards
        return render(
            request,
            "partials/book_page.html",
            headers=headers,
            entries=result.entries,
            next_url=next_url,
        )

    counts = library.count_by_status(db, user, q)
    show_shelf = not q and status == "all" and not device and page == 1
    context = {
        "user": user,
        "nav": "library",
        "q": q,
        "status": status,
        "sort": sort,
        "device": device,
        "device_count": library.count_device_books(db, user, q),
        "entries": result.entries,
        "next_url": next_url,
        "counts": counts,
        "continue_reading": library.continue_reading(db, user) if show_shelf else [],
        "has_books": counts["all"] > 0 or bool(q),
    }
    # htmx requests (search, filters, refresh after upload) only need the library fragment.
    template = "partials/library.html" if is_htmx else "library.html"
    return render(request, template, headers=headers, **context)


def _may_scan(request: Request, user: User) -> bool:
    """Everyone scans their own folder; the shared ingest folder belongs to the admins."""
    return not request.app.state.scanner.shared or user.is_admin


def _scan_status(request: Request) -> dict[str, object]:
    scanner = request.app.state.scanner
    result = scanner.last_result
    return {
        "running": scanner.running,
        "imported": result.imported if result else 0,
        "removed": result.removed if result else 0,
        "error": result.error if result else None,
    }


@router.post("/api/library/scan")
def start_scan(request: Request, user: CurrentUser) -> JSONResponse:
    """Scan the user's library folder for added or removed files, in the background."""
    if not _may_scan(request, user):
        return JSONResponse({"error": "Only administrators can scan the library folder."}, 403)
    started = request.app.state.scanner.scan_in_background(user.id)
    return JSONResponse({**_scan_status(request), "started": started}, status_code=202)


@router.get("/api/library/scan")
def scan_status(request: Request, _user: CurrentUser) -> JSONResponse:
    return JSONResponse(_scan_status(request))


@router.post("/api/books")
def upload_book(
    db: DB,
    user: CurrentUser,
    storage: AppStorage,
    settings: AppSettings,
    file: Annotated[UploadFile, File()],
) -> JSONResponse:
    try:
        book = library.import_book(
            db,
            storage,
            user,
            file.filename or "upload",
            file.file,
            max_bytes=settings.max_upload_bytes,
        )
    except library.DuplicateBookError as exc:
        return JSONResponse(
            {"error": str(exc), "book_id": exc.book.id, "duplicate": True}, status_code=409
        )
    except library.LibraryError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    return JSONResponse(
        {"id": book.id, "title": book.title, "url": f"/books/{book.id}"}, status_code=201
    )


def _render_book(
    request: Request,
    db: DB,
    storage: AppStorage,
    user: User,
    entry: BookEntry,
    *,
    error: str | None = None,
    progress_error: str | None = None,
) -> Response:
    stats = reading_stats.book_stats(
        reading_stats.statistics_path(storage, user.id),
        entry.book.partial_md5,
        db=db,
        user_id=user.id,
    )
    seconds_left = None
    if stats and entry.status == "reading":
        seconds_left = stats.seconds_left(entry.progress.percentage)
    outline = chapters.outline_of(storage, entry.book)
    chapter = None
    if entry.progress is not None and outline is not None:
        index = chapters.spine_index(entry.progress.progress)
        if index is not None and index >= 0:
            chapter = chapters.chapter_in(outline, index, entry.progress.progress)
    return render(
        request,
        "book.html",
        status_code=422 if error or progress_error else 200,
        user=user,
        nav="library",
        entry=entry,
        book=entry.book,
        stats=stats,
        seconds_left=seconds_left,
        chapter=chapter,
        chapter_total=outline.chapter_total if outline else None,
        chapter_kind="Chapter" if outline and outline.toc else "Section",
        error=error,
        progress_error=progress_error,
        **_sessions_page(request, db, storage, user, entry.book, offset=0),
    )


SESSIONS_PAGE_SIZE = 10


def _sessions_page(
    request: Request, db: DB, storage: AppStorage, user: User, book: Book, *, offset: int
) -> dict:
    """Template values for one page of the book's reading sessions."""
    sessions, more = reading_stats.book_sessions(
        reading_stats.statistics_path(storage, user.id),
        book.partial_md5,
        request.app.state.settings.tzinfo,
        db=db,
        user_id=user.id,
        offset=offset,
        limit=SESSIONS_PAGE_SIZE,
    )
    next_offset = offset + SESSIONS_PAGE_SIZE
    return {
        "sessions": sessions,
        "sessions_more_url": f"/books/{book.id}/sessions?offset={next_offset}" if more else None,
        "sessions_book_id": book.id,
        "sessions_can_resume": book.format in READABLE_FORMATS,
    }


@router.get("/books/{book_id}")
def book_page(
    request: Request, db: DB, user: CurrentUser, storage: AppStorage, book_id: int
) -> Response:
    return _render_book(request, db, storage, user, _entry_or_404(db, user, book_id))


@router.get("/books/{book_id}/sessions")
def book_sessions(
    request: Request,
    db: DB,
    user: CurrentUser,
    storage: AppStorage,
    book_id: int,
    offset: int = 0,
) -> Response:
    """More rows of the book page's reading session log (htmx)."""
    book = _entry_or_404(db, user, book_id).book
    page = _sessions_page(request, db, storage, user, book, offset=max(0, offset))
    return render(request, "partials/sessions.html", **page)


@router.post("/books/{book_id}/sessions/{session_id}/delete")
def delete_session(db: DB, user: CurrentUser, book_id: int, session_id: int) -> Response:
    """Delete a web reader session (and its time in the statistics)."""
    book = _entry_or_404(db, user, book_id).book
    if not reading_stats.delete_web_session(db, user.id, book.partial_md5, session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    return RedirectResponse(f"/books/{book_id}#sessions-title", status_code=303)


@router.post("/books/{book_id}/progress")
def set_progress(
    request: Request,
    db: DB,
    user: CurrentUser,
    storage: AppStorage,
    book_id: int,
    mode: Annotated[str, Form()] = "percent",
    percent: Annotated[str, Form()] = "",
    chapter: Annotated[str, Form()] = "",
    finished: Annotated[str, Form()] = "",
) -> Response:
    """Set the reading progress by hand (book page dialog). ``finished`` means 100%."""
    entry = _entry_or_404(db, user, book_id)
    try:
        if finished:
            progress.set_manual_progress(db, storage, entry.book, percent=100)
        elif mode == "chapter":
            # Only the field of the chosen mode counts; out-of-range values are capped.
            number = parse_float(chapter.strip().replace(",", "."))
            if number is None:
                raise progress.ProgressError("Enter a chapter number.")
            progress.set_manual_progress(db, storage, entry.book, chapter=round(number))
        else:
            value = parse_float(percent.strip().rstrip("%").replace(",", "."))
            if value is None:
                raise progress.ProgressError("Enter a percentage from 0 to 100.")
            progress.set_manual_progress(db, storage, entry.book, percent=value)
    except progress.ProgressError as exc:
        return _render_book(request, db, storage, user, entry, progress_error=str(exc))
    return RedirectResponse(f"/books/{book_id}", status_code=303)


@router.post("/books/{book_id}/progress/delete")
def delete_progress(db: DB, user: CurrentUser, book_id: int) -> Response:
    """Forget the reading progress (the book becomes unread)."""
    entry = _entry_or_404(db, user, book_id)
    progress.delete_progress(db, user.id, entry.book.partial_md5)
    return RedirectResponse(f"/books/{book_id}", status_code=303)


@router.post("/books/{book_id}")
def update_book(
    request: Request,
    db: DB,
    user: CurrentUser,
    storage: AppStorage,
    book_id: int,
    title: Annotated[str, Form()] = "",
    author: Annotated[str, Form()] = "",
    series: Annotated[str, Form()] = "",
    series_index: Annotated[str, Form()] = "",
    language: Annotated[str, Form()] = "",
    publisher: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    cover: Annotated[UploadFile | None, File()] = None,
) -> Response:
    entry = _entry_or_404(db, user, book_id)
    library.update_metadata(
        db,
        storage,
        entry.book,
        title=title,
        author=author,
        series=series,
        series_index=parse_float(series_index.strip()),
        language=language,
        publisher=publisher,
        description=description,
    )
    if cover is not None and cover.filename:
        data = cover.file.read()
        if data:
            try:
                library.replace_cover(db, storage, entry.book, data)
            except library.LibraryError as exc:
                entry = _entry_or_404(db, user, book_id)
                return _render_book(request, db, storage, user, entry, error=str(exc))
    return RedirectResponse(f"/books/{book_id}", status_code=303)


@router.post("/books/{book_id}/device")
def toggle_device_sync(
    db: DB, user: CurrentUser, book_id: int, enabled: Annotated[bool, Form()]
) -> Response:
    entry = _entry_or_404(db, user, book_id)
    library.set_device_sync(db, entry.book, enabled)
    return RedirectResponse(f"/books/{book_id}", status_code=303)


@router.post("/books/{book_id}/delete")
def delete_book(db: DB, user: CurrentUser, storage: AppStorage, book_id: int) -> Response:
    entry = _entry_or_404(db, user, book_id)
    library.delete_book(db, storage, entry.book)
    return RedirectResponse("/", status_code=303)


@router.get("/books/{book_id}/file")
def download_book(
    request: Request, db: DB, user: CurrentUser, storage: AppStorage, book_id: int
) -> Response:
    return book_file_response(storage, _entry_or_404(db, user, book_id).book, request)


@router.get("/books/{book_id}/cover")
def book_cover(db: DB, user: CurrentUser, storage: AppStorage, book_id: int) -> Response:
    return cover_response(storage, _entry_or_404(db, user, book_id).book)
