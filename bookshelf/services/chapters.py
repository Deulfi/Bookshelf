"""Which chapter a reading position is in, for the progress shown on book pages (EPUB only).

Sync records hold either a KOReader XPointer (``/body/DocFragment[12]/body/...``, written by
KOReader, Readest and the web reader) or an EPUB CFI (``epubcfi(/6/24!...)``, older web reader
records). Both name the spine item, which is matched against the book's table of contents.

Some books keep several chapters in one file, with table-of-contents entries pointing at anchors
(``part0.html#ch5``). For those, the element path of an XPointer is matched against the anchors'
positions in the file (see ``Section``), so the right chapter is found and set.
"""

from __future__ import annotations

import html.entities
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
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
# Positions are written at block level, like the web reader (static/js/reader/xpointer.js).
_INLINE = frozenset(
    {"a", "abbr", "b", "bdi", "bdo", "big", "br", "cite", "code", "del", "dfn", "em", "font", "i"}
    | {"img", "ins", "kbd", "mark", "q", "rp", "rt", "ruby", "s", "samp", "small", "span"}
    | {"strike", "strong", "sub", "sup", "time", "tt", "u", "var", "wbr"}
)
_XML_ENTITIES = frozenset({"amp", "lt", "gt", "quot", "apos"})
_ENTITY = re.compile(r"&([A-Za-z][A-Za-z0-9]*);")
_PATH_SEGMENT = re.compile(r"^([^[\].()]+)(?:\[(\d+)\])?(?:\.\d+)?$")


@dataclass(frozen=True)
class Outline:
    """Spine length and the table of contents as (spine index, title), in reading order.
    ``spine_sizes`` (uncompressed bytes per spine item) turns positions into percentages.
    ``anchors`` holds each TOC entry's ``#fragment`` (or None); ``source`` and ``spine_hrefs``
    let ``section`` read a spine file when anchors need resolving."""

    spine_length: int
    toc: tuple[tuple[int, str], ...]
    spine_sizes: tuple[int, ...] = ()
    anchors: tuple[str | None, ...] = ()
    spine_hrefs: tuple[str, ...] = field(default=(), compare=False)
    source: tuple[str, int, int] | None = field(default=None, compare=False)

    @property
    def chapter_total(self) -> int:
        return len(self.toc) if self.toc else self.spine_length

    def fraction_at(self, index: int, share: float = 0.0) -> float:
        """Share of the book before spine item ``index`` (plus ``share`` of that item)."""
        total = sum(self.spine_sizes)
        if not total:
            return (index + share) / self.spine_length if self.spine_length else 0.0
        return (sum(self.spine_sizes[:index]) + share * self.spine_sizes[index]) / total

    def index_at(self, fraction: float) -> int:
        """Spine item that contains ``fraction`` of the book."""
        total = sum(self.spine_sizes)
        if not total:
            return min(self.spine_length - 1, max(0, int(fraction * self.spine_length)))
        position = fraction * total
        for index, size in enumerate(self.spine_sizes):
            position -= size
            if position < 0:
                return index
        return len(self.spine_sizes) - 1

    def share_in(self, index: int, fraction: float) -> float:
        """Which share (0–1) of spine item ``index`` lies at ``fraction`` of the book."""
        total = sum(self.spine_sizes)
        if not total or not self.spine_sizes[index]:
            return 0.0
        before = sum(self.spine_sizes[:index])
        return min(1.0, max(0.0, (fraction * total - before) / self.spine_sizes[index]))

    def anchor(self, number: int) -> str | None:
        """The ``#fragment`` of TOC entry ``number`` (1-based), if any."""
        return self.anchors[number - 1] if len(self.anchors) >= number else None

    def section(self, index: int) -> Section | None:
        """Block elements of spine item ``index``, or None if it can't be read."""
        if self.source is None or index >= len(self.spine_hrefs) or not self.spine_hrefs[index]:
            return None
        path, mtime_ns, size = self.source
        try:
            return _section(path, mtime_ns, size, self.spine_hrefs[index])
        except (OSError, KeyError, ET.ParseError, zipfile.BadZipFile):
            return None


