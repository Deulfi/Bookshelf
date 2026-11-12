// Picks the position to read from when this browser and the KOReader sync record disagree
// (another device read on since this browser was last here). The reader setting
// "syncConflict" decides: "ask" shows a dialog, "latest" jumps to the newer position.
import { compare } from './position.js'

const percent = fraction => `${(Math.max(0, Math.min(1, fraction ?? 0)) * 100).toFixed(1)}%`

function ago(seconds) {
    const diff = Math.max(0, Date.now() / 1000 - seconds)
    if (diff < 60) return 'just now'
    const units = [[86400, 'day'], [3600, 'hour'], [60, 'minute']]
    for (const [size, unit] of units) {
        if (diff >= size) {
            const n = Math.floor(diff / size)
            return `${n} ${unit}${n === 1 ? '' : 's'} ago`
        }
    }
    return ''
}

export class Sync {
    #engine
    #position
    #prefs
    #dialog
    #seen = 0 // newest remote timestamp (s) already dealt with
    #asking = false

    constructor({ engine, position, prefs, dialog }) {
        this.#engine = engine
        this.#position = position
        this.#prefs = prefs
        this.#dialog = dialog
    }

    /** Open at a chosen record { progress, percentage } (resuming a session from the book
     *  page) instead of the synced position; it becomes the new position everywhere. */
    resume(record) {
        return { target: this.#target(record), fallback: record, push: true }
    }

    /** The position to open the book at (a CFI, an XPointer, { fraction } or null), and
     *  whether this browser's position won a conflict and should be sent to the server. */
    async initial() {
        const local = this.#position.local()
        const remote = await this.#position.remote()
        this.#seen = remote?.timestamp ?? 0
        const decision = compare(local, remote, this.#position.device)
        if (decision === 'reset') {
            this.#position.clear()
            return { target: null }
        }
        if (decision === 'local') return { target: local?.cfi ?? null }
        if (decision === 'remote') return { target: this.#target(remote), fallback: remote }
        const choice = await this.#choose(local, remote)
        if (choice === 'remote') return { target: this.#target(remote), fallback: remote }
        return { target: local.cfi, push: true }
    }

    /** Look for a newer position from another device (when the tab is shown again). */
    async check() {
        if (this.#asking) return
        const remote = await this.#position.remote()
        const local = this.#position.local()
        const decision = compare(local, remote, this.#position.device, this.#seen)
        this.#seen = Math.max(this.#seen, remote?.timestamp ?? 0)
        if (decision !== 'conflict') return
        const choice = await this.#choose(local, remote)
        if (choice === 'remote') await this.go(remote)
        else this.#keepLocal()
    }

    /** Open a remote record, falling back to its percentage if its position does not fit. */
    async go(remote) {
        try {
            await this.#engine.goToPosition(this.#target(remote))
        } catch {
            await this.#engine.goToPosition({ fraction: remote.percentage ?? 0 })
        }
    }

    #keepLocal() {
        // Send this browser's position so the other devices see it as the newest one.
        const location = this.#engine.location
        if (location) {
            this.#position.update(location)
            this.#position.flush()
        }
    }

    #target(remote) {
        const progress = remote.progress
        if (typeof progress === 'string'
            && (progress.startsWith('/body/') || progress.startsWith('epubcfi(')))
            return progress
        return { fraction: remote.percentage ?? 0 } // e.g. a page number from a PDF reader
    }

    async #where(progress, fraction) {
        const label = await this.#engine.chapterLabelOf(progress)
        return label ? `${label} · ${percent(fraction)}` : `About ${percent(fraction)}`
    }

    async #choose(local, remote) {
        if (this.#prefs.get('syncConflict', 'ask') === 'latest') return 'remote'
        const dialog = this.#dialog
        if (!dialog?.showModal) return 'remote'
        this.#asking = true
        dialog.querySelector('[data-remote-device]').textContent =
            [remote.device || 'Another device', ago(remote.timestamp)].filter(Boolean).join(' · ')
        const [remoteWhere, localWhere] = await Promise.all([
            this.#where(remote.progress, remote.percentage),
            // this browser's exact CFI resolves without loading anything
            this.#where(local.cfi ?? local.progress, local.fraction),
        ])
        dialog.querySelector('[data-remote-where]').textContent = remoteWhere
        dialog.querySelector('[data-local-where]').textContent = localWhere
        const always = dialog.querySelector('input[name="always"]')
        always.checked = false
        dialog.returnValue = ''
        dialog.showModal()
        await new Promise(resolve => dialog.addEventListener('close', resolve, { once: true }))
        this.#asking = false
        // Escape keeps reading here, like choosing this browser.
        const choice = dialog.returnValue === 'remote' ? 'remote' : 'local'
        if (always.checked) this.#prefs.set('syncConflict', 'latest')
        return choice
    }
}
