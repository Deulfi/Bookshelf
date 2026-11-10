// The only module that talks to foliate-js. Everything else uses this small interface, so a
// different renderer (e.g. a continuous multi-chapter scroller) can replace it later.
import '../foliate/view.js'
import { isXPointer, parseXPointer, resolveXPointer, toXPointer } from './xpointer.js'

const EDGE = 2 // px from a section edge that counts as "at the edge"

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

    /** Jump to a saved position while reading (e.g. one synced from another device). */
    async goToPosition(position) {
        const target = this.#xpointerTarget(position)
        if (target) return this.renderer.goTo(target)
        if (typeof position?.fraction === 'number') return this.goToFraction(position.fraction)
        return this.view.goTo(position)
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
                        this.#sectionLabels.push([section, item.label?.trim()])
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
    nextSection() { return this.renderer.nextSection() }
    prevSection() { return this.renderer.prevSection() }
    goTo(target) { return this.view.goTo(target) }
    goToFraction(fraction) { return this.view.goToFraction(fraction) }

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
