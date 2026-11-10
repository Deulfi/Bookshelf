// Browser reader entry point. The page inlines everything as JSON (see routers/reader.py):
// the book, the merged reader configuration and the user's saved preferences.
import { Engine } from './engine.js'
import { Prefs } from './prefs.js'
import { Position } from './position.js'
import { Bars } from './bars.js'
import { loadPlugins } from './elements/index.js'
import { Panels, buildTOC, buildSettings } from './panels.js'
import { ChapterFlow } from './chapter-flow.js'
import { Sync } from './sync.js'
import {
    activeTheme, applyChromeTheme, bookCSS, onSystemThemeChange, rendererAttributes,
} from './style.js'

const boot = JSON.parse(document.getElementById('reader-bootstrap').textContent)
const { book, config } = boot

const iconTemplates = new Map([...document.getElementById('reader-icons').content.children]
    .map(el => [el.dataset.icon, el.firstElementChild]))
const icon = name => iconTemplates.get(name)?.cloneNode(true) ?? document.createElement('span')

const engine = new Engine(document.getElementById('view'), { xpointers: book.format === 'epub' })
const prefs = new Prefs({ config, serverPrefs: boot.prefs, url: boot.prefsUrl })
const position = new Position({ document: book.document, url: book.positionUrl })
const panels = new Panels()

const ctx = {
    book, config, engine, prefs, panels, icon,
    theme: () => activeTheme(config, prefs),
    flush: () => Promise.all([position.flush(), prefs.flush()]),
}

// ---------- appearance ----------

function applyAppearance() {
    const theme = activeTheme(config, prefs)
    applyChromeTheme(theme)
    if (!engine.renderer) return
    engine.setAttributes(rendererAttributes(prefs))
    engine.setStyles(bookCSS(config, prefs, boot.fontsUrl))
}
prefs.addEventListener('change', ({ detail }) => {
    applyAppearance()
    if (detail.keys.includes('autoAdvance')) chapterFlow?.setEnabled(prefs.get('autoAdvance', true))
})
onSystemThemeChange(() => {
    if (prefs.get('theme') === 'auto') applyAppearance()
})
applyChromeTheme(activeTheme(config, prefs)) // before the book loads, to avoid a white flash

// ---------- open the book ----------

const status = document.getElementById('reader-status')
let chapterFlow = null
let bars = null
try {
    await engine.open(book.fileUrl)
} catch (error) {
    console.error(error)
    status.textContent = 'This book could not be opened in the browser.'
    status.hidden = false
    throw error
}
applyAppearance()

await loadPlugins(boot.plugins ?? [])
bars = new Bars(ctx, config.layout ?? {})
const toc = buildTOC(panels.get('toc').querySelector('.panel-body'), engine, () => panels.close())
buildSettings(panels.get('settings').querySelector('.panel-body'), config, prefs)
panels.addEventListener('open', ({ detail }) => {
    bars.show(false)
    if (detail.name === 'toc') toc.reveal()
})
panels.addEventListener('close', () => bars.show())

chapterFlow = new ChapterFlow(engine, {
    enabled: prefs.get('autoAdvance', true),
    options: config.layout?.chapterFlow,
})

engine.addEventListener('relocate', ({ detail }) => {
    bars.update(detail)
    toc.highlight(detail.tocItem)
    position.update(detail)
    status.hidden = true
})

// ---------- input inside the book ----------

function onBookClick(e, frame) {
    if (e.defaultPrevented || e.button !== 0) return
    if (e.target.closest?.('a[href], button, input, select, textarea, audio, video')) return
    const selection = e.view?.getSelection?.()
    if (selection && !selection.isCollapsed) return
    const rect = frame?.getBoundingClientRect() ?? { left: 0, top: 0 }
    bars.tap(rect.left + e.clientX, rect.top + e.clientY)
}

function onKey(e) {
    if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return
    if (e.target.closest?.('input, select, textarea, [contenteditable]')) return
    const scrolled = engine.scrolled
    switch (e.key) {
        case 'Escape':
            if (panels.open) panels.close()
            else bars.toggle()
            break
        case 'ArrowLeft':
            engine.view.goLeft()
            break
        case 'ArrowRight':
            engine.view.goRight()
            break
        case 'ArrowDown':
            if (scrolled) engine.next(80)
            else engine.next()
            break
        case 'ArrowUp':
            if (scrolled) engine.prev(80)
            else engine.prev()
            break
        case 'PageDown':
        case ' ':
            if (e.shiftKey) engine.prev()
            else engine.next()
            break
        case 'PageUp':
            engine.prev()
            break
        default:
            return
    }
    e.preventDefault()
}

engine.addEventListener('load', ({ detail: { doc } }) => {
    const frame = doc.defaultView?.frameElement ?? null
    doc.addEventListener('click', e => onBookClick(e, frame))
    doc.addEventListener('keydown', onKey)
})
document.getElementById('reader').addEventListener('click', e => {
    if (e.target.closest('foliate-view') || e.target === e.currentTarget) onBookClick(e, null)
})
document.addEventListener('keydown', onKey)

// ---------- start reading ----------

const sync = new Sync({
    engine, position, prefs, dialog: document.getElementById('sync-dialog'),
})
let started = false
const flush = () => { position.flush(); prefs.flush() }
addEventListener('pagehide', flush)
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush()
    else if (started) sync.check() // another device may have read on meanwhile
})

const { target, fallback, push } = await sync.initial()
const attempts = [target]
if (fallback) attempts.push({ fraction: fallback.percentage ?? 0 })
attempts.push(null)
for (const attempt of attempts) {
    try {
        await engine.start(attempt)
        break
    } catch (error) {
        // A position that does not fit this book (e.g. edited elsewhere): try the next one.
        console.warn('[reader] could not restore the reading position', attempt, error)
    }
}
started = true
status.hidden = true
if (push && engine.location) {
    position.update(engine.location)
    position.flush()
}
