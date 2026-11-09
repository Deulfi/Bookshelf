"""Library-folder scanning: on startup, on demand (button) and optionally on a timer."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ..models import User
from ..storage import Storage
from . import library as library_service

# Choices offered in the settings page (minutes; 0 = only on startup and on demand).
INTERVAL_CHOICES = ((0, "Off"), (15, "Every 15 minutes"), (60, "Every hour"), (1440, "Every day"))
_TICK_SECONDS = 30


@dataclass
class ScanResult:
    finished_at: datetime
    imported: int = 0
    removed: int = 0
    error: str | None = None


class LibraryScanner:
    def __init__(self, session_factory: sessionmaker, storage: Storage, state_file: Path) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._state_file = state_file
        self._lock = threading.Lock()
        self._started_at = 0.0
        self.last_result: ScanResult | None = None

    @property
    def enabled(self) -> bool:
        return self._storage.ingest_dir is not None

    @property
    def running(self) -> bool:
        return self._lock.locked()

    @property
    def interval_minutes(self) -> int:
        try:
            value = int(json.loads(self._state_file.read_text()).get("interval_minutes", 0))
        except (OSError, ValueError, AttributeError):
            return 0
        return value if value in dict(INTERVAL_CHOICES) else 0

    def set_interval(self, minutes: int) -> None:
        if minutes not in dict(INTERVAL_CHOICES):
            raise ValueError("Unsupported scan interval.")
        self._state_file.write_text(json.dumps({"interval_minutes": minutes}))

    def run_scan(self) -> ScanResult | None:
        """Scan now and wait for it. Returns None if a scan is already running."""
        if not self.enabled or not self._lock.acquire(blocking=False):
            return None
        try:
            self._started_at = time.monotonic()
            messages: list[str] = []
            result = ScanResult(finished_at=datetime.now())
            try:
                with self._session_factory() as db:
                    # Books go to the first admin (the owner) until per-user folders exist.
                    user = db.scalar(select(User).order_by(User.is_admin.desc(), User.id).limit(1))
                    if user is not None:
                        library_service.sync_library(
                            db, self._storage, user, log=lambda m: self._record(m, messages)
                        )
            except Exception as error:  # a scan must never take the server down
                result.error = str(error)
                print(f"[scan] error: {error}", flush=True)
            result.imported = sum(m.startswith("imported ") for m in messages)
            result.removed = sum(m.startswith("removed ") for m in messages)
            result.finished_at = datetime.now()
            self.last_result = result
            return result
        finally:
            self._lock.release()

    @staticmethod
    def _record(message: str, messages: list[str]) -> None:
        messages.append(message)
        print(f"[scan] {message}", flush=True)

    def scan_in_background(self) -> bool:
        """Start a scan in a thread. False if the feature is off or a scan is running."""
        if not self.enabled or self.running:
            return False
        threading.Thread(target=self.run_scan, daemon=True).start()
        return True

    def start(self) -> None:
        """Scan once at startup, then follow the configured interval."""
        if not self.enabled:
            return
        self.scan_in_background()
        threading.Thread(target=self._timer_loop, daemon=True).start()

    def _timer_loop(self) -> None:
        while True:
            time.sleep(_TICK_SECONDS)
            minutes = self.interval_minutes
            if minutes and time.monotonic() - self._started_at >= minutes * 60:
                self.run_scan()
