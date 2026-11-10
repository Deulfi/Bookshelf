// Bar editor for the web reader (Settings → Web reader). Drag elements from "Available
// elements" into the top or bottom bar and drag them to reorder; arrow and remove buttons do the
// same without dragging. Saves the "layout" part of the user's reader config file.
import { catalog, loadPlugins } from './reader/elements/index.js'

const root = document.getElementById('layout-editor')
const DRAG_THRESHOLD = 6
const BARS = [['top', 'Top bar'], ['bottom', 'Bottom bar']]

let elements = new Map() // id -> catalog entry
let layout // { top: [{id, ...options}], bottom: [...], autohide: {}, chapterFlow: {} }
let limits = {}
let openOptions = null // { bar, index } of the chip whose options are shown
let dirty = false

const h = (tag, attrs = {}, ...children) => {
    const el = document.createElement(tag)
    for (const [key, value] of Object.entries(attrs)) {
        if (value === undefined || value === null || value === false) continue
        if (key.startsWith('on')) el.addEventListener(key.slice(2), value)
        else if (key === 'class') el.className = value
        else el.setAttribute(key, value === true ? '' : value)
    }
    el.append(...children.flat().filter(c => c !== null && c !== undefined && c !== false))
    return el
}

const normalize = list => (Array.isArray(list) ? list : [])
    .map(item => typeof item === 'string' ? { id: item } : { ...item })
    .filter(item => typeof item.id === 'string')

const serialize = list => list.map(({ id, ...options }) =>
    Object.keys(options).length ? { id, ...options } : id)

function fromConfig(config) {
    return {
        top: normalize(config.top),
        bottom: normalize(config.bottom),
        autohide: { enabled: true, delayMs: 3500, tapZone: 0.18, ...config.autohide },
        chapterFlow: { overscrollPx: 160, ...config.chapterFlow },
    }
}

function changed() {
    dirty = true
    render()
}

// ---------- rendering ----------

function render() {
    const scroll = window.scrollY
    root.replaceChildren(
        ...BARS.map(([bar, title]) => h('div', { class: 'le-bar' },
            h('div', { class: 'le-bar-head' }, h('h3', {}, title),
                h('span', { class: 'muted small' }, `${layout[bar].length} element${layout[bar].length === 1 ? '' : 's'}`)),
            h('ol', { class: 'le-strip', 'data-bar': bar, 'aria-label': title },
                layout[bar].length ? layout[bar].map((item, index) => chip(bar, index, item))
                    : h('li', { class: 'le-empty' }, 'Empty: this bar is hidden. Drag elements here.')),
            openOptions?.bar === bar ? optionsForm(bar, openOptions.index) : null,
        )),
        palette(),
        behaviour(),
        h('div', { class: 'actions le-actions' },
            h('button', { type: 'button', class: 'btn btn-primary', onclick: save, disabled: !dirty }, 'Save bars'),
            h('button', { type: 'button', class: 'btn', onclick: resetToDefault }, 'Reset bars to default'),
            h('span', { class: 'le-status small muted', role: 'status' }),
        ),
    )
    window.scrollTo({ top: scroll })
}

function labelOf(id) {
    return elements.get(id)?.label ?? `Unknown element “${id}”`
}

function chip(bar, index, item) {
    const known = elements.has(item.id)
    const hasOptions = (elements.get(item.id)?.options ?? []).length > 0
    const list = layout[bar]
    const isOpen = openOptions?.bar === bar && openOptions.index === index
    return h('li', {
        class: `le-chip${known ? '' : ' is-unknown'}${item.id === 'spacer' ? ' is-spacer' : ''}${isOpen ? ' is-open' : ''}`,
        'data-index': index,
    },
        h('span', { class: 'le-handle', title: 'Drag to move', onpointerdown: e => startDrag(e, { bar, index }) },
            labelOf(item.id)),
        h('span', { class: 'le-chip-tools' },
            h('button', { type: 'button', class: 'le-tool', 'aria-label': `Move ${labelOf(item.id)} left`, disabled: index === 0,
                onclick: () => move(bar, index, index - 1) }, '‹'),
            h('button', { type: 'button', class: 'le-tool', 'aria-label': `Move ${labelOf(item.id)} right`, disabled: index === list.length - 1,
                onclick: () => move(bar, index, index + 1) }, '›'),
            h('button', { type: 'button', class: 'le-tool', 'aria-label': `Move ${labelOf(item.id)} to the ${bar === 'top' ? 'bottom' : 'top'} bar`,
                title: `Move to the ${bar === 'top' ? 'bottom' : 'top'} bar`,
                onclick: () => transfer({ bar, index }, bar === 'top' ? 'bottom' : 'top', Infinity) }, bar === 'top' ? '↓' : '↑'),
            hasOptions ? h('button', { type: 'button', class: 'le-tool', 'aria-label': `Options for ${labelOf(item.id)}`, 'aria-expanded': String(isOpen),
                onclick: () => { openOptions = isOpen ? null : { bar, index }; render() } }, '⚙') : null,
            h('button', { type: 'button', class: 'le-tool le-remove', 'aria-label': `Remove ${labelOf(item.id)}`,
                onclick: () => remove(bar, index) }, '×'),
        ),
    )
}

