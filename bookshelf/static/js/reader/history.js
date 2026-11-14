// Reading-position history for the "go back" / "go forward" bar elements, like Readest's
// undo/redo (and foliate's own view.history, which only sees some of our jumps).
//
// Every jump (table of contents, search, a link, chapter buttons, the book slider; the
// engine's `jump` event) starts a new entry; reading on (page turns, scrolling, chapter
// auto-advance) keeps updating the current entry, so going back returns to where you had
// read to before the jump. Going back or forward updates the entry it lands on the same way,
// so a landing spot that differs slightly from the stored CFI does not clear the forward steps.
//
// The first bar element that needs it creates one shared History for the page's engine,
// so "go back" and "go forward" share one stack.

const MAX_ENTRIES = 200

let shared = null

export function historyFor(engine) {
    shared ??= new History(engine)
    return shared
}

class History extends EventTarget {
    #engine
    #entries = [] // CFIs in visit order; null until the jump that made the entry lands
    #index = -1

    constructor(engine) {
        super()
        this.#engine = engine
        engine.addEventListener('relocate', e => this.#relocated(e.detail))
        engine.addEventListener('jump', () => this.#jumped())
    }

    get canGoBack() {
        return this.#index > 0
    }

    get canGoForward() {
        return this.#index >= 0 && this.#index < this.#entries.length - 1
    }

    #relocated(location) {
        if (!location?.cfi) return
        if (this.#index < 0) {
            this.#entries = [location.cfi]
            this.#index = 0
            this.#notify()
        } else this.#entries[this.#index] = location.cfi
    }

    #jumped() {
        // nothing read yet, or the last jump has not landed yet: one entry for both
        if (this.#index < 0 || this.#entries[this.#index] === null) return
        this.#entries.length = this.#index + 1 // a jump clears the forward steps
        this.#entries.push(null)
        this.#index += 1
        if (this.#entries.length > MAX_ENTRIES) {
            this.#entries.shift()
            this.#index -= 1
        }
        this.#notify()
    }

    async goBack() {
        if (!this.canGoBack) return
        // a jump that never landed (it failed) leaves nothing to come back to
        if (this.#entries[this.#index] === null) this.#entries.length = this.#index
        this.#index -= 1
        await this.#go()
    }

    async goForward() {
        if (!this.canGoForward) return
        this.#index += 1
        await this.#go()
    }

    async #go() {
        this.#notify()
        const cfi = this.#entries[this.#index]
        if (cfi === null) return
        try {
            await this.#engine.goToPosition(cfi, { jump: false })
        } catch {
            // the position no longer fits the book; the next relocate updates the entry
        }
    }

    #notify() {
        this.dispatchEvent(new Event('change'))
    }
}
