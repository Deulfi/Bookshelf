// Side panels: table of contents, search and the settings panel (generated from
// config.settings).
import { controlOptions } from './config.js'

export class Panels extends EventTarget {
    #panels = new Map()
    open = null

    constructor() {
        super()
        this.scrim = document.getElementById('reader-scrim')
        this.scrim.addEventListener('click', () => this.close())
        for (const panel of document.querySelectorAll('[data-panel]')) {
            this.#panels.set(panel.dataset.panel, panel)
            panel.querySelector('[data-close]')?.addEventListener('click', () => this.close())
        }
    }

    /** The open panel is docked (data-docked): beside the text, which stays usable. */
    get docked() {
        return this.open !== null && this.#panels.get(this.open)?.hasAttribute('data-docked')
    }

    get(name) {
        return this.#panels.get(name)
    }

    show(name) {
        if (this.open === name) return
        this.close(false)
        const panel = this.#panels.get(name)
        if (!panel) return
        panel.hidden = false
        // A docked panel (search) sits beside the text instead of over it: no scrim, the
        // book stays readable and scrollable.
        if (panel.hasAttribute('data-docked')) document.body.dataset.docked = panel.classList
            .contains('reader-panel-end') ? 'end' : 'start'
        else this.scrim.hidden = false
        this.open = name
        this.dispatchEvent(new CustomEvent('open', { detail: { name, panel } }))
        panel.querySelector('[data-autofocus], button, input, select, a')?.focus({ preventScroll: true })
    }

    close(notify = true) {
        if (!this.open) return
        this.#panels.get(this.open).hidden = true
        this.scrim.hidden = true
        delete document.body.dataset.docked
        this.open = null
        if (notify) this.dispatchEvent(new Event('close'))
    }

    toggle(name) {
        if (this.open === name) this.close()
        else this.show(name)
    }
}

// ---------- Table of contents ----------

export function buildTOC(container, engine, onNavigate) {
    const links = []
    const build = items => {
        const list = document.createElement('ol')
        for (const item of items) {
            const li = document.createElement('li')
            const link = document.createElement('a')
            link.href = '#'
            link.textContent = item.label?.trim() || '—'
            link.dataset.href = item.href ?? ''
            link.addEventListener('click', e => {
                e.preventDefault()
                if (item.href) engine.goTo(item.href)
                onNavigate()
            })
            links.push(link)
            li.append(link)
            if (item.subitems?.length) li.append(build(item.subitems))
            list.append(li)
        }
        return list
    }
    const toc = engine.toc
    container.replaceChildren(toc.length ? build(toc) : Object.assign(
        document.createElement('p'), { className: 'rp-empty', textContent: 'This book has no table of contents.' }))
    return {
        highlight(tocItem) {
            for (const link of links) {
                const current = Boolean(tocItem?.href) && link.dataset.href === tocItem.href
                link.classList.toggle('is-current', current)
                if (current) link.setAttribute('aria-current', 'location')
                else link.removeAttribute('aria-current')
            }
        },
        reveal() {
            container.querySelector('.is-current')?.scrollIntoView({ block: 'center' })
        },
    }
}

// ---------- Search ----------

const SEARCH_KEY = 'bookshelf-reader-search' // this browser's search options

function readSearchOptions() {
    try {
        return JSON.parse(localStorage.getItem(SEARCH_KEY)) ?? {}
    } catch {
        return {}
    }
}

function checkbox(label, checked) {
    const wrap = document.createElement('label')
    wrap.className = 'search-option'
    const input = Object.assign(document.createElement('input'), { type: 'checkbox', checked })
    wrap.append(input, document.createTextNode(label))
    return [wrap, input]
}

