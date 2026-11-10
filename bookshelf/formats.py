"""Supported e-book formats (file extension -> MIME type)."""

from __future__ import annotations

from pathlib import PurePath

SUPPORTED_FORMATS: dict[str, str] = {
    "epub": "application/epub+zip",
    "pdf": "application/pdf",
    "mobi": "application/x-mobipocket-ebook",
    "azw3": "application/vnd.amazon.ebook",
    "fb2": "application/x-fictionbook+xml",
    "cbz": "application/vnd.comicbook+zip",
    "cbr": "application/vnd.comicbook-rar",
    "djvu": "image/vnd.djvu",
    "txt": "text/plain",
    "rtf": "application/rtf",
    "html": "text/html",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "chm": "application/vnd.ms-htmlhelp",
}

# Formats the browser reader (foliate-js) opens without extra libraries.
READABLE_FORMATS = frozenset({"epub", "mobi", "azw3", "fb2", "cbz"})


def detect_format(filename: str) -> str | None:
    ext = PurePath(filename).suffix.lower().lstrip(".")
    return ext if ext in SUPPORTED_FORMATS else None


def mime_type(fmt: str) -> str:
    return SUPPORTED_FORMATS.get(fmt, "application/octet-stream")
