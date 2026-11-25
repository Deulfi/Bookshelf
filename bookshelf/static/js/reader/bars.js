// Top and bottom bars built from config.layout, with auto-hide and tap zones.
import { layoutItems, warn } from './config.js'
import { create } from './elements/index.js'
import { TapMap, findPattern } from './tap-pattern.js'

// What a letter in a tap pattern does in page mode. New letters (a settings corner, jumping a
// chapter) are added here; the pattern files and the preview need no change.
const ACTIONS = {
    L: (bars, ctx) => ctx.engine.prev(),
    R: (bars, ctx) => ctx.engine.next(),
    T: bars => bars.toggle(),
    ' ': bars => bars.toggle(), // empty space: the way to the bars in page mode
}

// Immersive full screen (the Fullscreen API) only makes sense on a touch device that still has
// browser chrome to hide: a plain mobile browser tab. The installed PWA is already chromeless
// through the manifest (display: fullscreen), so requesting it there is redundant and would bring
// back the browser's "exit full screen" toast — we skip it when already in fullscreen display
// mode. On a desktop with a mouse it would flip on every click, so (pointer: coarse) keeps it off
// there too (the Full screen bar button still works everywhere).
const immersiveContext = () =>
    document.fullscreenEnabled &&
    matchMedia('(pointer: coarse)').matches &&
    !matchMedia('(display-mode: fullscreen)').matches

export class Bars {
    #bars
    #items = []
    #options
    #timer = null
    #ctx
    #immersive = false
    #immersiveDone = false // full screen entered once this session; don't re-request

    constructor(ctx, layout) {
        this.#ctx = ctx
        ctx.bars = this // elements (e.g. the progress popover) reach the bars through ctx
        this.#options = { enabled: true, delayMs: 3500, tapZone: 0.18, ...layout.autohide }
        this.#immersive = this.#options.immersive !== false && immersiveContext()
        this.#bars = {
            top: document.getElementById('reader-top'),
            bottom: document.getElementById('reader-bottom'),
        }
        // Once we have actually entered full screen, never auto-request again: the browser shows
        // its "exit full screen" toast on each successful entry, so one per reading session is the
        // most we allow. If the reader leaves full screen (the button, Esc, a swipe), it stays out.
        document.addEventListener('fullscreenchange', () => {
            if (document.fullscreenElement) this.#immersiveDone = true
        })
        this.#build(layout)
        for (const bar of Object.values(this.#bars)) {
            // keep the bars up while the pointer or keyboard focus is on them
            bar.addEventListener('pointerenter', () => this.show(false))
            bar.addEventListener('pointerleave', () => this.#scheduleHide())
            bar.addEventListener('focusin', () => this.show(false))
            bar.addEventListener('focusout', () => this.#scheduleHide())
        }
        this.show()
    }

    #build(layout) {
        for (const [name, bar] of Object.entries(this.#bars)) {
            const entries = layoutItems(layout[name])
            for (const { id, ...options } of entries) {
                const item = create(id, this.#ctx, options)
                if (item === undefined) warn(`unknown bar element “${id}”`)
                if (!item) continue
                item.el.dataset.element = id
                bar.append(item.el)
                this.#items.push(item)
            }
            bar.hidden = entries.length === 0
        }
    }

    /** Replace both bars with a new layout (saved in the bar editor), keeping the position. */
    rebuild(layout, location) {
        for (const item of this.#items) item.destroy?.()
        this.#items = []
        for (const bar of Object.values(this.#bars)) bar.replaceChildren()
        this.#options = { enabled: true, delayMs: 3500, tapZone: 0.18, ...layout.autohide }
        this.#immersive = this.#options.immersive !== false && immersiveContext()
        this.#build(layout)
        if (location) this.update(location)
        this.show(false)
    }

    /** Go immersive once: enter full screen the first time the bars hide after a user gesture,
     *  then stay there — the bars just overlay the reader when shown, so there is no exit/re-enter
     *  churn and the browser's full-screen toast appears at most once. Entering needs a recent
     *  gesture (the tap that hid the bars provides it; the load-time auto-hide does not, which is
     *  harmless — a failed request shows no toast). Touch / installed-PWA only (immersiveContext). */
    #goImmersive() {
        if (!this.#immersive || this.#immersiveDone || document.fullscreenElement) return
        document.documentElement.requestFullscreen?.().catch(() => {})
    }

    get visible() {
        return document.body.classList.contains('bars-visible')
    }

    update(location) {
        for (const item of this.#items) item.update?.(location)
    }

    show(autoHide = true) {
        document.body.classList.add('bars-visible')
        // The bars overlay the reader; we stay in full screen (no exit) to avoid repeat toasts.
        clearTimeout(this.#timer)
        if (autoHide) this.#scheduleHide()
    }

    hide() {
        clearTimeout(this.#timer)
        if (this.#ctx.panels.open && !this.#ctx.panels.docked) return
        if (Object.values(this.#bars).some(bar => bar.contains(document.activeElement))) return
        document.body.classList.remove('bars-visible')
        this.#goImmersive() // back to reading: enter full screen once
    }

    toggle() {
        if (this.visible) this.hide()
        else this.show()
    }

    #scheduleHide() {
        clearTimeout(this.#timer)
        if (!this.#options.enabled) return
        this.#timer = setTimeout(() => this.hide(), this.#options.delayMs)
    }

    /** The tap grid of the chosen pattern (a missing or broken choice uses the default). */
    tapMap() {
        const { config, prefs } = this.#ctx
        return new TapMap(findPattern(config, prefs.get('tapPattern'))?.rows)
    }

    /**
     * A tap at viewport position (x, y). Top/bottom zones toggle the bars; in page mode the
     * left/right thirds turn pages; anything else hides the bars again.
     */
    tap(x, y) {
        const zone = Number(this.#options.tapZone) || 0.18
        const height = innerHeight
        if (!this.#ctx.engine.scrolled) {
            const action = this.tapMap().actionAt(x / innerWidth, y / height)
            // letters not listed here are reserved for future actions and do nothing
            return ACTIONS[action]?.(this, this.#ctx)
        }
        if (y < height * zone || y > height * (1 - zone)) return this.toggle()
        if (this.visible) this.hide()
    }
}
