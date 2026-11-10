from __future__ import annotations

import html
import json
import re

import pytest
from fastapi.testclient import TestClient

from bookshelf.config import Settings
from bookshelf.services import reader_config
from bookshelf.services.reader_config import ReaderConfigError, deep_merge
from tests.conftest import make_chapter_epub, upload


def bootstrap(page: str) -> dict:
    match = re.search(
        r'<script type="application/json" id="reader-bootstrap">(.*?)</script>', page, re.S
    )
    assert match, "reader page has no bootstrap JSON"
    return json.loads(html.unescape(match.group(1)))


def login_as_bob(admin_client: TestClient) -> None:
    admin_client.post("/admin/users", data={"username": "bob", "password": "bobpass1"})
    admin_client.post("/logout")
    admin_client.post("/login", data={"username": "bob", "password": "bobpass1"})


# ---------- merge rules ----------


def test_merge_objects_recursively_and_replace_plain_lists() -> None:
    base = {"layout": {"top": ["exit", "toc"], "autohide": {"enabled": True, "delayMs": 1}}}
    merged = deep_merge(base, {"layout": {"top": ["settings"], "autohide": {"delayMs": 9}}})
    assert merged["layout"]["top"] == ["settings"]
    assert merged["layout"]["autohide"] == {"enabled": True, "delayMs": 9}
    assert base["layout"]["autohide"]["delayMs"] == 1  # inputs are not modified


def test_merge_keyed_lists_by_id_and_key() -> None:
    base = reader_config.load_defaults()
    override = {
        "themes": [
            {"id": "night", "label": "Night", "bg": "#000", "fg": "#ccc"},
            {"id": "sepia", "label": "Old paper"},
        ],
        "settings": {"sections": [{"id": "text", "controls": [{"key": "fontSize", "max": 48}]}]},
    }
    merged = deep_merge(base, override)
    ids = [t["id"] for t in merged["themes"]]
    assert ids[: len(base["themes"])] == [t["id"] for t in base["themes"]]
    assert ids[-1] == "night"
    assert next(t for t in merged["themes"] if t["id"] == "sepia")["label"] == "Old paper"
    text = next(s for s in merged["settings"]["sections"] if s["id"] == "text")
    font_size = next(c for c in text["controls"] if c["key"] == "fontSize")
    assert font_size["max"] == 48
    assert font_size["min"] == 12  # untouched fields stay
    assert len(text["controls"]) == len(
        next(s for s in base["settings"]["sections"] if s["id"] == "text")["controls"]
    )


def test_hidden_items_are_removed(admin_client: TestClient, settings: Settings) -> None:
    admin_client.post(
        "/settings/reader",
        data={"config": json.dumps({"themes": [{"id": "sepia", "hidden": True}]})},
    )
    config = reader_config.effective_config(admin_client.app.state.storage, _admin(admin_client))
    assert "sepia" not in [t["id"] for t in config["themes"]]


def _admin(client: TestClient):
    from bookshelf.models import User

    with client.app.state.sessionmaker() as db:
        user = db.query(User).filter_by(username="admin").one()
        db.expunge(user)
        return user


# ---------- validation ----------


@pytest.mark.parametrize(
    "text",
    [
        "[1, 2]",
        '{"colors": {}}',
        '{"themes": [{"label": "no id"}]}',
        '{"layout": {"top": [42]}}',
        '{"layout": {"autohide": true}}',
        '{"settings": {"sections": [{"id": "x", "controls": [{"type": "range"}]}]}}',
        "{not json",
    ],
)
def test_invalid_overrides_are_rejected(text: str) -> None:
    with pytest.raises(ReaderConfigError):
        reader_config.parse_override(text)


def test_empty_override_is_allowed() -> None:
    assert reader_config.parse_override("  ") == {}


def test_defaults_are_valid() -> None:
    reader_config.validate_override(reader_config.load_defaults())


# ---------- layering ----------


def test_server_files_and_user_override_layer_on_defaults(
    admin_client: TestClient, settings: Settings
) -> None:
    reader_dir = settings.data_dir / "reader"
    reader_dir.mkdir()
    (reader_dir / "themes.json").write_text(
        json.dumps([{"id": "server", "label": "Server", "bg": "#111", "fg": "#eee"}])
    )
    (reader_dir / "layout.json").write_text('{"top": ["exit", "title"]}')
    (reader_dir / "settings.json").write_text("{broken")  # ignored, never breaks the reader

    admin_client.post(
        "/settings/reader", data={"config": '{"layout": {"top": ["settings", "exit"]}}'}
    )
    book_id = upload(admin_client, "c.epub", make_chapter_epub()).json()["id"]
    config = bootstrap(admin_client.get(f"/read/{book_id}").text)["config"]

    theme_ids = [t["id"] for t in config["themes"]]
    assert "server" in theme_ids and "light" in theme_ids
    assert config["layout"]["top"] == ["settings", "exit"]  # user wins over the server file
    assert config["layout"]["bottom"]  # defaults still present
    assert config["settings"]["sections"]  # broken server file skipped


