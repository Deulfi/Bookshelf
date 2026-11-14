// Small helpers shared by bar elements; plugins get them as ctx.ui.

/** A bar button with an icon and an accessible label (visible with showLabel). */
function button(ctx, { icon, label, onClick, showLabel = false }) {
    const el = document.createElement('button')
    el.type = 'button'
    el.className = 'rb-btn'
    el.title = label
    el.setAttribute('aria-label', label)
    if (icon) el.append(ctx.icon(icon))
    if (showLabel) {
        const span = document.createElement('span')
        span.className = 'rb-btn-label'
        span.textContent = label
        el.append(span)
    }
    el.addEventListener('click', onClick)
    return el
}

/** A muted text element for counters and labels. */
function text(className = '') {
    const el = document.createElement('div')
    el.className = `rb-text ${className}`.trim()
    return el
}

const percent = fraction => `${Math.round((fraction ?? 0) * 100)}%`

/** A 0-1 slider with an optional value label. onSeek(fraction, done) runs while dragging
 * (done = false, at most once per frame) and when released (done = true).
 * disabled: the slider shows the value but does nothing when clicked or dragged. */
function slider({ label, onSeek, showValue = true, format = percent, disabled = false }) {
    const el = document.createElement('div')
    el.className = 'rb-progress'
    const input = document.createElement('input')
    input.type = 'range'
    input.min = '0'
    input.max = '1000'
    input.value = '0'
    input.setAttribute('aria-label', label)
    if (disabled) input.disabled = true
    el.append(input)
    const output = showValue ? text('rb-percent') : null
    if (output) el.append(output)
    let dragging = false
    let frame = 0
    input.addEventListener('input', () => {
        dragging = true
        const fraction = input.value / 1000
        if (output) output.textContent = format(fraction)
        cancelAnimationFrame(frame)
        frame = requestAnimationFrame(() => onSeek(fraction, false))
    })
    input.addEventListener('change', async () => {
        cancelAnimationFrame(frame)
        await onSeek(input.value / 1000, true)
        dragging = false
    })
    return {
        el,
        set(fraction) {
            if (dragging) return
            input.value = String(Math.round((fraction ?? 0) * 1000))
            if (output) output.textContent = format(fraction)
        },
    }
}

/** Replace {name} placeholders: fill('Page {page}', { page: 3 }). */
const fill = (template, values) =>
    String(template).replace(/\{(\w+)\}/g, (match, key) => values[key] ?? match)

export const ui = { button, text, slider, percent, fill }
