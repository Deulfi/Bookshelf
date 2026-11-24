# Bookshelf

A lean, self-hosted e-book library with **KOReader progress sync** and an **OPDS catalog**.
Upload your books, read them on any KOReader device, and keep your reading position in sync.
Everything runs in one small Docker container with a single SQLite database.

> **This is a fork.** It is an opinionated fork of
> [Bookshelf by Hannes Thöne](https://github.com/hthoene/Bookshelf). It keeps the original's small
> footprint and adds some things like: a configurable **web reader**, **library scanner** with Audiobookshelf
> compatible folder structure (`Author/Series/Vol 1 - Title/`) and **reading session list**.
> It is shaped by one way of reading (long web novels, scroll mode) and does
> not try to be a complete library manager. If you want the lean original, use upstream. If you
> want a full-featured library with audiobooks, annotations and Kobo sync, look at
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
- **New versions of a book.** *Replace file* on a book's page swaps in a newer file, such as a web
  novel with new chapters, and keeps the book's details, reading position, reading time and
  sessions. Copying a new version over the file in the library folder does the same on the next scan.
- **Series.** The *Series* switch in the library shows each series as one stack of covers (the
  newest volume on top, with the number of books); a book's page lists the other books of its
  series. The switch is remembered.
- **Library folders.** Each book gets its own folder, laid out the way Audiobookshelf reads it
  (`Author/Series/Vol 1 - Title/Title.epub`). Copy files into the folder yourself, or point
  Bookshelf at an existing one, and a scan adds them.
- **Automatic metadata.** Title, author, series, description and cover are read from EPUB, FB2, CBZ
  (ComicInfo) and PDF files. Other formats fall back to `Author - Title.ext` file names.
- **KOReader progress sync.** Built-in server that is compatible with KOReader's *Progress sync* plugin.
  Your library shows reading progress, a *Continue reading* row, and Reading/Unread/Finished filters (the last one chosen stays on).
  On a book's page you can set the progress by percentage or chapter, or reset it.
- **OPDS catalog.** Browse, search and download your books directly from your e-reader.
- **Books on your e-reader.** Let KOReader keep your whole library, your unread books or a hand-picked
  selection ("Send to e-reader") in sync on the device automatically.
- **Reading statistics.** Total reading time, streaks, a reading calendar, time per book and an
  estimate of the time left. Time in the web reader is counted automatically; KOReader's statistics
  are added when you sync them via the built-in WebDAV server, and Readest's through its BookOrbit
  integration.
- **Read in the browser.** EPUB, MOBI, AZW3, FB2 and CBZ open in a built-in reader (foliate-js)
  with scroll or page mode, auto-hiding bars, themes and font settings. In scroll mode it moves on
  to the next chapter when you keep scrolling. It continues where KOReader or Readest stopped, and
  the other way round. Bars are arranged by drag and drop; themes, fonts and settings are
  configurable with JSON, and bar elements can be added as plugins (see [Web reader](#web-reader)).
- **Multiple users.** Every user has a private library. Admins manage accounts.
- **Your choice of sign-in.** A login page (default), no login at all for a single user at home,
  or sign-in through your reverse proxy (Authelia, Authentik, oauth2-proxy, so also OIDC and
  single sign-on). See [Signing in](#signing-in).
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

To update, run `docker compose pull && docker compose up -d`. `:latest` is the newest release;
pin a version with `image: ghcr.io/deulfi/bookshelf:0.3` (or `:0.3.4`) instead. Test builds are
published as pre-releases (`:0.3.5-beta.1` and `:beta`) and never move `:latest`.

Before an update changes the database, Bookshelf copies it to `/data/backups/`. Delete old copies
there whenever you like.

> **Updating from 0.3.1 or older:** the update to 0.3.1 deleted reading progress, reading time,
> "Send to e-reader" marks and reader settings (a migration bug, fixed in 0.3.2); books came back
> through the library scan. KOReader and Readest restore their positions on the next sync.

Data (database, books, covers) is stored in the `bookshelf-data` volume, mounted at `/data`.
If you prefer a bind mount instead, make sure the directory is writable by UID 1000.

Proxmox VE (9.1 and newer) can pull the same image as an LXC template (*CT Templates → Pull from
OCI Registry*); keep `/data` on a mount point so it survives replacing the container.

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
| `TZ` | `UTC` | Time zone for reading statistics, e.g. `Europe/Berlin` |

When running without Docker Compose, `BOOKSHELF_DATA_DIR` (default `./data`, `/data` in the
image) and `BOOKSHELF_PORT` (default `8080`) control the storage location and listening port.

### Signing in

`BOOKSHELF_AUTH` picks how the web UI signs people in:

- **`password`** (default): the login page, with accounts made on the setup page, by an
  administrator or with the command line.
- **`none`**: single-user mode without a login. Everyone who can reach Bookshelf uses the first
  administrator's account (created as `admin` on first start). Only use it on a home network or
  behind a proxy that asks for a login.
- **`header`**: a reverse proxy signs people in (for example Authelia, Authentik or oauth2-proxy,
  which also covers OIDC and single sign-on) and sends the username in `BOOKSHELF_AUTH_HEADER`.
  Accounts are created on first visit; the very first one becomes an administrator. Set
  `BOOKSHELF_AUTH_PROXIES` to the proxy's address so nobody else can send the header, and don't
  publish Bookshelf's port past the proxy.

KOReader sync, OPDS and WebDAV always sign in with a username and password, because devices
can't use a proxy's login page. In `none` and `header` mode set that password under
*Settings → Device password*, and let the proxy pass `/users`, `/syncs`, `/healthcheck`, `/opds`
and `/webdav` through without its own login. Both modes refuse form posts started by other
websites, since no login cookie protects them.

### Library folders

Uploaded books get a folder of their own, following Audiobookshelf's
[directory structure](https://audiobookshelf.org/docs/documentation/libraries/book-library/directory-structure):

| Book | Stored as |
| --- | --- |
| In a series, with a number | `Author/Series/Vol 2 - Title/Title.epub` |
| In a series, without a number | `Author/Series/Title/Title.epub` |
| Not in a series | `Author/Title/Title.epub` |
| Without an author | `Title/Title.epub` |

Editing a book's title, author or series moves its file to match. Files you copy in yourself
stay where you put them, in any layout. Without `BOOKSHELF_INGEST_DIR` every user has their
own library folder, `<data dir>/books/<user id>/` (`/data/books/<user id>/` in Docker). With it,
all books live in that one shared folder. Uploads go into the library folder, and files you copy
there yourself are picked up by a scan: on startup, with the **Scan** button next to Upload, or
automatically on an interval an administrator picks under *Settings → Library folders* (where
administrators can also scan every user's folder at once). A scan also
removes entries whose file was deleted, and takes over files that were replaced by a version
of a different size (see below). Files uploaded by older versions under random names are
moved into this layout on the first scan. With a shared folder only
administrators can scan, and new files found there belong to the first administrator.

Scans skip every file and folder whose name starts with a dot (such as Syncthing's `.stfolder`
and `.stversions`) and names matching the patterns under *Settings → Library folders → Skip names*
or in `BOOKSHELF_SCAN_IGNORE`; both apply. Books already imported from such a
folder are removed from the library on the next scan; their files are left alone.

**New versions of a book.** KOReader, Readest and Bookshelf tell books apart by a hash of the
file, so a new version (a web novel with more chapters) is a different document to them. Use
*Replace file* on the book's page, or copy the new file over the old one in the library folder.
The book keeps its details and cover, and its reading position, web reader and Readest time and
sessions move to the new file; if a device already synced a newer position for the new file, that
one is kept. KOReader and Readest continue there once they open the new file, so download it to
the e-reader again (OPDS sync doesn't fetch it by itself). KOReader's own statistics keep the old
file's time separately, as KOReader does. Positions stay valid as long as chapters were added at
the end. A scan only notices a copied-over file when its size changed.

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

**Readest and other apps.** Apps that support KOReader's progress sync use the same address and
login; in Readest, look for *KOReader Sync* in a book's menu. Positions are shared with the
[web reader](#web-reader) too.

**Readest (BookOrbit integration).** Readest can also sync through its *BookOrbit* integration,
and Bookshelf understands the progress and reading-statistics parts of BookOrbit's API. In
Readest's integration settings add a BookOrbit server with your Bookshelf address (no path, for
example `http://192.168.1.10:8080`), your username and your password, and turn on:

- **Sync progress** — your reading position, shared with KOReader and the [web reader](#web-reader).
- **Sync stats** — Readest's reading time, which then shows in the statistics and in a book's
  session log under the device name you gave Readest.

With both on you do not also need *KOReader Sync* for the same book; it would only send the
position a second time. That does no harm here: a progress sync just overwrites the one saved
position (newest wins) and never creates a reading-session or log entry, so running both cannot
clutter your session history. You can leave *Sync notes* and *Sync book states* on or off —
Bookshelf has no BookOrbit highlight, bookmark or reading-status sync, so they do nothing here;
turning them off just stops Readest from logging a failed sync for them.

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
synced `statistics.sqlite3` and adds the time spent in the web reader to it (page counts and the
time-left estimate come from KOReader only). Menu names can differ slightly between KOReader versions.

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

**Arranging the bars.** *Settings → Web reader* shows a small preview of both bars; *Edit bars*
opens the bar editor: drag elements from *Available elements* into the top or bottom bar, drag
them to reorder, or use the arrow buttons (handy on a phone). The gear on an element shows its
options, for example the text of the chapter counter. *Behaviour* sets how the bars hide and how
far to scroll past a chapter end. The same editor is in the reader itself (*Reader settings →
Arrange the bars*, or the *Bar editor* element), and saving there changes the bars right away.
While the *Scroll distance* field has focus, scrolling fills a meter that shows how far that is. Administrators
get a second editor, *Web reader: server-wide defaults*, for the bars, themes and fonts everyone starts from.
**Tap areas (page mode).** *Reader settings → Tap areas* picks which part of the screen turns pages
or shows the bars; the *Preview* button next to it shows the areas over the page (the settings step aside) until you
click, and they show briefly when you switch to page mode. Patterns are small text grids that are stretched over the screen: one
line per row, one character per column, `L` previous page, `R` next page. Empty space (a space
or a `.`, which editors show) shows or hides the bars; `T` does the same explicitly. Add your own as files in `<data dir>/reader/taps/`; the file name
(without extension) is the pattern's name. More rows and columns give finer control:

```
LL  RR
LL  RR
LL  RR
```

Keep some empty space in a pattern, or the bars can't be reached in page mode. Built in: Thirds, Kindle,
Edges, Halves, L-shape and Fine grid.

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

- **Bar elements:** `exit`, `title`, `chapter-title`, `spacer` (flexible), `space` (fixed width),
  `toc`, `search`, `settings`, `bar-editor`, `theme-toggle`, `fullscreen`, `prev-chapter`,
  `next-chapter`, `prev-page`, `next-page`, `go-back`, `go-forward`, `progress-bar`,
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

See [CLAUDE.md](CLAUDE.md) for the architecture and contribution conventions, and
[docs/tuning.md](docs/tuning.md) for tuning knobs (CSS tokens, chapter auto-advance numbers,
reader files).

To regenerate the screenshots in `docs/screenshots/`, see `scripts/screenshots.py`
(uses Playwright with demo data from `scripts/dev_seed.py`).

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
