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

export class Bars {
    #bars
    #items = []
    #options
    #timer = null
    #ctx

    constructor(ctx, layout) {
        this.#ctx = ctx
        this.#options = { enabled: true, delayMs: 3500, tapZone: 0.18, ...layout.autohide }
        this.#bars = {
            top: document.getElementById('reader-top'),
            bottom: document.getElementById('reader-bottom'),
        }
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
        this.#build(layout)
        if (location) this.update(location)
        this.show(false)
    }

    get visible() {
        return document.body.classList.contains('bars-visible')
    }

    update(location) {
        for (const item of this.#items) item.update?.(location)
    }

    show(autoHide = true) {
        document.body.classList.add('bars-visible')
        clearTimeout(this.#timer)
        if (autoHide) this.#scheduleHide()
    }

    hide() {
        clearTimeout(this.#timer)
        if (this.#ctx.panels.open && !this.#ctx.panels.docked) return
        if (Object.values(this.#bars).some(bar => bar.contains(document.activeElement))) return
        document.body.classList.remove('bars-visible')
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
