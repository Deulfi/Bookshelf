# Web reader: status and open issues

_Last updated 2026-11-10 (round 3)._

## Done in round 2

- **Per-user config file.** `<data dir>/reader/users/<username>.json` replaces the database field.
  The settings page's bar editor writes its `layout` part; the raw JSON editor sits under
  *Advanced*. A broken hand-edited file is ignored and reported on the settings page.
- **Bar editor.** Drag and drop between an element palette and the top/bottom bars (pointer
  events, works with mouse and touch), plus arrow/remove buttons for keyboard and phones. Element
  options and the auto-hide / chapter-flow numbers are form controls.
- **Element plugins.** Bar elements use one definition format (`static/js/reader/elements/`);
  any `.js` in `<data dir>/reader/plugins/` is loaded for all users and appears in the editor.
  New built-ins: `chapter-progress` (slider within the current chapter, now in the default bottom
  bar), `chapter-counter`, `page-counter`. Example plugin: `docs/reader-plugin-example.js`.
- **Library folders.** Without `BOOKSHELF_INGEST_DIR` each user has `books/<user id>/` with the
  `Author/Series/Title.ext` layout; uploads go there, files copied in are picked up by a scan
  (startup, interval, or the new **Scan** button next to Upload), and old random-named uploads are
  renamed on the first scan.
- **Chapter auto-advance hint.** Causes found: the hint was drawn under the bars, it only showed
  after the first counted overscroll tick (so it flashed or never appeared), and a tick that was
  still animating towards the edge reset the progress. Now the "next chapter" hint shows as soon as
  the end is reached (the "previous chapter" one when you scroll up at the start), it clears the
  bars, input only counts after resting at the edge for `settleMs` (a fast fling stops at the
  chapter end instead of running into the next one), and both directions follow the same rule.
  Measured with real wheel ticks: two ticks from rest in either direction.
- **Position restore.** The offline position copy is keyed by the book's content hash instead of
  its id, and a position that does not fit the book no longer aborts the reader's startup.

## Done in round 3

- **Chapter hint stuck on screen.** A hidden hint kept its `is-filling` class, and that class alone
  made it opaque: a half-filled "previous chapter" hint stayed (and moved with the bars), and the
  "next chapter" hint survived a chapter turn. Hiding now clears the fill too.
- **Sync with Readest/KOReader.** They store EPUB positions as KOReader XPointers, which the reader
  could not open (it started at 0%), and the reader stored foliate CFIs, which they could only
  read as a percentage. The reader now reads and writes XPointers (`static/js/reader/xpointer.js`,
  block-level elements, like Readest); its exact CFI stays in localStorage for this browser.
- **Sync conflicts.** Each browser has a device id. When another device updated the record since
  this browser was last at its position, the reader asks (dialog with chapter and percentage) or,
  with *Reader settings → Sync → Use latest*, jumps there. Checked on open and when the tab is
  shown again.
- **Book page** shows "Chapter X of Y" and the chapter title (`services/chapters.py`, from the
  EPUB's nav/NCX, cached per file version). **Continue reading** covers open the reader, with a
  book icon on hover.

## Open / ideas

- **Listening sessions** (like Audiobookshelf): a reading-session log per book. Planned for later.
- **XPointer precision.** Positions are written at paragraph level; going through another app can
  move the start of the screen back to the start of a long paragraph. KOReader's own DOM (crengine)
  can differ from the browser's for unusual markup, in which case the deepest matching element is
  used.

- **Continuous scrolling** (chapters stacked so text flows without a jump): needs its own renderer
  behind the `Engine` interface in `static/js/reader/engine.js`.
- **Touch** auto-advance and bar-editor dragging were only checked with mouse input and synthetic
  events; try both on a real phone (iOS rubber-banding in particular).
- **Chapter counter** counts table-of-contents entries, which can include front matter ("Ch. 7"
  while the heading says "Chapter 5"); an option to skip entries before the first linear chapter
  could help. The book page uses the same count (`services/chapters.py`).
- Annotations, search and TTS exist in foliate-js but are not exposed; they would be new bar
  elements plus panels.
