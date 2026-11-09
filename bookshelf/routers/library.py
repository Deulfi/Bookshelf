"""Library pages (grid, book details) and the upload API used by the web UI."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response

from ..deps import DB, AppSettings, AppStorage, CurrentUser
from ..models import User
from ..services import library, reading_stats
from ..services.library import BookEntry
from ..services.metadata.base import parse_float
from ..templating import render
from ._files import book_file_response, cover_response

router = APIRouter()

router = APIRouter()

PAGE_SIZE = 60  # books per page; more are loaded while scrolling


def _entry_or_404(db: DB, user: User, book_id: int) -> BookEntry:
    entry = library.get_entry(db, user, book_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Book not found.")
    return entry



@router.get("/read/{book_id}")
def read_book(
    request: Request, db: DB, user: CurrentUser, storage: AppStorage, book_id: int
) -> Response:
    """Read EPUB in browser using foliate-js."""
    entry = _entry_or_404(db, user, book_id)
    return render(
        request,
        "read.html",
        user=user,
        nav="reading",
        entry=entry,
        book=entry.book,
        file_url=f"/books/{book_id}/file",
    )

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


@router.get("/books/{book_id}")
def book_page(
    request: Request, db: DB, user: CurrentUser, storage: AppStorage, book_id: int
) -> Response:
    entry = _entry_or_404(db, user, book_id)
    stats = reading_stats.book_stats(
        reading_stats.statistics_path(storage, user.id), entry.book.partial_md5
    )
    seconds_left = None
    if stats and entry.status == "reading":
        seconds_left = stats.seconds_left(entry.progress.percentage)
    return render(
        request,
        "book.html",
        user=user,
        nav="library",
        entry=entry,
        book=entry.book,
        stats=stats,
        seconds_left=seconds_left,
    )


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
                return render(
                    request,
                    "book.html",
                    status_code=422,
                    user=user,
                    nav="library",
                    entry=entry,
                    book=entry.book,
                    error=str(exc),
                )
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
def download_book(db: DB, user: CurrentUser, storage: AppStorage, book_id: int) -> Response:
    return book_file_response(storage, _entry_or_404(db, user, book_id).book)


@router.get("/books/{book_id}/cover")
def book_cover(db: DB, user: CurrentUser, storage: AppStorage, book_id: int) -> Response:
    return cover_response(storage, _entry_or_404(db, user, book_id).book)