export function buildSearch(container, engine) {
    let results = [] // { cfi, excerpt: { pre, match, post } } in book order
    let hits = []
    let current = -1
    let active = null // running search generator
    let token = 0
    let jumped = false // the first match shown is a history step, moving between matches not
    const saved = readSearchOptions()

    const form = document.createElement('form')
    form.className = 'search-form'
    const scope = document.createElement('select')
    scope.setAttribute('aria-label', 'Where to search')
    scope.className = 'input'
    for (const [value, label] of [['book', 'In book'], ['chapter', 'In chapter']]) {
        const option = document.createElement('option')
        option.value = value
        option.textContent = label
        scope.append(option)
    }
    const query = document.createElement('input')
    query.type = 'text'
    query.placeholder = 'Text to find'
    query.className = 'input'
    query.dataset.autofocus = ''
    if (saved.scope === 'chapter') scope.value = 'chapter'
    const button = document.createElement('button')
    button.type = 'submit'
    button.textContent = 'Search'
    const row = Object.assign(document.createElement('div'), { className: 'search-row' })
    row.append(query, button)
    const [caseLabel, matchCase] = checkbox('Match case', Boolean(saved.matchCase))
    const [wordsLabel, wholeWords] = checkbox('Whole words only', Boolean(saved.matchWholeWords))
    const options = Object.assign(document.createElement('div'), { className: 'search-options' })
    options.append(scope, caseLabel, wordsLabel)
    form.append(row, options)
    const save = () => {
        try {
            localStorage.setItem(SEARCH_KEY, JSON.stringify({
                scope: scope.value, matchCase: matchCase.checked,
                matchWholeWords: wholeWords.checked,
            }))
        } catch {
            // storage blocked: the options last for this page
        }
    }
    // a changed option searches again right away when there is something to search for
    for (const control of [scope, matchCase, wholeWords])
        control.addEventListener('change', () => {
            save()
            if (query.value.trim()) run()
        })

    const status = Object.assign(document.createElement('p'), { className: 'search-status' })
    const nav = document.createElement('div')
    nav.className = 'search-nav'
    const prev = Object.assign(document.createElement('button'), { type: 'button', textContent: 'Previous' })
    const next = Object.assign(document.createElement('button'), { type: 'button', textContent: 'Next' })
    nav.append(prev, next)
    const list = document.createElement('div')
    list.className = 'search-results'
    container.append(form, status, nav, list)

    function updateNav() {
        prev.disabled = current <= 0
        next.disabled = current < 0 || current >= results.length - 1
    }

    function goTo(i) {
        if (i < 0 || i >= results.length) return
        hits[current]?.classList.remove('is-current')
        current = i
        hits[i].classList.add('is-current')
        hits[i].scrollIntoView({ block: 'center' })
        updateNav()
        engine.goToMatch(results[i].cfi, { jump: !jumped })
        jumped = true
    }

    prev.addEventListener('click', () => goTo(current - 1))
    next.addEventListener('click', () => goTo(current + 1))

    function addHits(items) {
        for (const result of items) {
            const i = results.length
            results.push(result)
            const hit = document.createElement('button')
            hit.type = 'button'
            hit.className = 'search-hit'
            hit.append(
                document.createTextNode(result.excerpt.pre),
                Object.assign(document.createElement('span'), {
                    className: 'search-match', textContent: result.excerpt.match,
                }),
                document.createTextNode(result.excerpt.post),
            )
            hit.addEventListener('click', () => goTo(i))
            hits.push(hit)
            list.append(hit)
        }
        updateNav()
    }

    function reset() {
        results = []
        hits = []
        current = -1
        list.replaceChildren()
        updateNav()
    }

    async function run() {
        const myToken = ++token
        active?.return()
        active = null
        reset()
        jumped = false
        const text = query.value.trim()
        if (!text) {
            status.textContent = 'Type some text to find.'
            return
        }
        const opts = {
            query: text, matchCase: matchCase.checked, matchWholeWords: wholeWords.checked,
        }
        if (scope.value === 'chapter') {
            const index = engine.location?.sectionIndex
            if (index === undefined) {
                status.textContent = 'Open a chapter first.'
                return
            }
            opts.index = index
        }
        status.textContent = 'Searching…'
        active = engine.search(opts)
        try {
            for await (const result of active) {
                if (myToken !== token) return
                if (result === 'done') break
                if (result.progress != null) {
                    status.textContent = `Searching… ${Math.round(result.progress * 100)}%`
                    continue
                }
                if (result.subitems) addHits(result.subitems)
                else if (result.cfi) addHits([result])
            }
        } finally {
            if (active && myToken === token) active = null
        }
        if (myToken !== token) return
        status.textContent = results.length
            ? `${results.length} ${results.length === 1 ? 'match' : 'matches'}`
            : 'No matches'
        if (results.length) goTo(0)
    }

    form.addEventListener('submit', e => { e.preventDefault(); run() })

    /** Stop a running search, drop the matches and their highlights in the text. */
    function clear() {
        token++
        active?.return()
        active = null
        reset()
        status.textContent = ''
        engine.clearSearch()
    }

    // Closing the panel (close button, Escape or another panel) ends the search.
    const panel = container.closest('[data-panel]')
    if (panel) new MutationObserver(() => { if (panel.hidden) clear() })
        .observe(panel, { attributes: true, attributeFilter: ['hidden'] })

    return { clear }
}

// ---------- Settings ----------

