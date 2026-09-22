"""Self-contained HTML renderer for photo-forensics findings.

Its own page rather than a section of the investigation report: an image is
looked at before it is read, so the picture is the subject here and the evidence
sits beside it. The design tokens, the mark and the icon sprite are the ones the
investigation report uses, so the two read as one tool.

The page is a workspace rather than an article. A rail on the left holds the
images and, under them, the analyses this report can bring to bear; the space
beside it holds one image at a time, laid out as panels that stand side by side.
Every panel has the same anatomy - a name, what it is for, what it produced, and
a strip saying what is on screen - so a reader learns to read one panel and can
then read all of them.

All of it is in the markup before a script runs. Without one the rail is an
index, each analysis links to the description of itself, and the images are a
document from first to last.
"""

# The embedded stylesheet and script are deliberately compact because they are
# written verbatim into every report. Splitting declarations to satisfy Python's
# line length would increase every generated artifact without improving either.
# ruff: noqa: E501

from __future__ import annotations

import base64
import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path, PurePath
from urllib.parse import quote

from . import __version__
from .htmlicons import FAVICON, ICONS, MARK, MARK_SMALL
from .models import BLOCK_LABELS
from .photo import PhotoArtifact, PhotoCollection, PhotoResult
from .photojpeg import JpegAnalysis, JpegMarker
from .photomap import Fix

#: A policy delivered in a `<meta>` element ignores `frame-ancestors`, and the
#: browser says so in the console of every report. A directive that does nothing
#: is worth less than a console a reader can still read.
POLICY = (
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
    "img-src data:; base-uri 'none'; form-action 'none'"
)

#: The same policy for a report whose images sit beside it rather than inside
#: it. Local files are allowed and nothing else is: no scheme here reaches the
#: network, which is the point the policy is there to make.
LINKED_POLICY = (
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
    "img-src 'self' data: file:; base-uri 'none'; form-action 'none'"
)

#: What to call a written-out image, by what it is.
_SUFFIXES = {"image/png": ".png", "image/jpeg": ".jpg"}

#: What a browser decodes inside an `<img>`. An image this tool reads but a
#: browser cannot - a TIFF, a raw file - is shown through the preview the pixel
#: reader derived from it rather than pointed at where it lies: an `<img>` given
#: a TIFF renders nothing at all, and the report showed a broken image instead
#: of the preview it had already produced.
_RENDERABLE = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif"}

#: The stage layers that are the image rather than a map derived from it.
_PHOTOGRAPHIC = ("main-preview", "embedded-preview", "maker-preview")


@dataclass(frozen=True, slots=True)
class _Method:
    """What one derived image is for, and the limitations on reading it.

    A map with no reading is decoration. Each one here says what it makes
    visible, what would be a mistake to conclude from it, and where the
    technique came from, because a report that names its methods should be
    able to say whose they are.
    """

    family: str
    shows: str
    caution: str
    source: str = ""


_GUIDE: dict[str, _Method] = {
    "main-preview": _Method(
        "Image",
        "The image itself, decoded and scaled to a bounded working size.",
        "Every map below is measured from this decode rather than from the file at full"
        " size, so none of them can show what the scaling removed.",
    ),
    "embedded-preview": _Method(
        "Image",
        "The small copy the camera wrote inside the file.",
        "An editor often leaves it as the camera left it, so a preview showing different"
        " framing, tone or content than the image is a strong sign the file was"
        " changed afterwards. The two are never expected to match in sharpness.",
    ),
    "maker-preview": _Method(
        "Image",
        "A copy the camera wrote into the vendor's own block.",
        "Read the same way as the standard preview: what matters is whether it shows the"
        " same scene, not whether it looks as good.",
    ),
    "histogram": _Method(
        "Colour",
        "How often each value occurs, per channel and in luminance.",
        "Comb-like gaps and isolated spikes are what a levels or curves adjustment leaves"
        " behind. A scene with little tonal range is uneven for its own reasons.",
    ),
    "luminance-gradient": _Method(
        "Detail",
        "How brightness changes from one pixel to the next, as a direction.",
        "Surfaces lit from the same angle take similar colours here, so an object lit"
        " differently from its surroundings stands out, and an edge sharper than the edges"
        " near it can be where something was placed. Compression blocks and sensor noise"
        " are gradients too: a busy map is not on its own a finding.",
        "after Krawetz, A Picture's Worth (2007)",
    ),
    "noise-residual": _Method(
        "Noise",
        "What is left when the picture is taken away and only local variation remains.",
        "Airbrushing, warping, rescaling and denoising flatten this in the places they"
        " touch, so a region quieter than the ones around it is worth looking at. It needs"
        " a large, lightly compressed image; a small one carries too little noise"
        " to read at all.",
    ),
    "bit-planes": _Method(
        "Noise",
        "Single bits of the luminance channel, the highest and three of the lowest.",
        "The low bits of an image off a sensor look like noise. Flat patches, block"
        " edges or regular patterns there mean those values were computed rather than"
        " captured, which is what rescaling, heavy compression and least-significant-bit"
        " steganography all leave behind.",
    ),
    "ela-q90": _Method(
        "Compression",
        "The image compared against itself saved again at a fixed quality.",
        "A region that has been through a different number of compressions can come out"
        " brighter or darker than the ones around it. The quality has to sit near the"
        " file's own or the whole frame lights up, which is why two are given. Bright"
        " edges are ordinary wherever the picture has detail.",
        "after Krawetz, A Picture's Worth (2007)",
    ),
}
_GUIDE["ela-q75"] = _GUIDE["ela-q90"]

#: What the panels that are not a derived image are for. A reader meeting one
#: should be able to ask it what it does without leaving it, which is what the
#: button in every panel bar opens.
_NOTES: dict[str, str] = {
    "image": "The working decode of the image, with any map derived from it laid"
    " over the same pixels rather than shown beside them.",
    "fileinfo": "What the file is, taken from the filesystem and from the header, so the two"
    " can be read against each other.",
    "structure": "Where this file's bytes go, segment by segment, in the order the encoder"
    " wrote them.",
    "fields": "Which blocks spoke for this image and how much each of them said. The"
    " values are gathered once for the whole report, where they can be compared.",
    "findings": "Disagreements this tool can support mechanically, and material it flags for"
    " a reader to decide.",
    "coverage": "Which methods ran against this file, and what stopped the ones that did not.",
    "markers": "The frame parameters and coding tables the encoder wrote.",
}

#: What reading each of those panels wrongly would look like. The maps carry
#: this in `_GUIDE`; the panels that are not maps mislead in their own ways, and
#: a panel that cannot say how it misleads has not finished explaining itself.
_CAUTIONS: dict[str, str] = {
    "image": "It is scaled, so nothing here can show what the scaling removed, and an"
    " overlay at less than full opacity mixes two pictures the eye will try to reconcile.",
    "fileinfo": "The filesystem times are the times of this copy, not of the image. Only"
    " the digest identifies the bytes that were read.",
    "structure": "A camera file spends nearly everything on the scan. A large application"
    " block or bytes after the end marker are worth looking at, but both are also ordinary:"
    " editors write large colour profiles and some cameras pad the tail.",
    "fields": "A count says how much a block said, never whether it was true. A file rewritten"
    " by an editor can carry a complete and entirely fabricated set.",
    "findings": "Neither state establishes that an image is authentic or manipulated. A"
    " conflict is a disagreement between two recorded things, nothing more.",
    "coverage": "A method that did not run found nothing because it did not look. It is not"
    " evidence of absence.",
    "markers": "Tables and marker order identify the last encoder, not the camera and not the"
    " photographer. Any editor that re-saves the file replaces them.",
}

#: The rail's taxonomy: the analyses this report can bring to an image,
#: in the order a reader meets them.
_TREE: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("General", (("image", "Image"), ("fileinfo", "File information"))),
    (
        "Metadata",
        (
            ("structure", "File structure"),
            ("fields", "Metadata sources"),
            ("embedded-preview", "Embedded preview"),
            ("maker-preview", "Maker preview"),
        ),
    ),
    ("Inspection", (("findings", "Findings"), ("coverage", "Analyses performed"))),
    ("Colour", (("histogram", "Channel histogram"),)),
    ("Detail", (("luminance-gradient", "Luminance gradient"),)),
    ("Noise", (("noise-residual", "Noise residual"), ("bit-planes", "Bit planes"))),
    (
        "Compression",
        (
            ("ela-q90", "Error level analysis q90"),
            ("ela-q75", "Error level analysis q75"),
            ("markers", "JPEG marker stream"),
        ),
    ),
)

#: What each kind of byte in a JPEG is doing there, and the colour that says so.
#: A file's own proportions are a fact about it: an image off a camera spends
#: almost everything on the scan, and anything that does not is worth a look.
_ROLES: tuple[tuple[str, str, str], ...] = (
    ("frame", "delimiter", "var(--line-2)"),
    ("app", "carried metadata", "var(--metadata)"),
    ("sof", "frame header", "var(--brand)"),
    ("table", "coding table", "var(--activity)"),
    ("sos", "scan header", "var(--accent)"),
    ("scan", "entropy-coded scan", "var(--line-2)"),
    ("tail", "after the end marker", "var(--alert)"),
)

#: The same table, read by role rather than iterated.
_ROLES_BY_KEY = {role: said for role, said, _paint in _ROLES}

#: The four marks that say the pixels inside a frame line up with the
#: image. A frame without them is a chart and carries a dashed border.
_CORNERS = "".join(
    f'<i class="rm {place}" aria-hidden="true"></i>' for place in ("tl", "tr", "bl", "br")
)


# What the summary's own panels are for. They are read the same way every other
# panel here is read, so they carry the same two sentences.
_GUIDE["clusters"] = _Method(
    "Collection",
    "Which images share a source, on four axes: the make the file claims, the body"
    " serial, the lens, and the encoder signature its tables and marker order make.",
    "A make is what the file says about itself. Files rewritten by an editor can carry a"
    " complete and fabricated set, and a file that says nothing is not thereby suspicious.",
)
_GUIDE["times"] = _Method(
    "Collection",
    "Every recorded capture time on one axis, with the files that record none in a strip"
    " beneath it.",
    "A recorded time is a claim by the file. The filesystem time of each copy sits on its"
    " own plate, where the two can be read against each other.",
)
_GUIDE["geolocation"] = _Method(
    "Collection",
    "Where the files that carry coordinates say they were, at three scales: the world, the"
    " same outline zoomed, and a plot in metres with no basemap under it.",
    "Coordinates say where the receiver believed it was when the file was written, to the"
    " precision the camera recorded. Distances under 20 m are inside a consumer receiver's"
    " error, and below country scale a 1:110m outline is too coarse to place anything.",
    "outline: Natural Earth 1:110m, public domain",
)
_GUIDE["world-scale"] = _GUIDE["geolocation"]
_GUIDE["region-scale"] = _GUIDE["geolocation"]
_GUIDE["coordinates"] = _GUIDE["geolocation"]

