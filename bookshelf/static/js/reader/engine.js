// The only module that talks to foliate-js. Everything else uses this small interface, so a
// different renderer (e.g. a continuous multi-chapter scroller) can replace it later.
import '../foliate/view.js'
import { isXPointer, parseXPointer, resolveXPointer, toXPointer } from './xpointer.js'

const EDGE = 2 // px from a section edge that counts as "at the edge"

/** A collapsed range at the end of a block's text. XPointers name blocks, but a range on the
 *  element itself loses its offset in foliate's CFI.fromRange (the CFI becomes the block's
 *  start), and foliate would then count a chapter anchor inside the block (a heading's
 *  <span id>) as not reached yet. See ../foliate/VENDORED.md ("Known quirks"). */
function blockEnd(doc, found) {
    if (found instanceof Range) return found
    const range = doc.createRange()
    const walker = doc.createTreeWalker(found, NodeFilter.SHOW_TEXT)
    let last = null
    while (walker.nextNode()) last = walker.currentNode
    if (last) range.setStart(last, last.length)
    else range.selectNodeContents(found)
    range.collapse(true)
    return range
}

/** The share of a document's text that lies before `found` (an element or a range). */
function textFraction(doc, found) {
    const range = doc.createRange()
    // a parsed document has no window, so no `instanceof Range`
    if (found.startContainer) range.setStart(found.startContainer, found.startOffset)
    else range.setStartBefore(found)
    const walker = doc.createTreeWalker(doc.documentElement, 4 /* NodeFilter.SHOW_TEXT */)
    let before = 0
    let total = 0
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        total += node.length
        if (range.comparePoint(node, 0) <= 0) before += node.length
    }
    return total > 0 ? before / total : 0
}

export class Engine extends EventTarget {
    view
    location = null
    #xpointers
    #sectionLabels = null

    /** xpointers: also report positions as KOReader XPointers (EPUB only). */
    constructor(view, { xpointers = false } = {}) {
        super()
        this.view = view
        this.#xpointers = xpointers
    }

    get renderer() {
        return this.view.renderer
    }

    get book() {
        return this.view.book
    }

    get toc() {
        return this.view.book?.toc ?? []
    }

    get scrolled() {
        return Boolean(this.renderer?.scrolled)
    }

    async open(url) {
        await this.view.open(url)
        this.view.addEventListener('relocate', e => this.#relocated(e.detail))
        // a link in the book (a footnote, a cross reference) is a jump too
        this.view.addEventListener('link', () => this.#jump())
        // forwarded so listeners can attach to each newly loaded section document
        this.view.addEventListener('load', e => this.dispatchEvent(
            new CustomEvent('load', { detail: e.detail })))
    }

    /** Open at a saved position: a CFI, a KOReader XPointer or { fraction }. */
    async start(position) {
        const target = this.#xpointerTarget(position)
        if (target) await this.renderer.goTo(target)
        else await this.view.init({ lastLocation: position, showTextStart: true })
    }

    /** Announce a jump (not reading on) before it happens, for the go back / go forward
     *  history. Page turns, scrolling, chapter auto-advance and the chapter slider are reading
     *  on; table of contents, search, links, chapter buttons and the book slider are jumps. */
    #jump() {
        this.dispatchEvent(new Event('jump'))
    }

    /** Jump to a saved position while reading (e.g. one synced from another device).
     *  jump: false for moves that are not a new history step (the history itself). */
    async goToPosition(position, { jump = true } = {}) {
        if (jump) this.#jump()
        const target = this.#xpointerTarget(position)
        if (target) return this.renderer.goTo(target)
        if (typeof position?.fraction === 'number') return this.view.goToFraction(position.fraction)
        return this.view.goTo(position)
    }

    /** Show a search match: like goToPosition, but in scroll mode the match ends up about a
     *  third down the screen instead of on the first line, so the text around it is visible. */
    async goToMatch(cfi, { jump = true } = {}) {
        await this.goToPosition(cfi, { jump })
        const r = this.renderer
        if (r?.scrolled) r.containerPosition = Math.max(0, r.containerPosition - r.size / 3)
    }

    #xpointerTarget(position) {
        const parsed = isXPointer(position) ? parseXPointer(position) : null
        if (!parsed || !this.book?.sections?.[parsed.index]) return null
        return { index: parsed.index, anchor: doc => resolveXPointer(doc, parsed.path) }
    }

