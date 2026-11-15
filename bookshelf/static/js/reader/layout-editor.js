// Bar editor for the web reader, used on the settings page (Settings → Web reader) and inside
// the reader (the "bar-editor" element / "Arrange bars" in the reader settings). Drag elements
// from "Available elements" into the top or bottom bar and drag them to reorder; arrow and
// remove buttons do the same without dragging. Saves the "layout" part of the user's reader
// config file. A small mockup of both bars sits on top and follows every edit.
import { catalog, loadPlugins } from './elements/index.js'

const DRAG_THRESHOLD = 6
const BARS = [['top', 'Top bar'], ['bottom', 'Bottom bar']]

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

/** Icons from a <template> of `<span data-icon="name"><svg …></span>` (reader-icons). */
export function iconsFrom(template) {
    const map = new Map([...(template?.content.children ?? [])]
        .map(el => [el.dataset.icon, el.firstElementChild]))
    return name => map.get(name)?.cloneNode(true) ?? null
}

/**
 * Mount the editor in `root`.
 *   elementsUrl, saveUrl  the JSON endpoints (/api/reader/layout, /settings/reader/layout)
 *   compact               show only the mockup and an "Edit bars" button until opened
 *   icon(name)            an icon element for the mockup, or null
 *   onSaved(layout)       called with the saved effective layout
 *   onChange(layout)      called with the edited, not yet saved layout after every edit
 *   onTapZone(fraction)   the tap area field has focus (fraction) or lost it (null), for a guide
 *   toolbar               an element with [data-le-save], [data-le-reset] buttons and a
 *                         .le-status (the reader's window head) used instead of the button row
 * Returns { dirty, discard() } once loaded: discard() forgets unsaved edits.
 */