STYLE = r"""
:root{color-scheme:dark;
--bg:#0C0C0D;--surface:#141415;--surface-2:#1A1A1C;--sunken:#08080A;
--line:#262628;--line-2:#353537;--line-3:#45464A;
--ink:#E6E8EB;--ink-2:#C3C8CE;--muted:#9AA1A9;--faint:#7B828B;
--accent:#7FB5A8;--brand:#5FA89A;--brand-soft:rgba(95,168,154,.14);
--metadata:#A39BD9;--activity:#C9A66B;--alert:#D08770;
--metadata-soft:rgba(163,155,217,.14);--activity-soft:rgba(201,166,107,.14);
--alert-soft:rgba(208,135,112,.16);
--t-label:11px;--t-small:12px;--t-table:12.5px;--t-body:13.5px;--t-lead:15px;--t-h2:21px;--track:.14em;
--mono:"IBM Plex Mono","JetBrains Mono","SF Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,"DejaVu Sans Mono",monospace;
--sans:"IBM Plex Sans",ui-sans-serif,system-ui,-apple-system,"Segoe UI","Noto Sans","Helvetica Neue",sans-serif;
--r:3px;--gutter:clamp(18px,3vw,40px);--nav:48px;--rail:318px;--cols:2}
*{box-sizing:border-box}
/* Author `display` beats the browser's own rule for the attribute, so a layer
   laid out as a grid stays on screen when it is hidden. Everything this report
   puts behind another thing - the icon sprite, the overlay, a filtered-out row,
   a panel's help - depends on this one line. */
[hidden]{display:none!important}
*{scrollbar-width:thin;scrollbar-color:var(--line-2) transparent}
::-webkit-scrollbar{width:7px;height:7px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--line-2);border-radius:4px}
html{scroll-behavior:smooth;scroll-padding-top:calc(var(--nav) + 12px)}
body{margin:0;background:var(--bg);color:var(--ink);font:400 var(--t-body)/1.6 var(--sans)}
h1,h2,h3,h4,p,figure,dl,dd,pre{margin:0}ul,ol{margin:0;padding:0;list-style:none}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
button{font:inherit;color:inherit;background:none;border:0;padding:0;text-align:left;cursor:pointer}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
img{max-width:100%}
.ic{width:14px;height:14px;fill:currentColor;flex:none;display:block}
.mono{font-family:var(--mono)}
.grow{flex:1;min-width:0}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;height:28px;padding:0 11px;
border:1px solid var(--line-2);border-radius:var(--r);color:var(--ink-2);background:var(--surface);
font:400 var(--t-small)/1 var(--sans);white-space:nowrap}
.btn:hover{border-color:var(--accent);color:var(--ink)}
.btn:disabled{opacity:.3;cursor:default}
.btn:disabled:hover{border-color:var(--line-2);color:var(--ink-2)}
.btn.icon{width:28px;padding:0}
.btn[aria-pressed=true]{border-color:var(--accent);color:var(--ink);background:var(--brand-soft)}
/* masthead */
.mast{padding:20px var(--gutter) 22px;border-bottom:1px solid var(--line)}
.mast .word{margin:0 0 16px;font:500 var(--t-label)/1.4 var(--sans);letter-spacing:.2em;
text-transform:uppercase;color:var(--muted)}
.mast .word small{font-size:inherit;font-weight:400;color:var(--faint)}
.mast-body{display:grid;grid-template-columns:auto 1fr;gap:0 24px;align-items:stretch}
.mast-mark{display:flex;align-items:stretch}
.mast .mark{height:100%;max-height:96px;width:auto;flex:none}
.facts{display:grid;grid-template-columns:auto 1fr;gap:5px 22px;justify-content:start;
font-size:var(--t-body);align-content:center}
.facts dt{font:500 var(--t-label)/1.5 var(--sans);letter-spacing:var(--track);
text-transform:uppercase;color:var(--faint)}
.facts dd{color:var(--ink);overflow-wrap:anywhere}
/* nav */
.nav{position:sticky;top:0;z-index:30;height:var(--nav);padding:0 var(--gutter);
display:flex;align-items:center;gap:2px;overflow-x:auto;scrollbar-width:none;
background:color-mix(in srgb,var(--surface-2) 94%,transparent);backdrop-filter:blur(12px);
border-bottom:1px solid var(--line)}
.nav::-webkit-scrollbar{display:none}
.nav a{color:var(--muted);font:400 14px/1 var(--sans);padding:0 13px;height:var(--nav);
display:inline-flex;align-items:center;gap:7px;white-space:nowrap}
.nav a:hover{color:var(--ink);text-decoration:none}
.nav a b{font:400 var(--t-small)/1 var(--mono);color:var(--faint)}
.nav .home{padding:0 14px 0 0}.nav .home .mark{width:15px;height:21px}
.nav-actions{display:none;gap:6px;align-items:center;flex:none;padding-left:10px}
.js .nav-actions{display:flex}
/* the workspace: a rail that stays, and the work beside it */
.shell{display:grid;grid-template-columns:var(--rail) minmax(0,1fr);align-items:start}
.rail{position:sticky;top:var(--nav);max-height:calc(100vh - var(--nav));overflow:auto;
border-right:1px solid var(--line);background:var(--surface);padding-bottom:18px}
.rail-block{padding:15px 0 4px;border-bottom:1px solid var(--line)}
.rail-block:last-child{border-bottom:0}
.rail h2{display:flex;align-items:baseline;gap:8px;margin:0 15px 9px;
font:500 var(--t-label)/1.4 var(--sans);letter-spacing:var(--track);text-transform:uppercase;color:var(--muted)}
.rail h2 .n{color:var(--accent);font:400 var(--t-small)/1 var(--mono)}
/* the roll of images: the list is the contact sheet now, so each row
   carries the picture it stands for and says what was found in it */
.roll li a{display:grid;grid-template-columns:auto 80px minmax(0,1fr);gap:0 10px;
grid-template-areas:"no thumb nm" "no thumb sub" "no thumb st";align-items:center;
padding:9px 14px;color:var(--ink-2);border-left:2px solid transparent;
border-bottom:1px solid var(--line)}
.roll li:last-child a{border-bottom:0}
.roll li a:hover{background:var(--surface-2);color:var(--ink);text-decoration:none}
.roll .no{grid-area:no;grid-row:1/4;align-self:start;padding-top:2px;
font:400 11px/1.4 var(--mono);color:var(--faint)}
.roll .th{grid-area:thumb;grid-row:1/4;width:80px;height:60px;background:var(--sunken);
overflow:hidden;display:flex;align-items:center;justify-content:center}
.roll .th img{width:100%;height:100%;object-fit:cover;display:block}
.roll .th.none{border:1px dashed var(--line-2);font:500 9.5px/1 var(--sans);
letter-spacing:.08em;color:var(--faint)}
.roll .nm{grid-area:nm;font:500 12px/1.35 var(--sans);color:var(--ink);
overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.roll .sub{grid-area:sub;font:400 11px/1.35 var(--sans);color:var(--muted);
overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.roll .st{grid-area:st;display:flex;gap:4px;flex-wrap:wrap;margin-top:3px}
.tag{display:inline-flex;align-items:center;font:600 9.5px/1 var(--mono);letter-spacing:.1em;
text-transform:uppercase;padding:3px 5px 2px;border:1px solid currentColor;border-radius:2px;
color:var(--muted);white-space:nowrap}
.tag.conflict{color:var(--alert);background:rgba(208,135,112,.16)}
.tag.signal{color:var(--activity);background:rgba(201,166,107,.14)}
.tag.preview{color:var(--metadata);background:rgba(163,155,217,.14)}
.tag.nodecode{color:var(--muted);border-style:dashed}
.roll li a[aria-current=true] .nm{color:var(--ink)}
.roll li a[aria-current=true]{background:var(--surface-2);border-left-color:var(--accent);color:var(--ink)}
.roll li a[aria-current=true] .no{color:var(--accent)}
/* the analysis tree: a taxonomy that carries state, the way a desktop tool does */
.tree .cat{display:block;padding:9px 15px 3px;font:500 var(--t-label)/1.4 var(--sans);
letter-spacing:var(--track);text-transform:uppercase;color:var(--faint)}
.tree .cat:before{content:"[";color:var(--line-2)}
.tree .cat:after{content:"]";color:var(--line-2)}
.tree a,.tree span.leaf{display:flex;align-items:center;gap:8px;padding:4px 15px 4px 24px;
font-size:var(--t-small);color:var(--ink-2);border-left:2px solid transparent}
.tree a:hover{background:var(--surface-2);color:var(--ink);text-decoration:none}
.tree .dot{width:5px;height:5px;border-radius:50%;background:var(--accent);flex:none}
/* an analysis that produced nothing anywhere in this report is set back
   rather than dropped: what a method did not find is part of what it did */
.tree span.leaf{color:var(--faint);font-style:italic}
.tree span.leaf .dot{background:transparent;box-shadow:inset 0 0 0 1px var(--line-2)}
.tree a[data-state=none]{color:var(--faint)}
.tree a[data-state=none] .dot{background:transparent;box-shadow:inset 0 0 0 1px var(--line-2)}
.tree a[aria-current=true]{background:var(--surface-2);border-left-color:var(--accent);color:var(--ink)}
/* sections */
main{padding:0 var(--gutter) 40px;counter-reset:sec;min-width:0}
/* Only the report's own sections are numbered. A frame holds panels that are
   sections of their own, and counting those numbered the document 213. */
main>section{padding:40px 0 8px;counter-increment:sec}
main>section.bare{counter-increment:none;padding-top:14px}
.js .frame-head{display:none}
.deck-id{display:flex;align-items:baseline;gap:10px;min-width:0;flex:1}
.deck-id b{font:500 var(--t-lead)/1.3 var(--sans);color:var(--ink);white-space:nowrap;
min-width:0;overflow:hidden;text-overflow:ellipsis}
.deck-id .path{font:400 var(--t-label)/1.5 var(--mono);color:var(--faint);
overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
main>section:first-child{padding-top:28px}
.h{display:flex;align-items:baseline;gap:14px;margin:0 0 18px;flex-wrap:wrap}
.js .h h2{cursor:pointer}
.fold{display:none;align-self:center;width:22px;height:22px;margin:0 -2px 0 -6px;
border-radius:var(--r);color:var(--faint);align-items:center;justify-content:center;flex:none}
.js .fold{display:inline-flex}
.fold:hover,.js .h:hover .fold{color:var(--accent)}
.fold .ic{transform:rotate(90deg);transition:transform .15s}
section.folded .fold .ic{transform:none}
section.folded .sec-body{display:none}
section.folded .h{margin-bottom:0}section.folded{padding-bottom:28px}
.h h2{font:600 var(--t-h2)/1.25 var(--sans);letter-spacing:-.25px}
.h h2:before{content:counter(sec,decimal-leading-zero);color:var(--accent);
font:400 var(--t-label)/1 var(--mono);letter-spacing:var(--track);margin-right:13px;vertical-align:3px}
.h .n{color:var(--accent);font-size:var(--t-small)}
h3{font:500 var(--t-label)/1.4 var(--sans);letter-spacing:var(--track);text-transform:uppercase;
color:var(--muted);margin:0 0 9px}
p.note{color:var(--muted);font:400 var(--t-body)/1.7 var(--sans);max-width:80ch}
/* summary cards */
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(128px,1fr));gap:10px}
.card{--c:var(--line-2);background:var(--surface);border:1px solid var(--line);
border-top:2px solid var(--c);border-radius:var(--r);padding:15px 17px 14px;
display:flex;flex-direction:column;min-width:0}
.card .v{font-size:28px;line-height:1.05;font-weight:500;letter-spacing:-.7px;color:var(--ink);overflow-wrap:anywhere}
.card .v.wordy{font-size:var(--t-lead);line-height:1.45;letter-spacing:0;color:var(--ink-2);padding:6px 0 3px}
.card .k{margin-top:3px;font:500 var(--t-label)/1.3 var(--sans);letter-spacing:var(--track);
text-transform:uppercase;color:var(--muted)}
.card.alert{--c:var(--alert)}.card.accent{--c:var(--accent)}.card.activity{--c:var(--activity)}
.card.alert .v,.card.accent .v,.card.activity .v{color:var(--c)}
/* contact sheet */
.sheet{display:grid;grid-template-columns:repeat(auto-fill,minmax(158px,1fr));gap:12px;margin-top:22px}
.shot{display:block;border:1px solid var(--line);border-radius:var(--r);overflow:hidden;
background:var(--surface);color:inherit}
.shot:hover{border-color:var(--accent);text-decoration:none}
.shot figure{aspect-ratio:4/3;background:var(--sunken);display:flex;align-items:center;justify-content:center;overflow:hidden}
.shot img{width:100%;height:100%;object-fit:cover}
.shot .none{font:400 var(--t-label)/1 var(--sans);letter-spacing:var(--track);text-transform:uppercase;color:var(--faint)}
.shot .cap{display:block;padding:8px 10px 9px;border-top:1px solid var(--line)}
.shot .cap b{display:block;font:400 var(--t-small)/1.4 var(--mono);color:var(--ink-2);
overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.shot .cap i{display:block;margin-top:2px;font:400 var(--t-label)/1.4 var(--sans);font-style:normal;color:var(--faint);
overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.shot .cap i.broken{color:var(--alert)}
.groups{margin-top:24px}
.groups li{padding:5px 0;border-bottom:1px solid var(--line);font-size:var(--t-small);color:var(--ink-2)}
.groups code{font-family:var(--mono);color:var(--activity)}
/* the deck: what a reader does to the workspace, where they can see it */
.deck{display:none;position:sticky;top:var(--nav);z-index:15;align-items:center;gap:8px;
padding:9px 0;margin-bottom:13px;background:var(--bg);border-bottom:1px solid var(--line)}
.js .deck{display:flex;flex-wrap:wrap}
.deck-at{font:400 var(--t-small)/1 var(--mono);color:var(--faint);min-width:76px;text-align:center}
.deck-name{font:400 var(--t-small)/1 var(--mono);color:var(--ink-2);overflow:hidden;
text-overflow:ellipsis;white-space:nowrap;max-width:34ch}
/* one image */
.frame{padding-bottom:30px}
.frame+.frame{border-top:1px solid var(--line);padding-top:26px}
.js .frame+.frame{border-top:0;padding-top:0}
.js .frame:not([data-current]){display:none}
/* a panel or a finding reached by its address: clear of the two sticky bars,
   and the row marked so the eye finds what the link named */
.frame [id]{scroll-margin-top:calc(var(--nav) + 64px)}
tr:target td{box-shadow:inset 0 1px 0 var(--accent),inset 0 -1px 0 var(--accent)}
.frame-head{display:flex;align-items:baseline;gap:12px;margin:0 0 12px;flex-wrap:wrap}
.frame-no{font:400 var(--t-small)/1.5 var(--mono);color:var(--accent)}
.frame-head h3{margin:0;font:500 var(--t-lead)/1.3 var(--sans);letter-spacing:0;
text-transform:none;color:var(--ink)}
.frame-head p{font:400 var(--t-label)/1.5 var(--mono);color:var(--faint);overflow-wrap:anywhere}
.stamp{margin-left:auto;font:500 var(--t-label)/1 var(--sans);letter-spacing:var(--track);
text-transform:uppercase;color:var(--muted);border:1px solid var(--line-2);border-radius:var(--r);padding:5px 8px}
/* the panel: one anatomy, learned once and then read everywhere */
/* A grid lays panels in rows, and a row is as tall as its tallest panel, so a
   short one leaves a hole beside a long one. Columns pack instead: each panel
   drops under the last one in its column. What it costs is reading order,
   which becomes column by column rather than row by row. */
.panels{column-count:var(--cols);column-gap:12px}
.panels>.panel{break-inside:avoid;margin-bottom:12px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
display:flex;flex-direction:column;min-width:0;overflow:hidden}
.panel.wide{column-span:all}
/* Two frames, and never the same frame. A solid border with corner marks says
   the pixels inside line up with the image; a dashed border says they do
   not, because a chart describes an image without standing on it. A reader
   who learns the difference once reads it everywhere in the report. */
.reg{position:relative;background:var(--sunken);border:1px solid var(--line-2);
overflow:hidden;display:block}
.reg>img{display:block;max-width:100%}
.rm{position:absolute;width:11px;height:11px;pointer-events:none;z-index:2;
border:0 solid var(--accent)}
.rm.tl{top:0;left:0;border-top-width:1.5px;border-left-width:1.5px}
.rm.tr{top:0;right:0;border-top-width:1.5px;border-right-width:1.5px}
.rm.bl{bottom:0;left:0;border-bottom-width:1.5px;border-left-width:1.5px}
.rm.br{bottom:0;right:0;border-bottom-width:1.5px;border-right-width:1.5px}
.chart{position:relative;background:var(--surface-2);border:1px dashed var(--line-3);
overflow:hidden;display:block}
.chart>img{display:block;width:100%;height:auto}
.regtag{position:absolute;left:8px;top:8px;z-index:2;font:600 10px/1 var(--mono);
letter-spacing:.1em;text-transform:uppercase;padding:4px 6px;border-radius:2px;
background:rgba(8,8,10,.8);color:var(--muted)}
.regtag.in{color:var(--accent)}
.regtag.off{color:var(--muted);border:1px dashed var(--line-3)}
/* the stage: a map laid over the image, so what is bright is a place */
.image-stage{display:grid;place-items:center;background:var(--sunken);padding:16px;
min-height:clamp(290px,52vh,620px)}
/* Sixteen files in an ordinary corpus are a hundred pixels across. Shown at
   their own size they are a stamp nothing can be read from; shown smoothed
   they would be pixels the camera never recorded. So the frame takes the height
   the panel allows and the image's own ratio decides its width - which is
   also what makes the corner marks hug the picture rather than the panel - and
   a magnified one is drawn nearest-neighbour, showing the sensor's own grid.
   The strip under the stage says by how much. */
.image-stage>.reg{aspect-ratio:var(--ar,4/3);max-width:100%;
width:min(100%,calc(clamp(258px,48vh,576px) * var(--arn,1.3333)))}
.image-stage>.reg>img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain}
.image-stage.sharp img{image-rendering:pixelated}
.map-shot{display:block;width:100%;height:auto;background:var(--sunken)}
.panel.sharp .map-shot{image-rendering:pixelated}
.plate-over{opacity:var(--blend,.85);pointer-events:none}
.image-stage.bare{min-height:0;padding:0}
.redacted-stage{padding:34px 20px;color:var(--faint);font-size:var(--t-small);text-align:center}
.lens{display:flex;align-items:center;gap:6px;padding:8px 12px;border-top:1px solid var(--line);
background:var(--surface);flex-wrap:wrap}
.lens-label{font:500 var(--t-label)/1 var(--sans);letter-spacing:var(--track);
text-transform:uppercase;color:var(--faint);margin-right:2px}
.lens .btn{height:25px;padding:0 9px;font-size:var(--t-label)}
.blend{display:flex;align-items:center;gap:9px;padding:5px 12px;min-height:30px;
border-top:1px solid var(--line);background:var(--surface-2);flex-wrap:wrap}
.blend label{display:flex;align-items:center;gap:7px;font:400 var(--t-label)/1.5 var(--mono);color:var(--faint)}
.blend input[type=range]{width:116px;accent-color:var(--brand)}
.blend input:disabled{opacity:.3}
.blend output{min-width:32px;color:var(--ink-2)}
.swap{display:flex;border:1px solid var(--line-2);border-radius:var(--r);overflow:hidden;flex:none}
.swap button{padding:0 9px;height:21px;font:400 var(--t-label)/21px var(--mono);color:var(--faint)}
.swap button[aria-pressed=true]{background:var(--brand-soft);color:var(--ink)}
/* The six facts a reader checks before anything else, along the top of the
   image view so the panels underneath can be read against them. */
.keyfacts{display:flex;border:1px solid var(--line);border-radius:var(--r);
background:var(--surface);margin-bottom:12px;overflow:hidden;flex-wrap:wrap}
.kf{flex:1 1 150px;padding:10px 14px;border-right:1px solid var(--line);min-width:0}
.kf:last-child{border-right:0}
.kf.wide{flex:2 1 300px}
.kf .label{display:block;margin-bottom:4px}
.kf .v{font:var(--t-table)/1.35 var(--mono);color:var(--ink);overflow-wrap:anywhere}
.kf .v.alert{color:var(--alert)}
.kf .v i{color:var(--faint);font-style:normal}
/* tables: the same shape everywhere, and colour only where something is flagged */
table{border-collapse:collapse;width:100%;font:var(--t-table)/1.4 var(--sans)}
th{text-align:left;font:600 var(--t-label)/1 var(--sans);letter-spacing:.1em;
text-transform:uppercase;color:var(--faint);padding:8px 10px;
border-bottom:1px solid var(--line-2);white-space:nowrap;background:var(--surface)}
thead th{position:sticky;top:0;z-index:1}
td{padding:6px 10px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}
tr:last-child td{border-bottom:0}
td.k{color:var(--muted);white-space:nowrap}
td.v,td.m{font-family:var(--mono);color:var(--ink);overflow-wrap:anywhere}
td.m{color:var(--faint)}
td.num{font-family:var(--mono);text-align:right;color:var(--ink-2);white-space:nowrap}
td.dim{color:var(--faint)}
th.num{text-align:right}
tr.conflict td{background:var(--alert-soft)}tr.conflict td.k{color:var(--alert)}
tr.signal td{background:var(--activity-soft)}tr.signal td.k{color:var(--activity)}
.empty{font-size:var(--t-small);color:var(--faint)}
/* the file structure map: where this file spends itself */
.bytes{display:flex;height:22px;border-radius:2px;overflow:hidden;background:var(--sunken)}
.bytes i{display:block;height:100%;min-width:1px}
.bytes.even i{min-width:8px}
.bytes-legend{display:flex;gap:14px;flex-wrap:wrap;font:11px var(--mono);color:var(--muted);margin-top:8px}
.bytes-legend i{display:inline-block;width:10px;height:10px;border-radius:1px;vertical-align:-1px;margin-right:5px}
.ruler{margin-bottom:12px}
.cap{display:block;font:11px/1.5 var(--mono);color:var(--faint);margin-top:6px}
.hexwrap{display:grid;grid-template-columns:minmax(0,1fr);gap:14px;margin-top:14px}
/* A grid item is as wide as its content unless it is told otherwise, and the
   hex dump is eighty columns wide: without this the panel pushed the page. */
.hexwrap>div{min-width:0}
.hexwrap .ranges{border-top:1px solid var(--line);padding-top:12px}
.hex{font:11.5px/1.7 var(--mono);color:var(--ink-2);overflow-x:auto}
.hex div{white-space:pre}
.hex .o{color:var(--faint)}
.hex .r-frame{color:var(--line-3)}.hex .r-app{color:var(--metadata)}.hex .r-sof{color:var(--brand)}
.hex .r-table{color:var(--activity)}.hex .r-sos{color:var(--accent)}
.hex .r-scan,.hex .r-tail{color:var(--muted)}
.qual{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
border-top:1px solid var(--line)}
.qual>div{padding:10px 12px}
.qual>div+div{border-left:1px solid var(--line)}
.qual .v{font:300 18px/1.3 var(--mono);color:var(--ink);margin-top:4px}
.qual .v .small{font-size:var(--t-small);font-family:var(--sans)}
/* The quantization tables themselves, which are what a signature is a name for */
.matrices{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;
padding:12px;border-top:1px solid var(--line)}
.matrices .label{display:block;margin-bottom:5px}
.matrix{font:400 11px/1.45 var(--mono);color:var(--ink-2);background:var(--sunken);
border:1px solid var(--line);border-radius:var(--r);padding:8px 10px;overflow-x:auto;margin:0}
/* the metadata table's own bar: a filter, the blocks, and the switches a forensic
   table is read with */
.meta-bar{display:flex;align-items:center;gap:8px;padding:8px 12px;
border-bottom:1px solid var(--line);flex-wrap:wrap}
.search{display:flex;align-items:center;gap:8px;flex:1;min-width:240px;
border:1px solid var(--line-2);border-radius:var(--r);padding:0 10px;height:30px;
background:var(--sunken);color:var(--muted)}
.search input{flex:1;min-width:0;background:none;border:0;color:var(--ink);
font:12.5px var(--sans);outline:none}
.count{font:12px var(--mono);color:var(--accent);white-space:nowrap}
.btn.bad{border-color:var(--alert);color:var(--alert)}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:currentColor;flex:none}
/* only a pointer can work these, so they are not offered without a script */
.needs-js{display:none}
.js .needs-js{display:flex}
/* footer */
footer{display:flex;flex-wrap:wrap;gap:6px 22px;padding:18px var(--gutter) 26px;
border-top:1px solid var(--line);color:var(--faint);font:400 var(--t-label)/1.6 var(--mono)}
.to-top{position:fixed;right:18px;bottom:18px;z-index:40;background:var(--surface-2)}
@media(max-width:1080px){
.shell{grid-template-columns:minmax(0,1fr)}
.rail{position:static;max-height:none;border-right:0;border-bottom:1px solid var(--line);
display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));align-items:start}
.rail-block{border-bottom:0;border-right:1px solid var(--line)}
:root{--cols:1}
}
@media(max-width:760px){
.mast-body{grid-template-columns:1fr;gap:16px}
.mast .mark{max-height:72px}
.rail{grid-template-columns:1fr}
.rail-block{border-right:0;border-bottom:1px solid var(--line)}
.panels{column-count:1}
.image-stage{min-height:200px;padding:10px}
.deck-id .path{display:none}
.image-stage>.reg{width:min(100%,calc(clamp(180px,42vh,420px) * var(--arn,1.3333)))}
.hexwrap .ranges{padding-top:10px}
.qual{grid-template-columns:1fr}
.qual>div+div{border-left:0;border-top:1px solid var(--line)}
.matrices{grid-template-columns:1fr}
.meta-bar{gap:6px}
}
@media print{
.nav,.rail,.deck,.to-top,.fold,.blend,.lens,.needs-js,.meta-bar{display:none!important}
.js .frame:not([data-current]){display:block}
.js [data-pane]:not(.on){display:block}
[data-pane] .pane-name{display:block}
html,body{background:#fff;color:#111}
.shell{display:block}
.panels{column-count:2}
.panel,.card,.stat,.keyfacts{border-color:#bbb;background:#fff;break-inside:avoid}
.bar,th{background:#f4f4f4;color:#333;border-color:#999}
.bar .t,.label,.stat .label{color:#333}
.reading,.body,td{color:#111}
.caution{color:#444;border-top-color:#999}
.caution b{color:#7a5a1a}
.foot{color:#555;border-top-color:#999}
.small,.hex .o,td.m,td.dim,.stat .sub,.brow .n,.facts dt,.cap{color:#555}
td{border-bottom-color:#ccc}
tr.conflict td{background:#fbe9e2}tr.conflict td.k{color:#9a3d1f}
tr.signal td{background:#fbf3e2}tr.signal td.k{color:#7a5a1a}
.reg{background:#eee;border-color:#999}.rm{border-color:#111}
.chart{background:#f7f7f7;border-color:#999}
.regtag{background:#fff;color:#333;border-color:#999}
.tag{color:#555}.tag.conflict{color:#9a3d1f;background:#fbe9e2}.tag.signal{color:#7a5a1a;background:#fbf3e2}
.blk{background:#eee;color:#333}
.scroll{max-height:none;overflow:visible}
.plate-over{display:none}
section.folded .sec-body{display:block}
a{color:#111}
}

/* the case summary: what the collection is, before any one image */
.section{padding:26px var(--gutter);border-top:1px solid var(--line)}
.section:first-child{border-top:0}
.section-h{display:flex;align-items:baseline;gap:14px;margin-bottom:16px;flex-wrap:wrap}
.section-h h2{font:500 var(--t-h2)/1.2 var(--sans)}
.section-h .small{font-size:var(--t-small);max-width:86ch}
.small{font-size:var(--t-small);color:var(--muted)}
.label{font:600 var(--t-label)/1 var(--sans);letter-spacing:var(--track);text-transform:uppercase;color:var(--muted)}
.sp{flex:1;min-width:0}
.stats{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:1px;background:var(--line);
border:1px solid var(--line);border-radius:var(--r);overflow:hidden}
.stat{background:var(--surface);padding:14px 16px;min-width:0}
.stat .n{font:300 30px/1 var(--mono);color:var(--ink);letter-spacing:-.02em}
.stat .n em{font-style:normal;color:var(--alert)}
.stat .label{display:block;margin-top:8px}
.stat .sub{font:11px/1.45 var(--mono);color:var(--faint);margin-top:5px;overflow-wrap:anywhere}
/* two columns, never three: geolocation takes the row under them */
.summary-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-top:16px;align-items:start}
.bars{display:flex;flex-direction:column;gap:6px}
.brow{display:grid;grid-template-columns:150px 1fr 36px;gap:10px;align-items:center;font-size:var(--t-small)}
.brow .k{color:var(--ink-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.brow .b{height:8px;background:var(--surface-2);border-radius:1px;overflow:hidden}
.brow .b i{display:block;height:100%;background:var(--line-3)}
.brow.none .b i{background:var(--line-2)}
.brow .n{font:11px var(--mono);color:var(--muted);text-align:right}
.js [data-pane]:not(.on){display:none}
[data-pane]+[data-pane]{margin-top:14px}
.js [data-pane]+[data-pane]{margin-top:0}
[data-pane] .pane-name{display:block;margin-bottom:6px}
.js [data-pane] .pane-name{display:none}
/* the panel shape the summary's cards use */
.bar{display:flex;align-items:center;gap:10px;padding:0 12px;min-height:38px;
border-bottom:1px solid var(--line);flex-wrap:wrap}
.bar .t{font:600 var(--t-label)/1 var(--sans);letter-spacing:var(--track);text-transform:uppercase;color:var(--ink-2);white-space:nowrap}
.bar .fam{font-size:11px;color:var(--faint);letter-spacing:.04em;min-width:0;
overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.reading{padding:9px 12px;font-size:var(--t-small);color:var(--ink-2);
border-bottom:1px solid var(--line);line-height:1.45;max-width:104ch}
.reading .lab{display:block;margin-bottom:4px;font:600 var(--t-label)/1 var(--sans);
letter-spacing:var(--track);text-transform:uppercase;color:var(--brand)}
.body{padding:12px;min-width:0}
.body.flush{padding:0;overflow-x:auto}
.body.sunk{padding:0;background:var(--sunken)}
.caution{padding:8px 12px;border-top:1px dashed var(--line-2);font-size:var(--t-small);
color:var(--muted);line-height:1.45}
.caution b{color:var(--activity);font-weight:600;letter-spacing:.08em;text-transform:uppercase;
font-size:10.5px;margin-right:6px}
.foot{display:flex;align-items:center;gap:16px;padding:6px 12px;min-height:30px;
border-top:1px solid var(--line);font:11px/1.5 var(--mono);color:var(--faint);flex-wrap:wrap}
.seg{display:flex;gap:2px;flex-wrap:wrap}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:28px;
padding:0 10px;border:1px solid var(--line-2);border-radius:var(--r);background:var(--surface);
color:var(--ink-2);font:500 12px/1 var(--sans);white-space:nowrap}
.btn:hover{border-color:var(--accent);color:var(--ink);text-decoration:none}
.btn[aria-pressed=true]{border-color:var(--accent);color:var(--ink);background:var(--brand-soft)}
/* geolocation at full size */
.site-body{height:min(60vh,560px)}
.world-body{height:180px}
.region-body{height:200px}
.scroll{overflow:auto;max-height:560px}
.blk{display:inline-block;padding:1px 6px;border-radius:2px;font:600 10.5px/1.5 var(--mono);
letter-spacing:.06em;white-space:nowrap}
.blk.meta{color:var(--metadata);background:var(--metadata-soft)}
.blk.act{color:var(--activity);background:var(--activity-soft)}
.blk.org{color:var(--brand);background:var(--brand-soft)}
@media(max-width:1000px){
.stats{grid-template-columns:repeat(3,minmax(0,1fr))}
.summary-grid{grid-template-columns:minmax(0,1fr)}
}
@media(max-width:760px){.stats{grid-template-columns:repeat(2,minmax(0,1fr))}}

/* two views: the collection, and one image */
.js .view:not(.on){display:none}
.view{min-width:0}
.scope{padding:20px var(--gutter);border-top:1px solid var(--line);background:var(--surface);
display:grid;grid-template-columns:minmax(0,1fr) auto;gap:16px 40px;align-items:start}
.scope p{max-width:92ch;font-size:var(--t-small);color:var(--muted);line-height:1.7}
.scope b{display:block;font:600 var(--t-label)/1.4 var(--sans);letter-spacing:var(--track);
text-transform:uppercase;color:var(--activity);margin-bottom:5px}
.scope .facts{display:grid;grid-template-columns:auto auto;gap:4px 18px;font-size:var(--t-small)}
.scope .facts dt{color:var(--faint);letter-spacing:.06em;text-transform:uppercase;
font:600 var(--t-label)/1.5 var(--sans);padding-top:2px}
.scope .facts dd{font-family:var(--mono);color:var(--ink-2);overflow-wrap:anywhere}
@media(max-width:1000px){.scope{grid-template-columns:minmax(0,1fr)}}
@media print{.js .view:not(.on){display:block}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*{transition:none!important}}
"""

