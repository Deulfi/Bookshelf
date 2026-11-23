"""WebDAV endpoint, exercised the way KOReader's cloud storage plugin uses it."""

from __future__ import annotations

import os
import re
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient

from .conftest import ADMIN

URL = "/webdav/statistics.sqlite3"
DAV = "{DAV:}"


def test_requires_basic_auth(admin_client: TestClient) -> None:
    response = admin_client.request("PROPFIND", "/webdav/", headers={"Depth": "1"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic")
    assert admin_client.get(URL, auth=(ADMIN[0], "wrong")).status_code == 401


def test_koreader_sync_cycle(admin_client: TestClient) -> None:
    # First sync: nothing on the server yet, so KOReader uploads without If-Match.
    assert admin_client.get(URL, auth=ADMIN).status_code == 404
    created = admin_client.put(URL, content=b"version 1", auth=ADMIN)
    assert created.status_code == 201
    first_etag = created.headers["etag"]

    # Next sync: download with ETag, merge on the device, upload with If-Match.
    downloaded = admin_client.get(URL, auth=ADMIN)
    assert downloaded.content == b"version 1"
    assert downloaded.headers["etag"] == first_etag
    updated = admin_client.put(
        URL, content=b"version 2", headers={"If-Match": first_etag}, auth=ADMIN
    )
    assert updated.status_code == 204
    assert updated.headers["etag"] != first_etag

    # Another device uploading on top of a stale download is rejected; KOReader then retries.
    stale = admin_client.put(URL, content=b"stale", headers={"If-Match": first_etag}, auth=ADMIN)
    assert stale.status_code == 412
    weak = admin_client.put(
        URL, content=b"version 3", headers={"If-Match": "W/" + updated.headers["etag"]}, auth=ADMIN
    )
    assert weak.status_code == 204
    assert admin_client.get(URL, auth=ADMIN).content == b"version 3"


def test_replacing_within_one_clock_tick_changes_the_etag(tmp_path) -> None:
    from bookshelf.services.files import FileStore

    store = FileStore(tmp_path)
    for content in (b"version 1", b"version 2", b"version 3"):
        old = store.get("stats.sqlite3")
        temp = store.new_temp_path()
        temp.write_bytes(content)
        if old is not None:  # same size and the same file time, as within one clock tick
            mtime = old.path.stat().st_mtime_ns
            os.utime(temp, ns=(mtime, mtime))
        store.commit(temp, "stats.sqlite3")
        new = store.get("stats.sqlite3")
        assert old is None or new.etag != old.etag
    assert new.path.read_bytes() == b"version 3"


def test_propfind_listing(admin_client: TestClient) -> None:
    admin_client.put(URL, content=b"12345", auth=ADMIN)
    response = admin_client.request("PROPFIND", "/webdav/", headers={"Depth": "1"}, auth=ADMIN)
    assert response.status_code == 207

    tree = ET.fromstring(response.content)
    entries = {
        r.findtext(f"{DAV}href"): r.find(f".//{DAV}prop") for r in tree.iter(f"{DAV}response")
    }
    assert entries["/webdav/"].find(f"{DAV}resourcetype/{DAV}collection") is not None
    file_props = entries["/webdav/statistics.sqlite3"]
    assert file_props.findtext(f"{DAV}getcontentlength") == "5"
    assert file_props.find(f"{DAV}resourcetype/{DAV}collection") is None

    # KOReader parses the XML with Lua patterns; mirror them to stay compatible.
    chunks = re.findall(r"<[^>]*response[^>]*>(.*?)</[^>]*response>", response.text, re.S)
    hrefs = [re.search(r"<[^>]*href[^>]*>(.*)</[^>]*href>", c).group(1) for c in chunks]
    assert hrefs == ["/webdav/", "/webdav/statistics.sqlite3"]

    depth0 = admin_client.request("PROPFIND", "/webdav/", headers={"Depth": "0"}, auth=ADMIN)
    assert depth0.text.count("<D:response>") == 1


def test_names_and_unsupported_methods(admin_client: TestClient) -> None:
    assert admin_client.put("/webdav/folder/file.txt", content=b"x", auth=ADMIN).status_code == 409
    assert admin_client.put("/webdav/.hidden", content=b"x", auth=ADMIN).status_code == 400
    assert admin_client.request("MKCOL", "/webdav/folder", auth=ADMIN).status_code == 405
    options = admin_client.options("/webdav/")
    assert options.headers["dav"] == "1"


def test_delete(admin_client: TestClient) -> None:
    admin_client.put(URL, content=b"x", auth=ADMIN)
    assert admin_client.delete(URL, auth=ADMIN).status_code == 204
    assert admin_client.delete(URL, auth=ADMIN).status_code == 404


def test_files_are_private(admin_client: TestClient) -> None:
    admin_client.put(URL, content=b"secret", auth=ADMIN)
    admin_client.post("/admin/users", data={"username": "bob", "password": "bobpass1"})
    assert admin_client.get(URL, auth=("bob", "bobpass1")).status_code == 404
    listing = admin_client.request("PROPFIND", "/webdav/", auth=("bob", "bobpass1"))
    assert "statistics.sqlite3" not in listing.text
