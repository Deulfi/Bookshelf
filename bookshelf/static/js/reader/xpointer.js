// KOReader XPointers, e.g. "/body/DocFragment[12]/body/div/p[3]/text().42".
//
// The KOReader sync record is shared with KOReader and Readest, which both store EPUB
// positions this way: DocFragment[n] is the n-th spine item (1-based), the rest is an element
// path inside that file's <body>. Like KOReader (crengine), an element gets an [index] only when
// its parent has several children with the same name, and whitespace-only text nodes do not count.

const PATTERN = /^\/body\/DocFragment\[(\d+)\](.*)$/
const TEXT = /^text\(\)(?:\[(\d+)\])?(?:\.(\d+))?$/
const ELEMENT = /^([^[\].]+)(?:\[(\d+)\])?(?:\.\d+)?$/
// Positions are written at block level: inline wrappers are not always kept by other readers.
const INLINE = new Set(['a', 'abbr', 'b', 'bdi', 'bdo', 'big', 'cite', 'code', 'del', 'dfn', 'em',
    'font', 'i', 'ins', 'kbd', 'mark', 'q', 'rp', 'rt', 'ruby', 's', 'samp', 'small', 'span',
    'strike', 'strong', 'sub', 'sup', 'time', 'tt', 'u', 'var', 'wbr', 'br', 'img'])

export const isXPointer = value => typeof value === 'string' && PATTERN.test(value)

/** { index (0-based spine item), path } or null. */
export function parseXPointer(value) {
    const match = typeof value === 'string' ? PATTERN.exec(value) : null
    if (!match) return null
    return { index: Number(match[1]) - 1, path: match[2] }
}

const name = el => el.localName.toLowerCase()
const meaningfulText = node => node.nodeType === 3 && node.nodeValue.trim() !== ''

/** The element (or a collapsed Range for a text position) an XPointer path points to. A path
 *  that stops matching (the other reader built a slightly different tree) resolves to the
 *  deepest element that still matched. */
export function resolveXPointer(doc, path) {
    let node = doc.documentElement
    for (const segment of path.split('/').filter(Boolean)) {
        const text = TEXT.exec(segment)
        if (text) {
            const nodes = [...node.childNodes].filter(meaningfulText)
            const target = nodes[(Number(text[1]) || 1) - 1]
            if (!target) return node
            const range = doc.createRange()
            range.setStart(target, Math.min(Number(text[2]) || 0, target.length))
            range.collapse(true)
            return range
        }
        const element = ELEMENT.exec(segment)
        if (!element) return node
        const wanted = element[1].toLowerCase()
        const matches = [...node.children].filter(child => name(child) === wanted)
        const next = matches[(Number(element[2]) || 1) - 1]
        if (!next) return node
        node = next
    }
    return node
}

/** XPointer for the start of a range in spine item `index` (its document is range's). */
export function toXPointer(index, range) {
    let node = range?.startContainer
    if (!node) return null
    if (node.nodeType === 1) node = node.childNodes[range.startOffset] ?? node
    if (node.nodeType !== 1) node = node.parentElement
    while (node && INLINE.has(name(node)) && node.parentElement) node = node.parentElement
    const doc = node?.ownerDocument
    if (!doc?.body) return null
    const parts = []
    for (; node && node !== doc.body; node = node.parentElement) {
        const parent = node.parentElement
        if (!parent) return null // outside <body>
        const same = [...parent.children].filter(child => name(child) === name(node))
        parts.unshift(same.length > 1 ? `${name(node)}[${same.indexOf(node) + 1}]` : name(node))
    }
    return `/body/DocFragment[${index + 1}]/body${parts.map(p => '/' + p).join('')}`
}
