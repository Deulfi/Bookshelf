"""File responses shared by the web UI and the OPDS catalog."""

from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response

from ..formats import mime_type
from ..models import Book
from ..storage import Storage


def book_file_response(storage: Storage, book: Book, request: Request | None = None) -> Response:
    """The book file. With ``request``, a browser that already has this version of the file
    (the web reader opening the book again) gets a 304 instead of the whole file."""
    path = storage.find_book_file(book)
    if path is None:
        raise HTTPException(status_code=404, detail="The book file is missing.")
    try:
        stat_result = path.stat()
    except OSError as error:
        raise HTTPException(status_code=404, detail="The book file is missing.") from error
    response = FileResponse(
        path,
        media_type=mime_type(book.format),
        filename=book.original_filename,
        stat_result=stat_result,
        headers={"Cache-Control": "private, no-cache"},  # keep a copy, but always revalidate
    )
    etag = response.headers.get("etag")
    if request is not None and etag:
        wanted = request.headers.get("if-none-match", "")
        if etag in {tag.strip().removeprefix("W/") for tag in wanted.split(",")}:
            return Response(
                status_code=304, headers={"ETag": etag, "Cache-Control": "private, no-cache"}
            )
    return response


def cover_response(storage: Storage, book: Book) -> FileResponse:
    path = storage.cover_path(book.id)
    if not book.has_cover or not path.is_file():
        raise HTTPException(status_code=404, detail="No cover.")
    # Cover URLs carry a version parameter, so they can be cached for a long time.
    return FileResponse(
        path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=31536000"}
    )
