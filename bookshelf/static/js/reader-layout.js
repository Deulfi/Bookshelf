// Settings → Web reader: a small mockup of the reader bars, with the bar editor behind
// "Edit bars" (static/js/reader/layout-editor.js, also used inside the reader).
import { iconsFrom, mountLayoutEditor } from './reader/layout-editor.js'

const root = document.getElementById('layout-editor')
const serverRoot = document.getElementById('server-layout-editor') // admins only

// The JSON box under "Advanced" shows the file; reload it so both views agree.
async function refreshJsonBox(id = 'reader-config') {
    const box = document.getElementById(id)
    if (!box) return
    const res = await fetch(location.pathname)
    const page = new DOMParser().parseFromString(await res.text(), 'text/html')
    box.value = page.getElementById(id)?.value ?? box.value
}

mountLayoutEditor(root, {
    elementsUrl: root.dataset.elementsUrl,
    saveUrl: root.dataset.saveUrl,
    compact: true,
    icon: iconsFrom(document.getElementById('reader-icons')),
    onSaved: refreshJsonBox,
})

if (serverRoot) {
    mountLayoutEditor(serverRoot, {
        elementsUrl: serverRoot.dataset.elementsUrl,
        saveUrl: serverRoot.dataset.saveUrl,
        compact: true,
        icon: iconsFrom(document.getElementById('reader-icons')),
        onSaved: () => refreshJsonBox('server-config'),
    })
}
