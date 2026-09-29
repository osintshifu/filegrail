"""The icons of the HTML report: one sprite, referenced by id.

Octicons (MIT), drawn once after `<body>` and used with `<use href="#i-…">`,
so a page with six hundred copy buttons carries each shape once.
"""

# ruff: noqa: E501

from __future__ import annotations

ICONS = """<svg hidden aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
<symbol id="i-copy" viewBox="0 0 16 16"><path d="M0 6.75C0 5.784.784 5 1.75 5h1.5a.75.75 0 0 1 0 1.5h-1.5a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-1.5a.75.75 0 0 1 1.5 0v1.5A1.75 1.75 0 0 1 9.25 16h-7.5A1.75 1.75 0 0 1 0 14.25Z"/><path d="M5 1.75C5 .784 5.784 0 6.75 0h7.5C15.216 0 16 .784 16 1.75v7.5A1.75 1.75 0 0 1 14.25 11h-7.5A1.75 1.75 0 0 1 5 9.25Zm1.75-.25a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-7.5a.25.25 0 0 0-.25-.25Z"/></symbol>
<symbol id="i-check" viewBox="0 0 16 16"><path d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.751.751 0 0 1 .018-1.042.751.751 0 0 1 1.042-.018L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0Z"/></symbol>
<symbol id="i-x" viewBox="0 0 16 16"><path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z"/></symbol>
<symbol id="i-print" viewBox="0 0 16 16"><path d="M4 1.75C4 .784 4.784 0 5.75 0h4.5C11.216 0 12 .784 12 1.75V4h1.25A2.75 2.75 0 0 1 16 6.75v4.5A1.75 1.75 0 0 1 14.25 13H12v1.25A1.75 1.75 0 0 1 10.25 16h-4.5A1.75 1.75 0 0 1 4 14.25V13H1.75A1.75 1.75 0 0 1 0 11.25v-4.5A2.75 2.75 0 0 1 2.75 4H4Zm1.5-.25V4h5V1.5ZM2.75 5.5c-.69 0-1.25.56-1.25 1.25v4.5c0 .138.112.25.25.25H4v-1.75C4 9.336 4.336 9 4.75 9h6.5c.414 0 .75.336.75.75v1.75h2.25a.25.25 0 0 0 .25-.25v-4.5c0-.69-.56-1.25-1.25-1.25Zm2.75 5v4h5v-4Z"/></symbol>
<symbol id="i-search" viewBox="0 0 16 16"><path d="M10.68 11.74a6 6 0 0 1-7.922-8.982 6 6 0 0 1 8.982 7.922l3.04 3.04a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215ZM11.5 7a4.499 4.499 0 1 0-8.997 0A4.499 4.499 0 0 0 11.5 7Z"/></symbol>
<symbol id="i-chevron" viewBox="0 0 16 16"><path d="M6.22 3.22a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L9.94 8 6.22 4.28a.75.75 0 0 1 0-1.06Z"/></symbol>
<symbol id="i-arrow" viewBox="0 0 16 16"><path d="M8.22 2.97a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L10.94 8.75H1.75a.75.75 0 0 1 0-1.5h9.19L8.22 4.03a.75.75 0 0 1 0-1.06Z"/></symbol>
<symbol id="i-up" viewBox="0 0 16 16"><path d="M3.22 9.78a.75.75 0 0 1 0-1.06l4.25-4.25a.75.75 0 0 1 1.06 0l4.25 4.25a.751.751 0 0 1-.018 1.042.751.751 0 0 1-1.042.018L8 6.06 4.28 9.78a.75.75 0 0 1-1.06 0Z"/></symbol>
<symbol id="i-focus" viewBox="0 0 16 16"><path d="M8 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z"/><path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM1.5 8a6.5 6.5 0 1 0 13 0 6.5 6.5 0 0 0-13 0Z"/></symbol>
<symbol id="i-refresh" viewBox="0 0 16 16"><path d="M1.705 8.005a.75.75 0 0 1 .834.656 5.5 5.5 0 0 0 9.592 2.97l-1.204-1.204a.25.25 0 0 1 .177-.427h3.646a.25.25 0 0 1 .25.25v3.646a.25.25 0 0 1-.427.177l-1.38-1.38A7.002 7.002 0 0 1 1.05 8.84a.75.75 0 0 1 .656-.834ZM8 2.5a5.487 5.487 0 0 0-4.131 1.869l1.204 1.204A.25.25 0 0 1 4.896 6H1.25A.25.25 0 0 1 1 5.75V2.104a.25.25 0 0 1 .427-.177l1.38 1.38A7.002 7.002 0 0 1 14.95 7.16a.75.75 0 0 1-1.49.178A5.5 5.5 0 0 0 8 2.5Z"/></symbol>
<symbol id="i-expand" viewBox="0 0 16 16"><path d="M1 6V2.5A1.5 1.5 0 0 1 2.5 1H6v1.5H2.5V6H1Zm9-5h3.5A1.5 1.5 0 0 1 15 2.5V6h-1.5V2.5H10V1ZM1 10h1.5v3.5H6V15H2.5A1.5 1.5 0 0 1 1 13.5V10Zm12.5 0H15v3.5a1.5 1.5 0 0 1-1.5 1.5H10v-1.5h3.5V10Z"/></symbol>
<symbol id="i-collapse" viewBox="0 0 16 16"><path d="M6 1v3.5A1.5 1.5 0 0 1 4.5 6H1V4.5h3.5V1H6Zm4 0h1.5v3.5H15V6h-3.5A1.5 1.5 0 0 1 10 4.5V1ZM1 10h3.5A1.5 1.5 0 0 1 6 11.5V15H4.5v-3.5H1V10Zm9 1.5a1.5 1.5 0 0 1 1.5-1.5H15v1.5h-3.5V15H10v-3.5Z"/></symbol>
</svg>"""


