"""Configuration of the browser reader: bar layout, settings schema and themes.

The effective configuration is built from three layers, later ones winning:

1. built-in defaults (``bookshelf/reader/defaults/*.json``),
2. optional server-wide files in ``<data_dir>/reader/`` (``layout.json``, ``settings.json``,
   ``themes.json``), edited by whoever runs the server,
3. the user's own override, stored in the database and edited on the settings page.

Besides the configuration, each user has *preferences*: the values currently chosen in the
reader's settings panel (theme, font size, ...).
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..models import ReaderProfile, User
from ..storage import Storage

DEFAULTS_DIR = Path(__file__).parent.parent / "reader" / "defaults"
PARTS = ("layout", "settings", "themes")
FONT_EXTENSIONS = {".woff2", ".woff", ".ttf", ".otf"}
MAX_CONFIG_BYTES = 64 * 1024
MAX_PREFS_BYTES = 16 * 1024

# Lists whose items are merged by a key instead of being replaced as a whole, so that an
# override with one extra theme adds to the defaults. Paths ignore list positions.
KEYED_LISTS = {
    "themes": "id",
    "settings.fonts": "id",
    "settings.sections": "id",
    "settings.sections.controls": "key",
}


# Numeric layout options and their allowed ranges (the bar editor offers these as controls).
LAYOUT_NUMBERS = {
    "autohide": {"delayMs": (500, 60000), "tapZone": (0.05, 0.45)},
    "chapterFlow": {
        "overscrollPx": (20, 2000),
        "settleMs": (0, 3000),
        "resetMs": (200, 10000),
        "cooldownMs": (0, 5000),
    },
}


class ReaderConfigError(Exception):
    """Invalid reader configuration or preferences; the message is shown to the user."""


def deep_merge(base: Any, override: Any, path: str = "") -> Any:
    """Merge ``override`` into a copy of ``base``.

    Objects merge key by key. Lists replace the base list, except the ``KEYED_LISTS``, whose
    items are matched by their key: matching items merge, new ones are appended.
    """
    if isinstance(base, dict) and isinstance(override, dict):
        merged = {key: copy.deepcopy(value) for key, value in base.items()}
        for key, value in override.items():
            child = f"{path}.{key}" if path else key
            merged[key] = deep_merge(merged[key], value, child) if key in merged else value
        return merged
    key = KEYED_LISTS.get(path)
    if key and isinstance(base, list) and isinstance(override, list):
        merged_list = [copy.deepcopy(item) for item in base]
        positions = {
            item[key]: index
            for index, item in enumerate(merged_list)
            if isinstance(item, dict) and key in item
        }
        for item in override:
            if isinstance(item, dict) and item.get(key) in positions:
                index = positions[item[key]]
                merged_list[index] = deep_merge(merged_list[index], item, path)
            else:
                merged_list.append(copy.deepcopy(item))
                if isinstance(item, dict) and key in item:
                    positions[item[key]] = len(merged_list) - 1
        return merged_list
    return copy.deepcopy(override)


def _drop_hidden(value: Any) -> Any:
    """Remove every object marked ``"hidden": true`` from lists (how overrides delete items)."""
    if isinstance(value, dict):
        return {key: _drop_hidden(child) for key, child in value.items()}
    if isinstance(value, list):
        return [
            _drop_hidden(item)
            for item in value
            if not (isinstance(item, dict) and item.get("hidden") is True)
        ]
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReaderConfigError(message)


def _check_keyed(items: Any, key: str, where: str) -> None:
    _require(isinstance(items, list), f"“{where}” must be a list.")
    for item in items:
        _require(
            isinstance(item, dict) and isinstance(item.get(key), str | int) and item[key] != "",
            f"Every entry in “{where}” must be an object with “{key}”.",
        )


def validate_override(data: Any) -> None:
    """Check the shape of an override (a server file set or a user's JSON)."""
    _require(isinstance(data, dict), "The reader configuration must be a JSON object.")
    unknown = sorted(set(data) - set(PARTS))
    _require(not unknown, f"Unknown section “{unknown[0] if unknown else ''}”. Use {PARTS}.")

    if "themes" in data:
        _check_keyed(data["themes"], "id", "themes")
    if "layout" in data:
        layout = data["layout"]
        _require(isinstance(layout, dict), "“layout” must be an object.")
        for bar in ("top", "bottom"):
            if bar not in layout:
                continue
            _require(isinstance(layout[bar], list), f"“layout.{bar}” must be a list.")
            for item in layout[bar]:
                ok = isinstance(item, str) or (
                    isinstance(item, dict) and isinstance(item.get("id"), str)
                )
                _require(ok, f"“layout.{bar}” entries must be element names or objects with “id”.")
        for name, limits in LAYOUT_NUMBERS.items():
            section = layout.get(name, {})
            _require(isinstance(section, dict), f"“layout.{name}” must be an object.")
            for key, value in section.items():
                if key == "enabled":
                    _require(
                        isinstance(value, bool), f"“layout.{name}.enabled” must be true/false."
                    )
                elif key in limits:
                    low, high = limits[key]
                    ok = isinstance(value, int | float) and not isinstance(value, bool)
                    _require(
                        ok and low <= value <= high,
                        f"“layout.{name}.{key}” must be a number from {low} to {high}.",
                    )
    if "settings" in data:
        settings = data["settings"]
        _require(isinstance(settings, dict), "“settings” must be an object.")
        if "fonts" in settings:
            _check_keyed(settings["fonts"], "id", "settings.fonts")
        if "sections" in settings:
            _check_keyed(settings["sections"], "id", "settings.sections")
            for section in settings["sections"]:
                if "controls" in section:
                    _check_keyed(section["controls"], "key", "settings.sections.controls")


def parse_override(text: str) -> dict[str, Any]:
    """Parse and validate override JSON typed by a user. Empty text means "no override"."""
    if not text.strip():
        return {}
    _require(len(text.encode()) <= MAX_CONFIG_BYTES, "The reader configuration is too large.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ReaderConfigError(
            f"Invalid JSON (line {error.lineno}, column {error.colno}): {error.msg}."
        ) from error
    validate_override(data)
    return data


@lru_cache(maxsize=1)
def _defaults() -> dict[str, Any]:
    return {
        part: json.loads((DEFAULTS_DIR / f"{part}.json").read_text(encoding="utf-8"))
        for part in PARTS
    }


def load_defaults() -> dict[str, Any]:
    return copy.deepcopy(_defaults())


def load_server_overrides(storage: Storage) -> dict[str, Any]:
    """Overrides from ``<data_dir>/reader/*.json``. Broken files are skipped with a warning,
    so a typo never takes the reader down."""
    overrides: dict[str, Any] = {}
    for part in PARTS:
        path = storage.reader_dir / f"{part}.json"
        if not path.is_file():
            continue
        try:
            data = {part: json.loads(path.read_text(encoding="utf-8"))}
            validate_override(data)
        except (OSError, ValueError, ReaderConfigError) as error:
            print(f"[reader] ignoring {path}: {error}", flush=True)
            continue
        overrides.update(data)
    return overrides


def _profile(db: Session, user: User) -> ReaderProfile | None:
    return db.get(ReaderProfile, user.id)


def _loads_object(text: str | None) -> dict[str, Any]:
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def user_config_path(storage: Storage, user: User) -> Path:
    """The user's override file: ``<data_dir>/reader/users/<username>.json``."""
    return storage.user_reader_config(user.id, user.username)


def user_config_text(storage: Storage, user: User) -> str:
    """The user's override file as it is on disk ("" when there is none)."""
    try:
        return user_config_path(storage, user).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def user_config_error(storage: Storage, user: User) -> str | None:
    """Why the user's (possibly hand-edited) file is ignored, or None when it is fine."""
    try:
        parse_override(user_config_text(storage, user))
    except ReaderConfigError as error:
        return str(error)
    return None


def _write_user_config(storage: Storage, user: User, data: dict[str, Any]) -> None:
    path = user_config_path(storage, user)
    if not data:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)  # atomic: a reader never sees a half-written file


