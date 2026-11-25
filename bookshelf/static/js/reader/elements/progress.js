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

// A compact percent button that opens the book progress slider in a small popover above the bar.
// On a narrow portrait phone an inline slider is cramped between the chapter buttons; this keeps
// the bar tidy and gives the slider the whole width only when you actually want to seek — the way
// Readest does it. Built for the bottom bar (the popover opens upward); in the top bar it opens
// downward (CSS). The popover holds the bars open while it is up, so the auto-hide cannot snatch
// the slider away mid-drag.
export const progressPopover = {
    id: 'progress-popover',
    label: 'Progress button',
    description: 'A percent button that opens the progress slider in a popover (good on phones)',
    options: [
        { key: 'showChapters', type: 'toggle', label: 'Show chapters (small lines)', default: false },
    ],
    create(ctx, o) {
        const wrap = document.createElement('div')
        wrap.className = 'rb-pop-wrap'

        const btn = document.createElement('button')
        btn.type = 'button'
        btn.className = 'rb-btn rb-pop-btn'
        btn.setAttribute('aria-label', 'Reading position')
        btn.setAttribute('aria-expanded', 'false')
        const value = ctx.ui.text('rb-percent')
        value.textContent = ctx.ui.percent(0)
        btn.append(value)

        const pop = document.createElement('div')
        pop.className = 'rb-pop'
        pop.hidden = true
        const slider = ctx.ui.slider({
            label: 'Position in book',
            onSeek: (fraction, done) => done && ctx.engine.goToFraction(fraction),
        })
        if (o.showChapters) {
            const input = slider.el.querySelector('input')
            const track = document.createElement('span')
            track.className = 'rb-track'
            input.replaceWith(track)
            track.append(input)
            chapterTicks(ctx, track, true)
        }
        pop.append(slider.el)
        wrap.append(btn, pop)

        let onOutside = null
        const close = () => {
            if (pop.hidden) return
            pop.hidden = true
            btn.setAttribute('aria-expanded', 'false')
            if (onOutside) {
                document.removeEventListener('pointerdown', onOutside, true)
                onOutside = null
            }
            ctx.bars?.show() // resume the normal auto-hide
        }
        const open = () => {
            if (!pop.hidden) return
            pop.hidden = false
            btn.setAttribute('aria-expanded', 'true')
            ctx.bars?.show(false) // keep the bars up while the slider is out
            onOutside = event => {
                if (!wrap.contains(event.target)) close()
            }
            document.addEventListener('pointerdown', onOutside, true)
        }
        btn.addEventListener('click', () => (pop.hidden ? open() : close()))
        pop.addEventListener('keydown', event => {
            if (event.key === 'Escape') {
                close()
                btn.focus()
            }
        })
        // If the bars leave for any other reason (a tap in the page, Escape, a panel), the
        // popover goes with them instead of floating over the text.
        const observer = new MutationObserver(() => {
            if (!document.body.classList.contains('bars-visible')) close()
        })
        observer.observe(document.body, { attributes: true, attributeFilter: ['class'] })

        return {
            el: wrap,
            update(location) {
                value.textContent = ctx.ui.percent(location.fraction)
                slider.set(location.fraction)
            },
            destroy() {
                close()
                observer.disconnect()
            },
        }
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

const FRONT_MATTER = /^(?:cover|(?:half[- ]|full[- ])?title(?: page)?|copyright|table of contents|contents|dedication|epigraph|acknowledge?ments?|about (?:the|this) (?:author|book)|also by|praise|newsletter|maps?|characters|dramatis personae|front matter|colophon|credits)\b/i

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
        {
            key: 'skipFront', type: 'toggle', default: false,
            label: 'Skip front matter (cover, contents, copyright… before chapter 1)',
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
        // Leading entries that are front matter by name are not counted (the book page's
        // "Chapter x of y" still counts every entry).
        let skip = 0
        if (useToc && o.skipFront) {
            while (skip < flat.length - 1 && FRONT_MATTER.test((flat[skip].label ?? '').trim())) skip++
        }
        return {
            el,
            update(location) {
                let current = location.sectionIndex + 1
                let total = location.sectionCount
                if (useToc) {
                    const index = byHref.get(location.tocItem?.href)
                    current = index === undefined || index < skip ? '–' : index + 1 - skip
                    total = flat.length - skip
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