SCRIPT = r"""
(function(){
  var all=function(selector,within){return Array.prototype.slice.call((within||document).querySelectorAll(selector))};
  document.body.classList.add("js");

  // A section folds from its own heading, so a long report is read a part at a
  // time. Folding hides; nothing is removed, and print puts it all back.
  all("main > section").forEach(function(section){
    var fold=section.querySelector(".h .fold"),title=section.querySelector(".h h2");
    if(!fold){return}
    var turn=function(){
      var shut=section.classList.toggle("folded");
      fold.setAttribute("aria-expanded",String(!shut));
    };
    fold.addEventListener("click",turn);
    if(title){title.addEventListener("click",turn)}
  });

  // The image comparison panel. A map laid over the image at a chosen opacity says
  // not "this map is bright" but "this part of this image is bright",
  // which is the part a reader can check. A chart cannot be laid over anything
  // and says so by taking the stage for itself.
  all(".frame").forEach(function(frame){
    var stage=frame.querySelector(".image-stage"),
        over=frame.querySelector(".plate-over"),
        bar=frame.querySelector(".blend"),
        lens=frame.querySelector(".lens"),
        tag=frame.querySelector(".stage-state"),
        clear=frame.querySelector("[data-clear]"),
        slider=frame.querySelector("[data-blend]"),
        readout=frame.querySelector(".blend output"),
        swaps=all(".swap button",frame),
        picks=all("[data-lens]",frame),
        base=tag?tag.textContent:"";
    if(!over||!bar||!picks.length){return}
    bar.hidden=false;
    if(lens){lens.hidden=false}
    function opacity(){
      var solo=bar.getAttribute("data-solo")==="on",
          value=solo?100:Number(slider.value);
      stage.style.setProperty("--blend",value/100);
      readout.textContent=value+"%";
      swaps.forEach(function(button){
        var pressed=!solo&&over.hidden===false&&(button.getAttribute("data-swap")==="original"?value===0:value===100);
        button.setAttribute("aria-pressed",String(pressed));
      });
    }
    // The map put in the overlay is the one already rendered in its own panel, so
    // a report that carries its images inside itself carries each of them once.
    // Two buttons offer the same map - one under the image, one in the map's
    // own panel - so the pressed state is held by key rather than by element.
    function put(key){
      var pick=null;
      picks.forEach(function(other){
        var same=other.getAttribute("data-lens")===key;
        other.setAttribute("aria-pressed",String(same));
        if(same&&!pick){pick=other}
      });
      clear.setAttribute("aria-pressed",String(!key));
      var panel=key?document.getElementById(frame.id+"-"+key):null,
          picture=panel?panel.querySelector("img"):null,
          source=picture?picture.getAttribute("src"):null;
      if(!pick||!source){
        over.hidden=true;over.removeAttribute("src");
        bar.removeAttribute("data-solo");
        slider.disabled=true;
        if(tag){tag.textContent=base;tag.classList.add("in");tag.classList.remove("off")}
        opacity();return;
      }
      over.src=source;
      over.hidden=false;
      var solo=pick.hasAttribute("data-solo");
      if(solo){bar.setAttribute("data-solo","on")}else{bar.removeAttribute("data-solo")}
      slider.disabled=solo;
      if(tag){
        tag.textContent=pick.getAttribute("data-name")+(solo?" \u00b7 shown alone":" \u00b7 over the image");
        tag.classList.toggle("off",solo);
        tag.classList.toggle("in",!solo);
      }
      opacity();
    }
    picks.forEach(function(pick){
      pick.addEventListener("click",function(){
        put(pick.getAttribute("aria-pressed")==="true"?null:pick.getAttribute("data-lens"));
      });
    });
    clear.addEventListener("click",function(){put(null)});
    slider.addEventListener("input",opacity);
    swaps.forEach(function(button){
      button.addEventListener("click",function(){
        if(slider.disabled){return}
        slider.value=button.getAttribute("data-swap")==="original"?0:100;
        opacity();
      });
    });
    put(null);
  });

  // One image at a time, with the rail saying which and the analysis tree
  // saying what this one has. Without this the page is the same
  // document from first to last, which is what print goes back to.
  var frames=all(".frame"),
      roll=all(".roll a"),
      leaves=all(".tree a[data-tool]"),
      deck=document.querySelector(".deck"),
      at=document.getElementById("deck-at"),
      named=document.getElementById("deck-name"),
      where=document.getElementById("deck-path"),
      kind=document.getElementById("deck-format"),
      back=document.getElementById("deck-prev"),
      on=document.getElementById("deck-next"),
      current=-1;
  function show(index,jump){
    if(!frames.length){return}
    index=Math.max(0,Math.min(frames.length-1,index));
    current=index;
    frames.forEach(function(frame,which){
      if(which===index){frame.setAttribute("data-current","")}else{frame.removeAttribute("data-current")}
    });
    roll.forEach(function(link,which){link.setAttribute("aria-current",String(which===index))});
    var frame=frames[index],held=(frame.getAttribute("data-has")||"").split(" ");
    leaves.forEach(function(leaf){
      var key=leaf.getAttribute("data-tool"),has=held.indexOf(key)>=0;
      leaf.setAttribute("data-state",has?"has":"none");
      leaf.setAttribute("href",has?"#"+frame.id+"-"+key:"#images");
      leaf.setAttribute("aria-current","false");
      leaf.setAttribute("title",has?"":"not produced for this image");
    });
    if(at){at.textContent="#"+frame.getAttribute("data-no")+" of "+frames.length}
    if(named){named.textContent=frame.getAttribute("data-name")}
    if(where){where.textContent=frame.getAttribute("data-path")}
    if(kind){kind.textContent=frame.getAttribute("data-format")}
    if(back){back.disabled=index===0}
    if(on){on.disabled=index===frames.length-1}
    if(jump&&deck){deck.scrollIntoView({block:"start"})}
  }
  roll.forEach(function(link,which){
    link.addEventListener("click",function(event){
      event.preventDefault();
      openView("images");
      show(which,true);
    });
  });
  leaves.forEach(function(leaf){
    leaf.addEventListener("click",function(){
      leaves.forEach(function(other){other.setAttribute("aria-current",String(other===leaf))});
    });
  });
  if(back){back.addEventListener("click",function(){show(current-1,true)})}
  if(on){on.addEventListener("click",function(){show(current+1,true)})}
  all("[data-cols]").forEach(function(button){
    button.addEventListener("click",function(){
      document.documentElement.style.setProperty("--cols",button.getAttribute("data-cols"));
      all("[data-cols]").forEach(function(other){
        other.setAttribute("aria-pressed",String(other===button));
      });
    });
  });
  // A reader with an image on screen reaches for the arrow keys before the
  // buttons, unless they are typing into the filter.
  document.addEventListener("keydown",function(event){
    var tag=(event.target.tagName||"").toLowerCase();
    if(tag==="input"||tag==="textarea"||event.metaKey||event.ctrlKey||event.altKey){return}
    if(event.key==="ArrowLeft"){show(current-1,true)}
    else if(event.key==="ArrowRight"){show(current+1,true)}
  });
  // A link into an image, from the rail or from the address bar, has to open
  // that image rather than scroll to something that is not on screen.
  // A panel or a finding inside it is scrolled to itself rather than to the
  // top of its image, or a link to F03 lands a screen above the row it names.
  function fromHash(){
    var id=(location.hash||"").slice(1);
    if(!id){return false}
    for(var index=0;index<frames.length;index++){
      if(frames[index].id===id||id.indexOf(frames[index].id+"-")===0){
        var inner=id!==frames[index].id?document.getElementById(id):null;
        openView("images");
        show(index,!inner);
        if(inner){
          // Straight there: the view has just changed under the reader, so no
          // scroll position is worth animating away from, and a page still
          // laying itself out would leave a smooth scroll short of the row.
          var root=document.documentElement.style;
          root.scrollBehavior="auto";
          inner.scrollIntoView({block:"start"});
          root.scrollBehavior="";
        }
        return true;
      }
    }
    return false;
  }
  if(frames.length){show(0,false)}
  window.addEventListener("hashchange",fromHash);
  // A link to what is already in the address bar changes nothing the browser
  // reports, so a reader going back to a finding they have read would click
  // and see nothing happen.
  document.addEventListener("click",function(event){
    var link=event.target.closest?event.target.closest('a[href^="#photo-"]'):null;
    if(link&&location.hash===link.getAttribute("href")){event.preventDefault();fromHash()}
  });

  // What the stage is doing to the picture, said in the strip under it.
  all(".image-stage").forEach(function(stage){
    var picture=stage.querySelector(".plate-base"),
        panel=stage.closest(".panel"),
        out=panel?panel.querySelector("[data-zoom]"):null;
    if(!picture||!out){return}
    var say=function(){
      if(!picture.naturalWidth||!picture.naturalHeight){return}
      var box=picture.getBoundingClientRect();
      if(!box.width){return}
      var factor=Math.min(box.width/picture.naturalWidth,box.height/picture.naturalHeight);
      out.textContent="zoom "+Math.round(factor*100)+" %";
      stage.classList.toggle("sharp",factor>1.4);
    };
    picture.addEventListener("load",say);
    // The frame an image sits in starts hidden, so the picture has no box
    // and often no decoded size until a reader opens it. Watching the element
    // catches both, where a load event on its own does not.
    if(window.ResizeObserver){new ResizeObserver(say).observe(picture)}
    window.addEventListener("resize",say,{passive:true});
    say();
  });


  // Two views, because a report is about a collection and about one image
  // at a time, and those are different things to read. Without a script both are
  // on the page one after the other, which is what print goes back to.
  var views=all(".view"),navLinks=all("[data-goto]");
  // One link is current, not every link into the view: four sections share the
  // summary, and a screen reader told all four are current is told nothing.
  function openView(name,chosen){
    views.forEach(function(view){view.classList.toggle("on",view.getAttribute("data-view")===name)});
    var current=chosen||navLinks.filter(function(link){return link.getAttribute("data-goto")===name})[0];
    navLinks.forEach(function(link){link.setAttribute("aria-current",String(link===current))});
  }
  navLinks.forEach(function(link){
    link.addEventListener("click",function(event){
      var name=link.getAttribute("data-goto"),to=link.getAttribute("href").slice(1);
      event.preventDefault();
      openView(name,link);
      var target=to?document.getElementById(to):null;
      if(target){target.scrollIntoView({block:"start"})}else{window.scrollTo({top:0})}
    });
  });
  // A link into an image, from a note or a bookmark, opens on that image. The
  // summary is where a reader starts only when the address asked for nothing.
  if(!fromHash()){openView("summary")}

  // One axis of a cluster, one scale of geolocation. Without a script every
  // one of them is on the page; this only decides which is in front.
  all("[data-switch]").forEach(function(group){
    var name=group.getAttribute("data-switch"),
        panes=all('[data-pane="'+name+'"]'),
        buttons=all('[data-show="'+name+'"]',group);
    function choose(key){
      panes.forEach(function(pane){pane.classList.toggle("on",pane.getAttribute("data-key")===key)});
      buttons.forEach(function(button){button.setAttribute("aria-pressed",String(button.getAttribute("data-key")===key))});
    }
    buttons.forEach(function(button){
      button.addEventListener("click",function(){choose(button.getAttribute("data-key"))});
    });
    if(buttons.length){choose(buttons[0].getAttribute("data-key"))}
  });

  // The metadata table. Without a script the table is delivered whole; this hides
  // rows, and says how many it left.
  var search=document.getElementById("meta-filter");
  if(search){
    var rows=all("#meta-rows tr"),cells=null,
        counted=document.getElementById("meta-count"),
        blank=document.getElementById("meta-empty"),
        cased=document.getElementById("meta-case"),
        whole=document.getElementById("meta-word"),
        expr=document.getElementById("meta-regex"),
        onlyBad=document.getElementById("meta-conflict"),
        blocks=all("[data-block]"),
        block="";
    var sift=function(){
      var query=search.value,kept=0,test=null,bad=false;
      var matchCase=cased&&cased.getAttribute("aria-pressed")==="true";
      if(expr&&expr.getAttribute("aria-pressed")==="true"&&query){
        try{test=new RegExp(query,matchCase?"":"i")}
        catch(error){bad=true;test=null}
      }else if(whole&&whole.getAttribute("aria-pressed")==="true"&&query){
        try{test=new RegExp("\\b"+query.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")+"\\b",matchCase?"":"i")}
        catch(error){test=null}
      }
      if(expr){expr.classList.toggle("bad",bad)}
      if(bad){query=""}
      var plain=matchCase?query:query.toLowerCase(),
          wantBad=onlyBad&&onlyBad.getAttribute("aria-pressed")==="true";
      // Read out once: the text of eleven thousand cells is the same on every
      // keystroke, and reading it again is what made the filter stutter.
      if(!cells){cells=rows.map(function(row){
        return all("td",row).map(function(cell){return cell.textContent.trim()});
      })}
      rows.forEach(function(row,index){
        var hit=!plain&&!test;
        if(!hit){
          hit=cells[index].some(function(value){
            if(test){return test.test(value)}
            return (matchCase?value:value.toLowerCase()).indexOf(plain)>=0;
          });
        }
        if(hit&&block){hit=row.getAttribute("data-blk")===block}
        if(hit&&wantBad){hit=!!row.getAttribute("data-state")}
        row.hidden=!hit;
        if(hit){kept++}
      });
      if(blank){blank.hidden=kept>0}
      if(counted){counted.textContent="showing "+kept+" of "+rows.length}
    };
    search.addEventListener("input",sift);
    [cased,whole,expr,onlyBad].forEach(function(button){
      if(!button){return}
      button.addEventListener("click",function(){
        button.setAttribute("aria-pressed",String(button.getAttribute("aria-pressed")!=="true"));
        sift();
      });
    });
    blocks.forEach(function(button){
      button.addEventListener("click",function(){
        block=button.getAttribute("data-block");
        blocks.forEach(function(other){other.setAttribute("aria-pressed",String(other===button))});
        sift();
      });
    });
    // An image's own fields are one filter away rather than one copy away.
    all("[data-filter]").forEach(function(link){
      link.addEventListener("click",function(event){
        event.preventDefault();
        openView("summary");
        search.value=link.getAttribute("data-filter");
        if(expr){expr.setAttribute("aria-pressed","false")}
        block="";
        blocks.forEach(function(other,index){other.setAttribute("aria-pressed",String(index===0))});
        sift();
        var seen=document.getElementById("metadata");
        if(seen){seen.scrollIntoView({block:"start"})}
      });
    });
  }

  // What is on screen leaves as text the reader can paste. The page reaches
  // nothing to do it: the clipboard is the one door out that is not a request.
  all("[data-copy]").forEach(function(button){
    if(!navigator.clipboard){return}
    button.hidden=false;
    button.addEventListener("click",function(){
      var target=document.getElementById(button.getAttribute("data-copy")),text="";
      if(!target){return}
      if(target.tagName==="TABLE"||target.tagName==="TBODY"){
        text=all("tr",target).filter(function(row){return !row.hidden}).map(function(row){
          return all("th,td",row).map(function(cell){return cell.textContent.trim()}).join("\t");
        }).join("\n");
      }else{text=target.textContent.trim()}
      navigator.clipboard.writeText(text).then(function(){
        var said=button.querySelector("span");
        if(!said){return}
        var was=said.textContent;said.textContent="copied";
        setTimeout(function(){said.textContent=was},1400);
      },function(){});
    });
  });

  var paper=document.getElementById("print");
  if(paper){paper.addEventListener("click",function(){window.print()})}

  var up=document.getElementById("to-top");
  if(up){
    up.addEventListener("click",function(){window.scrollTo({top:0,behavior:"smooth"})});
    var watch=function(){up.hidden=window.scrollY<500};
    window.addEventListener("scroll",watch,{passive:true});
    watch();
  }
})();
"""