function used(id) {
    return layout.top.some(i => i.id === id) || layout.bottom.some(i => i.id === id)
}

function palette() {
    const entries = [...elements.values()]
    return h('div', { class: 'le-palette-wrap' },
        h('h3', {}, 'Available elements'),
        h('ul', { class: 'le-palette', 'data-bar': 'palette' },
            entries.map(entry => {
                const taken = !entry.repeatable && used(entry.id)
                return h('li', { class: `le-chip le-source${taken ? ' is-used' : ''}` },
                    h('span', { class: 'le-handle', title: taken ? 'Already in a bar' : 'Drag into a bar',
                        onpointerdown: taken ? null : e => startDrag(e, { palette: entry.id }) },
                        entry.label, entry.plugin ? h('small', { class: 'le-badge' }, 'plugin') : null),
                    h('span', { class: 'le-chip-tools' },
                        h('button', { type: 'button', class: 'le-tool', disabled: taken, title: 'Add to the top bar',
                            'aria-label': `Add ${entry.label} to the top bar`, onclick: () => add('top', entry.id) }, '↑'),
                        h('button', { type: 'button', class: 'le-tool', disabled: taken, title: 'Add to the bottom bar',
                            'aria-label': `Add ${entry.label} to the bottom bar`, onclick: () => add('bottom', entry.id) }, '↓'),
                    ))
            })),
        h('p', { class: 'small muted' }, 'Drop a chip back here to remove it from its bar. Plugins placed in the server’s ',
            h('code', {}, 'reader/plugins/'), ' folder appear here automatically.'),
    )
}

function optionsForm(bar, index) {
    const item = layout[bar][index]
    const options = elements.get(item?.id)?.options ?? []
    if (!item || !options.length) return null
    const set = (key, value, fallback) => {
        if (value === fallback || value === '' || value === undefined) delete item[key]
        else item[key] = value
        dirty = true
        root.querySelector('.le-actions .btn-primary').disabled = false
    }
    return h('div', { class: 'le-options' },
        h('strong', {}, `${labelOf(item.id)} options`),
        options.map(option => {
            const value = item[option.key] ?? option.default
            const id = `le-${bar}-${index}-${option.key}`
            if (option.type === 'toggle') return h('label', { class: 'le-option le-option-inline', for: id },
                h('input', { type: 'checkbox', id, checked: Boolean(value),
                    onchange: e => set(option.key, e.target.checked, option.default) }), option.label ?? option.key)
            let control
            if (option.type === 'select') {
                control = h('select', { class: 'input', id, onchange: e => {
                    const chosen = (option.options ?? [])[Number(e.target.value)]
                    set(option.key, chosen?.value, option.default)
                } }, (option.options ?? []).map((o, i) =>
                    h('option', { value: i, selected: String(o.value) === String(value) }, o.label ?? String(o.value))))
            } else {
                const number = option.type === 'number'
                control = h('input', { class: 'input', id, type: number ? 'number' : 'text', value: value ?? '',
                    oninput: e => set(option.key, number ? Number(e.target.value) : e.target.value, option.default) })
            }
            return h('div', { class: 'le-option' }, h('label', { for: id }, option.label ?? option.key), control)
        }),
    )
}

