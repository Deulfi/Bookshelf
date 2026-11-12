# foliate-js in Bookshelf

This folder is a copy of **[readest/foliate-js](https://github.com/readest/foliate-js)**, Readest's
fork of [johnfactotum/foliate-js](https://github.com/johnfactotum/foliate-js) (MIT, see
`LICENSE.txt`). Bookshelf never edits these files: all reader code that talks to foliate is in
`../reader/engine.js`, and our workarounds live there too. Replace the folder as a whole when
updating, but keep `LICENSE.txt` and this file.

## Which version this is

Not one commit of either repository, as far as can be told today. Checked on 2026-11-12 by
comparing every file with the full history of both repositories:

- **Base:** upstream `052123b` (2025-03-29, "Add an EventTarget for transforming the book") plus
  Readest's own patches from that time (spring 2025). Readest keeps its patches as commits it
  rebases onto upstream, so the exact snapshot is no longer in its history.
- **Identical to a Readest version:** `epubcfi.js`, `fb2.js`, `fixed-layout.js`, `mobi.js`,
  `overlayer.js` (Readest's `f087826` patch set), `progress.js`, `search.js`, `vendor/fflate.js`.
  All of them existed together only between 2025-03-12 and 2025-05-13.
- **Small differences** (lines changed against the closest version): `view.js` 13 (no PDF
  support: `isPDF` and the `pdf.js` import are gone), `paginator.js` 89, `comic-book.js` 22,
  `tts.js` 23, `epub.js` 6, `text-walker.js` 1, `vendor/zip.js` 1. Whether those come from
  Readest or were trimmed before the copy reached Bookshelf (2026-11-09) is not recorded.
- Not copied: `pdf.js` and `vendor/pdfjs/` (PDF isn't read in the browser, see
  `READABLE_FORMATS` in `bookshelf/formats.py`), the UI and demo files (`reader.html`,
  `reader.js`, `ui/`), and `opds.js`, `dict.js`, `footnotes.js`, `quote-image.js`,
  `uri-template.js`.

When you update, write the commit you copied here, e.g.
`Readest 6f0faea (2026-11-12)`, so the next update can be diffed against it.

## Why Readest's fork, not upstream

Keep updating from Readest. Our theme CSS (`../reader/style.js`) sets `--theme-bg-color`, which
only Readest's `paginator.js` reads (`#replaceBackground`); upstream would lose the theme
background behind the pages. Readest is also the more active of the two: upstream's last change
was 2026-05-01, Readest has 568 commits with changes this week. foliate's README suggests a git
submodule because there are no releases; a pinned copy with the commit noted here is simpler for
us (no `submodules: true` in CI, no special Docker checkout, plain `git clone`).

## Updating

1. Copy the `.js` files listed above from a Readest checkout, plus any new module they import:
   read the `import` lines of `view.js` and `paginator.js` (Readest's `paginator.js` now imports
   `section-chunks.js`, see below). `reader_import_map` picks up new files automatically; restart
   the dev server, because static file hashes are computed once. Expect a big jump: Readest's
   `paginator.js` grew from 1,166 lines (ours) to 4,463, with 122 commits since our snapshot.
2. Write the commit hash into "Which version this is".
3. Check the foliate APIs `../reader/engine.js` uses. They are not a stable API:
   `view.open/init/goTo/goToFraction/next/prev/getCFI/resolveCFI/getTOCItemOf`, `view.book`,
   `book.sections[i].createDocument`, `book.resolveHref`, `renderer.goTo({ index, anchor })`,
   `renderer.start/end/size/viewSize/scrolled`, `renderer.nextSection/prevSection/setStyles`,
   the renderer's `scroll` event and the view's `relocate` and `load` events.
4. Test in the browser (there are no automated tests for the reader's JavaScript):
   scroll and page mode, chapter auto-advance at the end of a chapter, themes (the page
   background must follow the theme), opening at a saved KOReader XPointer, a sync conflict
   dialog, and its chapter label on a book with several chapters per file (see below).

## Not copied on purpose: `section-chunks.js`

Readest added it on 2026-10-09 (`1a8bd29`, readest/foliate-js#126, marked as a prototype). The
paginator renders any spine file bigger than 512 KB as separate chunk documents of about 256 KB,
because Chromium and WebKit can't lay out and paint one huge file in page (multi-column) mode:
the cases were a 20 MB concordance and a whole novel in one 600 KB file. Chunks keep element
indices identical to the full file, so CFIs still match, and the paginator maps them back to
spine indices at its public edges.

We don't need it. Our `paginator.js` predates it and doesn't import it, and our books don't
have files that big. Checked on 2026-11-12: of 63 EPUBs in the test library, the largest single
file is 230 KB. Web novels come as many small files: *Since The Red Moon Appeared* has 929, the
largest 117 KB. Images don't count: the limit is on a file's HTML markup, and images are separate
resources (a 207 MB manga-style EPUB in the test library is 204 MB of images and 667 XHTML files
of at most 19 KB). The reader does offer page mode, the case it targets, so a book with one
huge file would be slow there. It only arrives with a `paginator.js` update, and then it must be copied along, since
that `paginator.js` imports it. After such an update, re-check the `engine.js` code that reads
`renderer.start/end/size/viewSize` and calls `renderer.goTo({ index, anchor })`: with chunks,
the paginator's internal `index` is a chunk, translated back to a spine index only at its
public methods and events.

## Known quirks

- **`CFI.fromRange` drops offsets on element containers.** `nodeToParts` keeps an offset only for
  text, so a range point between an element's children, `(element, i)`, becomes the element
  itself and reads back as its start. Effect for us: asking `view.getTOCItemOf` for the chapter
  of an XPointer (which names a block such as a `<p>`) gave the *previous* chapter whenever that
  block holds the chapter's anchor (a heading's `<span id>`), because the anchor then lies after
  the point. Tested on *Black Blood Brother* (39 chapters in 5 files): p[623] gave chapter 34
  instead of 35, p[1109] gave 38 instead of 39, and every position inside a chapter was right.
  Our fix is `blockEnd()` in `../reader/engine.js`: it puts the range at the end of the block's
  last text node, where the CFI keeps its offset.
  Readest found the same root cause (commit `ac528ac`, 2026-10-03, readest/readest#6578), but its
  fix (`endInsideChild`) only moves the *end* of a non-collapsed range into a child. Collapsed
  ranges and range starts, which is our case, behave as before, so `blockEnd()` is needed with
  either fork. If foliate ever fixes the start too, `blockEnd()` stays harmless.
- **`view.getTOCItemOf(target)`** takes what `resolveNavigation` understands (a CFI, an href, a
  fraction or a section index), not KOReader XPointers. Convert first, as `chapterLabelOf` does.