@dataclass(frozen=True, slots=True)
class _Assets:
    """Where a report's images go when they are not carried inside the page.

    An image is already a file on disk, so the page points at it where it
    lies. A derived map is not a file anywhere, so it is written beside the page
    and pointed at there. The two move together as one directory.
    """

    directory: Path
    page: Path

    def source(self, photo: PhotoResult, artifact: PhotoArtifact) -> str:
        if artifact.key == "main-preview" and Path(photo.path).suffix.lower() in _RENDERABLE:
            linked = _relative(Path(photo.path), self.page)
            if linked is not None:
                return linked
        name = f"{photo.number:03d}-{artifact.key}{_SUFFIXES.get(artifact.mime, '.bin')}"
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / name).write_bytes(artifact.data)
        return f"{quote(self.directory.name)}/{name}"


def _relative(target: Path, page: Path) -> str | None:
    try:
        walked = os.path.relpath(target, page.parent)
    except ValueError:
        return None
    return quote(PurePath(walked).as_posix())


def render_photo_html(
    collection: PhotoCollection,
    *,
    output: Path | None = None,
    now: datetime | None = None,
    assets: Path | None = None,
) -> str:
    """Render one complete photo-forensics report.

    With `assets` the images are written into that directory and pointed at, and
    the page is the small part; without it every image is carried inside the page
    and the report is one file. `assets` needs `output`, because a relative link
    is relative to something.
    """
    if assets is not None and output is None:
        raise ValueError("assets needs output: a link is relative to the page holding it")
    written = _Assets(assets, output) if assets is not None and output is not None else None
    moment = (now or datetime.now().astimezone()).strftime("%Y-%m-%d %H:%M %Z").strip()
    title = f"{output.name} - Image examination report" if output else "Image examination report"
    rows = _field_rows(collection)
    from . import photomap

    fixes = _fixes(collection)
    refs = _refs(collection)
    # Everything that speaks for the whole collection is one view; the
    # images are the other. Neither is a section of the other.
    collected = (
        _summary(collection, rows)
        + _key_findings(collection, refs)
        + _section("metadata", "Metadata", str(len(rows)), _metadata_table(rows))
        + (_geolocation(fixes) if fixes else "")
    )
    places = [
        ("summary", "summary", "Case summary"),
        ("findings", "summary", "Findings"),
        ("metadata", "summary", "Metadata"),
    ]
    if fixes:
        places.append(("geolocation", "summary", "Geolocation"))
    places.append(("", "images", "Images"))
    head = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{LINKED_POLICY if written else POLICY}">'
        '<meta name="referrer" content="no-referrer">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="dark">'
        f"<title>{_e(title)}</title>{FAVICON}<style>{STYLE}</style></head><body>{ICONS}"
    )
    links = "".join(
        f'<a href="#{key}" data-goto="{view}" aria-current="false">{_e(name)}</a>'
        for key, view, name in places
    )
    nav = (
        '<nav class="nav"><a class="home" href="#top" title="Back to the top" '
        f'aria-label="Back to the top">{MARK_SMALL}</a>{links}<span class="grow"></span>'
        '<div class="nav-actions"><button class="btn icon" id="print" type="button" '
        'title="Print / PDF" aria-label="Print / PDF">'
        '<svg class="ic" aria-hidden="true"><use href="#i-print"/></svg></button></div></nav>'
    )
    # The images take no heading of their own: the bar above them names the
    # one being read and follows the reader down.
    main = (
        f'<div class="view on" data-view="summary">{collected}</div>'
        f'<div class="view" data-view="images">'
        f'<section class="bare" id="images">{_workspace(collection, written, refs)}</section>'
        "</div>"
    )
    top = (
        '<button class="btn icon to-top" id="to-top" type="button" title="Back to top" '
        'aria-label="Back to top" hidden><svg class="ic" aria-hidden="true">'
        '<use href="#i-up"/></svg></button>'
    )
    footer = (
        f"<footer><span>filegrail v{_e(__version__)} / Apache-2.0</span>"
        f"<span>generated {_e(moment)}</span>"
        "<span>this page makes no network requests</span></footer>"
    )
    return (
        head
        + (photomap.defs() if fixes else "")
        + nav
        + _mast(collection, moment, output, written)
        + f'<div class="shell">{_rail(collection, written)}<main>{main}</main></div>'
        + f'<section class="scope" id="scope">{_scope(collection, written)}</section>'
        + top
        + footer
        + f"<script>{SCRIPT}</script></body></html>"
    )