function behaviour() {
    const { autohide, chapterFlow } = layout
    const range = (section, key, fallback) => limits[section]?.[key] ?? fallback
    const [delayMin, delayMax] = range('autohide', 'delayMs', [500, 60000])
    const [zoneMin, zoneMax] = range('autohide', 'tapZone', [0.05, 0.45])
    const [overMin, overMax] = range('chapterFlow', 'overscrollPx', [20, 2000])
    const number = (section, key, scale = 1) => e => {
        const value = Number(e.target.value) * scale
        if (Number.isFinite(value)) { layout[section][key] = value; dirty = true; refreshSave() }
    }
    return h('div', { class: 'le-behaviour' },
        h('h3', {}, 'Behaviour'),
        h('label', { class: 'le-option le-option-inline' },
            h('input', { type: 'checkbox', checked: autohide.enabled !== false,
                onchange: e => { autohide.enabled = e.target.checked; dirty = true; refreshSave() } }),
            'Hide the bars automatically'),
        h('div', { class: 'le-option' }, h('label', { for: 'le-delay' }, 'Hide after (seconds)'),
            h('input', { class: 'input', id: 'le-delay', type: 'number', min: delayMin / 1000, max: delayMax / 1000, step: 0.5,
                value: (autohide.delayMs ?? 3500) / 1000, oninput: number('autohide', 'delayMs', 1000) })),
        h('div', { class: 'le-option' }, h('label', { for: 'le-zone' }, 'Tap area at the top and bottom (% of the screen)'),
            h('input', { class: 'input', id: 'le-zone', type: 'number', min: zoneMin * 100, max: zoneMax * 100, step: 1,
                value: Math.round((autohide.tapZone ?? 0.18) * 100), oninput: number('autohide', 'tapZone', 0.01) })),
        h('div', { class: 'le-option' }, h('label', { for: 'le-over' }, 'Scroll distance past a chapter end to load the next one (px)'),
            h('input', { class: 'input', id: 'le-over', type: 'number', min: overMin, max: overMax, step: 10,
                value: chapterFlow.overscrollPx ?? 160, oninput: number('chapterFlow', 'overscrollPx') })),
    )
}

function refreshSave() {
    const button = root.querySelector('.le-actions .btn-primary')
    if (button) button.disabled = false
}

// ---------- edits ----------

function move(bar, from, to) {
    const list = layout[bar]
    if (to < 0 || to >= list.length) return
    const [item] = list.splice(from, 1)
    list.splice(to, 0, item)
    openOptions = null
    changed()
}

function remove(bar, index) {
    layout[bar].splice(index, 1)
    openOptions = null
    changed()
}

function add(bar, id, at = Infinity) {
    if (!elements.get(id)?.repeatable && used(id)) return
    layout[bar].splice(Math.min(at, layout[bar].length), 0, { id })
    changed()
}

function transfer(source, bar, at) {
    const [item] = layout[source.bar].splice(source.index, 1)
    let index = Math.min(at, layout[bar].length)
    if (source.bar === bar && source.index < index) index -= 1
    layout[bar].splice(Math.max(0, index), 0, item)
    openOptions = null
    changed()
}

// ---------- drag and drop (pointer events: mouse, pen and touch) ----------

let drag = null

function startDrag(event, source) {
    if (event.button !== 0) return
    const chipEl = event.currentTarget.closest('.le-chip')
    drag = { source, chip: chipEl, startX: event.clientX, startY: event.clientY, active: false }
    document.addEventListener('pointermove', onDragMove)
    document.addEventListener('pointerup', onDragEnd, { once: true })
    document.addEventListener('pointercancel', cancelDrag, { once: true })
}

