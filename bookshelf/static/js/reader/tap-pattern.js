// Page mode tap areas: a text grid (see services/tap_patterns.py) stretched over the screen.
// Every character is an action: L previous page, R next page, T show or hide the bars. A space
// shows the bars too (that is how the bars are reached in page mode). Other letters are
// reserved for future actions (add them to ACTIONS in bars.js).

export const DEFAULT_PATTERN = 'Thirds'

export class TapMap {
    #rows

    /** rows: equal-width strings. */
    constructor(rows) {
        this.#rows = rows?.length ? rows : ['L R']
    }

    get rows() { return this.#rows }

    /** The action letter at a screen position (x and y as fractions 0-1); ' ' is empty space. */
    actionAt(x, y) {
        const rows = this.#rows
        const col = Math.min(rows[0].length - 1, Math.max(0, Math.floor(x * rows[0].length)))
        const row = Math.min(rows.length - 1, Math.max(0, Math.floor(y * rows.length)))
        return rows[row][col]
    }
}

export function findPattern(config, id) {
    const patterns = config.tapPatterns ?? []
    return patterns.find(p => p.id === id) ?? patterns.find(p => p.id === DEFAULT_PATTERN)
        ?? patterns[0]
}

const WORDS = { L: 'Previous', R: 'Next', T: 'Bars' }
const SVG = 'http://www.w3.org/2000/svg'

/** Cells with the same letter, merged into as few rectangles as possible (greedy: grow right,
 *  then down). Returns [{letter, row, col, height, width}] in grid units. */
export function mergeAreas(rows) {
    const used = rows.map(row => Array.from(row, () => false))
    const areas = []
    for (let r = 0; r < rows.length; r++) {
        for (let c = 0; c < rows[r].length; c++) {
            if (used[r][c]) continue
            const letter = rows[r][c]
            let width = 1
            while (c + width < rows[r].length && !used[r][c + width] && rows[r][c + width] === letter) width++
            let height = 1
            const rowFits = y => {
                for (let x = c; x < c + width; x++) if (used[y][x] || rows[y][x] !== letter) return false
                return true
            }
            while (r + height < rows.length && rowFits(r + height)) height++
            for (let y = r; y < r + height; y++) for (let x = c; x < c + width; x++) used[y][x] = true
            areas.push({ letter, row: r, col: c, height, width })
        }
    }
    return areas
}

/** Connected groups of equal letters (sides touching), each as a list of [row, col]. */
export function connectedAreas(rows) {
    const seen = rows.map(row => Array.from(row, () => false))
    const areas = []
    for (let r = 0; r < rows.length; r++) {
        for (let c = 0; c < rows[r].length; c++) {
            if (seen[r][c]) continue
            const letter = rows[r][c]
            const cells = []
            const stack = [[r, c]]
            seen[r][c] = true
            while (stack.length) {
                const [y, x] = stack.pop()
                cells.push([y, x])
                for (const [dy, dx] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
                    const ny = y + dy
                    const nx = x + dx
                    if (ny < 0 || nx < 0 || ny >= rows.length || nx >= rows[0].length) continue
                    if (seen[ny][nx] || rows[ny][nx] !== letter) continue
                    seen[ny][nx] = true
                    stack.push([ny, nx])
                }
            }
            areas.push({ letter, cells })
        }
    }
    return areas
}

/** Draw a pattern's areas into the preview element. Cells of one letter that touch are one
 *  shape (an L stays one piece), outlined as a whole, with one label in its biggest part. */
export function drawPreview(el, map) {
    const rows = map.rows
    const height = rows.length
    const width = rows[0].length
    const svg = document.createElementNS(SVG, 'svg')
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`)
    svg.setAttribute('preserveAspectRatio', 'none')
    const labels = []
    for (const { letter, cells } of connectedAreas(rows)) {
        if (letter === ' ') continue
        const known = WORDS[letter] ? letter : 'other'
        const fill = document.createElementNS(SVG, 'path')
        fill.setAttribute('class', `tp-${known}`)
        fill.setAttribute('d', cells.map(([y, x]) => `M${x} ${y}h1v1h-1z`).join(''))
        svg.append(fill)
        // the outline: only sides that touch a different letter or the screen edge
        const same = (y, x) => rows[y]?.[x] === letter
        let edge = ''
        for (const [y, x] of cells) {
            if (!same(y - 1, x)) edge += `M${x} ${y}h1`
            if (!same(y + 1, x)) edge += `M${x} ${y + 1}h1`
            if (!same(y, x - 1)) edge += `M${x} ${y}v1`
            if (!same(y, x + 1)) edge += `M${x + 1} ${y}v1`
        }
        const outline = document.createElementNS(SVG, 'path')
        outline.setAttribute('class', 'tp-edge')
        outline.setAttribute('d', edge)
        svg.append(outline)

        // label in the biggest rectangle of the shape
        const mask = rows.map(row => ' '.repeat(row.length).split(''))
        for (const [y, x] of cells) mask[y][x] = letter
        const biggest = mergeAreas(mask.map(row => row.join('')))
            .filter(a => a.letter === letter)
            .reduce((a, b) => (b.width * b.height > a.width * a.height ? b : a))
        const label = document.createElement('span')
        label.className = 'tp-label'
        label.style.left = `${((biggest.col + biggest.width / 2) / width) * 100}%`
        label.style.top = `${((biggest.row + biggest.height / 2) / height) * 100}%`
        const big = cells.length / (width * height) >= 0.02
        label.textContent = WORDS[letter] && big ? WORDS[letter] : letter
        labels.push(label)
    }
    el.replaceChildren(svg, ...labels)
}
