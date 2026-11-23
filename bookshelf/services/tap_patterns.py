"""Tap patterns for the web reader's page mode: which part of the screen does what.

A pattern is a small text grid. Every line is a row of the screen, every character a column, and
the grid is stretched over the whole screen, so a pattern can be tiny or very fine::

    LL  RR
    LL  RR
    LL  RR

Letters are actions: ``L`` previous page, ``R`` next page, ``T`` show or hide the bars. A space
or a dot (empty area) shows or hides the bars too, which is how they are reached in page
mode, so ``T`` is rarely needed. Other letters are reserved for future actions and are ignored
for now.

Patterns are files in ``<data dir>/reader/taps/``; the file name without its extension is the
pattern's name, and a file named like a built-in one replaces it. Bad files are skipped.
"""

from __future__ import annotations

from typing import Any

from ..storage import Storage

DEFAULT_PATTERN = "Thirds"
MAX_SIDE = 64
MAX_FILE_BYTES = 8 * 1024


class TapPatternError(ValueError):
    """The text is not a usable pattern."""


def _fine_grid() -> str:
    """A 24 x 20 grid to show how fine a pattern can get: empty strips along the top and
    bottom, page turns left and right with a split in the middle, an empty centre."""
    rows = []
    for y in range(20):
        if y < 2 or y >= 18:
            rows.append(" " * 24)
        elif 8 <= y < 12:
            rows.append("L" * 7 + "R" * 3 + " " * 4 + "L" * 3 + "R" * 7)
        else:
            rows.append("L" * 8 + ("L" if y < 10 else "R") * 8 + "R" * 8)
    return "\n".join(rows)


BUILT_IN: dict[str, str] = {
    # Three cells: previous on the left third, next on the right third, bars in the middle.
    "Thirds": "L R",
    "Kindle": "\n".join(["      ", *["LRRRRR"] * 4, "      "]),
    "Edges": "\n".join(["L    R"] * 3),
    "Halves": "\n".join(["    ", "LLLL", "LLLL", "RRRR", "RRRR", "    "]),
    "L-shape": "\n".join(["        ", *["LLLLLLRR"] * 4, "RRRRRRRR", "RRRRRRRR"]),
    "Fine grid": _fine_grid(),
}


def parse(text: str) -> list[str]:
    """Rows of equal width from a pattern text; raises ``TapPatternError`` when unusable."""
    if len(text.encode()) > MAX_FILE_BYTES:
        raise TapPatternError("The pattern file is too large.")
    # Rows made of spaces are rows (empty space); completely empty lines at the start and end
    # are just file padding.
    lines = [line.replace("	", " ").replace(".", " ") for line in text.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    width = max((len(line) for line in lines), default=0)
    if not any(line.strip() for line in lines):
        raise TapPatternError("The pattern is empty.")
    if len(lines) > MAX_SIDE or width > MAX_SIDE:
        raise TapPatternError(f"A pattern can be at most {MAX_SIDE} rows and columns.")
    return [line.ljust(width).upper() for line in lines]


def load_patterns(storage: Storage) -> list[dict[str, Any]]:
    """Built-in patterns plus the files in ``<data dir>/reader/taps/``, as
    ``[{"id": name, "rows": [...]}]`` (built-ins first, a file replaces a built-in of its name)."""
    texts = dict(BUILT_IN)
    folder = storage.reader_dir / "taps"
    if folder.is_dir():
        for path in sorted(folder.iterdir(), key=lambda p: p.name.casefold()):
            if not path.is_file() or path.name.startswith(".") or not path.stem:
                continue
            try:
                texts[path.stem] = "\n".join(parse(path.read_text(encoding="utf-8")))
            except (OSError, ValueError) as error:
                print(f"[reader] ignoring tap pattern {path}: {error}", flush=True)
    patterns = []
    for name, text in texts.items():
        try:
            patterns.append({"id": name, "rows": parse(text)})
        except TapPatternError:  # only possible for a broken built-in
            continue
    return patterns
