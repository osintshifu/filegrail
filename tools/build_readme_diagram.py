"""Draw the "How it works" figure of the README, once for light pages and once for dark.

GitHub and PyPI show a README image through an `<img>`, which cannot see the colours
of the page around it, so the figure is drawn twice with the same layout and chosen
with `<picture>`, the way the logo is. Both files come from here, so a change is made
once and the two cannot drift apart.

    python tools/build_readme_diagram.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.sax.saxutils import escape

ASSETS = Path(__file__).resolve().parent.parent / "assets"

W = 760
MONO = (
    "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, "
    "'Liberation Mono', 'DejaVu Sans Mono', monospace"
)

#: The provenance and metadata colours are the HTML report's.
PALETTES = {
    "onlight": {
        "bg": "#ffffff",
        "frame": "#d0d7de",
        "box": "#f6f8fa",
        "edge": "#d0d7de",
        "strong": "#1f2328",
        "ink": "#1f2328",
        "muted": "#59636e",
        "wire": "#8c959f",
        "provenance": "#2F8677",
        "metadata": "#5F58AD",
        "content": "#3D6FA8",
        "alert": "#B5563A",
    },
    "ondark": {
        "bg": "#0d1117",
        "frame": "#30363d",
        "box": "#151b23",
        "edge": "#3d444d",
        "strong": "#b1bac4",
        "ink": "#e6edf3",
        "muted": "#9198a1",
        "wire": "#656c76",
        "provenance": "#5FA89A",
        "metadata": "#A39BD9",
        "content": "#7FA7D6",
        "alert": "#D08770",
    },
}

LAYERS = [
    ("PROVENANCE", ["Browser history", "OS traces", "Shell history", "Archives", "Torrents"]),
    ("METADATA", ["EXIF", "XMP", "C2PA", "PDF", "Office"]),
    ("CONTENT", ["PDF text", "Office", "Email", "Structured data"]),
]
FINDINGS = ["PIVOTS", "CONFLICTS", "TIMELINE"]
OUTPUTS = [("REPORT", "terminal · HTML"), ("CASE/UCO", "JSON-LD export"), ("MCP", "AI agents")]

LABEL = (
    "How FileGrail works. A file is read for provenance (browser history, OS traces, "
    "shell history, archives, torrents), metadata (EXIF, XMP, C2PA, PDF, Office) and "
    "content (PDF text, Office, email, structured data). What is found becomes evidence, "
    "which gives pivots, conflicts and a timeline, then relationships and an evidence "
    "graph, delivered as a report, a CASE/UCO export or to AI agents over MCP."
)

CARD, GAP = 200, 30
LEFT = (W - 3 * CARD - 2 * GAP) / 2
CENTRES = [LEFT + CARD / 2 + i * (CARD + GAP) for i in range(3)]
MID = W / 2
NODE = 220


class Figure:
    def __init__(self, palette: dict[str, str]) -> None:
        self.p = palette
        self.out: list[str] = []

    def rect(self, x, y, w, h, *, stroke, width=1.0, fill=None, rx=6):
        self.out.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" '
            f'fill="{fill or self.p["box"]}" stroke="{stroke}" stroke-width="{width}"/>'
        )

    def text(self, x, y, s, *, size=13, fill=None, weight=None, spacing=None):
        attrs = f'x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill or self.p["ink"]}"'
        attrs += ' text-anchor="middle"'
        if weight:
            attrs += f' font-weight="{weight}"'
        if spacing:
            attrs += f' letter-spacing="{spacing}"'
        self.out.append(f"<text {attrs}>{escape(s)}</text>")

    def wire(self, points, *, arrow=True, r=8):
        """An orthogonal line through `points`, with its corners rounded."""
        d = f"M{points[0][0]:.1f},{points[0][1]:.1f}"
        for before, corner, after in zip(points, points[1:], points[2:], strict=False):
            into = _towards(corner, before, r)
            out = _towards(corner, after, r)
            d += f" L{into[0]:.1f},{into[1]:.1f} Q{corner[0]:.1f},{corner[1]:.1f} "
            d += f"{out[0]:.1f},{out[1]:.1f}"
        d += f" L{points[-1][0]:.1f},{points[-1][1]:.1f}"
        marker = ' marker-end="url(#head)"' if arrow else ""
        self.out.append(
            f'<path d="{d}" fill="none" stroke="{self.p["wire"]}" stroke-width="1.5"{marker}/>'
        )

    def dot(self, x, y):
        self.out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{self.p["wire"]}"/>')

    def fan_out(self, top, bar, bottom):
        """From one node down to three, the way the text diagram draws it."""
        self.wire([(MID, top), (MID, bottom)])
        for x in (CENTRES[0], CENTRES[2]):
            self.wire([(MID, bar), (x, bar), (x, bottom)])
        self.dot(MID, bar)

    def fan_in(self, top, bar, bottom):
        """From three nodes down to one."""
        self.wire([(MID, top), (MID, bottom)])
        for x in (CENTRES[0], CENTRES[2]):
            self.wire([(x, top), (x, bar), (MID, bar)], arrow=False)
        self.dot(MID, bar)

    def node(self, y, label, *, strong=False, width=NODE, h=40):
        colour = self.p["strong"] if strong else self.p["edge"]
        self.rect(MID - width / 2, y, width, h, stroke=colour, width=1.5 if strong else 1.0)
        self.text(MID, y + 25, label, size=15, weight="700", spacing="1")
        return y + h


def _towards(a, b, r):
    """The point `r` along the straight line from a to b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = (dx * dx + dy * dy) ** 0.5
    return a[0] + dx / length * r, a[1] + dy / length * r