const controls = {
    range(control, value, set) {
        const wrap = document.createElement('div')
        wrap.className = 'rp-range'
        const minus = stepButton('−', 'Decrease')
        const plus = stepButton('+', 'Increase')
        const input = document.createElement('input')
        input.type = 'range'
        input.id = `rp-${control.key}`
        Object.assign(input, { min: control.min ?? 0, max: control.max ?? 100, step: control.step ?? 1 })
        const output = document.createElement('output')
        const step = Number(control.step ?? 1)
        const decimals = (String(step).split('.')[1] ?? '').length
        const show = v => { output.textContent = `${Number(v).toFixed(decimals)}${control.unit ?? ''}` }
        input.value = value
        show(value)
        input.addEventListener('input', () => { show(input.value); set(Number(input.value)) })
        const nudge = dir => {
            const next = Math.min(Number(input.max), Math.max(Number(input.min),
                Number(input.value) + dir * step))
            input.value = String(Number(next.toFixed(decimals)))
            show(input.value)
            set(Number(input.value))
        }
        minus.addEventListener('click', () => nudge(-1))
        plus.addEventListener('click', () => nudge(1))
        wrap.append(minus, input, plus, output)
        return { el: wrap, update(v) { input.value = v; show(v) } }
    },
    select(control, value, set, config) {
        const select = document.createElement('select')
        select.id = `rp-${control.key}`
        select.className = 'input'
        const options = controlOptions(control, config)
        for (const [i, option] of options.entries())
            select.append(new Option(option.label, String(i)))
        const indexOf = v => options.findIndex(o => String(o.value) === String(v))
        select.value = String(indexOf(value))
        select.addEventListener('change', () => set(options[Number(select.value)].value))
        return { el: select, update(v) { select.value = String(indexOf(v)) } }
    },
    segmented(control, value, set, config) {
        const group = document.createElement('div')
        group.className = 'rp-segmented'
        group.setAttribute('role', 'radiogroup')
        const buttons = controlOptions(control, config).map(option => {
            const b = document.createElement('button')
            b.type = 'button'
            b.textContent = option.label
            b.dataset.value = String(option.value)
            b.setAttribute('role', 'radio')
            b.addEventListener('click', () => set(option.value))
            group.append(b)
            return b
        })
        const update = v => buttons.forEach(b =>
            b.setAttribute('aria-checked', String(b.dataset.value === String(v))))
        update(value)
        return { el: group, update }
    },
    toggle(control, value, set) {
        const input = document.createElement('input')
        input.type = 'checkbox'
        input.className = 'rp-switch'
        input.id = `rp-${control.key}`
        input.checked = Boolean(value)
        input.addEventListener('change', () => set(input.checked))
        return { el: input, update(v) { input.checked = Boolean(v) }, inline: true }
    },
    color(control, value, set) {
        const input = document.createElement('input')
        input.type = 'color'
        input.id = `rp-${control.key}`
        input.value = value ?? '#000000'
        input.addEventListener('input', () => set(input.value))
        return { el: input, update(v) { input.value = v }, inline: true }
    },
    themes(control, value, set, config) {
        const grid = document.createElement('div')
        grid.className = 'rp-themes'
        grid.setAttribute('role', 'radiogroup')
        const entries = (config.themes ?? []).map(t => ({ id: t.id, label: t.label ?? t.id, theme: t }))
        if (control.auto) entries.unshift({ id: 'auto', label: control.autoLabel ?? 'Auto' })
        const buttons = entries.map(entry => {
            const b = document.createElement('button')
            b.type = 'button'
            b.className = 'rp-theme'
            b.dataset.value = entry.id
            b.setAttribute('role', 'radio')
            const swatch = document.createElement('span')
            swatch.className = 'rp-swatch'
            swatch.textContent = 'Aa'
            if (entry.theme) Object.assign(swatch.style, { background: entry.theme.bg, color: entry.theme.fg })
            else swatch.classList.add('rp-swatch-auto')
            const label = document.createElement('span')
            label.textContent = entry.label
            b.append(swatch, label)
            b.addEventListener('click', () => set(entry.id))
            grid.append(b)
            return b
        })
        const update = v => buttons.forEach(b =>
            b.setAttribute('aria-checked', String(b.dataset.value === String(v))))
        update(value)
        return { el: grid, update }
    },
}

function stepButton(text, label) {
    const b = document.createElement('button')
    b.type = 'button'
    b.className = 'rp-step'
    b.textContent = text
    b.setAttribute('aria-label', label)
    return b
}

export function buildSettings(container, config, prefs) {
    const updaters = new Map()
    container.replaceChildren()
    for (const section of config.settings?.sections ?? []) {
        const group = document.createElement('section')
        group.className = 'rp-group'
        if (section.title) {
            const heading = document.createElement('h3')
            heading.textContent = section.title
            group.append(heading)
        }
        for (const control of section.controls ?? []) {
            const factory = controls[control.type]
            if (!factory) {
                console.warn('[reader] unknown control type', control.type)
                continue
            }
            const set = value => prefs.set(control.key, value)
            const built = factory(control, prefs.get(control.key), set, config)
            const row = document.createElement('div')
            row.className = built.inline ? 'rp-row rp-row-inline' : 'rp-row'
            if (control.type !== 'themes') {
                const label = document.createElement('label')
                label.textContent = control.label ?? control.key
                label.htmlFor = `rp-${control.key}`
                row.append(label)
            }
            row.append(built.el)
            group.append(row)
            updaters.set(control.key, built.update)
        }
        container.append(group)
    }
    const reset = document.createElement('button')
    reset.type = 'button'
    reset.className = 'btn rp-reset'
    reset.textContent = 'Reset to defaults'
    reset.addEventListener('click', () => prefs.reset())
    container.append(reset)

    prefs.addEventListener('change', ({ detail }) => {
        for (const key of detail.keys) updaters.get(key)?.(prefs.get(key))
    })
}
