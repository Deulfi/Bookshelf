"""Inline SVG icons (24x24, stroke-based). Use ``{{ icon("name") }}`` in templates."""

from __future__ import annotations

from markupsafe import Markup

_PATHS: dict[str, str] = {
    "book": '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/>'
    '<path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "upload": '<path d="M12 15V3"/><path d="m7 8 5-5 5 5"/>'
    '<path d="M20 15v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-4"/>',
    "download": '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/>'
    '<path d="M20 15v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-4"/>',
    "trash": '<path d="M3 6h18"/><path d="M8 6V4h8v2"/>'
    '<path d="m19 6-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/>'
    '<path d="M21 12H9"/>',
    "settings": '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
    "users": '<circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0"/>'
    '<path d="M16 4a4 4 0 0 1 0 8"/><path d="M22 21a7 7 0 0 0-4-6.3"/>',
    "check": '<path d="m5 12 5 5L20 7"/>',
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
    "copy": '<rect x="9" y="9" width="12" height="12" rx="2"/>'
    '<path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "arrow-left": '<path d="M19 12H5"/><path d="m12 19-7-7 7-7"/>',
    "arrow-right": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    "sync": '<path d="M21 12a9 9 0 0 1-15.5 6.2L3 16"/><path d="M3 12a9 9 0 0 1 15.5-6.2L21 8"/>'
    '<path d="M21 3v5h-5M3 21v-5h5"/>',
    "key": '<circle cx="7.5" cy="15.5" r="4.5"/><path d="m10.7 12.3 9.8-9.8M17 6l3 3M14 9l2 2"/>',
    "tablet": '<rect x="5" y="2" width="14" height="20" rx="2"/><path d="M10 18h4"/>',
    "chart": '<path d="M3 3v18h18"/><path d="M8 17v-5M13 17V8M18 17v-9"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/>'
    '<path d="M3 10h18M8 3v4M16 3v4"/>',
    "catalog": '<path d="M3 5h6v14H3zM9 5h6v14H9z"/><path d="m15 6 4.5-1 3 13.5-4.5 1z"/>',
    "chevron-left": '<path d="m15 18-6-6 6-6"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    "sun": '<circle cx="12" cy="12" r="4"/>'
    '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2'
    'M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "maximize": '<path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3'
    'M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3"/>',
}


def icon(name: str, size: int = 20) -> Markup:
    return Markup(
        f'<svg class="icon" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{_PATHS[name]}</svg>'
    )