def _mast(
    collection: PhotoCollection, moment: str, output: Path | None, written: _Assets | None
) -> str:
    facts = [("target", collection.root), ("analysed", moment)]
    if output is not None:
        facts.append(("report", str(output)))
    # Where the images are is the first thing to know about a page that may not
    # carry them: one of these reports travels alone and one does not, and a
    # reader has to be told which they are holding.
    facts.append(
        (
            "media",
            "redacted"
            if collection.redacted
            else ("linked beside the page" if written else "carried in the page"),
        )
    )
    pairs = "".join(f"<dt>{_e(label)}</dt><dd>{_e(value)}</dd>" for label, value in facts)
    return (
        '<header class="mast" id="top">'
        f'<h1 class="word">filegrail <small>v{_e(__version__)} / image examination</small></h1>'
        f'<div class="mast-body"><div class="mast-mark">{MARK}</div>'
        f'<dl class="facts">{pairs}</dl></div></header>'
    )


def _rail(collection: PhotoCollection, written: _Assets | None) -> str:
    """The two things that stay on screen: the evidence, and the analyses.

    A report that only scrolls asks the reader to hold the shape of it in their
    head. A rail holds it instead: what was examined, what this tool can bring
    to bear on an image, and which of each the reader is looking at.
    """
    roll = []
    for photo in collection.photos:
        broken = sum(1 for fact in photo.facts if fact.state == "conflict")
        artifact = _first_artifact(photo, *_PHOTOGRAPHIC)
        thumb = (
            f'<span class="th">{_image(artifact, photo.name, photo, written)}</span>'
            if artifact
            else f'<span class="th none">{_e(photo.format)}</span>'
        )
        signals = sum(1 for fact in photo.facts if fact.state == "signal")
        stamps = ""
        if broken:
            stamps += (
                f'<span class="tag conflict">{broken} conflict{"s" if broken > 1 else ""}</span>'
            )
        if signals:
            stamps += (
                f'<span class="tag signal">{signals} signal{"s" if signals > 1 else ""}</span>'
            )
        if _first_artifact(photo, "embedded-preview", "maker-preview"):
            stamps += '<span class="tag preview">preview</span>'
        if not artifact:
            stamps += '<span class="tag nodecode">no decode</span>'
        roll.append(
            f'<li><a href="#photo-{photo.number:03d}">'
            f'<span class="no">{photo.number:03d}</span>{thumb}'
            f'<span class="nm" title="{_e(photo.name)}">{_e(photo.name)}</span>'
            f'<span class="sub">{_e(photo.camera or "camera not recorded")}</span>'
            f'<span class="st">{stamps}</span></a></li>'
        )
    listed = (
        f'<ol class="roll">{"".join(roll)}</ol>'
        if roll
        else '<p class="empty" style="padding:0 15px 10px">nothing to examine</p>'
    )
    evidence = (
        f'<div class="rail-block"><h2>Images <span class="n">{len(collection.photos)}</span></h2>'
        f"{listed}</div>"
    )
    # An analysis that produced nothing anywhere in this report is still named
    # and set back rather than dropped. A reader has to be able to tell a method
    # that found nothing from a method that was never brought, and the rail is
    # the only place that can say which.
    anywhere = _available(collection)
    branches = []
    for category, leaves in _TREE:
        entries = []
        for key, label in leaves:
            if key not in anywhere:
                entries.append(
                    '<li><span class="leaf" title="not produced for any image here">'
                    f'<i class="dot"></i>{_e(label)}</span></li>'
                )
                continue
            entries.append(
                f'<li><a href="#images" data-tool="{_e(key)}" data-state="has">'
                f'<i class="dot"></i>{_e(label)}</a></li>'
            )
        branches.append(
            f'<li><span class="cat">{_e(category)}</span><ul>{"".join(entries)}</ul></li>'
        )
    tools = (
        f'<div class="rail-block"><h2>Analyses</h2><ul class="tree">{"".join(branches)}</ul></div>'
    )
    return f'<aside class="rail" aria-label="Images and analyses">{evidence}{tools}</aside>'


def _available(collection: PhotoCollection) -> set[str]:
    """Every analysis that produced something for at least one image."""
    found = {"image", "fileinfo", "findings", "coverage"}
    for photo in collection.photos:
        found.update(artifact.key for artifact in photo.artifacts)
        if photo.evidence:
            found.add("fields")
        if photo.jpeg is not None:
            found.update(("structure", "markers"))
    return found


def _held(photo: PhotoResult) -> list[str]:
    """Which analyses have a panel on this image."""
    keys = ["image", "fileinfo", "findings", "coverage"]
    if photo.evidence:
        keys.append("fields")
    if photo.jpeg is not None:
        keys.extend(("structure", "markers"))
    keys.extend(artifact.key for artifact in photo.artifacts if artifact.key != "main-preview")
    return keys


def _section(key: str, title: str, note: str, body: str) -> str:
    counted = f'<span class="n">{_e(note)}</span>' if note else ""
    fold = (
        f'<button class="fold" type="button" aria-expanded="true" aria-controls="{key}-body" '
        f'title="Collapse section" aria-label="Collapse {_e(title)}">'
        '<svg class="ic" aria-hidden="true"><use href="#i-chevron"/></svg></button>'
    )
    return (
        f'<section id="{key}"><div class="h">{fold}<h2>{_e(title)}</h2>{counted}</div>'
        f'<div class="sec-body" id="{key}-body">{body}</div></section>'
    )


def _card(
    key: str,
    title: str,
    family: str,
    body: str,
    *,
    reading: str = "",
    caution: str = "",
    foot: str = "",
    controls: str = "",
    flush: bool = False,
    sunk: bool = False,
    extra: str = "",
    element_id: str = "",
) -> str:
    """One analysis panel, with the anatomy every other panel also has.

    A bar that names it, a reading that says what it shows, a body, a caution
    that states the limitations, and a foot carrying the parameters. The
    reading and the caution are markup rather than something a script reveals,
    so they survive printing and a reader who never clicks anything.
    """
    guide = _GUIDE.get(key)
    if not reading and guide:
        reading = guide.shows
    if not caution and guide:
        caution = guide.caution
    ask = ""
    classes = "panel" + (f" {extra}" if extra else "")
    identifier = f' id="{_e(element_id)}"' if element_id else ""
    shape = "body" + (" flush" if flush else "") + (" sunk" if sunk else "")
    return (
        f'<section class="{classes}"{identifier}>'
        f'<div class="bar"><span class="t">{_e(title)}</span>'
        f'<span class="fam">{_e(family)}</span><span class="sp"></span>{controls}{ask}</div>'
        + (f'<div class="reading">{_e(reading)}</div>' if reading else "")
        + f'<div class="{shape}">{body}</div>'
        + (f'<div class="caution"><b>Limitations</b>{_e(caution)}</div>' if caution else "")
        + (f'<div class="foot">{foot}</div>' if foot else "")
        + "</section>"
    )


def _summary(collection: PhotoCollection, rows: list[tuple[str, str, str, str, str]]) -> str:
    """What the collection is, before any one image."""
    panels = _clusters(collection) + _times(collection)
    return (
        '<section class="section" id="summary"><div class="section-h"><h2>Case summary</h2>'
        '<span class="small">what the collection is, before any one image</span></div>'
        f"{_stats(collection, rows)}"
        f'<div class="summary-grid">{panels}</div></section>'
    )


def _key_findings(collection: PhotoCollection, refs: dict[tuple[int, int], str]) -> str:
    """Every numbered finding in the collection, each a link to the row it names."""
    by_number = {photo.number: photo for photo in collection.photos}
    rows = "".join(
        f"<tr{_flag(fact.state)}>"
        f'<td class="m"><a href="#photo-{number:03d}-{ref}">{ref}</a></td>'
        f'<td><span class="m">#{number:03d}</span> {_e(photo.name)}</td>'
        f'<td class="k">{_e(fact.state)}</td>'
        f"<td><b>{_e(fact.label)}</b> {_e(fact.value)}</td>"
        f'<td class="m">{_e(fact.method)}</td></tr>'
        for (number, index), ref in refs.items()
        for photo in (by_number[number],)
        for fact in (photo.facts[index],)
    )
    table = (
        '<div class="body flush"><div class="scroll"><table><thead><tr>'
        '<th style="width:56px">#</th><th style="width:240px">image</th>'
        '<th style="width:84px">state</th><th>finding</th><th style="width:200px">method</th>'
        f"</tr></thead><tbody>{rows}</tbody></table></div></div>"
        if rows
        else '<div class="body"><p class="small">No conflicts or signals were found in these'
        " images.</p></div>"
    )
    return _section(
        "findings",
        "Key findings",
        str(len(refs)),
        f'<div class="panel"><div class="reading">{_e(_NOTES["findings"])}</div>{table}'
        f'<div class="caution"><b>Limitations</b>{_e(_CAUTIONS["findings"])}</div></div>',
    )


def _stats(collection: PhotoCollection, rows: list[tuple[str, str, str, str, str]]) -> str:
    counted = len(collection.photos)
    formats: dict[str, int] = {}
    for photo in collection.photos:
        formats[photo.format] = formats.get(photo.format, 0) + 1
    embedded = sum(
        1
        for photo in collection.photos
        if _first_artifact(photo, "embedded-preview", "maker-preview")
    )
    conflicts = sum(
        1 for photo in collection.photos for fact in photo.facts if fact.state == "conflict"
    )
    signals = sum(
        1 for photo in collection.photos for fact in photo.facts if fact.state == "signal"
    )
    blocks: dict[str, None] = {}
    for _where, _name, block, _value, _state in rows:
        blocks[block] = None
    undecoded = counted - collection.rendered
    cards = (
        (
            str(counted),
            "images",
            " · ".join(
                f"{name} {count}"
                for name, count in sorted(formats.items(), key=lambda item: -item[1])
            ),
        ),
        (
            str(collection.rendered),
            "decoded to a preview",
            f"{undecoded} described without one" if undecoded else "every one of them",
        ),
        (str(embedded), "embedded previews", "written by the camera"),
        (str(conflicts), "conflicts", "two recorded things disagree", "alert"),
        (str(signals), "signal" if signals == 1 else "signals", "flagged for a reader"),
        (
            f"{len(rows):,}".replace(",", " "),
            "recorded fields",
            " · ".join(list(blocks)[:6]) or "none",
        ),
    )
    return (
        '<div class="stats">'
        + "".join(
            '<div class="stat"><div class="n">'
            + (f"<em>{_e(value)}</em>" if len(card) > 3 and value != "0" else _e(value))
            + f'</div><span class="label">{_e(label)}</span>'
            f'<div class="sub">{_e(sub)}</div></div>'
            for card in cards
            for value, label, sub in (card[:3],)
        )
        + "</div>"
    )


def _clusters(collection: PhotoCollection) -> str:
    """Which images share a source, on the four axes a file can be grouped by."""
    axes = (
        ("make", "camera make", lambda photo: _first_field(photo, "Make")),
        ("serial", "body serial", lambda photo: photo.serial),
        (
            "lens",
            "lens",
            lambda photo: _first_field(photo, "LensModel", "LensInfo", "LensSerialNumber"),
        ),
        ("encoder", "encoder signature", lambda photo: _signature(photo)),
    )
    panes = []
    buttons = []
    for key, label, pick in axes:
        counts: dict[str, int] = {}
        for photo in collection.photos:
            counts[pick(photo) or "not recorded"] = counts.get(pick(photo) or "not recorded", 0) + 1
        ordered = sorted(
            counts.items(), key=lambda item: (item[0] == "not recorded", -item[1], item[0])
        )
        largest = max((count for _name, count in ordered), default=1)
        bars = "".join(
            f'<div class="brow{" none" if name == "not recorded" else ""}">'
            f'<span class="k" title="{_e(name)}">{_e(name)}</span>'
            f'<span class="b"><i style="width:{count / largest * 100:.0f}%"></i></span>'
            f'<span class="n">{count}</span></div>'
            for name, count in ordered
        )
        panes.append(
            f'<div data-pane="clusters" data-key="{key}">'
            f'<span class="label pane-name">by {_e(label)}</span>'
            f'<div class="bars">{bars}</div></div>'
        )
        buttons.append(
            f'<button class="btn" type="button" data-show="clusters" data-key="{key}"'
            f' aria-pressed="false">{_e(label.split()[-1] if key != "encoder" else "encoder")}</button>'
        )
    groups = len({_first_field(photo, "Make") or "" for photo in collection.photos})
    return _card(
        "clusters",
        "Common source",
        "four axes",
        "".join(panes),
        controls=f'<span class="seg needs-js" data-switch="clusters">{"".join(buttons)}</span>',
        foot=f"<span>{len(collection.photos)} files</span><span>{groups} makes</span>",
    )


def _signature(photo: PhotoResult) -> str | None:
    """A short name for the encoder, made of what only an encoder decides.

    The quantization tables and the order of the markers around them are chosen
    by whatever last wrote the file, not by the scene, so two files that share
    them were written by the same software at the same setting. It is a name for
    a group, and the panel that shows it says so.
    """
    jpeg = photo.jpeg
    if jpeg is None or not jpeg.quantization:
        return None
    tables = ";".join(
        f"{table.identifier}:{table.precision}:" + ",".join(str(value) for value in table.values)
        for table in jpeg.quantization
    )
    order = "-".join(marker.name for marker in jpeg.markers if not 0xD0 <= marker.code <= 0xD7)
    digest = hashlib.sha256(f"{tables}|{order}".encode()).hexdigest()
    return digest[:8]


def _times(collection: PhotoCollection) -> str:
    """Every recorded capture time on one axis, and the files that record none."""
    stamped: list[tuple[PhotoResult, float]] = []
    silent = 0
    for photo in collection.photos:
        moment = _moment(photo)
        if moment is None:
            silent += 1
            continue
        stamped.append((photo, moment))
    if not stamped:
        body = '<p class="small">No image here records a capture time.</p>'
        return _card("times", "Capture times", "as recorded", body)
    first = min(value for _photo, value in stamped)
    last = max(value for _photo, value in stamped)
    low, high = int(first), int(last) + 1
    if high - low < 2:
        low, high = low - 1, high + 1
    step = max(1, round((high - low) / 8))
    ticks = "".join(
        f'<line x1="{_across(year, low, high):.1f}" y1="49" x2="{_across(year, low, high):.1f}"'
        ' y2="55" stroke="#45464A"/>'
        f'<text x="{_across(year, low, high):.1f}" y="70" fill="#7B828B" font-size="9"'
        ' font-family="IBM Plex Mono,monospace" text-anchor="middle">'
        f"{year}</text>"
        for year in range(low, high + 1, step)
    )
    marks = "".join(
        f'<rect x="{_across(value, low, high) - 1:.1f}" y="34" width="2" height="18"'
        f' fill="{"#D08770" if any(fact.state == "conflict" for fact in photo.facts) else "#C9A66B"}">'
        f"<title>#{photo.number:03d} {_e(photo.name)} · {_e(_captured(photo) or '')}</title></rect>"
        for photo, value in stamped
    )
    quiet = (
        f'<rect x="10" y="82" width="{380 * silent / len(collection.photos):.1f}" height="6" fill="#262628">'
        f"<title>{silent} with no recorded capture time</title></rect>"
        f'<text x="10" y="78" fill="#7B828B" font-size="9.5" font-family="IBM Plex Mono,monospace">'
        f"{silent} record no capture time</text>"
        if silent
        else ""
    )
    body = (
        '<svg viewBox="0 0 400 96" width="100%" height="96" role="img"'
        ' aria-label="Recorded capture times on one axis">'
        '<line x1="10" y1="52" x2="390" y2="52" stroke="#353537"/>'
        f"{ticks}{marks}{quiet}</svg>"
    )
    return _card(
        "times",
        "Capture times",
        "as recorded",
        body,
        foot=f"<span>axis {low} to {high}</span><span class='sp'></span>"
        f"<span>{len(stamped)} of {len(collection.photos)} carry one</span>",
    )


