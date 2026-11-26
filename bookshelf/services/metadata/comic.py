"""Comic book archives (CBZ): first page as cover, ComicInfo.xml if present."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

from .base import MAX_COVER_BYTES, BookMetadata, parse_float, read_member, register

_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def _natural_key(name: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name.lower())]


@register("cbz")
def extract_cbz(path: Path) -> BookMetadata:
    with zipfile.ZipFile(path) as archive:
        pages = sorted(
            (
                info
                for info in archive.infolist()
                if info.filename.lower().endswith(_IMAGE_SUFFIXES)
                and not PurePosixPath(info.filename).name.startswith(".")
            ),
            key=lambda info: _natural_key(info.filename),
        )
        cover = None
        if pages and pages[0].file_size <= MAX_COVER_BYTES:
            cover = archive.read(pages[0])

        metadata = BookMetadata(cover=cover)
        if "ComicInfo.xml" in archive.namelist():
            info = ET.fromstring(read_member(archive, "ComicInfo.xml"))

            def text(tag: str) -> str | None:
                value = info.findtext(tag)
                return value.strip() if value and value.strip() else None

            metadata.title = text("Title")
            metadata.series = text("Series")
            metadata.series_index = parse_float(text("Number"))
            metadata.author = text("Writer")
            metadata.description = text("Summary")
            metadata.language = text("LanguageISO")
            metadata.publisher = text("Publisher")
            if not metadata.title and metadata.series:
                number = f" #{text('Number')}" if text("Number") else ""
                metadata.title = f"{metadata.series}{number}"
        return metadata