    /** Section (spine item) of a saved position, or null if it can't be told. */
    sectionOf(position) {
        if (isXPointer(position)) return parseXPointer(position).index
        if (typeof position !== 'string') return null
        try {
            return this.view.resolveCFI(position)?.index ?? null
        } catch {
            return null
        }
    }

    /** Table-of-contents label of the chapter at a saved position (a CFI or an XPointer),
     *  from foliate's own TOC lookup, so books that keep several chapters in one file (TOC
     *  entries pointing at anchors) get the right one. Other books need no document load and
     *  use the section's chapter. */
    async chapterLabelOf(position) {
        const index = this.sectionOf(position)
        if (index === null || index === undefined) return null
        this.sectionLabel(index) // builds the TOC list
        const anchored = this.#sectionLabels
            .some(([section, , href]) => section === index && href?.includes('#'))
        if (!anchored) return this.sectionLabel(index)
        try {
            let cfi = position
            const target = this.#xpointerTarget(position)
            if (target) {
                const doc = await this.book.sections[target.index].createDocument()
                cfi = this.view.getCFI(target.index, blockEnd(doc, target.anchor(doc)))
            }
            const label = (await this.view.getTOCItemOf(cfi))?.label?.trim()
            if (label) return label
        } catch {
            // fall back to the section's chapter
        }
        return this.sectionLabel(index)
    }

    /** Table-of-contents label of the chapter a section belongs to. */
    sectionLabel(index) {
        if (index === null || index === undefined) return null
        if (!this.#sectionLabels) {
            this.#sectionLabels = []
            const walk = items => {
                for (const item of items ?? []) {
                    let section = null
                    try {
                        section = item.href ? this.book.resolveHref(item.href)?.index : null
                    } catch {
                        // a broken href: skip the entry
                    }
                    if (section !== null && section !== undefined && section >= 0)
                        this.#sectionLabels.push([section, item.label?.trim(), item.href])
                    walk(item.subitems)
                }
            }
            walk(this.toc)
        }
        let label = null
        for (const [section, text] of this.#sectionLabels) {
            if (section > index) break
            if (section === index) return text
            label = text
        }
        return label
    }

    /** Where each table-of-contents entry starts ({ fraction, label, href }, fraction 0–1 of
     *  the book), weighted by
     *  section size like foliate's location.fraction. Entries pointing at an anchor inside a
     *  section (`#fragment`) are placed at the anchor's share of the section's text, which
     *  loads that section (at most `maxDocuments` sections; the rest stay at the start). */
    async tocFractions({ maxDocuments = 50 } = {}) {
        const sections = this.book?.sections ?? []
        const sizes = sections.map(s => s.linear !== 'no' && s.size > 0 ? s.size : 0)
        const total = sizes.reduce((a, b) => a + b, 0)
        if (!total) return []
        const before = [0]
        for (const size of sizes) before.push(before.at(-1) + size)
        this.sectionLabel(0) // builds the TOC list
        const docs = new Map() // section index -> Promise<Document>
        return Promise.all(this.#sectionLabels
            .filter(([section]) => sizes[section])
            .map(async ([section, label, href]) => {
                let within = 0
                if (href?.includes('#') && (docs.has(section) || docs.size < maxDocuments)) {
                    try {
                        if (!docs.has(section))
                            docs.set(section, sections[section].createDocument())
                        const doc = await docs.get(section)
                        const found = this.book.resolveHref(href)?.anchor?.(doc)
                        if (found) within = textFraction(doc, found)
                    } catch {
                        // keep the section start
                    }
                }
                return { fraction: (before[section] + within * sizes[section]) / total, label, href }
            }))
    }

