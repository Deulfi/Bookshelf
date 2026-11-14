// Simple bar elements: space, exit, titles and the buttons that open panels or switch modes.

export const spacer = {
    id: 'spacer',
    label: 'Flexible space',
    description: 'Takes up all free room, pushing the elements after it to the end of the bar',
    repeatable: true,
    create() {
        const el = document.createElement('div')
        el.className = 'rb-spacer'
        return { el }
    },
}

export const space = {
    id: 'space',
    label: 'Fixed space',
    description: 'A gap of a set width between two elements',
    repeatable: true,
    options: [{ key: 'width', type: 'number', label: 'Width (pixels)', default: 16 }],
    create(ctx, o) {
        const el = document.createElement('div')
        el.className = 'rb-space'
        el.style.width = `${Math.max(0, Number(o.width) || 0)}px`
        return { el }
    },
}

/** Where "close reader" leads: the page the reader was opened from (library, book page,
 *  search results) when it is one of ours, otherwise the book's page. */
function exitTarget(fallback) {
    try {
        const from = new URL(document.referrer)
        if (from.origin === location.origin && !from.pathname.startsWith('/read/')
            && !from.pathname.startsWith('/login')) return from.href
    } catch {
        // no referrer
    }
    return fallback
}

export const exit = {
    id: 'exit',
    label: 'Close reader',
    description: 'Leaves the reader for the page it was opened from (the book page otherwise)',
    icon: 'arrow-left',
    create(ctx, o) {
        const el = document.createElement('a')
        el.className = 'rb-btn'
        el.href = o.href || exitTarget(ctx.book.exitUrl)
        el.title = o.label || 'Close reader'
        el.setAttribute('aria-label', el.title)
        el.append(ctx.icon(o.icon || 'arrow-left'))
        el.addEventListener('click', () => ctx.flush())
        return { el }
    },
}

export const title = {
    id: 'title',
    label: 'Book title',
    description: 'The title of the book, optionally with its author',
    options: [{ key: 'showAuthor', type: 'toggle', label: 'Show the author', default: false }],
    create(ctx, o) {
        const el = ctx.ui.text('rb-title')
        el.textContent = o.showAuthor && ctx.book.author
            ? `${ctx.book.title} · ${ctx.book.author}` : ctx.book.title
        el.title = el.textContent
        return { el }
    },
}

export const chapterTitle = {
    id: 'chapter-title',
    label: 'Chapter title',
    description: 'The title of the current chapter',
    create(ctx, o) {
        const el = ctx.ui.text('rb-title')
        return {
            el,
            update(location) {
                el.textContent = location.tocItem?.label?.trim() || o.fallback || ''
                el.title = el.textContent
            },
        }
    },
}

const showLabel = { key: 'showLabel', type: 'toggle', label: 'Show the label', default: false }

function panelButton(id, label, icon, panel, description) {
    return {
        id,
        label,
        description,
        icon,
        options: [showLabel],
        create: (ctx, o) => ({
            el: ctx.ui.button(ctx, {
                icon: o.icon || icon, label: o.label || label, showLabel: o.showLabel,
                onClick: () => ctx.panels.toggle(panel),
            }),
        }),
    }
}

export const toc = panelButton('toc', 'Contents', 'list', 'toc',
    'Opens the table of contents to jump to a chapter')
export const settings = panelButton('settings', 'Reader settings', 'settings', 'settings',
    'Opens the panel for font, layout, theme and sync settings')
export const search = {
    id: 'search',
    label: 'Search',
    description: 'Opens a panel beside the text to search the book or the current chapter',
    icon: 'search',
    options: [showLabel],
    create: (ctx, o) => ({
        el: ctx.ui.button(ctx, {
            icon: o.icon || 'search', label: o.label || 'Search', showLabel: o.showLabel,
            onClick: () => ctx.panels.toggle('search'),
        }),
    }),
}

export const themeToggle = {
    id: 'theme-toggle',
    label: 'Light/dark switch',
    description: 'Switches between the light and the dark theme',
    icon: 'sun',
    options: [showLabel],
    create: (ctx, o) => ({
        el: ctx.ui.button(ctx, {
            icon: o.icon || 'sun', label: o.label || 'Light or dark theme', showLabel: o.showLabel,
            onClick: () => {
                const dark = ctx.theme().scheme === 'dark'
                const auto = ctx.prefs.control('theme')?.auto ?? {}
                const target = dark ? (o.light || auto.light) : (o.dark || auto.dark)
                if (target) ctx.prefs.set('theme', target)
            },
        }),
    }),
}

export const fullscreen = {
    id: 'fullscreen',
    label: 'Full screen',
    description: 'Shows the reader in full screen (left out where the browser has none)',
    icon: 'maximize',
    options: [showLabel],
    create(ctx, o) {
        if (!document.fullscreenEnabled) return null
        return {
            el: ctx.ui.button(ctx, {
                icon: o.icon || 'maximize', label: o.label || 'Full screen', showLabel: o.showLabel,
                onClick: () => document.fullscreenElement
                    ? document.exitFullscreen()
                    : document.documentElement.requestFullscreen().catch(() => {}),
            }),
        }
    },
}
