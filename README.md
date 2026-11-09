# Bookshelf

A lean, self-hosted e-book library with **KOReader progress sync** and an **OPDS catalog**.
Upload your books, read them on any KOReader device, and keep your reading position in sync.
Everything runs in one small Docker container with a single SQLite database.

![Bookshelf library view](docs/screenshots/library-light.png)

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/book.png" alt="Book details with KOReader reading progress"></td>
    <td width="50%"><img src="docs/screenshots/library-dark.png" alt="Library in dark mode"></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/stats.png" alt="Reading statistics synced from KOReader"></td>
    <td><img src="docs/screenshots/settings.png" alt="KOReader sync, OPDS and statistics setup"></td>
  </tr>
</table>

<p align="center">
  <img src="docs/screenshots/mobile-library.png" alt="Library on a phone" width="260">
  &nbsp;&nbsp;
  <img src="docs/screenshots/mobile-book.png" alt="Book details on a phone" width="260">
  &nbsp;&nbsp;
  <img src="docs/screenshots/mobile-stats.png" alt="Reading statistics on a phone" width="260">
</p>

## Features

- **Simple uploads.** Drag and drop files anywhere on the page, or pick them. Duplicates are detected.
- **Automatic metadata.** Title, author, series, description and cover are read from EPUB, FB2, CBZ
  (ComicInfo) and PDF files. Other formats fall back to `Author - Title.ext` file names.
- **KOReader progress sync.** Built-in server that is compatible with KOReader's *Progress sync* plugin.
  Your library shows reading progress, a *Continue reading* row, and Reading/Unread/Finished filters.
- **OPDS catalog.** Browse, search and download your books directly from your e-reader.
- **Books on your e-reader.** Let KOReader keep your whole library, your unread books or a hand-picked
  selection ("Send to e-reader") in sync on the device automatically.
- **Reading statistics.** Sync KOReader's reading statistics via the built-in WebDAV server to see
  total reading time, streaks, a reading calendar, time per book and an estimate of the time left.
- **Multiple users.** Every user has a private library. Admins manage accounts.
- **Clean, responsive UI.** Works on phones, tablets and desktops, in light and dark mode.
  No build step and no JavaScript framework.

Supported formats: EPUB, PDF, MOBI, AZW3, FB2, CBZ, CBR, DJVU, TXT, RTF, HTML, DOCX, CHM.

## Quick start (Docker)

```bash
git clone https://github.com/hthoene/Bookshelf.git
cd Bookshelf
cp .env.example .env    # optional: adjust port, IP and other settings
docker compose up -d
```

Open <http://localhost:8080> and create the administrator account.

To update, run `git pull && docker compose up -d --build`. Your settings live in `.env`,
which is not tracked by Git, so `docker-compose.yml` never needs local changes.

Data (database, books, covers) is stored in the `bookshelf-data` volume, mounted at `/data`.
If you prefer a bind mount instead, make sure the directory is writable by UID 1000.

### Configuration

Set these in `.env` (see [.env.example](.env.example)). All of them are optional.

| Variable | Default | Description |
| --- | --- | --- |
| `BOOKSHELF_BIND_IP` | `0.0.0.0` | Host IP to listen on (`127.0.0.1` for local access only) |
| `BOOKSHELF_HOST_PORT` | `8080` | Port on the host |
| `BOOKSHELF_ALLOW_REGISTRATION` | `false` | Allow KOReader to create accounts via *Register* |
| `BOOKSHELF_MAX_UPLOAD_MB` | `200` | Maximum size of a single upload |
| `BOOKSHELF_SESSION_DAYS` | `30` | How long a web login lasts |
| `BOOKSHELF_SECURE_COOKIES` | `false` | Set to `true` when served over HTTPS |
| `BOOKSHELF_INGEST_DIR` | *(empty)* | Directory to scan for new books (empty = disabled) |
| `TZ` | `UTC` | Time zone for reading statistics, e.g. `Europe/Berlin` |

When running without Docker Compose, `BOOKSHELF_DATA_DIR` (default `./data`, `/data` in the
image) and `BOOKSHELF_PORT` (default `8080`) control the storage location and listening port.

### Command line

```bash
docker exec -it bookshelf python -m bookshelf create-user alice --admin
docker exec -it bookshelf python -m bookshelf set-password alice
```

## Connecting KOReader

The *Settings* page in Bookshelf shows the exact addresses to use.

**Progress sync.** Open a book, then go to *Tools → Progress sync → Custom sync server* and enter
your Bookshelf address (for example `http://192.168.1.10:8080`). Then choose *Login* and use your
Bookshelf username and password. Keep the default document matching (*Binary*).

**OPDS catalog.** In the file browser, open *Search → OPDS catalog*, tap **+** and add
`http://<your-server>:8080/opds` with your Bookshelf username and password.

**Books on your e-reader (OPDS sync).** KOReader can download new books from a catalog into a
folder automatically. Add a second OPDS catalog with one of these addresses and enable
*Sync catalog*:

| Address | Keeps on the e-reader |
| --- | --- |
| `http://<your-server>:8080/opds/sync` | Books you marked with *Send to e-reader* |
| `http://<your-server>:8080/opds/books?sort=recent` | Your whole library |
| `http://<your-server>:8080/opds/books?status=unread&sort=recent` | Books you haven't started |

Choose a sync folder in KOReader's OPDS menu and run *Sync*. KOReader downloads the books added
since the last sync (at most 50 per run by default; raise the limit or use *Force sync* for a large
first sync). Books removed in Bookshelf are not deleted from the device.

**Reading statistics.** KOReader keeps its statistics on the device and syncs them through a cloud
storage server. Bookshelf provides one at `/webdav`:

1. In the file browser, open *Cloud storage*, tap **+** and add a *WebDAV* server with the address
   `http://<your-server>:8080/webdav` and your Bookshelf username and password.
2. Open a book, go to *Tools → Reading statistics → Settings → Cloud sync*, choose that server and
   its main folder, then run *Synchronize now*.

Do this on every device. KOReader merges the statistics of all devices; Bookshelf only reads the
synced `statistics.sqlite3`. Menu names can differ slightly between KOReader versions.

> Run Bookshelf behind a reverse proxy with HTTPS if you want to reach it from outside your
> home network. KOReader and OPDS clients send your credentials with every request.

## Development

Requires Python 3.12 or newer.

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"          # Windows: .venv\Scripts\pip
BOOKSHELF_DATA_DIR=./data-dev .venv/bin/python -m bookshelf serve --port 8765 --reload
.venv/bin/python scripts/dev_seed.py        # optional: demo books (login demo / demo1234)
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format .
```

See [CLAUDE.md](CLAUDE.md) for the architecture and contribution conventions.

To regenerate the screenshots in `docs/screenshots/`, see `scripts/screenshots.py`
(uses Playwright with demo data from `scripts/dev_seed.py`).

## Tech stack

FastAPI · SQLAlchemy + Alembic · SQLite · Jinja2 · htmx · plain CSS and JavaScript

## Acknowledgements

- [KOReader](https://github.com/koreader/koreader) and its
  [sync server](https://github.com/koreader/koreader-sync-server), whose protocol Bookshelf implements.
- [htmx](https://htmx.org) (BSD Zero Clause License), bundled in `bookshelf/static/js/`.

## License

[MIT](LICENSE)
