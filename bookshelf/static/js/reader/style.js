// Turns the preferences and the active theme into CSS for the book and the reader chrome,
// and into the paginator's layout attributes.
import { allControls, controlCSS } from './config.js'

const darkQuery = matchMedia('(prefers-color-scheme: dark)')

/** The theme object currently in effect ("auto" follows the system light/dark setting). */
export function activeTheme(config, prefs) {
    const themes = config.themes ?? []
    let id = prefs.get('theme', 'auto')
    if (id === 'auto') {
        const auto = prefs.control('theme')?.auto ?? {}
        id = darkQuery.matches ? auto.dark : auto.light
    }
    return themes.find(t => t.id === id)
        ?? themes.find(t => (t.scheme === 'dark') === darkQuery.matches)
        ?? themes[0]
        ?? { id: 'none', scheme: 'light', bg: '#ffffff', fg: '#000000' }
}

export const onSystemThemeChange = callback => darkQuery.addEventListener('change', callback)

const absolute = url => new URL(url, location.href).href
const quote = text => `"${String(text).replace(/["\\]/g, '\\$&')}"`

/** The font stack for the chosen font, plus any @font-face rule it needs. */
function fontCSS(config, prefs, fontsUrl) {
    const font = (config.settings?.fonts ?? []).find(f => f.id === prefs.get('fontFamily'))
    if (!font) return ''
    let face = ''
    let stack = font.stack ?? ''
    const src = font.file ? absolute(fontsUrl + encodeURIComponent(font.file))
        : font.url ? absolute(font.url) : null
    if (src) {
        const family = font.family ?? font.label ?? font.id
        face = `@font-face { font-family: ${quote(family)}; src: url(${quote(src)}); }\n`
        stack = `${quote(family)}${stack ? ', ' + stack : ''}`
    }
    if (!stack) return face
    return `${face}body, p, li, blockquote, dd, dt, td, th, h1, h2, h3, h4, h5, h6, div {
        font-family: ${stack} !important; }\n`
}

function themeCSS(theme) {
    const { bg, fg, link } = theme
    return `
    html { color-scheme: ${theme.scheme ?? 'light'}; --theme-bg-color: ${bg}; }
    html, body { background: ${bg} !important; color: ${fg} !important; }
    body :is(p, div, span, li, h1, h2, h3, h4, h5, h6, blockquote, dd, dt, td, th,
        em, i, strong, b, small, sup, sub, section, article, cite, q) { color: inherit !important; }
    ${link ? `a:any-link { color: ${link} !important; }` : ''}
    ${theme.css ?? ''}\n`
}

/** The full stylesheet injected into every section document. */
export function bookCSS(config, prefs, fontsUrl) {
    const parts = [themeCSS(activeTheme(config, prefs)), fontCSS(config, prefs, fontsUrl)]
    for (const control of allControls(config))
        parts.push(controlCSS(control, prefs.get(control.key), config))
    return parts.filter(Boolean).join('\n')
}

/** Paginator attributes derived from the layout preferences. */
export function rendererAttributes(prefs) {
    return {
        flow: prefs.get('flow', 'scrolled') === 'paginated' ? 'paginated' : 'scrolled',
        'max-inline-size': `${prefs.get('maxWidth', 720)}px`,
        gap: `${prefs.get('margin', 6)}%`,
        'max-column-count': String(prefs.get('columns', 2)),
    }
}

/** Theme the reader chrome (bars, panels) and the page around the book. */
export function applyChromeTheme(theme) {
    const root = document.documentElement
    const body = document.body // .reader-page declares the fallbacks, so override them there
    body.style.setProperty('--reader-bg', theme.bg)
    body.style.setProperty('--reader-fg', theme.fg)
    body.style.setProperty('--reader-accent', theme.accent ?? theme.link ?? theme.fg)
    root.style.colorScheme = theme.scheme ?? 'light'
    root.dataset.scheme = theme.scheme ?? 'light'
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme.bg)
}
