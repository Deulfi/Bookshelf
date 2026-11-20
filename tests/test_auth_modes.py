"""BOOKSHELF_AUTH: password (default), none (single user) and header (reverse proxy) modes."""

from __future__ import annotations

import base64
import dataclasses

import pytest
from fastapi.testclient import TestClient

from bookshelf import security
from bookshelf.config import Settings
from bookshelf.main import create_app

PROXY = "testclient"  # the address TestClient connects from


def make_client(settings: Settings, **changes) -> TestClient:
    return TestClient(create_app(dataclasses.replace(settings, **changes)))


def basic(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_settings_check_the_mode(settings: Settings) -> None:
    with pytest.raises(ValueError, match="BOOKSHELF_AUTH must be"):
        dataclasses.replace(settings, auth="oidc")
    with pytest.raises(ValueError, match="BOOKSHELF_AUTH_PROXIES"):
        dataclasses.replace(settings, auth="header")


def test_single_user_mode_needs_no_login(settings: Settings) -> None:
    with make_client(settings, auth="none") as client:
        page = client.get("/", follow_redirects=False)
        assert page.status_code == 200
        for path in ("/login", "/setup"):
            assert client.get(path, follow_redirects=False).headers["location"] == "/"

        settings_page = client.get("/settings").text
        assert "Device password" in settings_page and "Log out" not in settings_page
        assert "current_password" not in settings_page
        # devices still need the password, which the settings page sets
        assert client.get("/opds", headers=basic("admin", "devicepw1")).status_code == 401
        response = client.post(
            "/settings/password",
            data={"new_password": "devicepw1", "new_password_confirm": "devicepw1"},
        )
        assert response.status_code == 200
        assert client.get("/opds", headers=basic("admin", "devicepw1")).status_code == 200


def test_single_user_mode_uses_the_existing_admin(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        client.post(
            "/setup",
            data={"username": "ada", "password": "secret123", "password_confirm": "secret123"},
        )
    with make_client(settings, auth="none") as client:
        assert "ada" in client.get("/settings").text
        assert client.get("/opds", headers=basic("ada", "secret123")).status_code == 200


def test_cross_site_posts_are_refused_without_login(settings: Settings) -> None:
    with make_client(settings, auth="none") as client:
        form = {"new_password": "devicepw1", "new_password_confirm": "devicepw1"}
        refused = client.post(
            "/settings/password", data=form, headers={"Sec-Fetch-Site": "cross-site"}
        )
        assert refused.status_code == 403
        refused = client.post(
            "/settings/password",
            data=form,
            headers={"Origin": "https://evil.example", "Host": "books.lan"},
        )
        assert refused.status_code == 403
        same = client.post(
            "/settings/password", data=form, headers={"Sec-Fetch-Site": "same-origin"}
        )
        assert same.status_code == 200
        # device clients send neither header
        response = client.put(
            "/syncs/progress",
            json={"document": "a" * 32, "progress": "x", "percentage": 0.5, "device": "Kobo"},
            headers={"x-auth-user": "admin", "x-auth-key": security.md5_hex("devicepw1")},
        )
        assert response.status_code == 200


def test_header_mode_signs_in_from_the_proxy(settings: Settings) -> None:
    with make_client(settings, auth="header", auth_proxies=(PROXY,)) as client:
        missing = client.get("/", headers={"Accept": "text/html"}, follow_redirects=False)
        assert missing.status_code == 401 and "Remote-User" in missing.text

        page = client.get("/settings", headers={"Remote-User": "Alice"})
        assert page.status_code == 200 and "alice" in page.text
        assert "Device password" in page.text
        # the first account is an administrator, later ones are not
        assert client.get("/admin/users", headers={"Remote-User": "alice"}).status_code == 200
        assert client.get("/admin/users", headers={"Remote-User": "bob"}).status_code == 403

        bad = client.get("/", headers={"Remote-User": "not valid!"})
        assert bad.status_code == 403


def test_header_mode_ignores_unlisted_addresses(settings: Settings) -> None:
    with make_client(settings, auth="header", auth_proxies=("10.0.0.0/8",)) as client:
        response = client.get("/", headers={"Remote-User": "alice"})
        assert response.status_code == 403
        assert "BOOKSHELF_AUTH_PROXIES" in response.text


def test_header_mode_custom_header(settings: Settings) -> None:
    changes = {"auth": "header", "auth_proxies": (PROXY,), "auth_header": "X-Forwarded-User"}
    with make_client(settings, **changes) as client:
        assert client.get("/", headers={"Remote-User": "alice"}).status_code == 401
        assert client.get("/", headers={"X-Forwarded-User": "alice"}).status_code == 200


def test_address_allowed() -> None:
    allowed = ("172.16.0.0/12", "192.168.1.5", "proxy")
    assert security.address_allowed("172.18.0.3", allowed)
    assert security.address_allowed("::ffff:172.18.0.3", allowed)
    assert security.address_allowed("192.168.1.5", allowed)
    assert security.address_allowed("proxy", allowed)
    assert not security.address_allowed("192.168.1.6", allowed)
    assert not security.address_allowed("", allowed)


def test_password_mode_is_unchanged(admin_client: TestClient) -> None:
    page = admin_client.get("/settings").text
    assert "Change password" in page and "current_password" in page and "Log out" in page
    # cross-site checks only apply without a login cookie
    response = admin_client.get("/login", follow_redirects=False)
    assert response.headers["location"] == "/"