# ---------- reader page and preferences ----------


def test_reader_page_inlines_book_config_and_prefs(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "c.epub", make_chapter_epub()).json()["id"]
    response = admin_client.get(f"/read/{book_id}")
    assert response.status_code == 200
    data = bootstrap(response.text)
    assert data["book"]["fileUrl"] == f"/books/{book_id}/file"
    assert data["book"]["title"] == "Chapter Test Book"
    assert data["prefs"] == {}
    assert data["config"]["layout"]["top"]
    assert 'data-icon="settings"' in response.text


def test_prefs_roundtrip(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "c.epub", make_chapter_epub()).json()["id"]
    prefs = {"theme": "sepia", "fontSize": 22, "autoAdvance": False}
    response = admin_client.put("/api/reader/prefs", json=prefs)
    assert response.status_code == 200
    assert bootstrap(admin_client.get(f"/read/{book_id}").text)["prefs"] == prefs


@pytest.mark.parametrize("body", [[1, 2], {"nested": {"a": 1}}, "text"])
def test_prefs_must_be_flat_objects(admin_client: TestClient, body: object) -> None:
    assert admin_client.put("/api/reader/prefs", json=body).status_code == 422


def test_prefs_require_login(client: TestClient) -> None:
    assert client.put("/api/reader/prefs", json={}).status_code == 401


def test_config_and_prefs_are_private(admin_client: TestClient) -> None:
    admin_client.put("/api/reader/prefs", json={"theme": "dark"})
    admin_client.post("/settings/reader", data={"config": '{"layout": {"top": ["exit"]}}'})
    login_as_bob(admin_client)
    book_id = upload(admin_client, "c.epub", make_chapter_epub()).json()["id"]
    data = bootstrap(admin_client.get(f"/read/{book_id}").text)
    assert data["prefs"] == {}
    assert data["config"]["layout"]["top"] != ["exit"]
    textarea = re.search(
        r'id="reader-config"[^>]*>(.*?)</textarea>', admin_client.get("/settings").text, re.S
    )
    assert textarea and textarea.group(1).strip() == ""


# ---------- settings page ----------


def test_invalid_override_rerenders_with_422(admin_client: TestClient) -> None:
    response = admin_client.post("/settings/reader", data={"config": '{"themes": 5}'})
    assert response.status_code == 422
    assert "must be a list" in response.text
    assert "{&#34;themes&#34;: 5}" in response.text or '{"themes": 5}' in response.text


def test_override_save_and_reset(admin_client: TestClient) -> None:
    saved = admin_client.post(
        "/settings/reader", data={"config": '{"layout": {"top": ["exit"]}}'}, follow_redirects=False
    )
    assert saved.status_code == 303
    assert "Reader configuration saved." in admin_client.get(saved.headers["location"]).text
    storage = admin_client.app.state.storage
    path = reader_config.user_config_path(storage, _admin(admin_client))
    assert path == settings_path(admin_client, "admin")
    assert json.loads(path.read_text()) == {"layout": {"top": ["exit"]}}
    admin_client.post("/settings/reader", data={"config": "ignored", "action": "reset"})
    assert not path.exists()
    assert reader_config.user_config_text(storage, _admin(admin_client)) == ""


def settings_path(client: TestClient, username: str):
    return client.app.state.storage.root / "reader" / "users" / f"{username}.json"


def test_hand_edited_file_is_used(admin_client: TestClient) -> None:
    path = settings_path(admin_client, "admin")
    path.parent.mkdir(parents=True)
    path.write_text('{"layout": {"top": ["toc"]}}', encoding="utf-8")
    book_id = upload(admin_client, "c.epub", make_chapter_epub()).json()["id"]
    assert bootstrap(admin_client.get(f"/read/{book_id}").text)["config"]["layout"]["top"] == [
        "toc"
    ]
    assert "toc" in admin_client.get("/settings").text


def test_broken_file_is_ignored_and_reported(admin_client: TestClient) -> None:
    path = settings_path(admin_client, "admin")
    path.parent.mkdir(parents=True)
    path.write_text('{"layout": {"top": ["toc"]', encoding="utf-8")
    book_id = upload(admin_client, "c.epub", make_chapter_epub()).json()["id"]
    page = admin_client.get(f"/read/{book_id}")
    assert page.status_code == 200
    assert bootstrap(page.text)["config"]["layout"]["top"] != ["toc"]
    assert "is ignored because it has an error" in admin_client.get("/settings").text


