// Position elements: book and chapter progress, chapter and page counters.

export const progressBar = {
    id: 'progress-bar',
    label: 'Book progress bar',
    options: [{ key: 'showPercent', type: 'toggle', label: 'Show percent', default: true }],
    create(ctx, o) {
        const slider = ctx.ui.slider({
            label: 'Position in book',
            showValue: o.showPercent,
            onSeek: (fraction, done) => done && ctx.engine.goToFraction(fraction),
        })
        return { el: slider.el, update: location => slider.set(location.fraction) }
    },
}

export const progressText = {
    id: 'progress-text',
    label: 'Book progress (text)',
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
