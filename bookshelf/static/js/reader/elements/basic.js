// Simple bar elements: space, exit, titles and the buttons that open panels or switch modes.

export const spacer = {
    id: 'spacer',
    label: 'Flexible space',
    repeatable: true,
    create() {
        const el = document.createElement('div')
        el.className = 'rb-spacer'
        return { el }
    },
}

export const exit = {
    id: 'exit',
    label: 'Back to the book',
    icon: 'arrow-left',
    create(ctx, o) {
        const el = document.createElement('a')
        el.className = 'rb-btn'
        el.href = o.href || ctx.book.exitUrl
        el.title = o.label || 'Back to the book'
        el.setAttribute('aria-label', el.title)
        el.append(ctx.icon(o.icon || 'arrow-left'))
        el.addEventListener('click', () => ctx.flush())
        return { el }
    },
}

export const title = {
    id: 'title',
    label: 'Book title',
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

function panelButton(id, label, icon, panel) {
    return {
        id,
        label,
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

export const toc = panelButton('toc', 'Contents', 'list', 'toc')
export const settings = panelButton('settings', 'Reader settings', 'settings', 'settings')

export const themeToggle = {
    id: 'theme-toggle',
    label: 'Light/dark switch',
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