def test_layout_editor_keeps_the_rest_of_the_file(admin_client: TestClient) -> None:
    theme = {"id": "night", "label": "Night", "bg": "#000", "fg": "#ccc"}
    admin_client.post("/settings/reader", data={"config": json.dumps({"themes": [theme]})})
    layout = {"top": ["exit", "settings"], "bottom": [], "autohide": {"delayMs": 5000}}
    response = admin_client.post("/settings/reader/layout", json={"layout": layout})
    assert response.status_code == 200
    assert response.json()["layout"]["top"] == ["exit", "settings"]
    saved = json.loads(settings_path(admin_client, "admin").read_text())
    assert saved == {"themes": [theme], "layout": layout}

    assert admin_client.post("/settings/reader/layout", json={"layout": None}).status_code == 200
    assert json.loads(settings_path(admin_client, "admin").read_text()) == {"themes": [theme]}


@pytest.mark.parametrize(
    "body",
    [
        {"layout": {"top": [42]}},
        {"layout": {"autohide": {"delayMs": 5}}},
        {"layout": {"chapterFlow": {"overscrollPx": "far"}}},
        {"nothing": 1},
        [1],
    ],
)
def test_layout_editor_rejects_bad_input(admin_client: TestClient, body: object) -> None:
    assert admin_client.post("/settings/reader/layout", json=body).status_code == 422


def test_layout_editor_refuses_to_overwrite_a_broken_file(admin_client: TestClient) -> None:
    path = settings_path(admin_client, "admin")
    path.parent.mkdir(parents=True)
    path.write_text("{oops", encoding="utf-8")
    response = admin_client.post("/settings/reader/layout", json={"layout": {"top": []}})
    assert response.status_code == 422
    assert path.read_text() == "{oops"


def test_deleting_a_user_removes_their_file(admin_client: TestClient) -> None:
    admin_client.post("/admin/users", data={"username": "bob", "password": "bobpass1"})
    path = settings_path(admin_client, "bob")
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    from bookshelf.services import users

    with admin_client.app.state.sessionmaker() as db:
        bob = users.get_by_username(db, "bob")
        users.delete_user(db, admin_client.app.state.storage, bob)
    assert not path.exists()


def test_defaults_reference(admin_client: TestClient) -> None:
    response = admin_client.get("/settings/reader/defaults")
    assert response.status_code == 200
    assert response.json()["themes"]


# ---------- fonts ----------


def test_fonts_are_served_by_name_only(admin_client: TestClient, settings: Settings) -> None:
    fonts = settings.data_dir / "reader" / "fonts"
    fonts.mkdir(parents=True)
    (fonts / "Literata.woff2").write_bytes(b"wOF2")
    (settings.data_dir / "secret.woff2").write_bytes(b"nope")

    assert admin_client.get("/reader/fonts/Literata.woff2").content == b"wOF2"
    assert admin_client.get("/reader/fonts/..%2Fsecret.woff2").status_code == 404
    assert admin_client.get("/reader/fonts/notes.txt").status_code == 404
    assert reader_config.font_file(admin_client.app.state.storage, "../secret.woff2") is None


# ---------- plugins and the bar editor ----------


def test_plugins_are_listed_and_served(admin_client: TestClient, settings: Settings) -> None:
    plugins = settings.data_dir / "reader" / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "clock.js").write_text("export default {id: 'clock', create() {}}")
    (plugins / "notes.txt").write_text("not a plugin")
    (settings.data_dir / "secret.js").write_text("nope")

    book_id = upload(admin_client, "c.epub", make_chapter_epub()).json()["id"]
    urls = bootstrap(admin_client.get(f"/read/{book_id}").text)["plugins"]
    assert len(urls) == 1 and urls[0].startswith("/reader/plugins/clock.js?v=")

    response = admin_client.get("/reader/plugins/clock.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert admin_client.get("/reader/plugins/notes.txt").status_code == 404
    assert admin_client.get("/reader/plugins/..%2Fsecret.js").status_code == 404


def test_plugins_require_login(client: TestClient) -> None:
    response = client.get("/reader/plugins/clock.js", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_layout_editor_data(admin_client: TestClient) -> None:
    admin_client.post("/settings/reader/layout", json={"layout": {"top": ["toc"]}})
    data = admin_client.get("/api/reader/layout").json()
    assert data["layout"]["top"] == ["toc"]
    assert data["defaultLayout"]["top"] != ["toc"]
    assert data["limits"]["autohide"]["delayMs"] == [500, 60000]
    assert data["plugins"] == []


def test_settings_page_loads_the_bar_editor(admin_client: TestClient) -> None:
    page = admin_client.get("/settings").text
    assert 'id="layout-editor"' in page
    assert "js/reader-layout.js" in page
    assert '"/static/js/reader/elements/index.js"' in page  # import map entry
