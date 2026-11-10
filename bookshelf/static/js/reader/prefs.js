// The values chosen in the settings panel. Source order: control defaults, then the user's
// server-side preferences, then local edits that have not reached the server yet.
import { allControls, controlDefaults, normalizeValue, warn } from './config.js'

const CACHE_KEY = 'bookshelf-reader-prefs'
const SAVE_DELAY = 800

function readCache() {
    try {
        return JSON.parse(localStorage.getItem(CACHE_KEY)) ?? null
    } catch {
        return null
    }
}

function writeCache(values, pending) {
    try {
        localStorage.setItem(CACHE_KEY, JSON.stringify({ values, pending }))
    } catch {
        // storage full or blocked: the server copy still applies
    }
}

export class Prefs extends EventTarget {
    #config
    #url
    #controls
    #timer = null
    values

    constructor({ config, serverPrefs, url }) {
        super()
        this.#config = config
        this.#url = url
        this.#controls = new Map(allControls(config).map(c => [c.key, c]))
        const cache = readCache()
        const local = cache?.pending ? cache.values : {}
        this.values = this.#normalize({ ...controlDefaults(config), ...serverPrefs, ...local })
        if (cache?.pending) this.#scheduleSave()
    }

    #normalize(values) {
        const result = { ...values }
        for (const [key, control] of this.#controls)
            result[key] = normalizeValue(control, values[key], this.#config)
        return result
    }

    get(key, fallback) {
        return this.values[key] ?? fallback
    }

    control(key) {
        return this.#controls.get(key)
    }

    set(key, value) {
        const control = this.#controls.get(key)
        const next = control ? normalizeValue(control, value, this.#config) : value
        if (this.values[key] === next) return
        this.values = { ...this.values, [key]: next }
        this.#changed([key])
    }

    reset() {
        this.values = this.#normalize(controlDefaults(this.#config))
        this.#changed([...this.#controls.keys()])
    }

    #changed(keys) {
        writeCache(this.values, true)
        this.#scheduleSave()
        this.dispatchEvent(new CustomEvent('change', { detail: { keys } }))
    }

    #scheduleSave() {
        clearTimeout(this.#timer)
        this.#timer = setTimeout(() => this.flush(), SAVE_DELAY)
    }

    async flush() {
        clearTimeout(this.#timer)
        const values = this.values
        try {
            const res = await fetch(this.#url, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(values),
                keepalive: true,
            })
            if (!res.ok) throw new Error(`HTTP ${res.status}`)
            if (values === this.values) writeCache(values, false)
        } catch (error) {
            warn('could not save preferences, keeping them locally', error)
        }
    }
}
