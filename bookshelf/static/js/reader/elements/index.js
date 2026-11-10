// Bar element registry. Every element, built in or a drop-in plugin, is a module whose default
// export looks like this (see docs/reader-plugin-example.js):
//
//   export default {
//     id: 'chapter-progress',             // used in layout.top / layout.bottom
//     label: 'Chapter progress bar',      // shown in the bar editor
//     icon: 'list',                       // optional icon name for the editor
//     repeatable: false,                  // may appear more than once (e.g. spacer)
//     options: [{ key, type: 'toggle' | 'select' | 'text' | 'number', label, default,
//                 options: [{ value, label }] }],  // drives the editor's option form
//     css: '',                            // optional extra CSS for the reader page
//     create(ctx, options) { return { el, update(location) {}, destroy() {} } },
//   }
//
// create() may return null to render nothing (e.g. full screen in a browser without it).
// A plugin module may also export an array of such definitions.
import { ui } from './ui.js'
import {
    spacer, exit, title, chapterTitle, toc, settings, themeToggle, fullscreen,
} from './basic.js'
import { prevChapter, nextChapter, prevPage, nextPage } from './navigation.js'
import {
    progressBar, progressText, chapterProgress, chapterCounter, pageCounter,
} from './progress.js'

export { ui }

const registry = new Map()
const warn = (...args) => console.warn('[reader]', ...args)

export function register(definition, source = 'built-in') {
    if (!definition || typeof definition.id !== 'string' || !definition.id
        || typeof definition.create !== 'function') {
        warn(`ignoring element from ${source}: it needs an "id" and a "create" function`)
        return false
    }
    if (registry.has(definition.id) && source !== 'built-in')
        warn(`element “${definition.id}” from ${source} replaces an existing one`)
    registry.set(definition.id, { ...definition, source })
    if (definition.css) {
        const style = document.createElement('style')
        style.dataset.element = definition.id
        style.textContent = definition.css
        document.head.append(style)
    }
    return true
}

for (const element of [
    spacer, exit, title, chapterTitle, toc, settings, themeToggle, fullscreen,
    prevChapter, nextChapter, prevPage, nextPage,
    progressBar, progressText, chapterProgress, chapterCounter, pageCounter,
]) register(element)

/** Import drop-in plugins (module URLs); a broken plugin is logged and skipped. */
export async function loadPlugins(urls = []) {
    await Promise.all(urls.map(async url => {
        try {
            const module = await import(url)
            const definitions = Array.isArray(module.default) ? module.default : [module.default]
            for (const definition of definitions) register(definition, url)
        } catch (error) {
            warn(`could not load plugin ${url}`, error)
        }
    }))
}

/** The element, null if it chose not to render, undefined if the id is unknown. */
export function create(id, ctx, options) {
    const definition = registry.get(id)
    if (!definition) return undefined
    const defaults = Object.fromEntries((definition.options ?? [])
        .filter(o => o.default !== undefined).map(o => [o.key, o.default]))
    try {
        return definition.create({ ...ctx, ui }, { ...defaults, ...options }) ?? null
    } catch (error) {
        warn(`element “${id}” failed to render`, error)
        return null
    }
}

/** What the bar editor offers: every registered element, without its code. */
export function catalog() {
    return [...registry.values()].map(({ id, label, icon, repeatable, options, source }) => ({
        id,
        label: label ?? id,
        icon,
        repeatable: Boolean(repeatable),
        options: options ?? [],
        plugin: source !== 'built-in',
    }))
}