#: The mark, drawn in the page as an outline holding a wash of its own colour - the
#: cup reads as a vessel rather than a blot. It does not follow the accent: the accent is
#: free to change, while the mark stays the brand green the packaged assets show.
#: The viewBox is padded by 26 units on every side so the stroke is not clipped.
MARK_PATH = (
    "M24,48 A48,48 0 0 1 72,0 H108 V24 "
    "H72 A24,24 0 0 0 48,48 V72 H144 V96 A60,60 0 0 1 96,154.79 V180 H132 V204 H36 V180 "
    "H72 V154.79 A60,60 0 0 1 24,96 H0 V72 H24 Z M48,96 H120 A36,36 0 0 1 48,96 Z"
)
MARK = (
    '<svg class="mark" viewBox="-26 -26 196 256" aria-hidden="true">'
    '<path fill="var(--brand-soft)" stroke="var(--brand)" stroke-width="1.5" '
    f'vector-effect="non-scaling-stroke" fill-rule="evenodd" d="{MARK_PATH}"/></svg>'
)

#: The same mark at nav size, solid: an outline a pixel wide is a smudge at 16 px.
MARK_SMALL = (
    '<svg class="mark" viewBox="0 0 144 204" aria-hidden="true">'
    f'<path fill="var(--brand)" fill-rule="evenodd" d="{MARK_PATH}"/></svg>'
)

#: The same mark as the tab icon. A data URI: drawn by the browser, fetched from nowhere.
#: A tab strip is light on one machine and dark on the next and the icon cannot ask which,
#: so it takes the mid verdigris rather than either end of the brand pair.
FAVICON = (
    '<link rel="icon" href="data:image/svg+xml,'
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 144 204'%3E"
    "%3Cpath fill='%233E7F6E' fill-rule='evenodd' d='M24,48 A48,48 0 0 1 72,0 H108 V24 "
    "H72 A24,24 0 0 0 48,48 V72 H144 V96 A60,60 0 0 1 96,154.79 V180 H132 V204 H36 V180 "
    "H72 V154.79 A60,60 0 0 1 24,96 H0 V72 H24 Z M48,96 H120 A36,36 0 0 1 48,96 Z'/%3E"
    '%3C/svg%3E">'
)
