// Side panels: table of contents and the settings panel (generated from config.settings).
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

    get(name) {
        return this.#panels.get(name)
    }

    show(name) {
        if (this.open === name) return
        this.close(false)
        const panel = this.#panels.get(name)
        if (!panel) return
        panel.hidden = false
        this.scrim.hidden = false
        this.open = name
        this.dispatchEvent(new CustomEvent('open', { detail: { name, panel } }))
        panel.querySelector('[data-autofocus], button, input, select, a')?.focus({ preventScroll: true })
    }

    close(notify = true) {
        if (!this.open) return
        this.#panels.get(this.open).hidden = true
        this.scrim.hidden = true
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