    /** foliate's book search: an async generator of progress updates and matches. */
    search(options) {
        return this.view.search(options)
    }

    clearSearch() {
        this.view.clearSearch?.()
    }

    setAttributes(attributes) {
        for (const [name, value] of Object.entries(attributes))
            if (this.renderer.getAttribute(name) !== value) this.renderer.setAttribute(name, value)
    }

    setStyles(css) {
        this.renderer.setStyles?.(css)
    }

    /** Position within the current section, for chapter auto-advance and edge buttons. */
    edges() {
        const r = this.renderer
        if (!r?.scrolled) return { atStart: false, atEnd: false }
        try {
            return { atStart: r.start <= EDGE, atEnd: r.viewSize - r.end <= EDGE }
        } catch {
            return { atStart: false, atEnd: false } // no section rendered yet
        }
    }

    /** Position within the current section: fraction (0 at the top, 1 at the very end) and
     *  pages (screens in scroll mode). */
    sectionPosition() {
        const r = this.renderer
        try {
            if (r.scrolled) {
                const scrollable = r.viewSize - r.size
                const fraction = scrollable > 1 ? Math.min(1, Math.max(0, r.start / scrollable)) : 1
                const pages = Math.max(1, Math.ceil(r.viewSize / r.size - 0.05))
                const page = Math.min(pages, Math.floor(r.start / r.size + 0.05) + 1)
                return { sectionFraction: fraction, page, pages }
            }
            const pages = Math.max(1, r.pages - 2) // the paginator adds a blank page at each end
            const page = Math.min(pages, Math.max(1, r.page))
            return { sectionFraction: pages > 1 ? (page - 1) / (pages - 1) : 1, page, pages }
        } catch {
            return { sectionFraction: 0, page: 1, pages: 1 } // no section rendered yet
        }
    }

    /** Jump within the current section only (the chapter progress bar). */
    goToSectionFraction(fraction) {
        const r = this.renderer
        const index = this.location?.sectionIndex
        if (index === undefined) return
        let anchor = fraction
        if (r.scrolled && r.viewSize > 0) anchor = fraction * (r.viewSize - r.size) / r.viewSize
        return r.goTo({ index, anchor: Math.min(1, Math.max(0, anchor)) })
    }

    hasSection(dir) {
        const sections = this.book?.sections ?? []
        const index = this.location?.sectionIndex ?? -1
        for (let i = index + dir; i >= 0 && i < sections.length; i += dir)
            if (sections[i].linear !== 'no') return true
        return false
    }

    next(distance) { return this.view.next(distance) }
    prev(distance) { return this.view.prev(distance) }
    // chapter buttons (chapter auto-advance reads on with next() / prev())
    nextSection() {
        this.#jump()
        return this.renderer.nextSection()
    }

    prevSection() {
        this.#jump()
        return this.renderer.prevSection()
    }

    goTo(target) {
        this.#jump()
        return this.view.goTo(target)
    }

    goToFraction(fraction) {
        this.#jump()
        return this.view.goToFraction(fraction)
    }

    #relocated(detail) {
        this.location = {
            cfi: detail.cfi,
            xpointer: this.#xpointers ? this.#xpointerOf(detail) : null,
            fraction: detail.fraction ?? 0,
            sectionIndex: detail.section?.current ?? 0,
            sectionCount: detail.section?.total ?? this.book?.sections?.length ?? 0,
            tocItem: detail.tocItem ?? null,
            timeInBook: detail.time?.total,
            timeInSection: detail.time?.section,
            ...this.edges(),
            ...this.sectionPosition(),
        }
        this.dispatchEvent(new CustomEvent('relocate', { detail: this.location }))
    }

    #xpointerOf(detail) {
        try {
            return toXPointer(detail.section?.current ?? 0, detail.range)
        } catch {
            return null
        }
    }
}
