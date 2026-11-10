// Helpers for the merged reader configuration (built on the server, see
// services/reader_config.py). The page never fails on a bad config: problems are logged and
// the affected item is skipped or falls back to its default.

export const warn = (...args) => console.warn('[reader]', ...args)

/** Every settings control, flattened from all sections. */
export function allControls(config) {
    return (config.settings?.sections ?? []).flatMap(section => section.controls ?? [])
}

/** Options of a select/segmented control as [{value, label, css?}]. "@fonts" means the fonts list. */
export function controlOptions(control, config) {
    let options = control.options
    if (options === '@fonts') options = (config.settings?.fonts ?? [])
        .map(font => ({ value: font.id, label: font.label ?? font.id }))
    if (!Array.isArray(options)) return []
    return options.map(option => typeof option === 'object' && option !== null
        ? { ...option, label: option.label ?? String(option.value) }
        : { value: option, label: String(option) })
}

const sameValue = (a, b) => String(a) === String(b)

/** Coerce a stored value into something valid for the control, or return its default. */
export function normalizeValue(control, value, config) {
    const fallback = control.default
    if (value === undefined || value === null) return fallback
    switch (control.type) {
        case 'range': {
            const number = Number(value)
            if (!Number.isFinite(number)) return fallback
            const min = Number(control.min ?? -Infinity)
            const max = Number(control.max ?? Infinity)
            return Math.min(max, Math.max(min, number))
        }
        case 'toggle':
            return Boolean(value)
        case 'select':
        case 'segmented': {
            const match = controlOptions(control, config).find(o => sameValue(o.value, value))
            return match ? match.value : fallback
        }
        case 'themes': {
            if (value === 'auto' && control.auto) return value
            return (config.themes ?? []).some(t => t.id === value) ? value : fallback
        }
        case 'color':
            return /^#[0-9a-f]{3,8}$/i.test(String(value)) ? value : fallback
        default:
            return value
    }
}

/** Default value of every control, keyed by the control's key. */
export function controlDefaults(config) {
    const defaults = {}
    for (const control of allControls(config)) defaults[control.key] = control.default
    return defaults
}

/** The CSS a control contributes for its current value (the generic extension mechanism). */
export function controlCSS(control, value, config) {
    const fill = template => typeof template === 'string'
        ? template.replaceAll('{value}', String(value)) : ''
    switch (control.type) {
        case 'toggle':
            return value ? fill(control.css) : fill(control.cssOff)
        case 'select':
        case 'segmented': {
            const option = controlOptions(control, config).find(o => sameValue(o.value, value))
            return option?.css ? fill(option.css) : fill(control.css)
        }
        default:
            return fill(control.css)
    }
}

/** Normalize a bar layout list into [{id, ...options}]. */
export function layoutItems(list) {
    if (!Array.isArray(list)) return []
    return list.flatMap(item => {
        if (typeof item === 'string') return [{ id: item }]
        if (item && typeof item === 'object' && typeof item.id === 'string') return [item]
        warn('ignoring layout entry', item)
        return []
    })
}
