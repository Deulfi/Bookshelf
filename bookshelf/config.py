"""Runtime configuration, read from environment variables prefixed with ``BOOKSHELF_``."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


def _env_list(name: str) -> tuple[str, ...]:
    """Comma-separated values, e.g. "@eaDir, *.tmp"."""
    return tuple(item.strip() for item in os.environ.get(name, "").split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("./data")
    # Allow KOReader clients to create accounts via the sync protocol (/users/create).
    allow_registration: bool = False
    max_upload_mb: int = 200
    session_days: int = 30
    # Set to true when Bookshelf is served over HTTPS (e.g. behind a reverse proxy).
    secure_cookies: bool = False
    # IANA time zone used to group reading statistics by day (standard TZ variable).
    timezone: str = "UTC"
    # Directory to scan for new books (empty = disabled)
    ingest_dir: Path | None = None
    # Extra names (fnmatch patterns) that library scans skip; names starting with "." always are.
    scan_ignore: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            data_dir=Path(os.environ.get("BOOKSHELF_DATA_DIR", "./data")),
            allow_registration=_env_bool("BOOKSHELF_ALLOW_REGISTRATION", False),
            max_upload_mb=int(os.environ.get("BOOKSHELF_MAX_UPLOAD_MB", "200")),
            session_days=int(os.environ.get("BOOKSHELF_SESSION_DAYS", "30")),
            secure_cookies=_env_bool("BOOKSHELF_SECURE_COOKIES", False),
            timezone=os.environ.get("TZ", "UTC"),
            ingest_dir=_env_path("BOOKSHELF_INGEST_DIR"),
            scan_ignore=_env_list("BOOKSHELF_SCAN_IGNORE"),
        )

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'bookshelf.db').as_posix()}"

    @property
    def tzinfo(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo("UTC")

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024
