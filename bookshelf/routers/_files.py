"""File responses shared by the web UI and the OPDS catalog."""

from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import FileResponse

from ..formats import mime_type
from ..models import Book
from ..storage import Storage


def book_file_response(storage: Storage, book: Book) -> FileResponse:
    path = storage.find_book_file(book)
    if path is None:
        raise HTTPException(status_code=404, detail="The book file is missing.")
    return FileResponse(path, media_type=mime_type(book.format), filename=book.original_filename)


def cover_response(storage: Storage, book: Book) -> FileResponse:
    path = storage.cover_path(book.id)
    if not book.has_cover or not path.is_file():
        raise HTTPException(status_code=404, detail="No cover.")
    # Cover URLs carry a version parameter, so they can be cached for a long time.
    return FileResponse(
        path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=31536000"}
    )
