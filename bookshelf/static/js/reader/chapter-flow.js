// Scroll mode: keep scrolling past the end of a chapter to load the next one (and past the
// start to go back to the end of the previous one). foliate shows one section at a time, so
// this watches wheel and touch "overscroll" at the section edges and then turns the section.
//
// The hint appears as soon as an edge with a neighbouring chapter is reached, then fills while
// overscrolling. Both directions use the same rule: only input that arrives while the reader is
// already resting at the edge counts, so the scroll that brings you to the edge never does.

export class ChapterFlow {
    #engine
    #enabled
    #options
    #hint
    #label
    #edge = 0 // 1 = at the end (next chapter ahead), -1 = at the start, 0 = elsewhere
    #amount = 0 // overscroll collected at the current edge, in px
    #idleTimer = null
    #busyUntil = 0
    #touchY = null
    #frame = 0
    #upIntentAt = -Infinity // when the reader last tried to scroll up at the start edge
    #edgeSince = 0 // when the current edge was reached
    #hovered = false // the pointer is on the hint, which keeps it up and makes it a button
    #demo = null // { px, amount, timer } while the bar editor's scroll distance field has focus

    constructor(engine, { enabled, options }) {
        this.#engine = engine
        this.#enabled = enabled
        // overscrollPx: how far to keep scrolling at an edge; settleMs: input only counts once
        // the reader has rested at the edge this long, so a fast fling stops at the end of a
        // chapter (with the hint showing) instead of running into the next one; resetMs: a pause
        // this long starts the count again; cooldownMs: ignore input after a chapter change.
        this.#options = {
            overscrollPx: 160, settleMs: 300, resetMs: 1500, cooldownMs: 450, ...options,
        }
        this.#hint = document.getElementById('chapter-hint')
        this.#label = this.#hint.querySelector('.ch-label')
        this.#hint.addEventListener('pointerenter', () => { this.#hovered = true; this.#render() })
        this.#hint.addEventListener('pointerleave', () => { this.#hovered = false; this.#render() })
        this.#hint.addEventListener('click', e => {
            e.stopPropagation() // a click here turns the chapter and nothing else (no bars)
            if (this.#edge && !this.#demo && performance.now() >= this.#busyUntil) this.#turn(this.#edge)
        })
        this.#listen(engine.view)
        // the scroll distance demo also listens outside the book (the editor covers it)
        addEventListener('wheel', e => this.#demoPush(e.deltaY * (e.deltaMode === 1 ? 32 : 1)),
            { passive: true })
        addEventListener('touchmove', e => {
            const y = e.touches[0]?.screenY
            if (this.#demo && this.#demo.y !== undefined && y !== undefined) this.#demoPush(this.#demo.y - y)
            if (this.#demo && y !== undefined) this.#demo.y = y
        }, { passive: true })
        addEventListener('touchend', () => { if (this.#demo) this.#demo.y = undefined }, { passive: true })
        engine.addEventListener('load', e => this.#listen(e.detail.doc))
        engine.renderer.addEventListener('scroll', () => this.#scheduleCheck())
        engine.addEventListener('relocate', () => this.#scheduleCheck())
    }

    /** New layout.chapterFlow numbers (saved in the bar editor). */
    setOptions(options) {
        this.#options = { ...this.#options, ...options }
    }

    /**
     * Show how far "the scroll distance" is: while the bar editor's field has focus, scrolling
     * with the wheel or a finger fills a meter up to `px`. Pass null when the field loses focus.
     */
    demoDistance(px) {
        if (this.#demo) clearTimeout(this.#demo.timer)
        this.#demo = px ? { px, amount: 0, timer: null } : null
        this.#render()
    }

    #demoPush(delta) {
        const demo = this.#demo
        if (!demo || !delta) return
        demo.amount = Math.min(demo.px, demo.amount + Math.abs(delta))
        clearTimeout(demo.timer)
        demo.timer = setTimeout(() => { demo.amount = 0; this.#render() }, this.#options.resetMs)
        this.#render()
    }

    setEnabled(enabled) {
        this.#enabled = enabled
        this.#check()
    }

    /**
     * How far to overscroll to turn the chapter, adapted to the viewport: the configured
     * distance, but never more than 40% of the screen height, so a short screen (a phone in
     * landscape) needs a proportionally smaller — and reachable — swipe. Floored so it stays
     * deliberate.
     */
    #threshold() {
        return Math.max(40, Math.min(this.#options.overscrollPx, innerHeight * 0.4))
    }

    // ---------- where are we? ----------

    #scheduleCheck() {
        cancelAnimationFrame(this.#frame)
        this.#frame = requestAnimationFrame(() => this.#check())
    }

    /** Which edge the reader rests at, if moving past it would change the chapter. */
    #currentEdge() {
        if (!this.#enabled || !this.#engine.scrolled) return 0
        const { atStart, atEnd } = this.#engine.edges()
        if (atEnd && this.#engine.hasSection(1)) return 1
        if (atStart && this.#engine.hasSection(-1)) return -1
        return 0
    }

    #setEdge(edge) {
        if (edge === this.#edge) return
        this.#edge = edge
        this.#amount = 0
        this.#edgeSince = performance.now()
    }

    #check() {
        this.#setEdge(this.#currentEdge())
        this.#render()
    }

    // ---------- input ----------

    #listen(target) {
        target.addEventListener('wheel', e => {
            const lines = e.deltaMode === 1 ? 32 : e.deltaMode === 2 ? innerHeight : 1
            this.#push(e.deltaY * lines)
        }, { passive: true })
        target.addEventListener('touchstart', e => { this.#touchY = e.touches[0]?.screenY ?? null },
            { passive: true })
        target.addEventListener('touchmove', e => {
            const y = e.touches[0]?.screenY
            if (this.#touchY === null || y === undefined) return
            this.#push(this.#touchY - y)
            this.#touchY = y
        }, { passive: true })
        target.addEventListener('touchend', () => {
            this.#touchY = null
            // Keep what this swipe collected: a phone (landscape especially) rarely has the room
            // to cross the whole distance in one stroke, so several swipes add up. The idle timer
            // (resetMs) still clears it after a pause, so a stray swipe never advances on its own.
            this.#render()
        }, { passive: true })
    }

    #push(delta) {
        if (!delta || performance.now() < this.#busyUntil) return
        // The edge is checked when the input arrives, so a tick still animating towards the
        // edge is simply not counted (it neither adds nor resets).
        const edge = this.#currentEdge()
        this.#setEdge(edge)
        if (!edge) return this.#render()
        if (edge < 0 && delta < 0) this.#upIntentAt = performance.now()
        if (Math.sign(delta) !== edge) {
            this.#amount = 0 // scrolling back into the chapter
            return this.#render()
        }
        if (performance.now() - this.#edgeSince < this.#options.settleMs) return this.#render()
        this.#amount += Math.abs(delta)
        clearTimeout(this.#idleTimer)
        this.#idleTimer = setTimeout(() => {
            this.#amount = 0
            this.#render()
        }, this.#options.resetMs)
        if (this.#amount >= this.#threshold()) this.#turn(edge)
        else this.#render()
    }

    async #turn(dir) {
        this.#busyUntil = performance.now() + this.#options.cooldownMs
        this.#amount = 0
        this.#edge = 0
        this.#render()
        // At a section edge, foliate's next()/prev() load the adjacent section: next() lands
        // at its top, prev() at its bottom.
        if (dir > 0) await this.#engine.next()
        else await this.#engine.prev()
        this.#busyUntil = performance.now() + this.#options.cooldownMs
        this.#scheduleCheck()
    }

    // ---------- hint ----------

    #render() {
        if (this.#demo) return this.#renderDemo()
        this.#hint.classList.remove('is-demo')
        const edge = this.#edge
        // The end of a chapter is where reading leads, so its hint shows on arrival. The start
        // is where every chapter opens, so that hint waits until you scroll up there.
        const visible = edge > 0
            || (edge < 0 && (this.#hovered
                || performance.now() - this.#upIntentAt < this.#options.resetMs))
        // A hidden hint drops its fill too: a stale "is-filling" would keep it on screen.
        const progress = visible ? Math.min(1, this.#amount / this.#threshold()) : 0
        this.#hint.classList.toggle('is-active', visible)
        this.#hint.classList.toggle('is-filling', progress > 0)
        this.#hint.style.setProperty('--progress', String(progress))
        if (!visible) return
        this.#hint.dataset.dir = edge > 0 ? 'next' : 'prev'
        this.#label.textContent = edge > 0
            ? 'Scroll on for the next chapter' : 'Scroll on for the previous chapter'
    }

    #renderDemo() {
        const { px, amount } = this.#demo
        this.#hint.classList.add('is-active')
        this.#hint.classList.toggle('is-filling', amount > 0)
        this.#hint.classList.add('is-demo')
        this.#hint.dataset.dir = 'next'
        this.#hint.style.setProperty('--progress', String(amount / px))
        this.#label.textContent = `Scroll to try it: ${Math.round(amount)} of ${px} px`
    }
}
