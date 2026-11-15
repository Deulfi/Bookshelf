// Settings → Web reader: a small mockup of the reader bars, with the bar editor behind
// "Edit bars" (static/js/reader/layout-editor.js, also used inside the reader).
import { iconsFrom, mountLayoutEditor } from './reader/layout-editor.js'

const root = document.getElementById('layout-editor')

// The JSON box under "Advanced" shows the file; reload it so both views agree.
async function refreshJsonBox() {
    const box = document.getElementById('reader-config')
    if (!box) return
    const res = await fetch(location.pathname)
    const page = new DOMParser().parseFromString(await res.text(), 'text/html')
    box.value = page.getElementById('reader-config')?.value ?? box.value
}

mountLayoutEditor(root, {
    elementsUrl: root.dataset.elementsUrl,
    saveUrl: root.dataset.saveUrl,
    compact: true,
    icon: iconsFrom(document.getElementById('reader-icons')),
    onSaved: refreshJsonBox,
})
