// Reading position. The server copy is the KOReader sync record that KOReader and Readest use
// too, so EPUB positions are sent as KOReader XPointers. This browser additionally keeps its
// exact foliate CFI in localStorage, used when the server still holds what this browser sent.
const REMOTE_DELAY = 5000
const DEVICE_KEY = 'bookshelf-reader-device'
export const DEVICE_NAME = 'Web reader'

/** A stable id for this browser, so other devices' updates can be told from our own. */
export function deviceId() {
    try {
        let id = localStorage.getItem(DEVICE_KEY)
        if (!id) {
            id = crypto.randomUUID?.() ?? `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`
            localStorage.setItem(DEVICE_KEY, id)
        }
        return id
    } catch {
        return ''
    }
}

/**
 * Local record: { progress, cfi, fraction, time, synced } where progress is what was (or will
 * be) sent to the server, time is when this browser was last at that position (ms) and synced
 * says the server received it.
 * Remote record: { progress, percentage, device, device_id, timestamp (s) } or null.
 */
export class Position {
    #url
    #key
    #device
    #timer = null
    #pending = null

    constructor({ document, url }) {
        this.#url = url
        // Keyed by the book's content hash, not its id: ids are reused after a database reset.
        this.#key = `bookshelf-reader-position-${document}`
        this.#device = deviceId()
    }

    get device() {
        return this.#device
    }

    local() {
        try {
            const raw = localStorage.getItem(this.#key)
            if (!raw) return null
            if (!raw.startsWith('{')) return null // pre-sync format (a bare CFI): let the server decide
            const record = JSON.parse(raw)
            return record?.cfi || record?.progress ? record : null
        } catch {
            return null
        }
    }

    /** The server record, null if there is none, undefined if the server can't be reached. */
    async remote() {
        try {
            const res = await fetch(this.#url, { cache: 'no-store' })
            if (!res.ok) return undefined
            const data = await res.json()
            return data.progress ? data : null
        } catch {
            return undefined // offline
        }
    }

    /** Remember a location; sent to the server after a pause in reading. */
    update(location) {
        if (!location?.cfi) return
        const record = {
            progress: location.xpointer || location.cfi,
            cfi: location.cfi,
            fraction: location.fraction ?? 0,
            time: Date.now(),
        }
        try {
            localStorage.setItem(this.#key, JSON.stringify(record))
        } catch {
            // ignore: the server copy is the primary one
        }
        this.#pending = record
        clearTimeout(this.#timer)
        this.#timer = setTimeout(() => this.flush(), REMOTE_DELAY)
    }

    /** Forget this browser's copy (the progress was reset on the server). */
    clear() {
        this.#pending = null
        clearTimeout(this.#timer)
        try {
            localStorage.removeItem(this.#key)
        } catch {
            // nothing to clear
        }
    }

    #markSynced(record) {
        try {
            const stored = this.local()
            if (stored?.time === record.time)
                localStorage.setItem(this.#key, JSON.stringify({ ...stored, synced: true }))
        } catch {
            // the flag only matters after a reset on the server
        }
    }

    async flush() {
        clearTimeout(this.#timer)
        this.#timer = null
        const record = this.#pending
        if (!record) return
        this.#pending = null
        try {
            const res = await fetch(this.#url, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    progress: record.progress,
                    fraction: record.fraction,
                    device: DEVICE_NAME,
                    device_id: this.#device,
                }),
                keepalive: true,
            })
            if (!res.ok) throw new Error(res.statusText)
            this.#markSynced(record)
        } catch {
            this.#pending ??= record // offline: retry with the next update
        }
    }
}

/**
 * Which position to open: 'local', 'remote', 'conflict' (another device moved on since this
 * browser was last here, to a different place) or 'reset' (the server had this browser's
 * position and no longer has it: the progress was reset). `seen` is the newest remote
 * timestamp (s) this browser already dealt with.
 */
export function compare(local, remote, device, seen = 0) {
    if (remote === undefined) return 'local' // offline: nothing to compare with
    if (!remote) return local?.synced ? 'reset' : 'local'
    if (!local) return 'remote'
    if (remote.progress === local.progress || remote.progress === local.cfi) return 'local'
    if (remote.device_id && remote.device_id === device) return 'local'
    const remoteTime = (remote.timestamp ?? 0) * 1000
    if (remoteTime <= Math.max(local.time ?? 0, seen * 1000)) return 'local'
    if (Math.abs((remote.percentage ?? 0) - (local.fraction ?? 0)) < 0.00005) return 'local'
    return 'conflict'
}