def draw(p: dict[str, str]) -> str:
    f = Figure(p)

    y = f.node(28, "FILE", strong=True, width=160)

    # Three ways of reading the same file.
    card_top, step = y + 44, 20
    card_h = 54 + (max(len(items) for _, items in LAYERS) - 1) * step + 18
    f.fan_out(y, y + 20, card_top)
    for (name, items), x in zip(LAYERS, CENTRES, strict=True):
        colour = p[name.lower()]
        f.rect(x - CARD / 2, card_top, CARD, card_h, stroke=p["edge"])
        f.out.append(
            f'<rect x="{x - CARD / 2 + 1:.1f}" y="{card_top:.1f}" width="{CARD - 2:.1f}" '
            f'height="4" rx="2" fill="{colour}"/>'
        )
        f.text(x, card_top + 28, name, size=14, weight="700", fill=colour, spacing="1")
        for n, item in enumerate(items):
            f.text(x, card_top + 54 + n * step, item)
    y = card_top + card_h

    f.fan_in(y, y + 22, y + 46)
    y = f.node(y + 46, "EVIDENCE", strong=True)

    # What the evidence gives.
    f.fan_out(y, y + 20, y + 44)
    y += 44
    for label, x in zip(FINDINGS, CENTRES, strict=True):
        colour = p["alert"] if label == "CONFLICTS" else p["ink"]
        f.rect(x - CARD / 2, y, CARD, 40, stroke=p["edge"])
        f.text(x, y + 25, label, size=14, weight="700", fill=colour, spacing="1")
    y += 40

    f.fan_in(y, y + 22, y + 46)
    y = f.node(y + 46, "RELATIONSHIPS")
    f.wire([(MID, y), (MID, y + 28)])
    y = f.node(y + 28, "EVIDENCE GRAPH", strong=True)

    # Where it goes.
    f.fan_out(y, y + 20, y + 44)
    y += 44
    for (label, what), x in zip(OUTPUTS, CENTRES, strict=True):
        f.rect(x - CARD / 2, y, CARD, 56, stroke=p["edge"])
        f.text(x, y + 25, label, size=14, weight="700", spacing="1")
        f.text(x, y + 43, what, size=12, fill=p["muted"])
    height = y + 56 + 28

    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height:.0f}" '
        f'viewBox="0 0 {W} {height:.0f}" role="img" aria-label="{escape(LABEL)}" '
        f'font-family="{MONO}">\n'
        f"<title>{escape(LABEL)}</title>\n"
        f'<defs><marker id="head" viewBox="0 0 8 8" refX="7.5" refY="4" markerWidth="8" '
        f'markerHeight="8" markerUnits="userSpaceOnUse" orient="auto">'
        f'<path d="M0,0 L8,4 L0,8 z" fill="{p["wire"]}"/></marker></defs>\n'
        f'<rect x="0.5" y="0.5" width="{W - 1}" height="{height - 1:.0f}" rx="8" '
        f'fill="{p["bg"]}" stroke="{p["frame"]}"/>\n'
    )
    return head + "\n".join(f.out) + "\n</svg>\n"


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ASSETS
    for variant, palette in PALETTES.items():
        path = target / f"filegrail-how-it-works-{variant}.svg"
        path.write_text(draw(palette), encoding="utf-8")
        print(path)
