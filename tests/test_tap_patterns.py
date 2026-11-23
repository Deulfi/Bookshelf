from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from bookshelf.config import Settings
from bookshelf.services import tap_patterns
from bookshelf.storage import Storage
from tests.conftest import make_chapter_epub, upload


def test_parse_pads_rows_and_trims_blank_edges() -> None:
    assert tap_patterns.parse("\n\nLL  RR\nL R\n\n") == ["LL  RR", "L R   "]
    assert tap_patterns.parse("lr") == ["LR"]  # letters are case-insensitive


@pytest.mark.parametrize("text", ["", "   \n \n", "L" * 65, "L\n" * 65])
def test_parse_rejects_unusable_patterns(text: str) -> None:
    with pytest.raises(tap_patterns.TapPatternError):
        tap_patterns.parse(text)


def test_built_ins_are_valid_and_vary_in_size(settings: Settings) -> None:
    patterns = tap_patterns.load_patterns(Storage(settings.data_dir))
    sizes = {(len(p["rows"][0]), len(p["rows"])) for p in patterns}
    assert {p["id"] for p in patterns} >= {"Thirds", "Kindle", "Fine grid"}
    assert min(c * r for c, r in sizes) <= 3 and max(c * r for c, r in sizes) >= 400


def test_files_add_and_replace_patterns(settings: Settings) -> None:
    taps = settings.data_dir / "reader" / "taps"
    taps.mkdir(parents=True)
    (taps / "Mine.txt").write_text("LL  RR\nLL  RR\n")
    (taps / "Thirds").write_text("RRRR")  # replaces the built-in of that name
    (taps / "broken.txt").write_text("   ")  # skipped
    (taps / ".hidden").write_text("LR")
    patterns = {p["id"]: p["rows"] for p in tap_patterns.load_patterns(Storage(settings.data_dir))}
    assert patterns["Mine"] == ["LL  RR", "LL  RR"]
    assert patterns["Thirds"] == ["RRRR"]
    assert "broken" not in patterns and ".hidden" not in patterns


def test_reader_page_lists_patterns(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "c.epub", make_chapter_epub()).json()["id"]
    page = admin_client.get(f"/read/{book_id}").text
    data = json.loads(re.search(r'id="reader-bootstrap"[^>]*>(.*?)</script>', page, re.S).group(1))
    assert "Thirds" in {p["id"] for p in data["tapPatterns"]}
    controls = [c for s in data["config"]["settings"]["sections"] for c in s["controls"]]
    assert next(c for c in controls if c["key"] == "tapPattern")["default"] == "Thirds"


def test_rows_of_spaces_are_kept_but_empty_edge_lines_are_not() -> None:
    assert tap_patterns.parse("\n    \nLRLR\n    \n\n") == ["    ", "LRLR", "    "]


def test_a_dot_is_empty_space() -> None:
    assert tap_patterns.parse("....\nL..R\n....") == ["    ", "L  R", "    "]