export async function mountLayoutEditor(root, {
    elementsUrl, saveUrl, compact = false, icon = () => null, onSaved = () => {},
    onChange = null, onTapZone = null, toolbar = null,
} = {}) {
    let elements = new Map() // id -> catalog entry
    let layout // { top: [{id, ...options}], bottom: [...], autohide: {}, chapterFlow: {} }
    let limits = {}
    let openOptions = null // { bar, index } of the chip whose options are shown
    let dirty = false
    let expanded = !compact
    // Behaviour starts open where there is room for it (the reader's window on a wide screen)
    let behaviourOpen = !compact && matchMedia('(min-width: 900px) and (orientation: landscape)').matches
    const saveButton = toolbar?.querySelector('[data-le-save]')
    const resetButton = toolbar?.querySelector('[data-le-reset]')
    // properties, not listeners: the reader mounts a fresh editor after unsaved edits are dropped
    if (saveButton) saveButton.onclick = () => save()
    if (resetButton) resetButton.onclick = () => resetToDefault()
    const toolbarStatus = toolbar?.querySelector('.le-status')
    if (toolbarStatus) toolbarStatus.textContent = ''

    const current = () => ({
        top: serialize(layout.top),
        bottom: serialize(layout.bottom),
        autohide: { ...layout.autohide },
        chapterFlow: { ...layout.chapterFlow },
    })

    const changed = () => {
        dirty = true
        render()
        onChange?.(current())
    }

    // ---------- rendering ----------

    function render() {
        const scroll = window.scrollY
        const parts = [mockup()]
        if (compact) parts.push(h('div', { class: 'le-compact-row' },
            h('button', {
                type: 'button', class: 'btn btn-sm', 'aria-expanded': String(expanded),
                onclick: () => { expanded = !expanded; render() },
            }, expanded ? 'Close the bar editor' : 'Edit bars'),
            dirty ? h('span', { class: 'small muted' }, 'Unsaved changes') : null))
        if (expanded) parts.push(
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
        )
        if (saveButton) saveButton.disabled = !dirty
        else if (expanded || dirty) parts.push(h('div', { class: 'actions le-actions' },
            h('button', { type: 'button', class: 'btn btn-primary', onclick: save, disabled: !dirty }, 'Save'),
            h('button', { type: 'button', class: 'btn', onclick: resetToDefault }, 'Reset to default'),
            h('span', { class: 'le-status small muted', role: 'status' }),
        ))
        root.replaceChildren(...parts)
        window.scrollTo({ top: scroll })
    }

    const labelOf = id => elements.get(id)?.label ?? `Unknown element “${id}”`
    /** Tooltip of an element chip: what the element does, else its name. */
    const describe = id => elements.get(id)?.description || labelOf(id)

    // ---------- mockup ----------

    const PREVIEW_TEXT = {
        'title': 'Book title', 'chapter-title': 'Chapter title', 'progress-text': '42%',
        'chapter-counter': 'Ch. 3/12', 'page-counter': '3/12',
    }

    function mockItem(item) {
        const entry = elements.get(item.id)
        const title = labelOf(item.id)
        if (item.id === 'spacer') return h('span', { class: 'le-pv-spacer', title })
        if (item.id === 'space')
            return h('span', { class: 'le-pv-space', title, style: `width:${Math.min(24, Math.max(2, (Number(item.width) || 16) / 2))}px` })
        if (item.id === 'progress-bar' || item.id === 'chapter-progress')
            return h('span', { class: 'le-pv-slider', title }, h('i'))
        if (PREVIEW_TEXT[item.id]) return h('span', { class: 'le-pv-text', title }, PREVIEW_TEXT[item.id])
        const svg = entry?.icon ? icon(entry.icon) : null
        const showLabel = item.showLabel ?? entry?.options?.find(o => o.key === 'showLabel')?.default
        if (svg) return h('span', { class: 'le-pv-btn', title }, svg,
            showLabel ? h('span', {}, entry.label) : null)
        return h('span', { class: 'le-pv-text', title }, entry?.label ?? item.id)
    }

    function mockBar(bar) {
        const list = layout[bar]
        return h('div', { class: `le-pv-bar le-pv-${bar}${list.length ? '' : ' is-empty'}` },
            list.length ? list.map(mockItem)
                : h('span', { class: 'le-pv-text' }, 'hidden'))
    }

    function mockup() {
        return h('div', { class: 'le-preview', 'aria-label': 'Preview of the reader bars', role: 'img' },
            mockBar('top'),
            h('div', { class: 'le-pv-page', 'aria-hidden': 'true' }, h('i'), h('i'), h('i')),
            mockBar('bottom'))
    }

    // ---------- chips ----------

    function chip(bar, index, item) {
        const known = elements.has(item.id)
        const hasOptions = (elements.get(item.id)?.options ?? []).length > 0
        const list = layout[bar]
        const isOpen = openOptions?.bar === bar && openOptions.index === index
        const other = bar === 'top' ? 'bottom' : 'top'
        return h('li', {
            class: `le-chip${known ? '' : ' is-unknown'}${item.id === 'spacer' ? ' is-spacer' : ''}${isOpen ? ' is-open' : ''}`,
            'data-index': index,
        },
            h('span', { class: 'le-handle', title: describe(item.id), onpointerdown: e => startDrag(e, { bar, index }) },
                labelOf(item.id)),
            h('span', { class: 'le-chip-tools' },
                h('button', { type: 'button', class: 'le-tool', 'aria-label': `Move ${labelOf(item.id)} left`, disabled: index === 0,
                    onclick: () => move(bar, index, index - 1) }, '‹'),
                h('button', { type: 'button', class: 'le-tool', 'aria-label': `Move ${labelOf(item.id)} right`, disabled: index === list.length - 1,
                    onclick: () => move(bar, index, index + 1) }, '›'),
                h('button', { type: 'button', class: 'le-tool', 'aria-label': `Move ${labelOf(item.id)} to the ${other} bar`,
                    title: `Move to the ${other} bar`,
                    onclick: () => transfer({ bar, index }, other, Infinity) }, bar === 'top' ? '↓' : '↑'),
                hasOptions ? h('button', { type: 'button', class: 'le-tool', 'aria-label': `Options for ${labelOf(item.id)}`, 'aria-expanded': String(isOpen),
                    onclick: () => { openOptions = isOpen ? null : { bar, index }; render() } }, '⚙') : null,
                h('button', { type: 'button', class: 'le-tool le-remove', 'aria-label': `Remove ${labelOf(item.id)}`,
                    onclick: () => remove(bar, index) }, '×'),
            ),
        )
    }

    const used = id => layout.top.some(i => i.id === id) || layout.bottom.some(i => i.id === id)

    function palette() {
        return h('div', { class: 'le-palette-wrap' },
            h('h3', {}, 'Available elements'),
            h('ul', { class: 'le-palette', 'data-bar': 'palette' },
                [...elements.values()].map(entry => {
                    const taken = !entry.repeatable && used(entry.id)
                    return h('li', { class: `le-chip le-source${taken ? ' is-used' : ''}` },
                        h('span', { class: 'le-handle', title: describe(entry.id) + (taken ? ' (already in a bar)' : ''),
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

    function markDirty() {
        dirty = true
        const button = saveButton ?? root.querySelector('.le-actions .btn-primary')
        if (button) button.disabled = false
        root.querySelector('.le-preview')?.replaceWith(mockup())
        onChange?.(current())
    }

    function optionsForm(bar, index) {
        const item = layout[bar][index]
        const options = elements.get(item?.id)?.options ?? []
        if (!item || !options.length) return null
        const set = (key, value, fallback) => {
            if (value === fallback || value === '' || value === undefined) delete item[key]
            else item[key] = value
            markDirty()
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
        const uid = compact ? 'le' : 'le-reader'
        const number = (section, key, scale = 1) => e => {
            const value = Number(e.target.value) * scale
            if (Number.isFinite(value)) { layout[section][key] = value; markDirty() }
        }
        return h('details', { class: 'le-behaviour', open: behaviourOpen,
            ontoggle: e => { behaviourOpen = e.target.open } },
            h('summary', {}, 'Behaviour'),
            h('label', { class: 'le-option le-option-inline' },
                h('input', { type: 'checkbox', checked: autohide.enabled !== false,
                    onchange: e => { autohide.enabled = e.target.checked; markDirty() } }),
                'Hide the bars automatically'),
            h('div', { class: 'le-option' }, h('label', { for: `${uid}-delay` }, 'Hide after (seconds)'),
                h('input', { class: 'input', id: `${uid}-delay`, type: 'number', min: delayMin / 1000, max: delayMax / 1000, step: 0.5,
                    value: (autohide.delayMs ?? 3500) / 1000, oninput: number('autohide', 'delayMs', 1000) })),
            h('div', { class: 'le-option' }, h('label', { for: `${uid}-zone` }, 'Tap area at the top and bottom (% of the screen)'),
                h('input', { class: 'input', id: `${uid}-zone`, type: 'number', min: zoneMin * 100, max: zoneMax * 100, step: 1,
                    value: Math.round((autohide.tapZone ?? 0.18) * 100),
                    oninput: e => { number('autohide', 'tapZone', 0.01)(e); onTapZone?.(layout.autohide.tapZone) },
                    onfocus: () => onTapZone?.(layout.autohide.tapZone ?? 0.18),
                    onblur: () => onTapZone?.(null) })),
            h('div', { class: 'le-option' }, h('label', { for: `${uid}-over` }, 'Scroll distance past a chapter end to load the next one (px)'),
                h('input', { class: 'input', id: `${uid}-over`, type: 'number', min: overMin, max: overMax, step: 10,
                    value: chapterFlow.overscrollPx ?? 160, oninput: number('chapterFlow', 'overscrollPx') })),
        )
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
        if (strip && root.contains(strip)) {
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
        } else if (paletteEl && root.contains(paletteEl) && drag.source.bar) {
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
        const el = (toolbar ?? root).querySelector('.le-status')
        if (!el) return
        el.textContent = text
        el.classList.toggle('le-error', isError)
    }

    async function send(body) {
        const res = await fetch(saveUrl, {
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
            const data = await send({ layout: current() })
            saved(data.layout, 'Saved.')
        } catch (error) {
            status(error.message, true)
        }
    }

    async function resetToDefault() {
        if (!confirm('Reset both bars and their behaviour to the defaults?')) return
        try {
            const data = await send({ layout: null })
            openOptions = null
            saved(data.layout, 'Bars reset to the defaults.')
        } catch (error) {
            status(error.message, true)
        }
    }

    function saved(config, message) {
        layout = fromConfig(config)
        dirty = false
        render()
        status(message)
        onSaved(config)
    }

    window.addEventListener('beforeunload', e => {
        if (dirty) e.preventDefault()
    })

    // ---------- start ----------

    try {
        const data = await (await fetch(elementsUrl)).json()
        await loadPlugins(data.plugins ?? [])
        elements = new Map(catalog().map(entry => [entry.id, entry]))
        layout = fromConfig(data.layout)
        limits = data.limits ?? {}
        render()
    } catch (error) {
        console.error(error)
        root.replaceChildren(h('p', { class: 'alert alert-error' }, 'The bar editor could not be loaded.'))
    }
    return {
        get dirty() { return dirty },
        discard() { dirty = false },
    }
}
