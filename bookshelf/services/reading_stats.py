"""Reading statistics: KOReader's ``statistics.sqlite3`` merged with the web reader's time.

KOReader owns its file (synced via WebDAV): it downloads it, merges its local data and uploads
it again. Bookshelf only ever opens it read-only. Books are identified by ``book.md5``, which is
the same partial MD5 that Bookshelf stores as ``Book.partial_md5``.

The browser reader reports its reading time with each position update; it is stored per book
and hour in ``WebReadingTime`` and added to KOReader's numbers here. The web reader has no
stable pages, so page counts (and the time-left estimate) come from KOReader only.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Book, WebReadingTime
from ..storage import Storage

log = logging.getLogger(__name__)

STATISTICS_FILE = "statistics.sqlite3"
CALENDAR_WEEKS = 53
RECENT_BOOKS_LIMIT = 12
MAX_WEB_SECONDS = 3600  # most reading time accepted from one reader update
_LEVEL_MINUTES = (15, 30, 60)  # thresholds for calendar intensity levels 2, 3 and 4


@dataclass(frozen=True)
class StatsBook:
    title: str
    authors: str | None
    md5: str | None
    seconds: int
    pages_read: int
    total_pages: int | None
    last_read: datetime  # naive UTC, like other datetimes in Bookshelf
    web_seconds: int = 0  # part of ``seconds`` read in the web reader (no pages)

    def seconds_left(self, fraction_read: float | None = None) -> int | None:
        """Estimated reading time left, based on this book's average time per KOReader page."""
        if not self.total_pages or self.pages_read <= 0:
            return None
        if fraction_read is None:
            fraction_read = min(self.pages_read / self.total_pages, 1.0)
        remaining_pages = max(self.total_pages * (1 - fraction_read), 0)
        return round((self.seconds - self.web_seconds) / self.pages_read * remaining_pages)


@dataclass(frozen=True)
class CalendarDay:
    day: date
    seconds: int

    @property
    def level(self) -> int:
        """0 (nothing read) to 4 (an hour or more)."""
        if self.seconds <= 0:
            return 0
        minutes = self.seconds / 60
        return 1 + sum(minutes >= limit for limit in _LEVEL_MINUTES)


@dataclass(frozen=True)
class CalendarWeek:
    label: str  # month abbreviation on the first week of each month, else ""
    days: tuple[CalendarDay | None, ...]  # Monday … Sunday; None for future days


@dataclass(frozen=True)
class ReadingStats:
    total_seconds: int
    year_seconds: int
    week_seconds: int
    pages_read: int
    days_read: int
    streak_days: int
    calendar: tuple[CalendarWeek, ...]
    books: tuple[StatsBook, ...]


def statistics_path(storage: Storage, user_id: int) -> Path:
    return storage.user_files_dir(user_id) / STATISTICS_FILE


def last_synced(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).replace(tzinfo=None)
    except FileNotFoundError:
        return None


def add_web_time(
    db: Session, user_id: int, document: str, seconds: float, now: int | None = None
) -> None:
    """Add reading time reported by the browser reader to the current hour's bucket."""
    seconds = min(int(seconds), MAX_WEB_SECONDS)
    if seconds <= 0 or not document:
        return
    now = int(time.time()) if now is None else now
    key = (user_id, document, now - now % 3600)
    row = db.get(WebReadingTime, key)
    if row is None:
        row = WebReadingTime(user_id=user_id, document=document, hour=key[2], seconds=0)
        db.add(row)
    row.seconds += seconds
    row.last_read = now
    db.commit()


