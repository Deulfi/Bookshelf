"""Shared metadata types, the extractor registry and filename-based fallbacks."""

from __future__ import annotations

import html
import logging
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, fields
from pathlib import Path, PurePath

log = logging.getLogger(__name__)

MAX_COVER_BYTES = 20 * 1024 * 1024
MAX_XML_BYTES = 20 * 1024 * 1024  # package files, tables of contents, chapter text
_FIELD_LIMITS = {"title": 500, "author": 500, "series": 500, "language": 20, "publisher": 300}


@dataclass
class BookMetadata:
    title: str | None = None
    author: str | None = None
    series: str | None = None
    series_index: float | None = None
    description: str | None = None
    language: str | None = None
    publisher: str | None = None
    cover: bytes | None = None

    def fill_missing(self, other: BookMetadata) -> None:
        for field in fields(self):
            if getattr(self, field.name) in (None, "") and getattr(other, field.name):
                setattr(self, field.name, getattr(other, field.name))

    def normalize(self) -> BookMetadata:
        for name, limit in _FIELD_LIMITS.items():
            value = getattr(self, name)
            if isinstance(value, str):
                value = " ".join(value.split())[:limit]
                setattr(self, name, value or None)
        if self.description:
            self.description = self.description.strip() or None
        return self


Extractor = Callable[[Path], BookMetadata]
_EXTRACTORS: dict[str, Extractor] = {}


def register(*formats: str) -> Callable[[Extractor], Extractor]:
    def decorator(extractor: Extractor) -> Extractor:
        for fmt in formats:
            _EXTRACTORS[fmt] = extractor
        return extractor

    return decorator


def read_member(archive: zipfile.ZipFile, name: str, limit: int = MAX_XML_BYTES) -> bytes:
    """Read one archive member, refusing one that would decompress to more than ``limit``.

    ``ZipInfo.file_size`` is the declared *uncompressed* size, and the zip reader never yields
    more than that, so checking it first bounds memory against a zip bomb.
    """
    info = archive.getinfo(name)
    if info.file_size > limit:
        raise ValueError(f"{name} is too large to read")
    return archive.read(info)


def extract_metadata(path: Path, fmt: str, filename: str) -> BookMetadata:
    """Best-effort metadata: the format's extractor first, then filename heuristics."""
    metadata = BookMetadata()
    extractor = _EXTRACTORS.get(fmt)
    if extractor is not None:
        try:
            metadata = extractor(path)
        except Exception:  # broken files must never block an upload
            log.warning("Metadata extraction failed for %s", filename, exc_info=True)
    metadata.fill_missing(from_filename(filename))
    return metadata.normalize()


def from_filename(filename: str) -> BookMetadata:
    """Parse ``Author - Title.ext`` style names; otherwise use the stem as title."""
    stem = PurePath(filename).stem.replace("_", " ").strip() or "Untitled"
    if " - " in stem:
        author, title = (part.strip() for part in stem.split(" - ", 1))
        if author and title:
            return BookMetadata(title=title, author=author)
    return BookMetadata(title=stem)


_BLOCK_TAGS = re.compile(r"<\s*/?\s*(p|div|br|li|h[1-6])\b[^>]*>", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")


def html_to_text(value: str | None) -> str | None:
    """Convert an HTML snippet (e.g. an EPUB description) to plain text with paragraphs."""
    if not value:
        return None
    text = html.unescape(_TAGS.sub("", _BLOCK_TAGS.sub("\n\n", value)))
    paragraphs = (" ".join(chunk.split()) for chunk in re.split(r"\n\s*\n", text))
    return "\n\n".join(p for p in paragraphs if p) or None


def parse_float(value: str | None) -> float | None:
    try:
        return float(value.replace(",", ".")) if value else None
    except ValueError:
        return None