@dataclass(frozen=True)
class Section:
    """The block elements of one spine file in document order, as KOReader XPointer paths
    relative to ``<body>`` (``"div/p[3]"``), and which block holds each ``id``."""

    paths: tuple[str, ...]
    ids: dict[str, int] = field(compare=False)
    orders: dict[str, int] = field(compare=False)  # path -> position in ``paths``

    def order_of(self, path: str) -> int | None:
        """Order of the deepest block an XPointer path (after ``.../body``) points into."""
        segments = []
        for segment in path.strip("/").split("/"):
            if not segment or segment.startswith("text()"):
                break
            match = _PATH_SEGMENT.match(segment)
            if not match:
                break
            name, number = match.group(1).lower(), match.group(2)
            segments.append(f"{name}[{number}]" if number else name)
        orders = self.orders
        while segments:
            order = orders.get("/".join(segments))
            if order is not None:
                return order
            # Readers differ on [1] for a single child of its name; try without it too.
            last = segments[-1]
            if last.endswith("[1]"):
                order = orders.get("/".join([*segments[:-1], last[:-3]]))
                if order is not None:
                    return order
            segments.pop()
        return None

    def share(self, order: int) -> float:
        return order / len(self.paths) if self.paths else 0.0

    def path_at(self, share: float) -> str:
        if not self.paths:
            return ""
        return self.paths[min(len(self.paths) - 1, max(0, int(share * len(self.paths))))]


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


def outline_of(storage: Storage, book: Book) -> Outline | None:
    """Spine and table of contents of an EPUB, or None for other formats and broken files."""
    if book.format != "epub":
        return None
    path = storage.find_book_file(book)
    if path is None:
        return None
    try:
        stat = path.stat()
        outline = _outline(str(path), stat.st_mtime_ns, stat.st_size)
    except (OSError, ValueError, KeyError, ET.ParseError, zipfile.BadZipFile):
        return None
    return outline if outline.spine_length else None


def chapter_at(storage: Storage, book: Book, progress: str | None) -> Chapter | None:
    index = spine_index(progress)
    if index is None or index < 0:
        return None
    outline = outline_of(storage, book)
    return chapter_in(outline, index, progress) if outline else None


def xpointer(index: int, path: str = "") -> str:
    """KOReader XPointer for the start of spine item ``index`` (or a block inside it)."""
    return f"/body/DocFragment[{index + 1}]/body" + (f"/{path}" if path else "")


def chapter_start(outline: Outline, number: int) -> int:
    """Spine item where chapter ``number`` (1-based, as counted by ``chapter_in``) starts."""
    if outline.toc:
        return outline.toc[number - 1][0]
    return number - 1


def chapter_position(outline: Outline, number: int) -> tuple[str, float]:
    """XPointer and book fraction of the start of chapter ``number`` (1-based). Chapters that
    start at an anchor inside a file start at that anchor's block."""
    index = chapter_start(outline, number)
    anchor = outline.anchor(number) if outline.toc else None
    section = outline.section(index) if anchor else None
    order = section.ids.get(anchor) if section and anchor else None
    if order is None or order == 0:
        return xpointer(index), outline.fraction_at(index)
    return xpointer(index, section.paths[order]), outline.fraction_at(index, section.share(order))


def position_at(outline: Outline, fraction: float) -> str:
    """XPointer of the block at ``fraction`` of the book (100% is the last block)."""
    index = outline.index_at(fraction)
    section = outline.section(index)
    if section is None or not section.paths:
        return xpointer(index)
    return xpointer(index, section.path_at(outline.share_in(index, fraction)))


def chapter_in(outline: Outline, index: int, progress: str | None = None) -> Chapter | None:
    if index >= outline.spine_length:
        return None
    if not outline.toc:
        return Chapter(index + 1, outline.spine_length, None, "Section")
    here = _order_in(outline, index, progress)
    # Several entries can point into one file (anchors). With a position inside the file, the
    # last entry whose anchor is at or before it wins; without one, the file's first entry.
    number = 0
    first_in_file = 0
    for position, (spine, _title) in enumerate(outline.toc, start=1):
        if spine < index:
            number = position
        elif spine == index:
            if here is None:
                number = position
                break
            first_in_file = first_in_file or position
            if _anchor_order(outline, index, position) <= here:
                number = position
        else:
            break
    if here is not None and first_in_file and number < first_in_file:
        number = number or first_in_file  # before the file's first anchor: previous chapter
    if number == 0:
        return None  # before the first chapter (cover, title page)
    return Chapter(number, len(outline.toc), outline.toc[number - 1][1])


def _order_in(outline: Outline, index: int, progress: str | None) -> int | None:
    """Block order of an XPointer position inside spine item ``index``, when that file holds
    anchored TOC entries (otherwise None: the file's first entry is good enough)."""
    if not progress or not progress.startswith("/body/DocFragment["):
        return None
    anchored = [
        n
        for n, (spine, _) in enumerate(outline.toc, start=1)
        if spine == index and outline.anchor(n)
    ]
    if not anchored:
        return None
    section = outline.section(index)
    if section is None:
        return None
    path = progress.split("]/body", 1)[1] if "]/body" in progress else ""
    order = section.order_of(path)
    return 0 if order is None else order


