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

from ..models import Book, ReadingSession, WebReadingTime
from ..storage import Storage

log = logging.getLogger(__name__)

STATISTICS_FILE = "statistics.sqlite3"
CALENDAR_WEEKS = 53
RECENT_BOOKS_LIMIT = 12
MAX_WEB_SECONDS = 3600  # most reading time accepted from one reader update
SESSION_GAP = 600  # a pause longer than this (seconds) starts a new reading session
SESSIONS_PER_SOURCE = 500  # most sessions per book and source shown in the log
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
class SessionRow:
    """One reading session for the book page's log."""

    started: datetime  # local time (the server's TZ)
    seconds: int
    source: str  # "Web reader", "KOReader", ...
    detail: str  # what was read: "12% → 15%" or "pages 30–52 of 534"
    # Where the session ended, to resume there: a position (XPointer/CFI) and/or a fraction.
    resume_position: str = ""
    resume_fraction: float | None = None
    id: int | None = None  # web reader sessions only; KOReader's come from its own file


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
    db: Session,
    user_id: int,
    document: str,
    seconds: float,
    now: int | None = None,
    *,
    fraction: float | None = None,
    previous_fraction: float | None = None,
    device: str = "Web reader",
    device_id: str = "",
    position: str = "",
) -> None:
    """Add reading time reported by the browser reader: to the current hour's bucket (totals,
    calendar) and to this device's current session (the book page's log). ``fraction`` and
    ``position`` are where the reading ended, ``previous_fraction`` the progress before it."""
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

    end = fraction if fraction is not None else previous_fraction or 0.0
    session = db.scalars(
        select(ReadingSession)
        .where(
            ReadingSession.user_id == user_id,
            ReadingSession.document == document,
            ReadingSession.device_id == device_id,
        )
        .order_by(ReadingSession.ended_at.desc())
        .limit(1)
    ).first()
    if session is not None and now - session.ended_at <= SESSION_GAP:
        session.seconds += seconds
        session.ended_at = now
        session.end_fraction = end
        session.end_position = position
    else:
        db.add(
            ReadingSession(
                user_id=user_id,
                document=document,
                device=device[:200],
                device_id=device_id[:200],
                started_at=now - seconds,
                ended_at=now,
                seconds=seconds,
                start_fraction=previous_fraction if previous_fraction is not None else end,
                end_fraction=end,
                end_position=position,
            )
        )
    db.commit()


def delete_web_session(db: Session, user_id: int, document: str, session_id: int) -> bool:
    """Delete one of the web reader's sessions of a book and take its time out of the
    statistics (the hour buckets it was added to, newest first). False if there is no such
    session for this user and book."""
    session = db.get(ReadingSession, session_id)
    if session is None or session.user_id != user_id or session.document != document:
        return False
    remaining = session.seconds
    buckets = db.scalars(
        select(WebReadingTime)
        .where(
            WebReadingTime.user_id == user_id,
            WebReadingTime.document == document,
            WebReadingTime.hour >= session.started_at - session.started_at % 3600,
            WebReadingTime.hour <= session.ended_at,
        )
        .order_by(WebReadingTime.hour.desc())
    ).all()
    for bucket in buckets:
        if remaining <= 0:
            break
        taken = min(bucket.seconds, remaining)
        bucket.seconds -= taken
        remaining -= taken
        if bucket.seconds <= 0:
            db.delete(bucket)
    db.delete(session)
    db.commit()
    return True


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


