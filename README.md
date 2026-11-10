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
- **Read in the browser.** EPUB, MOBI, AZW3, FB2 and CBZ open in a built-in reader (foliate-js)
  with scroll or page mode, auto-hiding bars, themes and font settings. In scroll mode it moves on
  to the next chapter when you keep scrolling. Bars, themes, fonts and settings are configurable
  with JSON (see [Web reader](#web-reader)).
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
| `BOOKSHELF_INGEST_DIR` | *(empty)* | Shared library folder, e.g. a NAS share (empty = one folder per user in the data dir) |
| `TZ` | `UTC` | Time zone for reading statistics, e.g. `Europe/Berlin` |

When running without Docker Compose, `BOOKSHELF_DATA_DIR` (default `./data`, `/data` in the
image) and `BOOKSHELF_PORT` (default `8080`) control the storage location and listening port.

### Library folders

Books are stored as `Author/Series/Title.ext`. Without `BOOKSHELF_INGEST_DIR` every user has their
own library folder, `<data dir>/books/<user id>/` (`/data/books/<user id>/` in Docker). With it,
all books live in that one shared folder. Uploads go into the library folder, and files you copy
there yourself are picked up by a scan: on startup, with the **Scan** button next to Upload, or
automatically on an interval an administrator picks under *Settings → Library folders*. A scan also
removes entries whose file was deleted. Files uploaded by older versions under random names are
renamed to the `Author/Series/Title` layout on the first scan. With a shared folder only
administrators can scan, and new files found there belong to the first administrator.

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

## Web reader

*Read in Browser* on a book page (or the cover in *Continue reading*) opens the built-in reader.
Tap near the top or bottom edge to show the bars; they hide again after a few seconds. In scroll
mode, keep scrolling past the end of a chapter to load the next one (and past the start to go
back). Your settings are saved to your account.

**Reading position.** The reader shares the KOReader progress sync record with KOReader and
Readest. EPUB positions are stored as KOReader XPointers (`/body/DocFragment[12]/body/p[3]`), so
each app opens where another left off; book pages show the chapter ("Chapter 151 of 1,100").
When another device read on since you last read in this browser, the reader asks where to
continue. *Reader settings → Sync* can switch that to always use the latest position.

**Arranging the bars.** *Settings → Web reader* has a bar editor: drag elements from *Available
elements* into the top or bottom bar, drag them to reorder, or use the arrow buttons (handy on a
phone). The gear on an element shows its options, for example the text of the chapter counter.
The same card sets how the bars hide and how far to scroll past a chapter end.

For web novels with thousands of chapters, the default bottom bar has a **chapter progress bar**:
it only moves within the current chapter, so a slip never jumps hundreds of chapters. The book-wide
progress bar, a chapter counter ("Chapter 812 / 2431") and a page counter are in the palette.

**Configuration files.** Everything around the book is JSON in three layers, each merged on top of
the previous one:

1. **Built-in defaults:** [`bookshelf/reader/defaults/`](bookshelf/reader/defaults) (`layout.json`,
   `settings.json`, `themes.json`). *Settings → Web reader → current defaults* shows the result.
2. **Server-wide overrides:** files with the same names in `<data dir>/reader/` (`/data/reader/` in
   Docker). They apply to every user. A file with a syntax error is skipped and logged.
3. **Per-user file:** `<data dir>/reader/users/<username>.json`. The bar editor writes its `layout`
   part; *Settings → Web reader → Advanced* shows and edits the whole file, and you can also edit it
   on disk or drop in one you got from someone else. A broken file is ignored (the settings page
   says why) instead of breaking the reader.

Merge rules: objects merge key by key, and `layout.top` / `layout.bottom` replace the default list.
`themes`, `settings.fonts`, `settings.sections` (by `id`) and each section's `controls` (by `key`)
merge entry by entry, so you only list what you add or change. `"hidden": true` removes an entry.

```json
{
  "layout": {
    "top": ["exit", "chapter-title", "spacer", "toc", "settings"],
    "bottom": ["prev-chapter", {"id": "progress-text", "format": "both"}, "spacer", "next-chapter"],
    "autohide": {"delayMs": 5000}
  },
  "themes": [
    {"id": "night", "label": "Night", "scheme": "dark", "bg": "#101418", "fg": "#c9d1d9", "link": "#58a6ff"},
    {"id": "gray", "hidden": true}
  ],
  "settings": {
    "fonts": [{"id": "literata", "label": "Literata", "file": "Literata.woff2", "stack": "serif"}],
    "sections": [
      {"id": "text", "controls": [
        {"key": "fontSize", "max": 48},
        {"key": "wordSpacing", "type": "range", "label": "Word spacing", "min": 0, "max": 0.5,
         "step": 0.05, "default": 0, "unit": "em", "css": "p { word-spacing: {value}em !important; }"}
      ]}
    ]
  }
}
```

- **Bar elements:** `exit`, `title`, `chapter-title`, `spacer`, `toc`, `settings`, `theme-toggle`,
  `fullscreen`, `prev-chapter`, `next-chapter`, `prev-page`, `next-page`, `progress-bar`,
  `progress-text`, `chapter-progress`, `chapter-counter`, `page-counter`, plus any plugin. Their
  options are the ones the bar editor shows (e.g. `{"id": "chapter-counter", "format": "Ch. {current}"}`).
- **Themes:** `id`, `label`, `scheme` (`light`/`dark`), `bg`, `fg`, optional `link`, `accent` and
  extra `css` for the book.
- **Fonts:** `id`, `label`, `stack` (a CSS font list); put font files in `<data dir>/reader/fonts/`
  and reference them with `file`.
- **Controls:** `range`, `select`, `segmented`, `toggle`, `color` and `themes`. A control with a
  `css` template (`{value}` is replaced) adds its own setting; select and segmented options can carry
  their own `css`. The built-in keys `theme`, `fontFamily`, `flow`, `maxWidth`, `margin`, `columns`
  and `autoAdvance` drive the reader itself.
- **Chapter auto-advance:** `layout.chapterFlow` sets `overscrollPx` (how far to keep scrolling),
  `settleMs` (how long to rest at the end before overscroll counts, so a fast fling stops at the
  chapter end), `resetMs` and `cooldownMs`.

### Writing a bar element (plugin)

Bar elements are small JavaScript modules. Put a `.js` file in `<data dir>/reader/plugins/` and it
appears in the bar editor for every user; nothing else to configure. Only whoever runs the server
can add plugins, since they run in the reader with the user's login.

```js
export default {
  id: 'clock',                                   // name used in the layout
  label: 'Clock',                                // shown in the bar editor
  options: [{ key: 'seconds', type: 'toggle', label: 'Show seconds', default: false }],
  create(ctx, options) {
    const el = ctx.ui.text()
    const tick = () => { el.textContent = new Date().toLocaleTimeString([], options.seconds ? {} : { timeStyle: 'short' }) }
    const timer = setInterval(tick, 1000)
    tick()
    return { el, update(location) {}, destroy() { clearInterval(timer) } }
  },
}
```

[`docs/reader-plugin-example.js`](docs/reader-plugin-example.js) is a complete, commented example
(a clock with the reading time left in the chapter) that documents `ctx` (book, navigation,
settings, UI helpers) and the `location` passed to `update()`. The built-in elements in
[`bookshelf/static/js/reader/elements/`](bookshelf/static/js/reader/elements) use the same format.

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