def _across(value: float, low: int, high: int) -> float:
    return 10 + (value - low) / max(high - low, 1) * 380


def _spread(fixes: list[Fix]) -> tuple[float, str]:
    """How far apart the located images are, in metres and as a phrase."""
    import math

    if len(fixes) < 2:
        return 0.0, ""
    reach = 0.0
    for index, one in enumerate(fixes):
        for other in fixes[index + 1 :]:
            across = 111_320.0 * math.cos(math.radians((one.latitude + other.latitude) / 2))
            metres = math.hypot(
                (one.longitude - other.longitude) * across,
                (one.latitude - other.latitude) * 111_320.0,
            )
            reach = max(reach, metres)
    if reach >= 100_000:
        return reach, f"{reach / 1000:.0f} km"
    if reach >= 1000:
        return reach, f"{reach / 1000:.1f} km"
    return reach, f"{reach:.0f} m"


def _geolocation(fixes: list[Fix]) -> str:
    """Three scales, none of them a map tile."""
    from . import photomap

    dots = tuple((*photomap.project(fix.latitude, fix.longitude), 12.0) for fix in fixes)
    near = tuple((*photomap.project(fix.latitude, fix.longitude), 6.0) for fix in fixes)
    view = photomap.window(fixes)
    left, top, wide, high = (float(part) for part in view.split())
    frame = (
        f'<rect x="{left:.1f}" y="{top:.1f}" width="{wide:.1f}" height="{high:.1f}" fill="none"'
        ' stroke="#7FB5A8" stroke-width=".8" stroke-dasharray="3 2"'
        ' vector-effect="non-scaling-stroke"/>'
    )
    drawing, centre, per_pixel = photomap.site(fixes)
    # A plot in metres is the right scale for one place and the wrong one for
    # three continents, so whichever scale says something opens the panel.
    reach, _said = _spread(fixes)
    scales = (("site", "site"), ("region", "region"), ("world", "world"))
    if reach > 50_000:
        scales = (("world", "world"), ("region", "region"), ("site", "site"))
    panes = (
        '<div data-pane="scales" data-key="site">'
        '<span class="label pane-name">site</span>'
        f'<div class="site-body">{drawing}</div>'
        f'<span class="cap">local metres from {_e(centre)} \u00b7 1 px = {per_pixel:.2f} m'
        " \u00b7 no basemap under it</span></div>"
        f'<div data-pane="scales" data-key="world" class="world-body">'
        f'<span class="label pane-name">world</span>'
        f"{photomap.outline('0 0 1000 500', dots=dots, extra=frame)}</div>"
        f'<div data-pane="scales" data-key="region" class="region-body">'
        f'<span class="label pane-name">region</span>{photomap.outline(view, dots=near)}</div>'
    )
    controls = (
        '<span class="seg needs-js" data-switch="scales">'
        + "".join(
            f'<button class="btn" type="button" data-show="scales" data-key="{key}"'
            f' aria-pressed="false">{_e(label)}</button>'
            for key, label in scales
        )
        + "</span>"
    )
    site_panel = _card(
        "geolocation",
        scales[0][1].title(),
        f"{len(fixes)} point{'' if len(fixes) == 1 else 's'} · capture order dashed",
        panes,
        controls=controls,
        sunk=True,
        foot=f"<span>{len(fixes)} of the images carry coordinates</span>"
        "<span class='sp'></span><span>outline: Natural Earth 1:110m, public domain</span>",
    )
    rows = "".join(
        f'<tr><td class="m">{fix.number:03d}</td>'
        f'<td class="v">{abs(fix.latitude):.6f} {"N" if fix.latitude >= 0 else "S"}'
        f" \u00b7 {_e(_dms(fix.latitude, 'lat').rsplit(' ', 1)[0])}</td>"
        f'<td class="v">{abs(fix.longitude):.6f} {"E" if fix.longitude >= 0 else "W"}'
        f" \u00b7 {_e(_dms(fix.longitude, 'lon').rsplit(' ', 1)[0])}</td>"
        f'<td class="v{"" if fix.altitude else " dim"}">{_e(fix.altitude or "not recorded")}</td>'
        f'<td class="v{"" if fix.gps_time else " dim"}">{_e(fix.gps_time or "not recorded")}</td>'
        f'<td class="v{"" if fix.at else " dim"}">{_e(fix.at or "not recorded")}</td></tr>'
        for fix in fixes
    )
    table = _card(
        "coordinates",
        "Recorded coordinates",
        "decimal and sexagesimal",
        '<div class="scroll"><table id="coord-rows"><thead><tr><th>#</th><th>latitude</th>'
        "<th>longitude</th><th>altitude</th><th>GPS time</th><th>recorded time</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>",
        flush=True,
        controls='<button class="btn needs-js" type="button" data-copy="coord-rows" hidden'
        ' title="Copy the coordinates"><svg class="ic" aria-hidden="true">'
        '<use href="#i-copy"/></svg><span>copy</span></button>',
        caution="Coordinates say where the receiver believed it was when the file was written,"
        " to the precision the camera recorded. Distances under 20 m are inside a consumer"
        " receiver's error.",
    )
    return (
        '<section class="section" id="geolocation"><div class="section-h"><h2>Geolocation</h2>'
        f'<span class="small">{len(fixes)} image{"" if len(fixes) == 1 else "s"} carry'
        " coordinates. Three scales, none of them a map tile: world and region from an outline"
        " carried in the page, the site as a plot in metres.</span></div>"
        f"{site_panel}"
        f'<div style="margin-top:16px">{table}</div></section>'
    )


def _dms(value: float, axis: str) -> str:
    from . import photomap

    return photomap.sexagesimal(value, axis)


def _fixes(collection: PhotoCollection) -> list[Fix]:
    """Every image that recorded where it believed it was."""
    from . import photomap

    found: list[Fix] = []
    for photo in collection.photos:
        raw = next((record.geo for record in photo.evidence if record.geo), None)
        if not raw:
            continue
        pair = photomap.parse_geo(raw)
        if pair is None:
            continue
        found.append(
            Fix(
                number=photo.number,
                name=photo.name,
                latitude=pair[0],
                longitude=pair[1],
                at=_captured(photo),
                gps_time=_gps_time(photo),
                altitude=_altitude(photo),
            )
        )
    return found


def _gps_time(photo: PhotoResult) -> str | None:
    """The receiver's own clock, which is not always the camera's."""
    stamp = _first_field(photo, "GPSTimeStamp")
    if not stamp:
        return None
    parts = [part.strip() for part in stamp.split(",")]
    if len(parts) != 3:
        return f"{stamp} UTC"
    try:
        hours, minutes, seconds = (float(part) for part in parts)
    except ValueError:
        return f"{stamp} UTC"
    day = _first_field(photo, "GPSDateStamp")
    said = f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d} UTC"
    return f"{day.replace(':', '-')} {said}" if day else said


def _altitude(photo: PhotoResult) -> str | None:
    """How high the receiver believed it was, with the unit it is recorded in."""
    said = _first_field(photo, "GPSAltitude")
    if not said:
        return None
    try:
        metres = float(said)
    except ValueError:
        return said
    # A reference of 1 means the value was recorded as a depth below sea level.
    below = _first_field(photo, "GPSAltitudeRef") == "1"
    return f"{'-' if below else ''}{metres:.1f} m"


def _captured(photo: PhotoResult) -> str | None:
    """When the file says the image was taken."""
    said = _first_field(photo, "DateTimeOriginal", "CreateDate", "DateTimeDigitized")
    if said:
        return said.replace(":", "-", 2) if re.match(r"^\d{4}:\d{2}:\d{2}", said) else said
    return next((record.at for record in photo.evidence if record.at), None)


_MOMENT = re.compile(r"^(\d{4})[-:](\d{2})[-:](\d{2})")


def _moment(photo: PhotoResult) -> float | None:
    """The recorded capture time as a year with a fraction, for one axis."""
    said = _captured(photo)
    if not said:
        return None
    found = _MOMENT.match(said)
    if not found:
        return None
    year, month, day = (int(part) for part in found.groups())
    if not (1826 <= year <= 2200 and 1 <= month <= 12 and 1 <= day <= 31):
        return None
    return year + ((month - 1) * 31 + day - 1) / 372


def _workspace(
    collection: PhotoCollection, written: _Assets | None, refs: dict[tuple[int, int], str]
) -> str:
    """The image view: what a reader does to it, and the images laid out in it."""
    if not collection.photos:
        return '<p class="empty">No supported images were included in this report.</p>'
    deck = (
        '<div class="deck">'
        '<button class="btn icon" id="deck-prev" type="button" title="Previous image"'
        ' aria-label="Previous image"><svg class="ic" aria-hidden="true"'
        ' style="transform:rotate(180deg)"><use href="#i-chevron"/></svg></button>'
        '<span class="deck-at" id="deck-at"></span>'
        '<button class="btn icon" id="deck-next" type="button" title="Next image"'
        ' aria-label="Next image"><svg class="ic" aria-hidden="true">'
        '<use href="#i-chevron"/></svg></button>'
        '<span class="deck-id"><b id="deck-name"></b>'
        '<span class="path" id="deck-path"></span></span>'
        '<span class="stamp" id="deck-format"></span>'
        '<button class="btn" type="button" data-cols="1" aria-pressed="false">single</button>'
        '<button class="btn" type="button" data-cols="2" aria-pressed="true">tile</button>'
        "</div>"
    )
    frames = "".join(
        _frame(photo, collection.redacted, written, refs) for photo in collection.photos
    )
    return deck + frames


def _frame(
    photo: PhotoResult, redacted: bool, written: _Assets | None, refs: dict[tuple[int, int], str]
) -> str:
    """One image, and every analysis that had something to say about it."""
    layers = _layers(photo, redacted)
    frame_id = f"photo-{photo.number:03d}"
    held = " ".join(_held(photo))
    head = (
        f'<article class="frame" id="{frame_id}" data-no="{photo.number:03d}"'
        f' data-name="{_e(photo.name)}" data-path="{_e(photo.path)}"'
        f' data-format="{_e(photo.format)}" data-has="{_e(held)}">'
        f'<header class="frame-head"><span class="frame-no">#{photo.number:03d}</span>'
        f"<div><h3>{_e(photo.name)}</h3><p>{_e(photo.path)}</p></div>"
        f'<span class="stamp">{_e(photo.format)}</span></header>'
    )
    panels = [
        _stage_panel(photo, layers, redacted, written, frame_id),
        _fileinfo_panel(photo, frame_id),
        _findings_panel(photo, frame_id, refs),
    ]
    if photo.evidence:
        panels.append(_blocks_panel(photo, frame_id))
    if photo.jpeg is not None:
        panels.append(_bytemap_panel(photo, photo.jpeg, frame_id))
    panels.extend(
        _map_panel(photo, artifact, layers, written, frame_id) for artifact in _derived(layers)
    )
    if photo.jpeg is not None:
        panels.append(_markers_panel(photo, photo.jpeg, frame_id))
    panels.append(_coverage_panel(photo, frame_id))
    return head + _keyfacts(photo) + f'<div class="panels">{"".join(panels)}</div></article>'


def _panel(
    key: str,
    frame_id: str,
    title: str,
    family: str,
    body: str,
    *,
    reading: str = "",
    caution: str = "",
    foot: str = "",
    controls: str = "",
    flush: bool = False,
    sunk: bool = False,
    wide: bool = False,
    extra: str = "",
) -> str:
    """One analysis panel in the image view, in the shape the summary's cards use.

    The image view had an anatomy of its own - a bar and a body, with the reading
    folded behind a button - and the case summary had another. A reader who learns
    to read one panel should be able to read every panel in the report, so there
    is one shape, and the reading is markup rather than something a script
    reveals.
    """
    classes = " ".join(part for part in ("wide" if wide else "", extra) if part)
    return _card(
        key,
        title,
        family,
        body,
        reading=reading,
        caution=caution,
        foot=foot,
        controls=controls,
        flush=flush,
        sunk=sunk,
        extra=classes,
        element_id=f"{frame_id}-{key}",
    )


def _declared_pixels(photo: PhotoResult) -> tuple[int, int] | None:
    """The size the metadata claims, which is not always the size that decoded."""
    across = _first_field(photo, "PixelXDimension", "ImageWidth", "ExifImageWidth")
    down = _first_field(photo, "PixelYDimension", "ImageHeight", "ExifImageHeight")
    try:
        return int(str(across)), int(str(down))
    except (TypeError, ValueError):
        return None


def _keyfacts(photo: PhotoResult) -> str:
    """The facts a reader checks first, in the order they check them."""
    declared = _declared_pixels(photo)
    decoded = (
        f"{photo.width} \u00d7 {photo.height}" if photo.width and photo.height else "not decoded"
    )
    pixels = f'<div class="v">{_e(decoded)}</div>'
    if declared is not None and (photo.width, photo.height) != declared:
        # A file that says one size and decodes to another was resized after its
        # metadata was written, so the strip carries both numbers rather than one.
        pixels = (
            f'<div class="v alert">{_e(decoded)}'
            f" <i>\u2260 {declared[0]} \u00d7 {declared[1]}</i></div>"
        )
    facts = [
        ("format", f'<div class="v">{_e(photo.format)}</div>'),
        (
            "bytes",
            f'<div class="v">{_e(_size(photo.size))} <i>\u00b7 {photo.size:,}</i></div>'.replace(
                ",", " "
            ),
        ),
        ("pixels", pixels),
        ("camera", f'<div class="v">{_e(photo.camera or "not recorded")}</div>'),
        ("captured", f'<div class="v">{_e(_captured(photo) or "not recorded")}</div>'),
    ]
    cells = "".join(
        f'<div class="kf"><span class="label">{_e(label)}</span>{value}</div>'
        for label, value in facts
    )
    digest = photo.sha256
    grouped = (
        " ".join(digest[index : index + 8] for index in range(0, len(digest), 8))
        if digest
        else "not calculated"
    )
    cells += (
        '<div class="kf wide"><span class="label">SHA-256</span>'
        f'<div class="v">{_e(grouped)}</div></div>'
    )
    return f'<div class="keyfacts">{cells}</div>'


def _layers(photo: PhotoResult, redacted: bool) -> list[PhotoArtifact]:
    """Every image derived from this file, the working decode first and its maps after."""
    if redacted:
        return []
    order = {key: index for index, key in enumerate(_PHOTOGRAPHIC)}
    return sorted(photo.artifacts, key=lambda item: order.get(item.key, len(order)))


def _derived(layers: list[PhotoArtifact]) -> list[PhotoArtifact]:
    """Everything in the image view that is not the working decode of the image."""
    return [item for item in layers if item.key != "main-preview"]


def _same_frame(artifact: PhotoArtifact, layers: list[PhotoArtifact]) -> bool:
    base = next((item for item in layers if item.key == "main-preview"), None)
    return base is not None and (artifact.width, artifact.height) == (base.width, base.height)


