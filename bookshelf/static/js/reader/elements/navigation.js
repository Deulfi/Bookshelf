// Previous/next chapter and page buttons.

function nav({ id, label, description, icon, labelByDefault, action, available }) {
    return {
        id,
        label,
        description,
        icon,
        options: [{ key: 'showLabel', type: 'toggle', label: 'Show the label', default: labelByDefault }],
        create(ctx, o) {
            const el = ctx.ui.button(ctx, {
                icon: o.icon || icon, label: o.label || label, showLabel: o.showLabel,
                onClick: () => action(ctx.engine),
            })
            el.classList.add('rb-nav')
            return {
                el,
                update() {
                    el.disabled = available ? !available(ctx.engine) : false
                },
            }
        },
    }
}

export const prevChapter = nav({
    id: 'prev-chapter', label: 'Previous chapter', icon: 'chevron-left', labelByDefault: true,
    description: 'Goes to the start of the previous chapter',
    action: engine => engine.prevSection(), available: engine => engine.hasSection(-1),
})

export const nextChapter = nav({
    id: 'next-chapter', label: 'Next chapter', icon: 'chevron-right', labelByDefault: true,
    description: 'Goes to the start of the next chapter',
    action: engine => engine.nextSection(), available: engine => engine.hasSection(1),
})

export const prevPage = nav({
    id: 'prev-page', label: 'Previous page', icon: 'arrow-left', labelByDefault: false,
    description: 'Turns back one page (one screen up in scroll mode)',
    action: engine => engine.prev(),
})

export const nextPage = nav({
    id: 'next-page', label: 'Next page', icon: 'arrow-right', labelByDefault: false,
    description: 'Turns one page forward (one screen down in scroll mode)',
    action: engine => engine.next(),
})
