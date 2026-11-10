"""Which chapter a reading position is in, for the progress shown on book pages (EPUB only).

Sync records hold either a KOReader XPointer (``/body/DocFragment[12]/body/...``, written by
KOReader, Readest and the web reader) or an EPUB CFI (``epubcfi(/6/24!...)``, older web reader
records). Both name the spine item, which is matched against the book's table of contents.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from ..models import Book
from ..storage import Storage
from .metadata.epub import NS, _package_path

_XPOINTER = re.compile(r"^/body/DocFragment\[(\d+)\]")
_CFI = re.compile(r"^epubcfi\(/6/(\d+)")
_NCX = "{http://www.daisy.org/z3986/2005/ncx/}"
_NCX_TYPE = "application/x-dtbncx+xml"
_XHTML = "{http://www.w3.org/1999/xhtml}"
_EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"


@dataclass(frozen=True)
class Outline:
    """Spine length and the table of contents as (spine index, title), in reading order."""

    spine_length: int
    toc: tuple[tuple[int, str], ...]


@dataclass(frozen=True)
class Chapter:
    number: int  # 1-based
    total: int
    title: str | None  # None when the book has no usable table of contents
    kind: str = "Chapter"  # "Section" when counting spine items


def spine_index(progress: str | None) -> int | None:
    """0-based spine item of a sync position, or None for other position formats."""
    if not progress:
        return None
    if match := _XPOINTER.match(progress):
        return int(match.group(1)) - 1
    if match := _CFI.match(progress):
        return int(match.group(1)) // 2 - 1
    return None


def chapter_at(storage: Storage, book: Book, progress: str | None) -> Chapter | None:
    if book.format != "epub":
        return None
    index = spine_index(progress)
    if index is None or index < 0:
        return None
    path = storage.find_book_file(book)
    if path is None:
        return None
    try:
        stat = path.stat()
        outline = _outline(str(path), stat.st_mtime_ns, stat.st_size)
    except (OSError, ValueError, KeyError, ET.ParseError, zipfile.BadZipFile):
        return None
    return chapter_in(outline, index)


def chapter_in(outline: Outline, index: int) -> Chapter | None:
    if index >= outline.spine_length:
        return None
    if not outline.toc:
        return Chapter(index + 1, outline.spine_length, None, "Section")
    # Several entries can point into one file (anchors); without a finer position the first
    # entry of the current file is the best guess, otherwise the last one before it.
    number = 0
    for position, (spine, _title) in enumerate(outline.toc, start=1):
        if spine == index:
            number = position
            break
        if spine < index:
            number = position
    if number == 0:
        return None  # before the first chapter (cover, title page)
    return Chapter(number, len(outline.toc), outline.toc[number - 1][1])


@lru_cache(maxsize=64)
def _outline(path: str, _mtime_ns: int, _size: int) -> Outline:
    """Parsed once per file version; web novels can have thousands of TOC entries."""
    with zipfile.ZipFile(path) as archive:
        opf_path = _package_path(archive)
        base = posixpath.dirname(opf_path)
        package = ET.fromstring(archive.read(opf_path))
        manifest = {
            item.get("id"): item for item in package.findall(".//opf:manifest/opf:item", NS)
        }
        spine_ids = [ref.get("idref") for ref in package.findall(".//opf:spine/opf:itemref", NS)]
        position = {}
        for i, idref in enumerate(spine_ids):
            item = manifest.get(idref)
            if item is not None and item.get("href"):
                position.setdefault(_join(base, item.get("href", "")), i)

        entries: list[tuple[str, str]] = []  # (archive path, title)
        nav = next(
            (i for i in manifest.values() if "nav" in (i.get("properties") or "").split()), None
        )
        if nav is not None:
            entries = _nav_entries(archive, _join(base, nav.get("href", "")))
        if not entries:
            spine = package.find(".//opf:spine", NS)
            ncx = manifest.get(spine.get("toc") if spine is not None else None)
            if ncx is None:
                ncx = next(
                    (i for i in manifest.values() if i.get("media-type") == _NCX_TYPE),
                    None,
                )
            if ncx is not None:
                entries = _ncx_entries(archive, _join(base, ncx.get("href", "")))

    toc = tuple((position[href], title) for href, title in entries if href in position)
    return Outline(len(spine_ids), toc)


def _join(base: str, href: str) -> str:
    return posixpath.normpath(posixpath.join(base, unquote(href.split("#", 1)[0])))


def _nav_entries(archive: zipfile.ZipFile, nav_path: str) -> list[tuple[str, str]]:
    root = ET.fromstring(archive.read(nav_path))
    base = posixpath.dirname(nav_path)
    navs = list(root.iter(f"{_XHTML}nav"))
    toc = next((n for n in navs if n.get(_EPUB_TYPE) == "toc"), navs[0] if navs else None)
    if toc is None:
        return []
    return [
        (_join(base, a.get("href", "")), " ".join("".join(a.itertext()).split()))
        for a in toc.iter(f"{_XHTML}a")
        if a.get("href")
    ]


def _ncx_entries(archive: zipfile.ZipFile, ncx_path: str) -> list[tuple[str, str]]:
    root = ET.fromstring(archive.read(ncx_path))
    base = posixpath.dirname(ncx_path)
    entries = []
    for point in root.iter(f"{_NCX}navPoint"):  # document order = reading order
        content = point.find(f"{_NCX}content")
        label = point.find(f"{_NCX}navLabel/{_NCX}text")
        if content is None or not content.get("src"):
            continue
        title = " ".join((label.text or "").split()) if label is not None else ""
        entries.append((_join(base, content.get("src", "")), title))
    return entries