def _stage_panel(
    photo: PhotoResult,
    layers: list[PhotoArtifact],
    redacted: bool,
    written: _Assets | None,
    frame_id: str,
) -> str:
    """The image, large, in a frame that hugs it, with room for a map.

    A map read on its own says a region differs from its surroundings; laid over
    the image at a chosen opacity it says which region, which is the part
    that can be checked. The overlay is empty until a script fills it from the
    panel that already holds the map, so a page without a script shows the
    image and the maps beside it, whole, and carries neither twice.
    """
    dimensions = (
        f"{photo.width} \u00d7 {photo.height} px"
        if photo.width and photo.height
        else "dimensions unavailable"
    )
    base = next((item for item in layers if item.key == "main-preview"), None) or (
        layers[0] if layers else None
    )
    if base is None:
        said = (
            "No pixel-bearing image is embedded in this redacted report."
            if redacted
            else "No decodable report preview was produced."
        )
        return _panel(
            "image",
            frame_id,
            "Image comparison",
            "no decode was produced",
            f'<figure class="image-stage bare"><p class="redacted-stage">{said}</p></figure>',
            foot=f'<span class="mono">{_e(dimensions)}</span>'
            f'<span class="sp"></span><span>{_e(_size(photo.size))}</span>',
            wide=True,
            flush=True,
        )
    picture = _image(base, f"{photo.name}: {base.label}", photo, written).replace(
        "<img ", '<img class="plate-base" '
    )
    derived = _derived(layers)
    overlay = '<img class="plate-over" alt="" hidden>' if derived else ""
    # The frame takes the image's own ratio, so it ends where the picture
    # ends and the corner marks mean the picture rather than the panel.
    shape = (
        f' style="--ar:{base.width}/{base.height};--arn:{base.width / base.height:.4f}"'
        if base.width and base.height
        else ""
    )
    # Marked here as well as by the script, so a page without one still shows
    # the sensor's grid rather than a smoothed guess at it.
    close = base.width is not None and base.width < 500
    said = f"image \u00b7 {base.label}"
    body = (
        f'<figure class="image-stage{" sharp" if close else ""}">'
        f'<span class="reg"{shape}>{_CORNERS}{picture}{overlay}'
        f'<span class="regtag in stage-state">{_e(said)}</span></span></figure>'
    )
    if derived:
        body += (
            '<div class="lens" hidden><span class="lens-label">overlay</span>'
            '<button class="btn" type="button" data-clear aria-pressed="true">image</button>'
            + "".join(_lens_button(item, layers) for item in derived)
            + "</div>"
            '<div class="blend" hidden>'
            '<span class="swap"><button type="button" data-swap="original" aria-pressed="false">'
            'original</button><button type="button" data-swap="processed" aria-pressed="false">'
            "processed</button></span>"
            '<label>overlay<input type="range" min="0" max="100" value="85" data-blend'
            ' aria-label="Overlay opacity" disabled><output>85%</output></label></div>'
        )
    return _panel(
        "image",
        frame_id,
        "Image comparison",
        "image and registered maps",
        body,
        reading=_NOTES["image"],
        caution=_CAUTIONS["image"],
        foot=f'<span class="mono">{_e(dimensions)}</span><span data-zoom></span>'
        f'<span class="sp"></span><span>{_e(base.label)} / {_e(_size(photo.size))}</span>',
        wide=True,
        flush=True,
    )


def _lens_button(artifact: PhotoArtifact, layers: list[PhotoArtifact]) -> str:
    """One map, offered for the stage rather than copied onto it.

    The button names the map and nothing more: the image it puts up is the one
    already in that map's own panel, so a report carrying its images inside
    itself carries each of them exactly once.
    """
    # A map drawn on the image's own pixels can be registered over it. A
    # chart cannot, and says so rather than pretending to line up with anything.
    solo = "" if _same_frame(artifact, layers) else " data-solo"
    return (
        f'<button class="btn" type="button" data-lens="{_e(artifact.key)}"'
        f' data-name="{_e(artifact.label)}"{solo} aria-pressed="false">{_e(artifact.label)}</button>'
    )


def _map_panel(
    photo: PhotoResult,
    artifact: PhotoArtifact,
    layers: list[PhotoArtifact],
    written: _Assets | None,
    frame_id: str,
) -> str:
    """One derived map, framed by whether it is in register with the image.

    A map measured on the image's own pixels can be laid over it, and a
    solid frame with corner marks says so. A chart describes the image
    without standing on it, and a dashed frame says that before a reader reads
    a place into it.
    """
    guide = _GUIDE.get(artifact.key)
    close = artifact.width is not None and artifact.width < 500
    dimensions = (
        f"{artifact.width} \u00d7 {artifact.height} px"
        if artifact.width and artifact.height
        else "dimensions unavailable"
    )
    registered = _same_frame(artifact, layers)
    shot = _image(artifact, f"{photo.name}: {artifact.label}", photo, written).replace(
        "<img ", '<img class="map-shot" '
    )
    body = (
        f'<span class="reg">{_CORNERS}{shot}<span class="regtag in">registered</span></span>'
        if registered
        else f'<span class="chart">{shot}'
        '<span class="regtag off">chart \u00b7 off register</span></span>'
    )
    stage = (
        f'<button class="btn" type="button" data-lens="{_e(artifact.key)}"'
        f' data-name="{_e(artifact.label)}"{"" if registered else " data-solo"}'
        ' aria-pressed="false">use in overlay</button>'
    )
    foot = (
        f'<span class="mono">{_e(dimensions)}</span>'
        f"<span>{_e(artifact.parameters or artifact.method)}</span>"
        '<span class="sp"></span>'
        + (f"<span>{_e(guide.source)}</span>" if guide and guide.source else "")
        + stage
    )
    return _panel(
        artifact.key,
        frame_id,
        artifact.label,
        "registered to the image" if registered else "not registered to the image",
        body,
        foot=foot,
        extra="sharp" if close else "",
    )


def _fileinfo_panel(photo: PhotoResult, frame_id: str) -> str:
    """What the filesystem says about the file, against what the file says about itself.

    Two columns rather than one list, because almost every question a reader has
    here is whether the two agree, and a row where they do not is coloured.
    """
    declared = _declared_pixels(photo)
    decoded = (
        f"{photo.width} \u00d7 {photo.height} decoded"
        if photo.width and photo.height
        else "not decoded"
    )
    jpeg = photo.jpeg
    ends = "\u2014"
    if jpeg is not None:
        ends = (
            f"{photo.size:,} to EOI \u00b7 {jpeg.trailing_bytes} after".replace(",", " ")
            if jpeg.eoi_offset is not None
            else "no end marker found"
        )
    rows = [
        ("format", Path(photo.path).suffix.lower() or "\u2014", _container(photo), False),
        ("bytes", f"{photo.size:,}".replace(",", " "), ends, False),
        (
            "dimensions",
            decoded,
            f"{declared[0]} \u00d7 {declared[1]} in EXIF" if declared else "\u2014",
            declared is not None and (photo.width, photo.height) != declared,
        ),
        (
            "modified",
            photo.mtime,
            _first_field(photo, "DateTime", "ModifyDate") or "\u2014",
            False,
        ),
        ("captured", "\u2014", _captured(photo) or "not recorded", False),
        ("camera", "\u2014", photo.camera or "not recorded", False),
        ("body serial", "\u2014", photo.serial or "not recorded", False),
        (
            "lens",
            "\u2014",
            _first_field(photo, "LensModel", "LensSerialNumber") or "not recorded",
            False,
        ),
        # Where an image says it was taken is evidence before it is a map,
        # and it is the one field a subject most often did not mean to publish.
        ("location", "\u2014", _located(photo) or "not recorded", False),
    ]
    body = (
        '<table><thead><tr><th style="width:30%">field</th><th>the filesystem says</th>'
        "<th>the file says</th></tr></thead><tbody>"
        + "".join(
            f'<tr{" class=conflict" if bad else ""}><td class="k">{_e(label)}</td>'
            f'<td class="v">{_e(left)}</td><td class="v">{_e(right)}</td></tr>'
            for label, left, right, bad in rows
        )
        + f'<tr><td class="k">SHA-256</td><td class="v" colspan="2" id="sha-{photo.number:03d}">'
        f"{_e(photo.sha256 or 'not calculated')}</td></tr>"
        "</tbody></table>"
    )
    copy = (
        f'<button class="btn needs-js" type="button" data-copy="sha-{photo.number:03d}" hidden'
        ' title="Copy the digest"><svg class="ic" aria-hidden="true"><use href="#i-copy"/></svg>'
        "<span>copy</span></button>"
        if photo.sha256
        else ""
    )
    return _panel(
        "fileinfo",
        frame_id,
        "File information",
        "filesystem against header",
        body,
        reading=_NOTES["fileinfo"],
        caution=_CAUTIONS["fileinfo"],
        controls=copy,
        flush=True,
    )


def _container(photo: PhotoResult) -> str:
    """What the file says it is, from its own header rather than its name."""
    jpeg = photo.jpeg
    if jpeg is None:
        return photo.format
    parts = [jpeg.encoding or "JPEG"]
    if jpeg.precision is not None:
        parts.append(f"{jpeg.precision}-bit")
    if jpeg.components:
        parts.append(f"{len(jpeg.components)} components")
    return " \u00b7 ".join(parts)


def _flag(state: str) -> str:
    """A row is coloured only where something was flagged."""
    return f' class="{_status(state)}"' if state in ("conflict", "signal") else ""


#: Values a reader may have to compare character by character.
_EXACT = frozenset({"SHA-256", "modified", "captured", "location", "body serial"})


def _refs(collection: PhotoCollection) -> dict[tuple[int, int], str]:
    """A number for every flagged row, running across the images in order.

    Numbered the way the investigation report numbers its findings, so a note
    can cite one. An ordinary fact is an observation and takes no number.
    """
    refs: dict[tuple[int, int], str] = {}
    for photo in collection.photos:
        for index, fact in enumerate(photo.facts):
            if fact.state in ("conflict", "signal"):
                refs[(photo.number, index)] = f"F{len(refs) + 1:02d}"
    return refs


def _findings_panel(photo: PhotoResult, frame_id: str, refs: dict[tuple[int, int], str]) -> str:
    conflicts = sum(1 for fact in photo.facts if fact.state == "conflict")
    signals = sum(1 for fact in photo.facts if fact.state == "signal")
    if not photo.facts:
        body = '<p class="small">Nothing structural disagreed on this file.</p>'
    else:
        rows = []
        for index, fact in enumerate(photo.facts):
            ref = refs.get((photo.number, index), "")
            anchor = f' id="{frame_id}-{ref}"' if ref else ""
            # Only a flagged row is coloured and numbered. An ordinary finding
            # is a fact, and a table where every row is painted says nothing by
            # painting one.
            rows.append(
                f"<tr{_flag(fact.state)}{anchor}>"
                f'<td class="m">{ref}</td><td class="k">{_e(fact.state)}</td>'
                f"<td><b>{_e(fact.label)}</b> {_e(fact.value)}"
                f"{f' {_e(fact.detail)}' if fact.detail else ''}</td>"
                f'<td class="m">{_e(fact.method)}</td></tr>'
            )
        body = (
            "<table><thead><tr><th>#</th><th>state</th><th>finding</th><th>method</th>"
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        )
    named = (
        " \u00b7 ".join(
            part
            for part in (
                f"{conflicts} conflict{'s' if conflicts != 1 else ''}" if conflicts else "",
                f"{signals} signal{'s' if signals != 1 else ''}" if signals else "",
            )
            if part
        )
        or "nothing flagged"
    )
    return _panel(
        "findings",
        frame_id,
        "Findings",
        named,
        body,
        reading=_NOTES["findings"],
        caution=_CAUTIONS["findings"],
        flush=bool(photo.facts),
    )


def _coverage_panel(photo: PhotoResult, frame_id: str) -> str:
    ran = sum(1 for method in photo.methods if method.status != "not evaluated")
    dots = (
        "".join(
            '<div class="brow" style="grid-template-columns:auto 1fr auto">'
            f'<span class="dot" style="color:{_lamp(method.status)}"></span>'
            f'<span class="k">{_e(method.name)}</span>'
            f'<span class="n" title="{_e(method.detail)}">{_e(method.status)}</span></div>'
            for method in photo.methods
        )
        or '<p class="small">No methods were recorded for this file.</p>'
    )
    return _panel(
        "coverage",
        frame_id,
        "Analyses performed",
        f"{ran} ran \u00b7 {len(photo.methods) - ran} did not",
        f'<div class="bars">{dots}</div>',
        reading=_NOTES["coverage"],
        caution=_CAUTIONS["coverage"],
    )


def _lamp(status: str) -> str:
    if status == "not evaluated":
        return "var(--line-3)"
    if "no " in status or "nothing" in status:
        return "var(--activity)"
    return "var(--brand)"


def _blocks_panel(photo: PhotoResult, frame_id: str) -> str:
    """Which blocks spoke, how much each said, and the first of what they carry.

    The values themselves are gathered once, in the Metadata table: printing all
    of them beside every image would put the same two thousand lines in the report
    twice and bury the pictures between them.
    """
    rows = []
    total = 0
    for record in photo.evidence:
        named = BLOCK_LABELS.get(record.block or "") or record.source
        held = len(record.fields) + sum(1 for value in (record.at, record.geo) if value)
        total += held
        carries = ", ".join(list(record.fields)[:9]) or "no named fields"
        if len(record.fields) > 9:
            carries += " \u2026"
        rows.append(
            f'<tr><td><span class="blk meta">{_e(named)}</span></td>'
            f'<td class="num">{held}</td>'
            f"<td{' class=dim' if not held else ''}>{_e(carries)}</td></tr>"
        )
    body = (
        '<table><thead><tr><th>block</th><th class="num">fields</th><th>carries</th></tr>'
        f"</thead><tbody>{''.join(rows)}</tbody></table>"
        if rows
        else '<p class="small">No metadata evidence was recorded.</p>'
    )
    return _panel(
        "fields",
        frame_id,
        "Metadata sources",
        f"{total} field{'' if total == 1 else 's'} in this image",
        body,
        reading=_NOTES["fields"],
        caution=_CAUTIONS["fields"],
        controls='<a class="small" href="#metadata"'
        f' data-filter="{_e(photo.name)}">open in Metadata</a>',
        flush=bool(rows),
    )


def _role(code: int) -> str:
    """What a marker's bytes are doing in the file."""
    if code in (0xD8, 0xD9):
        return "frame"
    if 0xE0 <= code <= 0xEF or code == 0xFE:
        return "app"
    if code == 0xDA:
        return "sos"
    if 0xC0 <= code <= 0xCF and code not in (0xC4, 0xC8, 0xCC):
        return "sof"
    return "table"


def _spans(jpeg: JpegAnalysis, size: int) -> list[tuple[str, str, int, int]]:
    """Every stretch of the file, named, with nothing between them unaccounted.

    The restart markers inside a scan are left folded into it. An image can
    carry thousands of them, and a map broken into thousands of pieces stops
    being a map of anything.
    """
    marked = [
        (marker.name, _role(marker.code), marker.offset, marker.offset + marker.length)
        for marker in sorted(jpeg.markers, key=lambda item: item.offset)
        if not 0xD0 <= marker.code <= 0xD7
    ]
    spans: list[tuple[str, str, int, int]] = []
    at = 0
    scanning = False
    for name, role, start, end in marked:
        if start > at:
            spans.append(
                ("entropy-coded scan", "scan", at, start)
                if scanning
                else ("unaccounted bytes", "tail", at, start)
            )
        spans.append((name, role, start, end))
        at = max(at, end)
        if role == "sos":
            scanning = True
    if size > at:
        spans.append(
            ("trailing bytes", "tail", at, size)
            if jpeg.eoi_offset is not None
            else ("entropy-coded scan", "scan", at, size)
        )
    return spans


