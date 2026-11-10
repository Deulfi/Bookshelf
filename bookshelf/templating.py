"""Jinja2 environment: template filters, globals and the ``render`` helper."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from starlette.responses import HTMLResponse

from . import __version__
from .formats import READABLE_FORMATS, SUPPORTED_FORMATS
from .icons import icon

TEMPLATES_DIR = Path(__file__).parent / "templates"

STATUS_LABELS = {"all": "All", "reading": "Reading", "unread": "Unread", "finished": "Finished"}
SORT_LABELS = {
    "recent": "Recently added",
    "title": "Title",
    "author": "Author",
    "last_read": "Last read",
}


def filesize(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def timeago(value: datetime | None) -> str:
    if value is None:
        return "never"
    seconds = (datetime.now(UTC).replace(tzinfo=None) - value).total_seconds()
    if seconds < 60:
        return "just now"
    for limit, divisor, unit in (
        (3600, 60, "minute"),
        (86400, 3600, "hour"),
        (604800, 86400, "day"),
    ):
        if seconds < limit:
            count = int(seconds // divisor)
            return f"{count} {unit}{'s' if count != 1 else ''} ago"
    return date(value)


def date(value: datetime) -> str:
    return f"{value:%b} {value.day}, {value.year}"


def isotime(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def number(value: float | None) -> str:
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def hue(text: str) -> int:
    """A stable hue (0–359) derived from text, for generated placeholder covers."""
    return int(hashlib.md5(text.encode()).hexdigest()[:4], 16) % 360


def paragraphs(text: str | None) -> Markup:
    parts = [part.strip() for part in re.split(r"\n\s*\n", text or "") if part.strip()]
    return Markup("".join(f"<p>{escape(part)}</p>" for part in parts))


def timestamp(value: datetime) -> int:
    return int(value.replace(tzinfo=UTC).timestamp())


def duration(seconds: int | float | None) -> str:
    """Human reading time: "45 min", "3 h 20 min", "120 h"."""
    minutes = round((seconds or 0) / 60)
    if minutes < 1:
        return "<1 min" if seconds else "0 min"
    hours, minutes = divmod(minutes, 60)
    if not hours:
        return f"{minutes} min"
    if minutes == 0 or hours >= 100:
        return f"{hours} h"
    return f"{hours} h {minutes} min"


def thousands(value: int) -> str:
    return f"{value:,}"


STATIC_DIR = Path(__file__).parent / "static"


@lru_cache(maxsize=64)
def _static_version(path: str) -> str:
    """Content hash, so browsers fetch assets again whenever they change."""
    try:
        return hashlib.md5((STATIC_DIR / path).read_bytes()).hexdigest()[:10]
    except OSError:
        return __version__


def static_url(path: str) -> str:
    return f"/static/{path}?v={_static_version(path)}"


@lru_cache(maxsize=1)
def reader_import_map() -> dict[str, dict[str, str]]:
    """Map every browser reader module (ours and the vendored foliate-js ones they import) to
    its content-hashed URL. Modules imported by other modules are then cached for good and
    still fetched again after an update, just like the entry point."""
    paths = sorted(
        p.relative_to(STATIC_DIR).as_posix()
        for folder in ("reader", "foliate")
        for p in (STATIC_DIR / "js" / folder).rglob("*.js")
    )
    return {"imports": {f"/static/{path}": static_url(path) for path in paths}}


templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters.update(
    filesize=filesize,
    timeago=timeago,
    date=date,
    isotime=isotime,
    number=number,
    hue=hue,
    paragraphs=paragraphs,
    timestamp=timestamp,
    duration=duration,
    thousands=thousands,
)
templates.env.globals.update(
    icon=icon,
    static=static_url,
    reader_import_map=reader_import_map,
    version=__version__,
    readable_formats=READABLE_FORMATS,
    status_labels=STATUS_LABELS,
    sort_labels=SORT_LABELS,
    upload_accept=",".join(f".{ext}" for ext in SUPPORTED_FORMATS),
)


def render(
    request: Request,
    template: str,
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
    media_type: str | None = None,
    **context: object,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        template,
        context,
        status_code=status_code,
        headers=headers,
        media_type=media_type,
    )