def book_sessions(
    path: Path,
    md5: str,
    tz: ZoneInfo,
    *,
    db: Session,
    user_id: int,
    offset: int = 0,
    limit: int = 10,
) -> tuple[list[SessionRow], bool]:
    """Reading sessions of one book from the web reader and KOReader, newest first, and
    whether there are more after this page."""
    rows: list[tuple[int, SessionRow]] = []
    for session in db.scalars(
        select(ReadingSession)
        .where(ReadingSession.user_id == user_id, ReadingSession.document == md5)
        .order_by(ReadingSession.ended_at.desc())
        .limit(SESSIONS_PER_SOURCE)
    ):
        detail = f"{_percent(session.start_fraction)} → {_percent(session.end_fraction)}"
        rows.append(
            (
                session.started_at,
                SessionRow(
                    started=datetime.fromtimestamp(session.started_at, tz),
                    seconds=session.seconds,
                    source=session.device or "Web reader",
                    detail=detail,
                    resume_position=session.end_position,
                    resume_fraction=session.end_fraction,
                    id=session.id,
                ),
            )
        )
    for started, seconds, first, last, end_page, total in _koreader_sessions(path, md5):
        pages = f"page {first}" if first == last else f"pages {first}–{last}"
        if total:
            pages += f" of {total}"
        rows.append(
            (
                started,
                SessionRow(
                    started=datetime.fromtimestamp(started, tz),
                    seconds=seconds,
                    source="KOReader",
                    detail=pages,
                    # KOReader's page numbers depend on its layout; the share of the book doesn't.
                    resume_fraction=min(end_page / total, 1.0) if total else None,
                ),
            )
        )
    rows.sort(key=lambda row: row[0], reverse=True)
    page = [row for _, row in rows[offset : offset + limit]]
    return page, len(rows) > offset + limit


def _percent(fraction: float) -> str:
    value = max(0.0, min(1.0, fraction or 0.0)) * 100
    return f"{value:.0f}%" if value >= 10 or value == 0 else f"{value:.1f}%"


def _koreader_sessions(path: Path, md5: str) -> tuple[tuple[int, ...], ...]:
    if not path.is_file():
        return ()
    stat = path.stat()
    return _load_koreader_sessions(str(path), stat.st_mtime_ns, stat.st_size, md5)


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


@lru_cache(maxsize=64)
def _load_koreader_sessions(
    path: str, _mtime_ns: int, _size: int, md5: str
) -> tuple[tuple[int, ...], ...]:
    """(start, seconds, first page, last page, page read last, page count then) per sitting,
    newest first. A pause longer than SESSION_GAP since the end of the previous page starts a
    new session. The page count is the one KOReader recorded with that page (it changes with
    the font size), else the book's."""
    try:
        with closing(_connect(Path(path))) as conn:
            rows = conn.execute(
                f"""WITH reads AS (
                        SELECT p.start_time AS start, p.duration AS duration, p.page AS page,
                               COALESCE(NULLIF(p.total_pages, 0), b.pages, 0) AS total,
                               CASE WHEN p.start_time - MAX(p.start_time + p.duration) OVER (
                                   ORDER BY p.start_time
                                   ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                               ) > ? THEN 1 ELSE 0 END AS starts_session
                        FROM page_stat_data p JOIN book b ON b.id = p.id_book
                        WHERE b.md5 = ?
                    ), numbered AS (
                        SELECT *, SUM(starts_session) OVER (
                            ORDER BY start ROWS UNBOUNDED PRECEDING
                        ) AS session
                        FROM reads
                    ), ranked AS (
                        SELECT *, ROW_NUMBER() OVER (
                            PARTITION BY session ORDER BY start DESC
                        ) AS newest
                        FROM numbered
                    )
                    SELECT MIN(start), SUM(duration), MIN(page), MAX(page),
                           MAX(CASE WHEN newest = 1 THEN page END),
                           MAX(CASE WHEN newest = 1 THEN total END)
                    FROM ranked GROUP BY session ORDER BY 1 DESC
                    LIMIT {SESSIONS_PER_SOURCE}""",
                (SESSION_GAP, md5),
            ).fetchall()
    except sqlite3.Error:
        log.warning("Could not read statistics file %s", path, exc_info=True)
        return ()
    return tuple(tuple(int(value or 0) for value in row) for row in rows)


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