def save_user_config(storage: Storage, user: User, text: str) -> None:
    """Replace the user's whole override file (the "Advanced" JSON editor)."""
    _write_user_config(storage, user, parse_override(text))  # raises ReaderConfigError


def save_user_layout(storage: Storage, user: User, layout: dict[str, Any] | None) -> None:
    """Set (or with None remove) only the ``layout`` part of the user's file; the bar editor
    uses this so that hand-written themes and settings stay untouched."""
    try:
        data = parse_override(user_config_text(storage, user))
    except ReaderConfigError as error:
        raise ReaderConfigError(
            f"Your reader configuration file has an error, fix it first: {error}"
        ) from error
    if layout is None:
        data.pop("layout", None)
    else:
        validate_override({"layout": layout})
        data["layout"] = layout
    _write_user_config(storage, user, data)


def effective_config(storage: Storage, user: User | None = None) -> dict[str, Any]:
    """Defaults, then server files, then the user's file; hidden items removed. A broken user
    file is ignored (and reported on the settings page) instead of breaking the reader."""
    config = deep_merge(load_defaults(), load_server_overrides(storage))
    if user is not None:
        try:
            override = parse_override(user_config_text(storage, user))
        except ReaderConfigError as error:
            print(f"[reader] ignoring {user_config_path(storage, user)}: {error}", flush=True)
            override = {}
        config = deep_merge(config, override)
    return _drop_hidden(config)


def get_prefs(db: Session, user: User) -> dict[str, Any]:
    profile = _profile(db, user)
    return _loads_object(profile.prefs) if profile else {}


def save_prefs(db: Session, user: User, prefs: Any) -> dict[str, Any]:
    """Store the values chosen in the settings panel: a flat object of simple values."""
    _require(isinstance(prefs, dict), "Preferences must be a JSON object.")
    for key, value in prefs.items():
        _require(
            isinstance(key, str) and (value is None or isinstance(value, str | int | float | bool)),
            "Preferences must be simple values.",
        )
    text = json.dumps(prefs, separators=(",", ":"))
    _require(len(text.encode()) <= MAX_PREFS_BYTES, "Too many preferences.")
    profile = _profile(db, user) or ReaderProfile(user_id=user.id)
    profile.prefs = text
    db.add(profile)
    db.commit()
    return prefs


def plugin_urls(storage: Storage) -> list[str]:
    """URLs of the drop-in bar element plugins in ``<data_dir>/reader/plugins/*.js``. The
    modification time is part of the URL, so browsers fetch a plugin again after an update."""
    folder = storage.reader_dir / "plugins"
    if not folder.is_dir():
        return []
    return [
        f"/reader/plugins/{path.name}?v={int(path.stat().st_mtime)}"
        for path in sorted(folder.glob("*.js"))
        if path.is_file()
    ]


def plugin_file(storage: Storage, name: str) -> Path | None:
    """A plugin module by plain file name (``*.js`` only, no paths)."""
    if Path(name).name != name or not name.endswith(".js"):
        return None
    path = storage.reader_dir / "plugins" / name
    return path if path.is_file() else None


def font_file(storage: Storage, name: str) -> Path | None:
    """A font in ``<data_dir>/reader/fonts/``; only plain file names of font types."""
    if Path(name).name != name or Path(name).suffix.lower() not in FONT_EXTENSIONS:
        return None
    path = storage.reader_dir / "fonts" / name
    return path if path.is_file() else None
