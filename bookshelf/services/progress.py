"""Reading progress records as stored by the KOReader sync protocol."""

from __future__ import annotations

import time

from pypdf import PdfReader
from sqlalchemy.orm import Session

from ..models import Book, ReadingProgress
from ..storage import Storage
from . import chapters


def get_progress(db: Session, user_id: int, document: str) -> ReadingProgress | None:
    return db.get(ReadingProgress, (user_id, document))


def save_progress(
    db: Session,
    user_id: int,
    document: str,
    *,
    progress: str,
    percentage: float,
    device: str,
    device_id: str,
) -> ReadingProgress:
    record = get_progress(db, user_id, document)
    if record is None:
        record = ReadingProgress(user_id=user_id, document=document)
        db.add(record)
    record.progress = progress
    record.percentage = min(max(percentage, 0.0), 1.0)
    record.device = device[:200]
    record.device_id = device_id[:200]
    record.timestamp = int(time.time())
    db.commit()
    return record


# --- Editing progress by hand (book page) ----------------------------------------------------

MANUAL_DEVICE = "Bookshelf (edited)"
MANUAL_DEVICE_ID = "bookshelf-book-page"


class ProgressError(Exception):
    """Invalid manual progress, with a user-facing message."""


def set_manual_progress(
    db: Session,
    storage: Storage,
    book: Book,
    *,
    percent: float | None = None,
    chapter: int | None = None,
) -> ReadingProgress:
    """Set ``book``'s progress to a percentage (0–100) or to the start of a chapter.

    The record is shared with KOReader, Readest and the web reader, so the position is written
    in their format where possible: a KOReader XPointer for EPUBs, a page number for PDFs.
    Other formats only get the percentage; readers then fall back to it.
    """
    outline = chapters.outline_of(storage, book)
    if chapter is not None:
        if outline is None:
            raise ProgressError("This book has no chapters to choose from.")
        if not 1 <= chapter <= outline.chapter_total:
            raise ProgressError(f"Choose a chapter from 1 to {outline.chapter_total}.")
        index = chapters.chapter_start(outline, chapter)
        fraction = outline.fraction_at(index)
        position = chapters.xpointer(index)
    elif percent is not None:
        if not 0 <= percent <= 100:
            raise ProgressError("Enter a percentage from 0 to 100.")
        fraction = percent / 100
        position = _position_at(storage, book, outline, fraction)
    else:
        raise ProgressError("Enter a percentage or a chapter.")
    return save_progress(
        db,
        book.user_id,
        book.partial_md5,
        progress=position,
        percentage=fraction,
        device=MANUAL_DEVICE,
        device_id=MANUAL_DEVICE_ID,
    )


def _position_at(
    storage: Storage, book: Book, outline: chapters.Outline | None, fraction: float
) -> str:
    if outline is not None:
        return chapters.xpointer(outline.index_at(fraction))
    if book.format == "pdf":
        pages = _pdf_pages(storage, book)
        if pages:
            return str(min(pages, max(1, round(fraction * pages))))
    return ""


def _pdf_pages(storage: Storage, book: Book) -> int | None:
    path = storage.find_book_file(book)
    if path is None:
        return None
    try:
        return len(PdfReader(path).pages)
    except Exception:  # pypdf raises many types for damaged files
        return None


def delete_progress(db: Session, user_id: int, document: str) -> bool:
    record = get_progress(db, user_id, document)
    if record is None:
        return False
    db.delete(record)
    db.commit()
    return True
