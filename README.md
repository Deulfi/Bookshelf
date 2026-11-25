# Bookshelf

A lean, self-hosted e-book library with **KOReader progress sync** and an **OPDS catalog**.
Upload your books, read them on any KOReader device, and keep your reading position in sync.
Everything runs in one small Docker container with a single SQLite database.

> **This is a fork.** It is an opinionated fork of
> [Bookshelf by Hannes Thöne](https://github.com/hthoene/Bookshelf). It keeps the original's small
> footprint and adds a configurable **web reader**, a **library scanner** with Audiobookshelf
> compatible folders (`Author/Series/Vol 1 - Title/`), a **reading session list** and **web novel**
> fetching. It is shaped by one way of reading (long web novels, scroll mode) and does not try to
> be a complete library manager. If you want the lean original, use upstream. If you want a
> full-featured library with audiobooks, annotations and Kobo sync, look at
> [BookOrbit](https://github.com/bookorbit/bookorbit).

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

- **Simple uploads.** Drag and drop files or whole folders anywhere on the page, or pick them.
  Duplicates are detected.
- **Automatic metadata.** Title, author, series, description and cover are read from EPUB, FB2, CBZ
  (ComicInfo) and PDF files. Other formats fall back to `Author - Title.ext` file names.
- **Library folders.** Each book gets an Audiobookshelf-style folder
  (`Author/Series/Vol 1 - Title/`); point Bookshelf at an existing library and a scan imports it.
- **Series.** A *Series* switch shows each series as one stack of covers.
- **New versions.** *Replace file* swaps in a newer file (such as a web novel with more chapters)
  and keeps the book's details, reading position, time and sessions.
- **KOReader progress sync.** Built-in server compatible with KOReader's *Progress sync* plugin.
  Your library shows reading progress, a *Continue reading* row and Reading/Unread/Finished filters.
- **Read in the browser.** Built-in reader (foliate-js) with scroll or page mode, themes and font
  settings. It continues where KOReader or Readest stopped, and the other way round.
- **OPDS catalog.** Browse, search and download from your e-reader, and let KOReader keep your
  whole library or a hand-picked selection in sync on the device automatically.
- **Reading statistics.** Total reading time, streaks, a reading calendar, time per book and an
  estimate of the time left — from the web reader, KOReader (via WebDAV) and Readest (via BookOrbit).
- **Web novels.** Fetch web novels as EPUBs from an [lncrawl](#web-novels) server and re-fetch new
  chapters later.
- **Multiple users.** Every user has a private library. Admins manage accounts.
- **Your choice of sign-in.** A login page, no login at all for a single user at home, or sign-in
  through your reverse proxy (so also OIDC and single sign-on). See [Signing in](#signing-in).
- **Clean, responsive UI.** Works on phones, tablets and desktops, in light and dark mode.
  No build step and no JavaScript framework.

Supported formats: EPUB, PDF, MOBI, AZW3, FB2, CBZ, CBR, DJVU, TXT, RTF, HTML, DOCX, CHM.

## Quick start (Docker)

Bookshelf is published as `ghcr.io/deulfi/bookshelf` (amd64 and arm64). In an empty folder:

```bash
curl -O https://raw.githubusercontent.com/Deulfi/Bookshelf/main/docker-compose.yml
curl -o .env https://raw.githubusercontent.com/Deulfi/Bookshelf/main/.env.example   # optional
docker compose up -d
```

Open <http://localhost:8080> and create the administrator account. Adjust the port, IP and other
settings in `.env`; `docker-compose.yml` never needs local changes.

To update, run `docker compose pull && docker compose up -d`. `:latest` is the newest release; pin
a version with `image: ghcr.io/deulfi/bookshelf:0.3`. Before an update changes the database,
Bookshelf copies it to `/data/backups/`.

Data (database, books, covers) lives in the `bookshelf-data` volume, mounted at `/data`. For a bind
mount instead, make sure the directory is writable by UID 1000.

See the [wiki](https://github.com/Deulfi/Bookshelf/wiki/Deployment-and-updates) for Proxmox LXC,
pre-release builds and upgrading from 0.3.1 or older.

### Build from source

```bash
git clone https://github.com/Deulfi/Bookshelf.git
cd Bookshelf
cp .env.example .env    # optional
```

Uncomment the `build: .` line in `docker-compose.yml`, then run `docker compose up -d --build`
(again after each `git pull`).

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
| `BOOKSHELF_INGEST_DIR` | *(empty)* | Shared library folder, e.g. a NAS share (empty = one folder per user in the data dir) |
| `BOOKSHELF_SCAN_IGNORE` | *(empty)* | File and folder names scans skip, comma-separated patterns, e.g. `@eaDir,*.tmp` |
| `BOOKSHELF_AUTH` | `password` | Web sign-in: `password`, `none` or `header`, see [Signing in](#signing-in) |
| `BOOKSHELF_AUTH_HEADER` | `Remote-User` | Header with the username, for `BOOKSHELF_AUTH=header` |
| `BOOKSHELF_AUTH_PROXIES` | *(empty)* | Proxy IPs or networks allowed to send that header, e.g. `172.16.0.0/12` |
| `BOOKSHELF_LNCRAWL_URL` | *(empty)* | A remote [lncrawl](#web-novels) server to fetch web novels from (empty = hide the Web novels tab) |
| `BOOKSHELF_LNCRAWL_USERNAME` | *(empty)* | lncrawl account to sign in as (its admin account works) |
| `BOOKSHELF_LNCRAWL_PASSWORD` | *(empty)* | Password for that lncrawl account |
| `BOOKSHELF_LNCRAWL_VERIFY_TLS` | `true` | Verify the lncrawl server's TLS certificate (`false` for a self-signed one) |
| `BOOKSHELF_LNCRAWL_TIMEOUT` | `60` | Seconds to wait for the lncrawl server (raise it if large crawls time out) |
| `TZ` | `UTC` | Time zone for reading statistics, e.g. `Europe/Berlin` |

When running without Docker Compose, `BOOKSHELF_DATA_DIR` (default `./data`, `/data` in the
image) and `BOOKSHELF_PORT` (default `8080`) control the storage location and listening port.

### Web novels

Point `BOOKSHELF_LNCRAWL_URL` (plus `BOOKSHELF_LNCRAWL_USERNAME` and `BOOKSHELF_LNCRAWL_PASSWORD`)
at a [lightnovel-crawler (lncrawl)](https://github.com/lncrawl/lightnovel-crawler) server and a
**Web novels** tab appears: paste a novel's URL, lncrawl crawls it in the background, and the
finished EPUB lands in your library like any upload. A **Check for new chapters** button re-fetches
it later. See the [wiki](https://github.com/Deulfi/Bookshelf/wiki/Web-novels) for running lncrawl.

### Signing in

`BOOKSHELF_AUTH` picks how the web UI signs people in:

- **`password`** (default): the login page.
- **`none`**: single-user mode with no login; everyone shares the first administrator's account.
  Use only on a home network or behind a proxy that asks for a login.
- **`header`**: a reverse proxy (Authelia, Authentik, oauth2-proxy, so also OIDC and single
  sign-on) signs people in and sends the signed-in user's name in `BOOKSHELF_AUTH_HEADER`
  (default `Remote-User`) on each request. Accounts are created on first visit and matched to that
  name afterwards. Set `BOOKSHELF_AUTH_PROXIES` to the proxy's address so nobody else can send the
  header.

KOReader sync, OPDS and WebDAV always sign in with a username and password; in `none` and `header`
mode set it under *Settings → Device password*. See the
[wiki](https://github.com/Deulfi/Bookshelf/wiki/Signing-in) for an Authelia example, how existing
accounts are matched, and proxy pass-through details.

### Library folders

Each book gets its own Audiobookshelf-style folder (`Author/Series/Vol 2 - Title/Title.epub`);
editing a book's title, author or series moves its file to match. Without `BOOKSHELF_INGEST_DIR`
every user has a folder under `<data dir>/books/<user id>/`; set it to share one folder (such as a
NAS share). Copy files in yourself and a **Scan** picks them up — on startup, with the button next
to Upload, or on an interval set under *Settings → Library folders*. See the
[wiki](https://github.com/Deulfi/Bookshelf/wiki/Library-folders) for scan skip rules, shared-folder
behaviour and replacing a book's file.

### Command line

```bash
docker exec -it bookshelf python -m bookshelf create-user alice --admin
docker exec -it bookshelf python -m bookshelf set-password alice
```

## Connecting KOReader

The *Settings* page in Bookshelf shows the exact addresses to use.

**Progress sync.** Open a book, then go to *Tools → Progress sync → Custom sync server* and enter
your Bookshelf address (for example `http://192.168.1.10:8080`). Choose *Login* with your Bookshelf
username and password, and keep the default document matching (*Binary*).

**Readest.** Apps that support KOReader's progress sync use the same address and login (in Readest,
*KOReader Sync* in a book's menu). Readest can also sync its reading time through its *BookOrbit*
integration; see the [wiki](https://github.com/Deulfi/Bookshelf/wiki/Readest-and-BookOrbit).

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

Do this on every device. KOReader merges the statistics of all devices; Bookshelf reads the synced
`statistics.sqlite3` and adds the time spent in the web reader. Menu names can differ slightly
between KOReader versions.

> Run Bookshelf behind a reverse proxy with HTTPS if you want to reach it from outside your
> home network. KOReader and OPDS clients send your credentials with every request.

## Web reader

*Read in Browser* on a book page (or the cover in *Continue reading*) opens the built-in reader.
Tap near the top or bottom edge to show the bars; in scroll mode, keep scrolling past the end of a
chapter to load the next one. Settings are saved to your account, and the reading position is
shared with KOReader and Readest (EPUB positions are stored as KOReader XPointers), so each app
opens where another left off.

*Settings → Web reader* has a bar editor (drag elements into the top or bottom bar) and tap-area
patterns for page mode. Everything around the book — bars, themes, fonts and controls — is JSON in
three layers (built-in defaults, server-wide files and a per-user file), and bar elements can be
added as plugins. The full guide is in the
[wiki](https://github.com/Deulfi/Bookshelf/wiki/Web-reader); finer knobs are in
[docs/tuning.md](docs/tuning.md).

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

See [CLAUDE.md](CLAUDE.md) for the architecture and contribution conventions, and
[docs/tuning.md](docs/tuning.md) for tuning knobs. To regenerate the screenshots in
`docs/screenshots/`, see `scripts/screenshots.py`.

## Tech stack

FastAPI · SQLAlchemy + Alembic · SQLite · Jinja2 · htmx · foliate-js · plain CSS and JavaScript

## Acknowledgements

- [Bookshelf](https://github.com/hthoene/Bookshelf) by Hannes Thöne, the project this fork is
  built on. The library, KOReader sync, OPDS, statistics and the design are his work.
- [foliate-js](https://github.com/johnfactotum/foliate-js) (MIT License) renders the books in the
  web reader. It is bundled in `bookshelf/static/js/foliate/` together with
  [zip.js](https://github.com/gildas-lormeau/zip.js) (BSD 3-Clause) and
  [fflate](https://github.com/101arrowz/fflate) (MIT); their licences are in
  [`LICENSE.txt`](bookshelf/static/js/foliate/LICENSE.txt) in that folder.
- [Readest](https://github.com/readest/readest), whose way of storing positions on a KOReader sync
  server the web reader follows, and whose sync conflict prompt inspired the one here.
- [KOReader](https://github.com/koreader/koreader) and its
  [sync server](https://github.com/koreader/koreader-sync-server), whose protocol Bookshelf implements.
- [htmx](https://htmx.org) (BSD Zero Clause License), bundled in `bookshelf/static/js/`.

## License

[MIT](LICENSE)