def _bytemap_panel(photo: PhotoResult, jpeg: JpegAnalysis, frame_id: str) -> str:
    """Where this file spends itself, drawn to scale and then read out in full.

    A camera file is almost entirely scan, so a ruler to scale shows one bar and
    little else. That is the truth about the file and it stays first; the second
    ruler drops the scan and gives the header its own line, which is where
    anything worth noticing actually is.
    """
    spans = _spans(jpeg, photo.size)
    if not spans:
        return _panel(
            "structure",
            frame_id,
            "File structure",
            "nothing read",
            '<p class="small">Nothing was read.</p>',
        )
    colours = {role: paint for role, _said, paint in _ROLES}
    totals: dict[str, int] = {}
    for _name, role, start, end in spans:
        totals[role] = totals.get(role, 0) + (end - start)
    legend = "".join(
        f'<span><i style="background:{colours[role]}'
        + (";border:1px solid var(--line-3)" if role == "scan" else "")
        + f'"></i>{_e(_ROLES_BY_KEY[role])} {_e(_size(totals[role]))}'
        + (f" \u00b7 {totals[role] * 100 / photo.size:.1f} %" if photo.size else "")
        + "</span>"
        for role, _said, _paint in _ROLES
        if totals.get(role)
    )
    axis = f"bytes-{photo.number:03d}"
    rulers = (
        f'<div data-pane="{axis}" data-key="scale" class="ruler">'
        f'<span class="label pane-name">to scale</span>{_ruler(spans, colours, False)}'
        '<span class="cap">every byte of the file, in the order the encoder wrote'
        " them</span></div>"
        f'<div data-pane="{axis}" data-key="header" class="ruler">'
        f'<span class="label pane-name">header only</span>{_ruler(spans, colours, True)}'
        '<span class="cap">the same segments with the scan dropped, so the header has a line'
        " of its own rather than a sliver of one</span></div>"
    )
    controls = (
        f'<span class="seg needs-js" data-switch="{axis}">'
        f'<button class="btn" type="button" data-show="{axis}" data-key="scale"'
        ' aria-pressed="false">to scale</button>'
        f'<button class="btn" type="button" data-show="{axis}" data-key="header"'
        ' aria-pressed="false">header only</button></span>'
    )
    # A file whose markers run into the hundreds is a file with something wrong
    # with it, and the first twelve say so as well as all of them would.
    heads = [
        marker
        for marker in sorted(jpeg.markers, key=lambda item: item.offset)
        if marker.head and not 0xD0 <= marker.code <= 0xD7
    ][:12]
    dump = (
        f'<div class="hex" id="hex-{photo.number:03d}">'
        + "".join(
            f'<div><span class="o">{marker.offset:06x}</span>  '
            f'<span class="r-{_role(marker.code)}">{marker.head.hex(" ")}</span>'
            f'  <span class="o">{_e(marker.name)}</span></div>'
            for marker in heads
        )
        + "</div>"
        if heads
        else ""
    )
    ranges = "".join(
        f'<tr><td class="m" style="width:74px">0x{marker.offset:04X}</td>'
        f'<td><span class="blk {_tone(marker.code)}">{_e(marker.name)}</span>'
        f" {_e(_says(marker, jpeg, photo))}</td></tr>"
        for marker in heads
    )
    body = (
        rulers
        + f'<ul class="bytes-legend">{legend}</ul>'
        + (
            f'<div class="hexwrap"><div>{dump}</div>'
            '<div class="ranges"><span class="label">what each range means</span>'
            f'<table style="margin-top:6px"><tbody>{ranges}</tbody></table></div></div>'
            if heads
            else ""
        )
    )
    copy = (
        f'<button class="btn needs-js" type="button" data-copy="hex-{photo.number:03d}" hidden'
        ' title="Copy the opening bytes">'
        '<svg class="ic" aria-hidden="true"><use href="#i-copy"/></svg>'
        "<span>copy hex</span></button>"
        if heads
        else ""
    )
    return _panel(
        "structure",
        frame_id,
        "File structure",
        f"{photo.size:,} bytes, in the order the encoder wrote them".replace(",", " "),
        body,
        reading=_NOTES["structure"],
        caution=_CAUTIONS["structure"],
        controls=controls + copy,
        foot=f"<span>{len(spans)} segments</span><span class='sp'></span>"
        f"<span>first {len(heads)} shown byte for byte</span>",
    )


def _ruler(spans: list[tuple[str, str, int, int]], colours: dict[str, str], even: bool) -> str:
    """The file drawn along one line, either to scale or with the header spread out."""
    chosen = [span for span in spans if span[3] > span[2]]
    if even:
        chosen = [span for span in chosen if span[1] != "scan"]
    if not chosen:
        return ""
    return (
        f'<div class="bytes{" even" if even else ""}">'
        + "".join(
            f'<i style="flex:{end - start} 1 0;background:{colours[role]}'
            + (";border:1px solid var(--line-3)" if role == "scan" else "")
            + f'" title="{_e(name)} \u00b7 {_e(_size(end - start))} \u00b7 0x{start:08X}"></i>'
            for name, role, start, end in chosen
        )
        + "</div>"
    )


def _tone(code: int) -> str:
    """Which of the three chip colours a marker's name is printed in."""
    return {"app": "meta", "table": "act", "sof": "org", "sos": "org"}.get(_role(code), "meta")


def _app_name(head: bytes) -> str:
    """The identifier an application segment opens with, as text if it is text."""
    name = head[4:].split(b"\x00", 1)[0]
    try:
        said = name.decode("ascii")
    except UnicodeDecodeError:
        return ""
    return said if said.isprintable() and said else ""


def _exif_shape(photo: PhotoResult) -> str:
    """How many fields each block inside the EXIF segment turned out to hold."""
    parts = [
        f"{BLOCK_LABELS.get(record.block or '') or record.source} {len(record.fields)} entries"
        for record in photo.evidence
        if record.block and record.source == "embedded"
    ]
    return " \u00b7 ".join(parts[:4])


def _says(marker: JpegMarker, jpeg: JpegAnalysis, photo: PhotoResult) -> str:
    """What this segment is, from what was read rather than from its name."""
    code, length = marker.code, marker.length
    if code == 0xD8:
        return "start of image."
    if code == 0xD9:
        return f"end of image. {jpeg.trailing_bytes} B after the end marker."
    if code == 0xDA:
        scan = (jpeg.eoi_offset or photo.size) - (marker.offset + length)
        interval = (
            f"restart interval {jpeg.restart_interval}"
            if jpeg.restart_interval
            else "no restart interval"
        )
        return (
            f"{jpeg.scans} scan{'' if jpeg.scans == 1 else 's'}, {interval},"
            f" {_size(scan)} of entropy-coded data follows."
        )
    if code == 0xDB:
        quality = ""
        if jpeg.quality:
            basis = "an exact match" if jpeg.quality.exact else "nearest, not exact"
            quality = f" Nearest IJG scaling q\u2248{jpeg.quality.quality}, {basis}."
        return f"{len(jpeg.quantization)} quantization table(s) in the file.{quality}"
    if code == 0xC4:
        return f"{len(jpeg.huffman)} Huffman table(s) in the file, {length} B here."
    if 0xC0 <= code <= 0xCF and code not in (0xC4, 0xC8, 0xCC):
        sampling = ", ".join(
            f"{across}\u00d7{down}" for _identifier, across, down, _table in jpeg.components
        )
        return (
            f"{jpeg.encoding or 'frame'}, {jpeg.width} \u00d7 {jpeg.height},"
            f" {len(jpeg.components)} components sampled {sampling}."
        )
    if code == 0xFE:
        return f"comment, {length} B."
    if 0xE0 <= code <= 0xEF:
        named = _app_name(marker.head)
        blocks = " " + _exif_shape(photo) if named == "Exif" else ""
        return f"{named or 'application'} data, {_size(length)}.{blocks}"
    return f"{_size(length)}."


def _markers_panel(photo: PhotoResult, jpeg: JpegAnalysis, frame_id: str) -> str:
    """The marker stream as a list, and the two numbers that name the encoder."""
    spans = _spans(jpeg, photo.size)
    rows = "".join(
        f'<tr><td class="v">{_e(name)}</td><td class="m">0x{start:04X}</td>'
        f'<td class="num">{end - start:,}</td>'.replace(",", " ")
        + f"<td>{_e(_ROLES_BY_KEY.get(role, role))}</td></tr>"
        for name, role, start, end in spans
    )
    quality = f"\u2248 {jpeg.quality.quality}" if jpeg.quality else "not estimated"
    basis = (
        (
            "an exact match to a standard table"
            if jpeg.quality.exact
            else "IJG scaling \u00b7 nearest, not exact"
        )
        if jpeg.quality
        else "no quantization table was read"
    )
    signature = _signature(photo) or "no tables to read"
    sampling = (
        ", ".join(f"{across}\u00d7{down}" for _identifier, across, down, _table in jpeg.components)
        or "not read"
    )
    matrices = "".join(
        f'<div><span class="label">DQT {table.identifier} \u00b7 {table.precision}-bit</span>'
        f'<pre class="matrix">{_e(chr(10).join(lines))}</pre></div>'
        for table in jpeg.quantization
        for lines in (
            [
                " ".join(f"{value:3d}" for value in table.values[index : index + 8])
                for index in range(0, len(table.values), 8)
            ],
        )
    )
    body = (
        '<div class="scroll"><table><thead><tr><th>segment</th><th>offset</th>'
        '<th class="num">bytes</th><th>what it is</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div>"
        f'<div class="qual"><div><span class="label">estimated quality</span>'
        f'<div class="v">{_e(quality)} <span class="small">{_e(basis)}</span></div></div>'
        '<div><span class="label">encoder signature</span>'
        f'<div class="v">{_e(signature)} '
        '<span class="small">tables and marker order</span></div></div>'
        '<div><span class="label">sampling</span>'
        f'<div class="v">{_e(sampling)} '
        f'<span class="small">{len(jpeg.components)} components</span></div></div></div>'
        + (f'<div class="matrices">{matrices}</div>' if matrices else "")
    )
    comments = " | ".join(jpeg.comments)
    return _panel(
        "markers",
        frame_id,
        "JPEG marker stream",
        "frame parameters and coding tables",
        body,
        reading=_NOTES["markers"],
        caution=_CAUTIONS["markers"],
        foot=f"<span>{len(jpeg.quantization)} quantization</span>"
        f"<span>{len(jpeg.huffman)} Huffman</span><span class='sp'></span>"
        + (f"<span>comments: {_e(comments)}</span>" if comments else "<span>no comments</span>"),
        flush=True,
    )


def _first_field(photo: PhotoResult, *names: str) -> str | None:
    for name in names:
        for record in photo.evidence:
            value = record.fields.get(name)
            if value:
                return str(value)
    return None


def _located(photo: PhotoResult) -> str | None:
    return next((record.geo for record in photo.evidence if record.geo), None)


def _field_rows(collection: PhotoCollection) -> list[tuple[str, str, str, str, str]]:
    """Every recorded field of every image, as one list to be sifted."""
    rows = []
    for photo in collection.photos:
        state = ""
        if any(fact.state == "conflict" for fact in photo.facts):
            state = "conflict"
        elif any(fact.state == "signal" for fact in photo.facts):
            state = "signal"
        for record in photo.evidence:
            block = BLOCK_LABELS.get(record.block or "") or record.source
            pairs = [
                (label, value)
                for label, value in (("time", record.at), ("location", record.geo))
                if value
            ]
            pairs.extend(sorted(record.fields.items()))
            for name, value in pairs:
                rows.append((f"#{photo.number:03d} {photo.name}", name, block, value, state))
    return rows


def _metadata_table(rows: list[tuple[str, str, str, str, str]]) -> str:
    """Every recorded value in the collection, gathered once so they can be compared."""
    if not rows:
        return '<p class="small">No metadata evidence was recorded.</p>'
    blocks: dict[str, int] = {}
    for _where, _name, block, _value, _state in rows:
        blocks[block] = blocks.get(block, 0) + 1
    chips = (
        '<button class="btn" type="button" data-block="" aria-pressed="true">all blocks</button>'
    )
    chips += "".join(
        f'<button class="btn" type="button" data-block="{_e(block)}" aria-pressed="false">'
        f'<span class="dot" style="color:var(--metadata)"></span>{_e(block)}</button>'
        for block in sorted(blocks, key=lambda name: -blocks[name])[:6]
    )
    body = "".join(
        f'<tr data-blk="{_e(block)}"'
        + (f' data-state="{_e(state)}"' if state else "")
        + f'><td class="m">{_e(where.split(" ")[0])}</td>'
        f"<td>{_e(where.partition(' ')[2])}"
        + (f' <span class="tag {state}">{state}</span>' if state else "")
        + f'</td><td><span class="blk meta">{_e(block)}</span></td>'
        f'<td class="v">{_e(name)}</td><td class="v">{_e(value)}</td></tr>'
        for where, name, block, value, state in rows
    )
    switches = (
        '<span class="seg needs-js">'
        '<button class="btn" id="meta-case" type="button" aria-pressed="false"'
        ' title="Match case">Aa</button>'
        '<button class="btn" id="meta-word" type="button" aria-pressed="false"'
        ' title="Whole word">W</button>'
        '<button class="btn" id="meta-regex" type="button" aria-pressed="false"'
        ' title="Read the filter as a regular expression">.*</button></span>'
        '<button class="btn needs-js" id="meta-conflict" type="button" aria-pressed="false"'
        ' title="Only rows from files carrying a conflict or a signal">'
        '<span class="dot" style="color:var(--alert)"></span>flagged files only</button>'
    )
    bar = (
        '<div class="meta-bar"><label class="search needs-js">'
        '<svg class="ic" aria-hidden="true"><use href="#i-search"/></svg>'
        '<input type="search" id="meta-filter"'
        ' placeholder="filter image, block, field or value"'
        ' aria-label="Filter the metadata table"></label>'
        f'<span class="seg needs-js">{chips}</span>{switches}'
        '<span class="sp"></span>'
        f'<span class="count" id="meta-count">showing {len(rows)} of {len(rows)}</span>'
        '<button class="btn needs-js" type="button" data-copy="meta-rows" hidden'
        ' title="Copy what is on screen as tab-separated text">'
        '<svg class="ic" aria-hidden="true"><use href="#i-copy"/></svg>'
        "<span>copy</span></button></div>"
    )
    table = (
        '<div class="body flush"><div class="scroll"><table>'
        '<thead><tr><th style="width:56px">#</th>'
        '<th style="width:220px">image</th><th style="width:110px">block</th>'
        '<th style="width:200px">field</th><th>recorded value</th></tr></thead>'
        f'<tbody id="meta-rows">{body}</tbody></table></div>'
        '<p class="small" id="meta-empty" style="padding:12px" hidden>No matching fields.</p>'
        "</div>"
    )
    return (
        f'<div class="panel">{bar}{table}'
        '<div class="caution"><b>Limitations</b>A value here is what the file records, never'
        " whether it was true. Where a recorded value disagrees with what was measured, the"
        " findings for that image say which two things disagree.</div>"
        '<div class="foot"><span>without a script this table is delivered whole and printable;'
        " the filter only hides rows</span></div></div>"
    )


def _scope(collection: PhotoCollection, written: _Assets | None) -> str:
    """What the report does not claim.

    It belongs to the whole report rather than to a view of it, so it sits under
    every view instead of taking the top of one. A reader who has to click to
    reach the sentence saying this settles nothing will not read it.
    """
    redaction = (
        " Pixel-bearing previews and diagnostics were omitted by redaction."
        if collection.redacted
        else ""
    )
    # Every map names its own encoding, but the consequence belongs here: a
    # reader looking for fine texture in an ELA map has to know that some of it
    # can come from the report rather than from the image.
    encoding = (
        " Images and continuous-tone maps are stored as JPEG, and fine texture in a map"
        " can come from that encoding. Histograms and bit planes are stored losslessly."
        if any(photo.artifacts for photo in collection.photos)
        else ""
    )
    # Where the images are is a fact about the report, and one with a
    # consequence: a page that points at its material shows whatever is at
    # those paths now, which is why the digest of each image is beside it.
    where = (
        " Each image is shown from where it lies on disk and the maps sit in the"
        f" directory {_e(written.directory.name)} beside this page, so the two move together."
        " The digest recorded for an image is the one read at the time; a file that no"
        " longer matches it is no longer the file described here."
        if written is not None
        else " Every image is carried inside this page, which is one portable file."
    )
    return (
        "<p><b>Scope and limitations</b>"
        "This report records observable file structure, metadata and declared image transformations. "
        "A conflict is a mechanically supported disagreement. A signal identifies material for review. "
        "Neither state establishes that an image is authentic or manipulated."
        f"{where}{encoding}{redaction}</p>"
    )


def _first_artifact(photo: PhotoResult, *keys: str) -> PhotoArtifact | None:
    return next((item for key in keys for item in photo.artifacts if item.key == key), None)


def _image(artifact: PhotoArtifact, alt: str, photo: PhotoResult, written: _Assets | None) -> str:
    if written is None:
        encoded = base64.b64encode(artifact.data).decode("ascii")
        source = f"data:{artifact.mime};base64,{encoded}"
    else:
        source = written.source(photo, artifact)
    width = f' width="{artifact.width}"' if artifact.width else ""
    height = f' height="{artifact.height}"' if artifact.height else ""
    return f'<img src="{_e(source)}" alt="{_e(alt)}"{width}{height} loading="lazy">'


def _size(value: int) -> str:
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value / (1024 * 1024):.1f} MiB"


def _status(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value.lower()).strip(
        "-"
    )


def _e(value: object) -> str:
    return escape(str(value), quote=True)