function onDragMove(event) {
    if (!drag) return
    if (!drag.active) {
        if (Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < DRAG_THRESHOLD) return
        drag.active = true
        const rect = drag.chip.getBoundingClientRect()
        drag.ghost = drag.chip.cloneNode(true)
        drag.ghost.classList.add('le-ghost')
        drag.ghost.style.width = `${rect.width}px`
        drag.offsetX = drag.startX - rect.left
        drag.offsetY = drag.startY - rect.top
        document.body.append(drag.ghost)
        drag.chip.classList.add('is-dragging')
        drag.placeholder = h('li', { class: 'le-placeholder', 'aria-hidden': 'true' })
        document.body.classList.add('le-dragging')
    }
    event.preventDefault()
    drag.ghost.style.transform = `translate(${event.clientX - drag.offsetX}px, ${event.clientY - drag.offsetY}px)`
    const target = document.elementFromPoint(event.clientX, event.clientY)
    const strip = target?.closest('.le-strip')
    const paletteEl = target?.closest('.le-palette-wrap')
    root.querySelectorAll('.is-target').forEach(el => el.classList.remove('is-target'))
    drag.placeholder.remove()
    drag.target = null
    if (strip) {
        strip.classList.add('is-target')
        const chips = [...strip.querySelectorAll('.le-chip:not(.is-dragging)')]
        let index = chips.length
        for (const [i, el] of chips.entries()) {
            const r = el.getBoundingClientRect()
            if (event.clientY < r.top || (event.clientY <= r.bottom && event.clientX < r.left + r.width / 2)) {
                index = i
                break
            }
        }
        strip.querySelector('.le-empty')?.remove()
        if (chips[index]) strip.insertBefore(drag.placeholder, chips[index])
        else strip.append(drag.placeholder)
        drag.target = { bar: strip.dataset.bar, index: Number(chips[index]?.dataset.index ?? layout[strip.dataset.bar].length) }
    } else if (paletteEl && drag.source.bar) {
        paletteEl.classList.add('is-target')
        drag.target = { palette: true }
    }
}

function onDragEnd() {
    document.removeEventListener('pointermove', onDragMove)
    const finished = drag
    cancelDrag()
    if (!finished?.active || !finished.target) {
        if (finished?.active) render()
        return
    }
    const { source, target } = finished
    if (target.palette) remove(source.bar, source.index)
    else if (source.palette) add(target.bar, source.palette, target.index)
    else transfer(source, target.bar, target.index)
}

function cancelDrag() {
    document.removeEventListener('pointermove', onDragMove)
    if (!drag) return
    drag.ghost?.remove()
    drag.placeholder?.remove()
    drag.chip?.classList.remove('is-dragging')
    document.body.classList.remove('le-dragging')
    root.querySelectorAll('.is-target').forEach(el => el.classList.remove('is-target'))
    drag = null
}

// ---------- saving ----------

function status(text, isError = false) {
    const el = root.querySelector('.le-status')
    el.textContent = text
    el.classList.toggle('le-error', isError)
}

async function send(body) {
    const res = await fetch(root.dataset.saveUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`)
    return data
}

async function save() {
    status('Saving…')
    try {
        const data = await send({
            layout: {
                top: serialize(layout.top),
                bottom: serialize(layout.bottom),
                autohide: layout.autohide,
                chapterFlow: layout.chapterFlow,
            },
        })
        layout = fromConfig(data.layout)
        dirty = false
        render()
        status('Saved. Reload open books to see the new bars.')
        refreshJsonBox()
    } catch (error) {
        status(error.message, true)
    }
}

async function resetToDefault() {
    if (!confirm('Reset both bars and their behaviour to the defaults?')) return
    try {
        const data = await send({ layout: null })
        layout = fromConfig(data.layout)
        dirty = false
        openOptions = null
        render()
        status('Bars reset to the defaults.')
        refreshJsonBox()
    } catch (error) {
        status(error.message, true)
    }
}

// The JSON box under "Advanced" shows the file; reload it so both views agree.
async function refreshJsonBox() {
    const box = document.getElementById('reader-config')
    if (!box) return
    const res = await fetch(location.pathname)
    const page = new DOMParser().parseFromString(await res.text(), 'text/html')
    box.value = page.getElementById('reader-config')?.value ?? box.value
}

window.addEventListener('beforeunload', e => {
    if (dirty) e.preventDefault()
})

// ---------- start ----------

try {
    const data = await (await fetch(root.dataset.elementsUrl)).json()
    await loadPlugins(data.plugins ?? [])
    elements = new Map(catalog().map(entry => [entry.id, entry]))
    layout = fromConfig(data.layout)
    limits = data.limits ?? {}
    render()
} catch (error) {
    console.error(error)
    root.replaceChildren(h('p', { class: 'alert alert-error' }, 'The bar editor could not be loaded.'))
}
