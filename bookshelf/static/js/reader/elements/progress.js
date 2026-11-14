// Position elements: book and chapter progress, chapter and page counters.

export const progressBar = {
    id: 'progress-bar',
    label: 'Book progress bar',
    description: 'A slider for your position in the whole book',
    options: [
        { key: 'showPercent', type: 'toggle', label: 'Show percent', default: true },
        { key: 'readOnly', type: 'toggle', label: 'Read only (clicking does nothing)', default: false },
        { key: 'showChapters', type: 'toggle', label: 'Show chapters (small lines)', default: false },
    ],
    create(ctx, o) {
        const slider = ctx.ui.slider({
            label: 'Position in book',
            showValue: o.showPercent,
            disabled: o.readOnly,
            onSeek: (fraction, done) => done && ctx.engine.goToFraction(fraction),
        })
        if (o.showChapters) {
            const input = slider.el.querySelector('input')
            const track = document.createElement('span')
            track.className = 'rb-track'
            input.replaceWith(track)
            track.append(input)
            chapterTicks(ctx, track, !o.readOnly)
        }
        return { el: slider.el, update: location => slider.set(location.fraction) }
    },
}

export const progressText = {
    id: 'progress-text',
    label: 'Book progress (text)',
    description: 'Your position in the book as a percentage or section number',
    options: [{
        key: 'format', type: 'select', label: 'Show', default: 'percent',
        options: [
            { value: 'percent', label: 'Percent of the book' },
            { value: 'section', label: 'Section x / y' },
            { value: 'both', label: 'Both' },
        ],
    }],
    create(ctx, o) {
        const el = ctx.ui.text('rb-percent')
        return {
            el,
            update(location) {
                const parts = []
                if (o.format !== 'section') parts.push(ctx.ui.percent(location.fraction))
                if (o.format !== 'percent')
                    parts.push(`${location.sectionIndex + 1} / ${location.sectionCount}`)
                el.textContent = parts.join(' · ')
            },
        }
    },
}

// A slider over the current chapter only, so a slip of the finger moves a few paragraphs
// instead of hundreds of chapters.
export const chapterProgress = {
    id: 'chapter-progress',
    label: 'Chapter progress bar',
    description: 'A slider for your position in the current chapter',
    options: [{ key: 'showPercent', type: 'toggle', label: 'Show percent', default: true }],
    create(ctx, o) {
        const slider = ctx.ui.slider({
            label: 'Position in chapter',
            showValue: o.showPercent,
            onSeek: fraction => ctx.engine.goToSectionFraction(fraction),
        })
        return { el: slider.el, update: location => slider.set(location.sectionFraction) }
    },
}

// "Chapter 812 / 2431". Counts table-of-contents entries when the book has them (web novels
// usually do), otherwise the sections of the book file.
export const chapterCounter = {
    id: 'chapter-counter',
    label: 'Chapter counter',
    description: 'Which chapter you are in, like “Ch. 7/39”',
    options: [
        {
            key: 'source', type: 'select', label: 'Count', default: 'toc',
            options: [
                { value: 'toc', label: 'Table of contents entries' },
                { value: 'section', label: 'Sections of the book file' },
            ],
        },
        { key: 'format', type: 'text', label: 'Text', default: 'Chapter {current} / {total}' },
    ],
    create(ctx, o) {
        const el = ctx.ui.text('rb-counter')
        const flat = []
        const walk = items => {
            for (const item of items ?? []) {
                flat.push(item)
                walk(item.subitems)
            }
        }
        walk(ctx.engine.toc)
        const byHref = new Map(flat.map((item, i) => [item.href, i]))
        const useToc = o.source !== 'section' && flat.length > 0
        return {
            el,
            update(location) {
                let current = location.sectionIndex + 1
                let total = location.sectionCount
                if (useToc) {
                    const index = byHref.get(location.tocItem?.href)
                    current = index === undefined ? '–' : index + 1
                    total = flat.length
                }
                el.textContent = ctx.ui.fill(o.format, { current, total })
            },
        }
    },
}

// "Page 3 / 12" within the current chapter: real pages in page mode, screens in scroll mode.
export const pageCounter = {
    id: 'page-counter',
    label: 'Page counter (chapter)',
    description: 'Page or screen within the current chapter',
    options: [{ key: 'format', type: 'text', label: 'Text', default: 'Page {page} / {pages}' }],
    create(ctx, o) {
        const el = ctx.ui.text('rb-counter')
        return {
            el,
            update(location) {
                el.textContent = ctx.ui.fill(o.format, { page: location.page, pages: location.pages })
            },
        }
    },
}

/** Thin tick marks above the book progress bar, one per table-of-contents entry. Resting the
 *  pointer on a tick for HOVER_MS shows its chapter title; clicking it opens the chapter
 *  (unless the bar is read only). */
const HOVER_MS = 400

async function chapterTicks(ctx, track, clickable) {
    const chapters = await ctx.engine.tocFractions()
    if (!chapters.length) return
    const tip = Object.assign(document.createElement('span'), { className: 'rb-tick-tip' })
    tip.hidden = true
    let timer = null
    const hide = () => {
        clearTimeout(timer)
        tip.hidden = true
    }
    const show = (tick, label) => {
        tip.textContent = label || 'Chapter'
        tip.hidden = false
        // centred on the tick, but kept inside the bar
        const width = track.clientWidth
        const half = tip.offsetWidth / 2
        tip.style.left = `${Math.min(width - half, Math.max(half, tick.offsetLeft))}px`
    }
    for (const { fraction, label, href } of chapters) {
        const tick = document.createElement(clickable ? 'button' : 'span')
        tick.className = 'rb-tick'
        // where the slider's knob centre is at this fraction: it runs from half a knob in from
        // the left to half a knob in from the right, not across the full width
        tick.style.left = `calc(var(--rb-thumb) / 2 + ${fraction} * (100% - var(--rb-thumb)))`
        tick.addEventListener('pointerenter', () => {
            clearTimeout(timer)
            timer = setTimeout(() => show(tick, label), HOVER_MS)
        })
        tick.addEventListener('pointerleave', hide)
        if (clickable) {
            tick.type = 'button'
            tick.setAttribute('aria-label', `Go to ${label || 'chapter'}`)
            tick.tabIndex = -1 // the slider and the contents panel cover keyboard use
            tick.addEventListener('click', () => {
                hide()
                ctx.engine.goTo(href)
            })
        }
        track.append(tick)
    }
    track.append(tip)
}
