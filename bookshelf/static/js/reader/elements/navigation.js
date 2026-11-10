// Previous/next chapter and page buttons.

function nav({ id, label, icon, labelByDefault, action, available }) {
    return {
        id,
        label,
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
    action: engine => engine.prevSection(), available: engine => engine.hasSection(-1),
})

export const nextChapter = nav({
    id: 'next-chapter', label: 'Next chapter', icon: 'chevron-right', labelByDefault: true,
    action: engine => engine.nextSection(), available: engine => engine.hasSection(1),
})

export const prevPage = nav({
    id: 'prev-page', label: 'Previous page', icon: 'arrow-left', labelByDefault: false,
    action: engine => engine.prev(),
})

export const nextPage = nav({
    id: 'next-page', label: 'Next page', icon: 'arrow-right', labelByDefault: false,
    action: engine => engine.next(),
})