def _anchor_order(outline: Outline, index: int, number: int) -> int:
    anchor = outline.anchor(number)
    section = outline.section(index) if anchor else None
    return (section.ids.get(anchor, 0) if section and anchor else 0) or 0


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
        sizes = {info.filename: info.file_size for info in archive.infolist()}
        position = {}
        spine_sizes = []
        spine_hrefs = []
        for i, idref in enumerate(spine_ids):
            item = manifest.get(idref)
            href = _join(base, item.get("href", "")) if item is not None else ""
            if href:
                position.setdefault(href, i)
            spine_hrefs.append(href)
            spine_sizes.append(sizes.get(href, 0))

        entries: list[tuple[str, str, str | None]] = []  # (archive path, title, fragment)
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

    kept = [(href, title, fragment) for href, title, fragment in entries if href in position]
    return Outline(
        len(spine_ids),
        tuple((position[href], title) for href, title, _ in kept),
        tuple(spine_sizes),
        anchors=tuple(fragment for _, _, fragment in kept),
        spine_hrefs=tuple(spine_hrefs),
        source=(path, _mtime_ns, _size),
    )


@lru_cache(maxsize=256)
def _section(path: str, _mtime_ns: int, _size: int, href: str) -> Section:
    """Block elements of one spine file, parsed once per file version."""
    with zipfile.ZipFile(path) as archive:
        text = archive.read(href).decode("utf-8", "replace")
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        # XHTML files often use HTML entities (&nbsp;) that XML doesn't know.
        root = ET.fromstring(_ENTITY.sub(_replace_entity, text))
    body = next((el for el in root.iter() if _local(el.tag) == "body"), None)
    paths: list[str] = []
    ids: dict[str, int] = {}
    if body is not None:
        _walk(body, "", paths, ids, None)
    return Section(tuple(paths), ids, {p: order for order, p in enumerate(paths)})


def _walk(
    element: ET.Element, prefix: str, paths: list[str], ids: dict[str, int], block: int | None
) -> None:
    """Collect block paths in document order. Inline elements and their ids belong to the
    nearest block, like positions written by the web reader."""
    children = [child for child in element if isinstance(child.tag, str)]
    counts: dict[str, int] = {}
    for child in children:
        counts[_local(child.tag)] = counts.get(_local(child.tag), 0) + 1
    seen: dict[str, int] = {}
    for child in children:
        name = _local(child.tag)
        seen[name] = seen.get(name, 0) + 1
        if name in _INLINE:
            order = block
            child_prefix = None
        else:
            segment = f"{name}[{seen[name]}]" if counts[name] > 1 else name
            child_prefix = f"{prefix}/{segment}" if prefix else segment
            order = len(paths)
            paths.append(child_prefix)
        if order is not None and (child_id := child.get("id")):
            ids.setdefault(child_id, order)
        if child_prefix is not None:
            _walk(child, child_prefix, paths, ids, order)
        else:
            _collect_ids(child, ids, order)


def _collect_ids(element: ET.Element, ids: dict[str, int], order: int | None) -> None:
    if order is None:
        return
    for inner in element.iter():
        if isinstance(inner.tag, str) and (inner_id := inner.get("id")):
            ids.setdefault(inner_id, order)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _replace_entity(match: re.Match[str]) -> str:
    name = match.group(1)
    if name in _XML_ENTITIES:
        return match.group(0)
    char = html.entities.html5.get(name + ";")
    return char if char is not None else match.group(0)


def _join(base: str, href: str) -> str:
    return posixpath.normpath(posixpath.join(base, unquote(href.split("#", 1)[0])))


def _fragment(href: str) -> str | None:
    if "#" not in href:
        return None
    return unquote(href.split("#", 1)[1]) or None


def _nav_entries(archive: zipfile.ZipFile, nav_path: str) -> list[tuple[str, str, str | None]]:
    root = ET.fromstring(archive.read(nav_path))
    base = posixpath.dirname(nav_path)
    navs = list(root.iter(f"{_XHTML}nav"))
    toc = next((n for n in navs if n.get(_EPUB_TYPE) == "toc"), navs[0] if navs else None)
    if toc is None:
        return []
    return [
        (
            _join(base, a.get("href", "")),
            " ".join("".join(a.itertext()).split()),
            _fragment(a.get("href", "")),
        )
        for a in toc.iter(f"{_XHTML}a")
        if a.get("href")
    ]


def _ncx_entries(archive: zipfile.ZipFile, ncx_path: str) -> list[tuple[str, str, str | None]]:
    root = ET.fromstring(archive.read(ncx_path))
    base = posixpath.dirname(ncx_path)
    entries = []
    for point in root.iter(f"{_NCX}navPoint"):  # document order = reading order
        content = point.find(f"{_NCX}content")
        label = point.find(f"{_NCX}navLabel/{_NCX}text")
        if content is None or not content.get("src"):
            continue
        title = " ".join((label.text or "").split()) if label is not None else ""
        src = content.get("src", "")
        entries.append((_join(base, src), title, _fragment(src)))
    return entries
