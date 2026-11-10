// Top and bottom bars built from config.layout, with auto-hide and tap zones.
import { layoutItems, warn } from './config.js'
import { create } from './elements/index.js'

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
        for (const [name, bar] of Object.entries(this.#bars)) {
            const entries = layoutItems(layout[name])
            for (const { id, ...options } of entries) {
                const item = create(id, ctx, options)
                if (item === undefined) warn(`unknown bar element “${id}”`)
                if (!item) continue
                item.el.dataset.element = id
                bar.append(item.el)
                this.#items.push(item)
            }
            bar.hidden = entries.length === 0
            // keep the bars up while the pointer or keyboard focus is on them
            bar.addEventListener('pointerenter', () => this.show(false))
            bar.addEventListener('pointerleave', () => this.#scheduleHide())
            bar.addEventListener('focusin', () => this.show(false))
            bar.addEventListener('focusout', () => this.#scheduleHide())
        }
        this.show()
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
        if (this.#ctx.panels.open) return
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

    /**
     * A tap at viewport position (x, y). Top/bottom zones toggle the bars; in page mode the
     * left/right thirds turn pages; anything else hides the bars again.
     */
    tap(x, y) {
        const zone = Number(this.#options.tapZone) || 0.18
        const height = innerHeight
        if (y < height * zone || y > height * (1 - zone)) return this.toggle()
        if (!this.#ctx.engine.scrolled) {
            if (x < innerWidth * 0.3) return this.#ctx.engine.prev()
            if (x > innerWidth * 0.7) return this.#ctx.engine.next()
            return this.toggle()
        }
        if (this.visible) this.hide()
    }
}