def load_stats(
    path: Path,
    tz: ZoneInfo,
    today: date | None = None,
    *,
    db: Session | None = None,
    user_id: int | None = None,
) -> ReadingStats | None:
    """Overall statistics from KOReader's file plus the web reader's time (when ``db`` and
    ``user_id`` are given), or None if there is nothing to show yet."""
    today = today or datetime.now(tz).date()
    koreader = _koreader_stats(path, tz)
    web = db is not None and user_id is not None
    days: dict[date, int] = defaultdict(int, koreader[0] if koreader else ())
    if web:
        for hour, seconds in db.execute(
            select(WebReadingTime.hour, func.sum(WebReadingTime.seconds))
            .where(WebReadingTime.user_id == user_id)
            .group_by(WebReadingTime.hour)
        ):
            days[datetime.fromtimestamp(hour, tz).date()] += seconds or 0
    if koreader is None and not days:
        return None

    books = koreader[2] if koreader else ()
    if web:
        books = _merge_books(path, db, user_id, books)
    week_start = today - timedelta(days=today.weekday())
    return ReadingStats(
        total_seconds=sum(days.values()),
        year_seconds=sum(s for d, s in days.items() if d.year == today.year and d <= today),
        week_seconds=sum(s for d, s in days.items() if week_start <= d <= today),
        pages_read=koreader[1] if koreader else 0,
        days_read=sum(1 for s in days.values() if s > 0),
        streak_days=_streak(days, today),
        calendar=build_calendar(days, today),
        books=books,
    )


def book_stats(
    path: Path, md5: str, *, db: Session | None = None, user_id: int | None = None
) -> StatsBook | None:
    """Statistics for one book, matched by KOReader's partial MD5, with its web reading time."""
    koreader = _koreader_book(path, md5)
    if db is None or user_id is None:
        return koreader
    web = _web_books(db, user_id, documents=[md5]).get(md5)
    return _combine(koreader, web)


def _koreader_stats(path: Path, tz: ZoneInfo) -> tuple | None:
    if not path.is_file():
        return None
    stat = path.stat()
    return _load_koreader(str(path), stat.st_mtime_ns, stat.st_size, tz.key)


def _koreader_book(path: Path, md5: str) -> StatsBook | None:
    if not path.is_file():
        return None
    stat = path.stat()
    return _book_stats(str(path), stat.st_mtime_ns, stat.st_size, md5)


# --- Web reader time ---------------------------------------------------------------------------


def _web_books(
    db: Session, user_id: int, *, documents: list[str] | None = None, limit: int | None = None
) -> dict[str, StatsBook]:
    """Web reading time per book: for the given documents, or the most recently read ones."""
    if documents is not None and not documents:
        return {}
    last = func.max(WebReadingTime.last_read)
    statement = (
        select(
            WebReadingTime.document,
            func.sum(WebReadingTime.seconds),
            last,
            func.max(Book.title),
            func.max(Book.author),
        )
        .outerjoin(
            Book,
            (Book.user_id == WebReadingTime.user_id)
            & (Book.partial_md5 == WebReadingTime.document),
        )
        .where(WebReadingTime.user_id == user_id)
        .group_by(WebReadingTime.document)
        .order_by(last.desc())
    )
    if documents is not None:
        statement = statement.where(WebReadingTime.document.in_(documents))
    if limit is not None:
        statement = statement.limit(limit)
    return {
        document: StatsBook(
            title=title or "Removed from the library",
            authors=author or None,
            md5=document,
            seconds=int(seconds or 0),
            pages_read=0,
            total_pages=None,
            last_read=datetime.fromtimestamp(last_read or 0, UTC).replace(tzinfo=None),
            web_seconds=int(seconds or 0),
        )
        for document, seconds, last_read, title, author in db.execute(statement)
    }


def _combine(koreader: StatsBook | None, web: StatsBook | None) -> StatsBook | None:
    """One book's KOReader statistics plus its web reading time (pages stay KOReader's)."""
    if koreader is None or web is None:
        return koreader or web
    return replace(
        koreader,
        seconds=koreader.seconds + web.seconds,
        web_seconds=koreader.web_seconds + web.seconds,
        last_read=max(koreader.last_read, web.last_read),
    )


def _merge_books(
    path: Path, db: Session, user_id: int, koreader: tuple[StatsBook, ...]
) -> tuple[StatsBook, ...]:
    """The most recently read books of either source, each with both sources' time."""
    recent_web = _web_books(db, user_id, limit=RECENT_BOOKS_LIMIT)
    known = {book.md5 for book in koreader if book.md5}
    web = recent_web | _web_books(db, user_id, documents=sorted(known - recent_web.keys()))
    books = [_combine(book, web.get(book.md5)) if book.md5 else book for book in koreader]
    books += [
        _combine(_koreader_book(path, md5), book)
        for md5, book in recent_web.items()
        if md5 not in known
    ]
    books.sort(key=lambda book: book.last_read, reverse=True)
    return tuple(books[:RECENT_BOOKS_LIMIT])


