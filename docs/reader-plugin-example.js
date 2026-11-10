// Example bar element plugin for the Bookshelf web reader: a clock with the reading time left
// in the current chapter.
//
// Install: copy this file to <data dir>/reader/plugins/ (for Docker: /data/reader/plugins/).
// It then shows up under "Available elements" in Settings → Web reader, where you can drag it
// into the top or bottom bar. Every *.js file in that folder is loaded for all users.
//
// A plugin module exports one element definition (or an array of them) as its default export:
//
//   id          unique name, used in layout.top / layout.bottom
//   label       name shown in the bar editor
//   icon        optional icon name for the editor (see bookshelf/icons.py)
//   repeatable  true if it may appear more than once
//   options     settings the editor offers for it: { key, type, label, default, options }
//               type is 'toggle', 'select' (with options: [{ value, label }]), 'text' or 'number'
//   css         optional CSS added to the reader page
//   create(ctx, options) → { el, update(location), destroy() } or null to render nothing
//
// ctx gives access to the reader:
//   ctx.book      { id, title, author, exitUrl }
//   ctx.engine    navigation: next(), prev(), nextSection(), prevSection(), goTo(href),
//                 goToFraction(f), goToSectionFraction(f), hasSection(±1), toc, location
//   ctx.prefs     the reader settings: get(key), set(key, value)
//   ctx.panels    toggle('toc' | 'settings')
//   ctx.icon(name), ctx.theme()
//   ctx.ui        helpers: button(ctx, { icon, label, onClick, showLabel }), text(className),
//                 slider({ label, onSeek, showValue }), percent(f), fill(template, values)
//
// update(location) runs after every move. location has:
//   fraction (book, 0–1), sectionIndex, sectionCount, sectionFraction (0–1 in the chapter),
//   page, pages (in the chapter; screens in scroll mode), tocItem { label, href },
//   timeInSection, timeInBook (estimated minutes left), atStart, atEnd, cfi

export default {
    id: 'clock',
    label: 'Clock and time left in chapter',
    options: [
        { key: 'showTimeLeft', type: 'toggle', label: 'Show minutes left in the chapter', default: true },
    ],
    css: '.rb-clock { font-variant-numeric: tabular-nums; white-space: nowrap; padding: 0 6px; }',

    create(ctx, options) {
        const el = ctx.ui.text('rb-clock')
        let minutesLeft = null
        const render = () => {
            const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
            el.textContent = options.showTimeLeft && minutesLeft !== null
                ? `${time} · ${minutesLeft} min left`
                : time
        }
        const timer = setInterval(render, 30 * 1000)
        render()
        return {
            el,
            update(location) {
                minutesLeft = location.timeInSection == null
                    ? null : Math.max(1, Math.round(location.timeInSection))
                render()
            },
            destroy() {
                clearInterval(timer)
            },
        }
    },
}
