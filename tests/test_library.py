from fastapi.testclient import TestClient

from .conftest import make_epub, upload


def test_upload_epub_extracts_metadata(admin_client: TestClient) -> None:
    epub = make_epub()
    response = upload(admin_client, "whatever.epub", epub)
    assert response.status_code == 201
    book_id = response.json()["id"]

    page = admin_client.get(f"/books/{book_id}")
    assert page.status_code == 200
    assert "The Test Book" in page.text
    assert "Ada Lovelace" in page.text
    assert "Some Illustrator" not in page.text  # only authors, not illustrators
    assert "Engines · Book 2" in page.text
    assert "<p>Second paragraph.</p>" in page.text

    cover = admin_client.get(f"/books/{book_id}/cover")
    assert cover.status_code == 200
    assert cover.headers["content-type"] == "image/jpeg"

    download = admin_client.get(f"/books/{book_id}/file")
    assert download.status_code == 200
    assert download.content == epub


def test_duplicate_upload_is_rejected(admin_client: TestClient) -> None:
    epub = make_epub()
    assert upload(admin_client, "a.epub", epub).status_code == 201
    duplicate = upload(admin_client, "b.epub", epub)
    assert duplicate.status_code == 409
    assert duplicate.json()["duplicate"] is True


def test_unsupported_and_empty_files(admin_client: TestClient) -> None:
    assert upload(admin_client, "virus.exe", b"MZ").status_code == 422
    assert upload(admin_client, "empty.epub", b"").status_code == 422


def test_filename_fallback_for_unparseable_files(admin_client: TestClient) -> None:
    response = upload(admin_client, "Jane Austen - Emma.mobi", b"not really a mobi file")
    assert response.status_code == 201
    page = admin_client.get(response.json()["url"])
    assert "Emma" in page.text and "Jane Austen" in page.text


def test_search_filter_and_fragment(admin_client: TestClient) -> None:
    upload(admin_client, "a.epub", make_epub(title="Dune", author="Frank Herbert", series=None))
    upload(admin_client, "b.epub", make_epub(title="Emma", author="Jane Austen", series=None))

    full = admin_client.get("/?q=herbert")
    assert "Dune" in full.text and "Emma" not in full.text
    assert "<html" in full.text

    fragment = admin_client.get("/?q=austen", headers={"HX-Request": "true"})
    assert "Emma" in fragment.text and "Dune" not in fragment.text
    assert "<html" not in fragment.text


def test_edit_and_delete_book(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "a.epub", make_epub()).json()["id"]
    admin_client.post(
        f"/books/{book_id}",
        data={"title": "Renamed", "author": "Someone", "series": "", "series_index": "1,5"},
    )
    page = admin_client.get(f"/books/{book_id}")
    assert "Renamed" in page.text and "Someone" in page.text

    admin_client.post(f"/books/{book_id}/delete")
    assert admin_client.get(f"/books/{book_id}").status_code == 404


def test_libraries_are_private(admin_client: TestClient, client: TestClient) -> None:
    book_id = upload(admin_client, "a.epub", make_epub()).json()["id"]
    admin_client.post("/admin/users", data={"username": "bob", "password": "bobpass1"})
    admin_client.post("/logout")
    client.post("/login", data={"username": "bob", "password": "bobpass1"})
    assert client.get(f"/books/{book_id}").status_code == 404
    assert client.get(f"/books/{book_id}/file").status_code == 404


def test_upload_requires_login(client: TestClient) -> None:
    assert upload(client, "a.epub", make_epub()).status_code == 401


def test_position_roundtrip(admin_client: TestClient) -> None:
    book_id = upload(admin_client, "a.epub", make_epub()).json()["id"]

    empty = admin_client.get(f"/api/books/{book_id}/position")
    assert empty.status_code == 200
    assert empty.json() == {"cfi": None, "percentage": None}

    cfi = "epubcfi(/6/2[para:1]{1})"
    put = admin_client.put(f"/api/books/{book_id}/position", json={"cfi": cfi, "fraction": 0.42})
    assert put.status_code == 200
    assert put.json() == {"cfi": cfi, "percentage": 0.42}

    got = admin_client.get(f"/api/books/{book_id}/position")
    assert got.json() == {"cfi": cfi, "percentage": 0.42}

    # the record is the one the library displays (keyed by the book's partial_md5)
    page = admin_client.get(f"/books/{book_id}")
    assert "42%" in page.text


def test_position_requires_login(client: TestClient) -> None:
    assert client.get("/api/books/1/position").status_code == 401
    assert (
        client.put("/api/books/1/position", json={"cfi": "x", "fraction": 0.5}).status_code == 401
    )


def test_position_is_private(admin_client: TestClient, client: TestClient) -> None:
    book_id = upload(admin_client, "a.epub", make_epub()).json()["id"]
    admin_client.post("/admin/users", data={"username": "bob", "password": "bobpass1"})
    admin_client.post("/logout")
    client.post("/login", data={"username": "bob", "password": "bobpass1"})
    assert client.get(f"/api/books/{book_id}/position").status_code == 404
    assert (
        client.put(f"/api/books/{book_id}/position", json={"cfi": "x", "fraction": 0.5}).status_code
        == 404
    )