# --- KOReader's statistics file ----------------------------------------------------------------
# The cache keys include mtime and size, so a newly synced file is picked up immediately.


@lru_cache(maxsize=32)
def _load_koreader(
    path: str, _mtime_ns: int, _size: int, tz_key: str
) -> tuple[tuple[tuple[date, int], ...], int, tuple[StatsBook, ...]] | None:
    """(seconds per local day, pages read, recent books), or None if the file is unreadable."""
    tz = ZoneInfo(tz_key)
    try:
        with closing(_connect(Path(path))) as conn:
            days: dict[date, int] = defaultdict(int)
            # Aggregate per hour in SQL, then map hours to local days (handles DST correctly).
            for hour, seconds in conn.execute(
                "SELECT start_time / 3600, SUM(duration) FROM page_stat_data GROUP BY 1"
            ):
                days[datetime.fromtimestamp(hour * 3600, tz).date()] += seconds or 0
            pages_read = conn.execute(
                "SELECT COUNT(*) FROM (SELECT DISTINCT id_book, page FROM page_stat_data)"
            ).fetchone()[0]
            books = tuple(
                _stats_book(row)
                for row in conn.execute(
                    f"""SELECT b.title, b.authors, b.md5, b.pages, SUM(p.duration),
                               COUNT(DISTINCT p.page), MAX(p.start_time + p.duration)
                        FROM book b JOIN page_stat_data p ON p.id_book = b.id
                        GROUP BY b.id ORDER BY 7 DESC LIMIT {RECENT_BOOKS_LIMIT}"""
                )
            )
    except sqlite3.Error:
        log.warning("Could not read statistics file %s", path, exc_info=True)
        return None
    return tuple(days.items()), pages_read, books


@lru_cache(maxsize=256)
def _book_stats(path: str, _mtime_ns: int, _size: int, md5: str) -> StatsBook | None:
    try:
        with closing(_connect(Path(path))) as conn:
            row = conn.execute(
                """SELECT MAX(b.title), MAX(b.authors), b.md5, MAX(b.pages), SUM(p.duration),
                          COUNT(DISTINCT p.id_book || ':' || p.page), MAX(p.start_time + p.duration)
                   FROM book b JOIN page_stat_data p ON p.id_book = b.id
                   WHERE b.md5 = ?""",
                (md5,),
            ).fetchone()
    except sqlite3.Error:
        log.warning("Could not read statistics file %s", path, exc_info=True)
        return None
    return _stats_book(row) if row and row[4] else None


def _connect(path: Path) -> sqlite3.Connection:
    # Read-only and "immutable": never create journals or locks next to KOReader's file.
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA trusted_schema = OFF")
    return conn


def _stats_book(row: tuple) -> StatsBook:
    title, authors, md5, total_pages, seconds, pages_read, last_read = row
    return StatsBook(
        title=title or "Untitled",
        authors=authors or None,
        md5=md5,
        seconds=int(seconds or 0),
        pages_read=int(pages_read or 0),
        total_pages=int(total_pages) if total_pages else None,
        last_read=datetime.fromtimestamp(last_read or 0, UTC).replace(tzinfo=None),
    )


def _streak(days: dict[date, int], today: date) -> int:
    """Consecutive reading days up to today (or yesterday, if nothing was read yet today)."""
    day = today if days.get(today, 0) > 0 else today - timedelta(days=1)
    streak = 0
    while days.get(day, 0) > 0:
        streak += 1
        day -= timedelta(days=1)
    return streak


def build_calendar(
    days: dict[date, int], today: date, weeks: int = CALENDAR_WEEKS
) -> tuple[CalendarWeek, ...]:
    """Weeks (Monday first) ending with the current one, for a GitHub-style heatmap."""
    first_monday = today - timedelta(days=today.weekday(), weeks=weeks - 1)
    result = []
    previous_month = None
    for week in range(weeks):
        monday = first_monday + timedelta(weeks=week)
        cells = tuple(
            CalendarDay(day, days.get(day, 0)) if day <= today else None
            for day in (monday + timedelta(days=offset) for offset in range(7))
        )
        label = monday.strftime("%b") if monday.month != previous_month else ""
        previous_month = monday.month
        result.append(CalendarWeek(label, cells))
    return tuple(result)
