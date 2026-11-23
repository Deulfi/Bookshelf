# Good to know: tuning knobs

Details that are too fine for the README but handy when dialling Bookshelf in.

## Restart after changing CSS or JS

Static files are linked with a `?v=<content hash>` so browsers can cache them for good. The hashes
are computed once per process: restart the server after editing anything in `bookshelf/static/`
(`--reload` restarts on Python changes only when a Python file changes too). In Docker, rebuild the
image.

## CSS tokens

| Token | File | What it does |
| --- | --- | --- |
| `--stack-step` (9px) | `static/css/app.css`, top | How far each book of a series stack is offset behind the newest one |
| `--stack-dim` (0.6) | `static/css/app.css`, top | Brightness of the books behind the front cover (1 = not dimmed) |
| `--rb-thumb` (16px) | `static/css/reader.css`, `.rb-track` | Width of the reader slider knob. Chapter ticks are placed on the knob's path, so it must match the styled knob (`::-webkit-slider-thumb`, `::-moz-range-thumb`) |

## Chapter auto-advance numbers

The bar editor shows only `overscrollPx` (*Scroll distance*; while its field has focus, scrolling
fills a meter that shows how far that is). The rest live in the `layout.chapterFlow` part of your
reader JSON (*Settings → Web reader → Advanced*):

| Key | Default | Meaning |
| --- | --- | --- |
| `overscrollPx` | 160 | Scroll distance past the chapter end that loads the next chapter |
| `settleMs` | 300 | Input only counts after resting at the edge this long, so a fast fling stops at the end of the chapter |
| `resetMs` | 1500 | A pause this long starts the count again |
| `cooldownMs` | 450 | Input is ignored this long after a chapter change |

The hint at the edge is also a button: hover it and click to change chapter without scrolling.

## Reader configuration

Three layers, later ones winning: built-in defaults (`bookshelf/reader/defaults/`), server-wide
files in `<data dir>/reader/` (`layout.json`, `settings.json`, `themes.json`; admins edit them in
*Settings → Web reader: server-wide defaults*), and each user's own
`<data dir>/reader/users/<username>.json`.

- Fonts: put font files (`.woff2`, `.woff`, `.ttf`, `.otf`) in `<data dir>/reader/fonts/` and list
  them in `settings.fonts` with a `file` entry.
- Bar element plugins: any `.js` file in `<data dir>/reader/plugins/` loads for everyone, see
  `docs/reader-plugin-example.js`.
- Tap patterns for page mode: text files in `<data dir>/reader/taps/`, see the README. Other
  letters than `L`, `R` and `T` are ignored for now; a new action is one entry in `ACTIONS` in
  `static/js/reader/bars.js` (for example `S` for the settings), and existing files and the
  preview pick it up without further changes.
- *Chapter counter*, option *Skip front matter*: leading entries named cover, title page,
  copyright, contents, dedication, and similar are not counted. The book page's "Chapter x of y"
  still counts every table-of-contents entry.

## Environment

`BOOKSHELF_DATA_DIR` (default `./data`, `/data` in the image) and `BOOKSHELF_PORT` (default `8080`)
control where files live and which port is used; the full list is in the README's configuration
table.
