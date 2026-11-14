// "Go back" and "go forward": undo and redo of reading positions, like Readest.
import { historyFor } from '../history.js'

function historyNav({ id, label, description, icon, action, available }) {
    return {
        id,
        label,
        description,
        icon,
        options: [{ key: 'showLabel', type: 'toggle', label: 'Show the label', default: false }],
        create(ctx, o) {
            const history = historyFor(ctx.engine)
            const el = ctx.ui.button(ctx, {
                icon, label, showLabel: o.showLabel,
                onClick: () => action(history),
            })
            el.classList.add('rb-nav')
            const refresh = () => { el.disabled = !available(history) }
            history.addEventListener('change', refresh)
            refresh()
            return { el }
        },
    }
}

export const goBack = historyNav({
    id: 'go-back', label: 'Go back', icon: 'undo',
    description: 'Returns to where you were before the last jump (contents, search, link, chapter button)',
    action: history => history.goBack(), available: history => history.canGoBack,
})

export const goForward = historyNav({
    id: 'go-forward', label: 'Go forward', icon: 'redo',
    description: 'Redoes a jump you went back from',
    action: history => history.goForward(), available: history => history.canGoForward,
})
