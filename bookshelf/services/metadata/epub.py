"""EPUB 2/3: title, authors, series (Calibre and EPUB3 collections), description, cover."""

from __future__ import annotations

import posixpath
import zipfile
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from .base import MAX_COVER_BYTES, BookMetadata, html_to_text, parse_float, register

NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}
_OPF_ROLE = f"{{{NS['opf']}}}role"


@register("epub")
def extract_epub(path: Path) -> BookMetadata:
    with zipfile.ZipFile(path) as archive:
        opf_path = _package_path(archive)
        package = ET.fromstring(archive.read(opf_path))
        metadata = package.find(".//opf:metadata", NS)
        cover = _cover(archive, package, posixpath.dirname(opf_path))
        if metadata is None:
            return BookMetadata(cover=cover)

        title = _text(metadata, ".//dc:title")
        series, series_index = _series(metadata)
        # lightnovel-crawler (and some tools) set calibre:series to the book's own title with no
        # number; that is not a real series, just a redundant folder level, so drop it.
        if series and series_index is None and title and series.strip() == title.strip():
            series = None
        return BookMetadata(
            title=title,
            author=" & ".join(_authors(metadata)) or None,
            series=series,
            series_index=series_index,
            description=html_to_text(_text(metadata, ".//dc:description")),
            language=_text(metadata, ".//dc:language"),
            publisher=_text(metadata, ".//dc:publisher"),
            cover=cover,
        )


def _package_path(archive: zipfile.ZipFile) -> str:
    try:
        container = ET.fromstring(archive.read("META-INF/container.xml"))
        rootfile = container.find(".//c:rootfile", NS)
        if rootfile is not None and rootfile.get("full-path"):
            return rootfile.get("full-path", "")
    except KeyError:
        pass
    for name in archive.namelist():
        if name.lower().endswith(".opf"):
            return name
    raise ValueError("EPUB has no package document")


def _text(parent: ET.Element, path: str) -> str | None:
    element = parent.find(path, NS)
    if element is None or not element.text or not element.text.strip():
        return None
    return element.text.strip()


def _authors(metadata: ET.Element) -> list[str]:
    # EPUB3 declares roles via <meta refines="#id" property="role">aut</meta>.
    refined_roles = {
        meta.get("refines", "").lstrip("#"): (meta.text or "").strip()
        for meta in metadata.findall(".//opf:meta[@property='role']", NS)
    }
    authors: list[str] = []
    for creator in metadata.findall(".//dc:creator", NS):
        role = creator.get(_OPF_ROLE) or refined_roles.get(creator.get("id", ""))
        name = (creator.text or "").strip()
        if role in (None, "", "aut") and name and name not in authors:
            authors.append(name)
    return authors


def _series(metadata: ET.Element) -> tuple[str | None, float | None]:
    series = index = None
    for meta in metadata.findall(".//opf:meta", NS):
        if meta.get("name") == "calibre:series":
            series = meta.get("content")
        elif meta.get("name") == "calibre:series_index":
            index = parse_float(meta.get("content"))
    if series:
        return series, index

    collection = metadata.find(".//opf:meta[@property='belongs-to-collection']", NS)
    if collection is None or not (collection.text or "").strip():
        return None, None
    collection_id = collection.get("id")
    for meta in metadata.findall(".//opf:meta[@property='group-position']", NS):
        if collection_id and meta.get("refines") == f"#{collection_id}":
            index = parse_float(meta.text)
    return collection.text.strip(), index


def _cover(archive: zipfile.ZipFile, package: ET.Element, base_dir: str) -> bytes | None:
    items = package.findall(".//opf:manifest/opf:item", NS)
    by_id = {item.get("id"): item for item in items}
    href: str | None = None

    for item in items:  # EPUB3
        if "cover-image" in (item.get("properties") or "").split():
            href = item.get("href")
            break

    if href is None:  # EPUB2: <meta name="cover" content="<manifest id>"/>
        meta = package.find(".//opf:meta[@name='cover']", NS)
        reference = meta.get("content", "") if meta is not None else ""
        if reference in by_id:
            href = by_id[reference].get("href")
        elif reference:
            href = reference

    if href is None:  # heuristic: an image whose id or href mentions "cover"
        for item in items:
            hint = f"{item.get('id', '')} {item.get('href', '')}".lower()
            if (item.get("media-type") or "").startswith("image/") and "cover" in hint:
                href = item.get("href")
                break

    if not href:
        return None
    name = posixpath.normpath(posixpath.join(base_dir, unquote(href)))
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    return archive.read(info) if info.file_size <= MAX_COVER_BYTES else None
