"""Self-contained HTML renderer for digital image examination findings.

Its own page rather than a section of the investigation report: an image is
looked at before it is read, so the picture is the subject here and the evidence
sits beside it. The design tokens, the mark and the icon sprite are the ones the
investigation report uses, so the two read as one tool.

The gallery is the entry point. One inline inspector expands beneath the selected
thumbnail row, retaining collection context and filters. Its panels are grouped
by task; without JavaScript and in print every panel remains readable.
"""

# The embedded stylesheet and script are deliberately compact because they are
# written verbatim into every report. Splitting declarations to satisfy Python's
# line length would increase every generated artifact without improving either.
# ruff: noqa: E501

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import quote

from . import __version__, reportchrome
from .htmlicons import FAVICON, ICONS, MARK_SMALL
from .models import ACTIVITY, BLOCK_LABELS, METADATA, ORIGIN, EvidenceRecord
from .models import label as record_label
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

#: The stage layers that are working images rather than analytical outputs.
_PHOTOGRAPHIC = ("main-preview", "embedded-preview", "maker-preview")


@dataclass(frozen=True, slots=True)
class _Method:
    """What one analytical output is for, and the limitations on reading it.

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
        "The working image, decoded from the evidence file and scaled to a bounded size.",
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

#: What the panels that are not analytical outputs are for. A reader meeting one
#: should be able to ask it what it does without leaving it, which is what the
#: button in every panel bar opens.
_NOTES: dict[str, str] = {
    "image": "The working decode of the image, with any analytical output laid"
    " over the same pixels rather than shown beside them.",
    "fileinfo": "What the file is, taken from the filesystem and from the header, so the two"
    " can be read against each other.",
    "structure": "Where this file's bytes go, segment by segment, in the order the encoder"
    " wrote them.",
    "fields": "Which origin, metadata and activity sources spoke for this image and how"
    " each record was matched. Values are gathered once for comparison.",
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
    "fields": "Category and match basis describe a record; they do not make its value true."
    " File-carried metadata can be complete and entirely fabricated.",
    "findings": "Neither state establishes that an image is authentic or manipulated. A"
    " conflict is a disagreement between two recorded things, nothing more.",
    "coverage": "A method that did not run found nothing because it did not look. It is not"
    " evidence of absence.",
    "markers": "Tables and marker order identify the last encoder, not the camera and not the"
    " photographer. Any editor that re-saves the file replaces them.",
}

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
    "Digital Image Collection",
    "How images group by four shared attributes: claimed camera make, body serial, lens,"
    " and the JPEG encoding fingerprint made from tables and marker order.",
    "Shared attributes support grouping, not common-source attribution. A file can be"
    " rewritten or fabricated, and distinct encoders can produce the same fingerprint.",
)
_GUIDE["times"] = _Method(
    "Digital Image Collection",
    "Every recorded capture time on one axis, one dot per image; captures close together"
    " stack into a column.",
    "A recorded time is a claim by the file. The filesystem time of each copy sits on its"
    " own plate, where the two can be read against each other.",
)
_GUIDE["geolocation"] = _Method(
    "Digital Image Collection",
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
--r:3px;--gutter:16px;--nav:48px;--rail:318px}
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
.mast{padding:14px var(--gutter) 12px;border-bottom:1px solid var(--line)}
/* the case file on the left, the collection in figures on the right, and the
   two paths on a line of their own beneath, where they can be as long as they are */
.mast-body{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:0 40px;align-items:center}
/* the case is the title; what is known about the examination sits in one line under it */
.case-id{margin:0;font:600 22px/1.2 var(--sans);letter-spacing:-.3px;color:var(--ink);
overflow-wrap:anywhere}
.facts.meta{display:flex;flex-wrap:wrap;gap:4px 20px;margin-top:7px;font-size:var(--t-small)}
.facts.meta>div{display:flex;gap:8px;align-items:baseline;min-width:0}
.facts{display:grid;grid-template-columns:auto minmax(0,1fr) auto minmax(0,1fr);gap:7px 18px;
justify-content:start;font-size:var(--t-body);align-content:end}
.facts dt{font:500 var(--t-label)/1.5 var(--sans);letter-spacing:var(--track);
text-transform:uppercase;color:var(--faint)}
.facts dd{color:var(--ink);white-space:nowrap}
.facts.paths{margin-top:12px;padding-top:10px;border-top:1px solid var(--line);
grid-template-columns:auto minmax(0,1fr);gap:3px 18px}
.facts.paths dd{font:400 var(--t-small)/1.5 var(--mono);color:var(--ink-2);white-space:normal;
overflow-wrap:anywhere}
/* figures, not tiles: a number, its name, a hairline between neighbours, and
   each one a link to the place where it was counted */
.figures{display:flex;justify-content:flex-end;margin:0;padding:0;list-style:none}
.figures li{padding:0 22px;border-left:1px solid var(--line)}
.figures li:first-child{border-left:0;padding-left:0}
.figures li:last-child{padding-right:0}
.figures a{display:block;color:inherit;text-decoration:none}
.figures .n{display:block;font:300 26px/1 var(--mono);color:var(--ink);letter-spacing:-.02em;
white-space:nowrap}
.figures .n.alert{color:var(--alert)}.figures .n.activity{color:var(--activity)}
.figures .label{display:block;margin-top:6px;white-space:nowrap}
.figures a:hover .n{color:var(--accent)}.figures a:hover .label{color:var(--ink-2)}
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
/* shared report container */
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
main{padding:0 var(--gutter) 28px;min-width:0}
/* Only the report's own sections are numbered. A frame holds panels that are
   sections of their own, and counting those numbered the document 213. */
.view>section{padding:26px 0 8px}
.view>section.bare{padding-top:14px}
.js .frame-head{display:none}
.deck-id{display:flex;align-items:baseline;gap:10px;min-width:0;flex:1}
.deck-id b{font:500 var(--t-lead)/1.3 var(--sans);color:var(--ink);white-space:nowrap;
min-width:0;overflow:hidden;text-overflow:ellipsis}
.deck-id .path{font:400 var(--t-label)/1.5 var(--mono);color:var(--faint);
overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.view>section:first-child{padding-top:20px}
.h{position:relative;display:flex;align-items:center;gap:12px;margin:0 0 14px;flex-wrap:wrap}
.h .caution{top:calc(100% - 6px)}
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
/* the panels stand on a grid in the order the rail's tree lists them, each
   taking half a row, a third of one, or the whole of it */
.panels{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px}
.panels>.panel{break-inside:avoid;grid-column:span 3;min-width:0}
.panels>.panel.third{grid-column:span 2}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
display:flex;flex-direction:column;min-width:0;overflow:hidden}
.panel.wide{grid-column:1/-1}
/* one panel to a row, at the reader's request, whatever the width says */
body.single .panels>.panel,body.single .panels>.panel.third{grid-column:1/-1}
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
/* the evidence table's own bar: a filter, the categories, and the switches a forensic
   table is read with */
.meta-bar{position:relative;display:flex;align-items:center;gap:8px;padding:8px 12px;
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
@media(max-width:1380px){.panels>.panel.third{grid-column:span 3}}
@media(max-width:1080px){
.shell{grid-template-columns:minmax(0,1fr)}
.rail{position:static;max-height:none;border-right:0;border-bottom:1px solid var(--line);
display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));align-items:start}
.rail-block{border-bottom:0;border-right:1px solid var(--line)}
.mast-body{grid-template-columns:1fr;gap:10px}
}
@media(max-width:760px){
.mast-body{grid-template-columns:1fr;gap:12px}
.facts{grid-template-columns:auto minmax(0,1fr)}
.facts dd{white-space:normal;overflow-wrap:anywhere}
.bar{flex-wrap:wrap;padding:6px 12px}.bar .fam{flex-basis:100%;white-space:normal}
/* On a phone the rail cannot be a column beside the work, and laid above it
   at full length it puts the whole roll between the reader and the first
   image. The roll becomes a strip swiped sideways, the tree a row of chips,
   and the rail ends within one screen with the work directly under it. */
.rail{grid-template-columns:minmax(0,1fr)}
.rail-block{min-width:0;border-right:0;border-bottom:1px solid var(--line);padding-top:10px}
.roll{display:flex;overflow-x:auto;gap:0;padding:0 8px 8px;scroll-snap-type:x proximity}
.roll li{flex:none;width:132px;scroll-snap-align:start}
.roll li a{display:grid;grid-template-columns:minmax(0,1fr);grid-template-areas:"thumb" "nm" "sub" "st";
gap:3px 0;padding:6px;border-left:0;border-bottom:0;border-top:2px solid transparent}
.roll li a[aria-current=true]{border-left-color:transparent;border-top-color:var(--accent)}
.roll .no{display:none}
.roll .th{grid-row:auto;width:100%;height:80px}
.roll .st{margin-top:0}
.tree{display:flex;flex-wrap:wrap;gap:4px 6px;padding:0 12px 10px}
.tree>li{display:contents}
.tree .cat{display:inline-flex;align-items:center;padding:4px 2px 4px 0}
.tree ul{display:contents}
.tree a,.tree span.leaf{padding:3px 8px;border:1px solid var(--line);border-radius:999px;
border-left-width:1px;gap:6px}
.tree a[aria-current=true]{border-color:var(--accent)}
.panels>.panel,.panels>.panel.third{grid-column:1/-1}
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
.panels{display:block}.panels>.panel{margin-bottom:12px}
.panel,.card,.stat,.keyfacts{border-color:#bbb;background:#fff;break-inside:avoid}
.bar,th{background:#f4f4f4;color:#333;border-color:#999}
.bar .t,.label{color:#333}
.reading,.body,td{color:#111}
.why{display:none}
.caution{display:block;position:static;width:auto;padding:8px 12px;background:none;
border:0;border-top:1px dashed #999;border-radius:0;box-shadow:none;color:#444}
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
.small{font-size:var(--t-small);color:var(--muted)}
.label{font:600 var(--t-label)/1 var(--sans);letter-spacing:var(--track);text-transform:uppercase;color:var(--muted)}
.sp{flex:1;min-width:0}
/* a file name is one line; a table with a long one scrolls sideways rather than folds it */
td.file{white-space:nowrap}
/* the capture-time chart: one dot per image, a link each, stacked where they meet */
.times .scroll svg{display:block;min-width:640px}
.times svg a:hover circle,.times svg a:focus circle{stroke:var(--ink);stroke-width:1.5}
/* two cards to a row, the same height: the list that outgrows its neighbour scrolls */
.summary-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;align-items:stretch}
.summary-grid>.panel{display:flex;flex-direction:column;min-width:0}
.summary-grid>.panel>.body{flex:1 1 auto}
.stack{display:grid;gap:12px}
.bars{column-count:2;column-gap:32px}
.brow{break-inside:avoid;margin-bottom:6px}
.brow{display:grid;grid-template-columns:150px 1fr 36px;gap:10px;align-items:center;font-size:var(--t-small)}
.brow .k{color:var(--ink-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.brow .k a{color:inherit}.brow .k a:hover{color:var(--accent);text-decoration:none}
.brow .b{height:8px;background:var(--surface-2);border-radius:1px;overflow:hidden}
.brow .b i{display:block;height:100%;background:var(--line-3)}
.brow.none .b i{background:var(--line-2)}
.brow .n{font:11px var(--mono);color:var(--muted);text-align:right}
.js [data-pane]:not(.on){display:none}
[data-pane]+[data-pane]{margin-top:14px}
.js [data-pane]+[data-pane]{margin-top:0}
[data-pane] .pane-name{display:block;margin-bottom:6px}
#geolocation-body [data-pane] svg{display:block;width:100%;height:100%}
#geolocation-body svg a:hover circle{stroke:var(--ink)}
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
/* a limitation stands behind a mark in the bar and opens on hover or focus.
   Under an analytical output it stays in view, because there it says how to
   read the picture. Print lays every one of them back under its panel. */
.bar{position:relative}
.why{display:inline-flex;align-items:center;justify-content:center;flex:none;width:20px;height:20px;
margin:0 2px;border:1px solid var(--line-2);border-radius:50%;background:transparent;
color:var(--faint);font:600 10px/1 var(--mono);cursor:help;padding:0}
.why:hover,.why:focus-visible{color:var(--activity);border-color:var(--activity);outline:none}
.caution{display:none;position:absolute;left:8px;top:calc(100% + 6px);z-index:25;
width:min(52ch,calc(100% - 16px));padding:10px 12px;background:var(--surface-2);
border:1px solid var(--line-2);border-radius:var(--r);box-shadow:0 10px 28px rgba(0,0,0,.5);
font:400 var(--t-small)/1.55 var(--sans);color:var(--ink-2);text-align:left;white-space:normal;
letter-spacing:0;text-transform:none}
.why:hover+.caution,.why:focus+.caution,.why:focus-visible+.caution,.caution:hover{display:block}
.caution.shown{display:block;position:static;width:auto;padding:8px 12px;background:none;
border:0;border-top:1px dashed var(--line-2);border-radius:0;box-shadow:none}
.caution b{display:block;margin-bottom:4px;color:var(--activity);font:600 var(--t-label)/1 var(--sans);
letter-spacing:.08em;text-transform:uppercase}
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
.world-body{height:min(52vh,460px)}
.region-body{height:min(52vh,460px)}
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
@media(max-width:760px){.figures{flex-wrap:wrap;justify-content:flex-start;gap:10px 0}
.figures li{padding:0 14px}.figures li:first-child{padding-left:0}.bars{column-count:1}}

/* two views: the collection, and one image */
.js .view:not(.on){display:none}
.view{min-width:0}
@media print{.js .view:not(.on){display:block}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*{transition:none!important}}

.time-image{display:flex;align-items:center;gap:12px}.time-image img{width:52px;height:40px;object-fit:contain;background:var(--sunken);flex:none}
#findings table{min-width:1000px}#coord-rows{min-width:920px}.time-list table{min-width:740px}
/* Collection and detail are distinct reading widths. */
body[data-view="summary"] .rail{display:none}
body[data-view="summary"] .shell{display:block}
body[data-view="summary"] main{padding:0 clamp(20px,4vw,64px) 80px}
.view[data-view="summary"]{counter-reset:summary-section}
.view[data-view="summary"]>section{padding:56px 0 8px;counter-increment:summary-section}
.view[data-view="summary"]>section:first-child{padding-top:36px}
.view[data-view="summary"]>section>.h{margin-bottom:22px}
.view[data-view="summary"]>section>.h h2:before{content:counter(summary-section,decimal-leading-zero);color:var(--accent);font:400 11px var(--mono);letter-spacing:.1em;margin-right:13px;vertical-align:3px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(132px,1fr))}
.cards a.card{color:inherit;text-decoration:none}.cards a.card:hover{background:var(--surface)}
.cards .s{font:11px/1.5 var(--sans);color:var(--muted);margin-top:4px}
.nav a[aria-current="true"]{color:var(--accent);box-shadow:inset 0 -2px var(--accent)}
.m,td.m,.frame .m{white-space:nowrap;word-break:normal!important;overflow-wrap:normal!important}
.frame table{table-layout:auto}.frame td:first-child{min-width:44px}
.contacts{display:grid;grid-template-columns:repeat(auto-fill,minmax(185px,1fr));gap:16px}
.contact{min-width:0;border:1px solid var(--line);background:var(--surface)}
.contact a{display:block;color:var(--ink-2);text-decoration:none;height:100%}
.contact:hover{border-color:var(--accent)}
.contact-image{height:148px;background:var(--sunken);display:flex;align-items:center;justify-content:center;color:var(--muted)}
.contact-image img{width:100%;height:100%;object-fit:contain}
.contact-image small{display:block;font-size:11px}
.contact-caption{padding:12px;display:grid;grid-template-columns:auto 1fr;gap:5px 9px}
.contact-caption b{font-size:12px;overflow-wrap:anywhere}.contact-caption small{grid-column:2;color:var(--muted)}
.contact-caption .tag{grid-column:2;width:fit-content}
.gallery-controls,.time-controls{display:flex;align-items:center;flex-wrap:wrap;gap:12px;padding:14px 0}
.gallery-controls label,.time-pick{display:flex;gap:10px;align-items:center;font-size:12px;color:var(--muted)}
.gallery-controls input,select{background:var(--surface);color:var(--ink);border:1px solid var(--line-2);padding:7px 10px;border-radius:3px;max-width:100%;font:inherit}
#gallery-group{padding:12px;border-left:2px solid var(--accent);margin-bottom:12px;background:var(--brand-soft)}
.time-years{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px;padding:20px;border-bottom:1px solid var(--line)}
.time-year{display:grid;gap:6px;text-align:left;padding:10px;background:transparent;border:1px solid transparent;border-radius:3px;color:var(--muted);cursor:pointer;font:12px var(--mono)}
.time-year b{font-weight:500;color:var(--ink)}.time-year small{font:11px var(--sans);color:var(--muted)}
.time-year meter{width:100%;height:6px;appearance:none;border:0;background:var(--line);border-radius:2px}
.time-year meter::-webkit-meter-bar{background:var(--line);border:0;height:6px}.time-year meter::-webkit-meter-optimum-value{background:var(--metadata)}
.time-year:hover,.time-year[aria-pressed="true"]{background:var(--surface-2);border-color:var(--accent)}
.time-controls{padding:14px 20px}.time-list{max-height:420px;overflow:auto}
.time-list th{position:sticky;top:0;background:var(--surface-2);z-index:1}
.time-list td{padding:12px 16px}.time-list small,#coord-rows small{display:block;color:var(--muted);font-size:11px}
.time-list time{white-space:nowrap;font:12px var(--mono)}
.place-overview{display:grid;grid-template-columns:280px minmax(0,1fr);gap:26px;padding:20px;align-items:center;border-bottom:1px solid var(--line)}
.place-world svg{display:block;width:100%;height:155px}.place-world{background:var(--sunken)}
.place-title{font-size:18px;color:var(--ink);margin-bottom:5px}.place-buttons{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.place-buttons .btn{height:auto;min-height:40px;white-space:normal;text-align:left;padding:8px 12px}.place-buttons b{color:var(--accent);margin-left:6px}
.place-pane{display:grid;grid-template-columns:minmax(0,1fr) 320px;min-width:0}
.js .place-pane:not(.on){display:none}
.place-plot{background:var(--sunken);min-width:0;padding:12px}.place-plot>svg{display:block;width:100%;height:360px}
.place-plot>p{padding:4px 8px;overflow-wrap:anywhere}
.place-list{border-left:1px solid var(--line);max-height:410px;overflow:auto}
.place-list li{padding:14px 16px;border-bottom:1px solid var(--line)}
.place-list li.selected{background:var(--brand-soft);box-shadow:inset 3px 0 var(--accent)}
.place-select{display:grid;grid-template-columns:auto 1fr;gap:4px 8px;width:100%}
.place-select b{font-size:12px;overflow-wrap:anywhere}.place-select small{grid-column:2;font:11px var(--mono);color:var(--muted)}
.place-list li>a{display:inline-block;font-size:11px;margin:8px 14px 0 0}
.point-label{display:block}.place-plot a:hover .point-label,.place-plot a:focus .point-label,.place-plot a.selected .point-label{display:block}
.place-plot a.selected circle{stroke:var(--accent);stroke-width:3;fill:var(--brand-soft)}
.place-plot a{cursor:pointer}
@media(max-width:760px){body[data-view="summary"] main{padding:20px 16px}.place-overview{grid-template-columns:1fr;gap:12px}.place-world svg{height:120px}.place-pane{grid-template-columns:1fr}.place-list{border-left:0;border-top:1px solid var(--line)}.contacts{grid-template-columns:repeat(2,minmax(0,1fr))}.contact-image{height:120px}.contact-caption{padding:8px}.gallery-controls label{flex-wrap:wrap}.gallery-controls input{width:180px}.place-plot>svg{height:280px}}
@media print{.js .place-pane:not(.on){display:grid}.contact[hidden],.time-list tr[hidden]{display:revert!important}.time-list,.place-list{max-height:none;overflow:visible}.gallery-controls,.time-controls,.place-buttons{display:none}.contacts{grid-template-columns:repeat(4,minmax(0,1fr))}}
.shell{display:block}
.inline-inspector{grid-column:1/-1;order:9999;min-width:0;border:1px solid var(--line-2);border-top:2px solid var(--accent);background:var(--bg);padding:0 18px 18px;scroll-margin-top:calc(var(--nav) + 12px);overflow-anchor:none}
.js .inline-inspector{order:0}
.js .inline-inspector:not(.open){display:none}
.contact.selected{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}
.contact a:focus-visible{outline-offset:-3px}
.inline-inspector .deck{position:static;background:transparent;padding:14px 0;border-bottom:1px solid var(--line)}
.detail-tabs{display:flex;gap:8px;margin:16px 0;flex-wrap:wrap}
.analysis-picker,.js .analysis-picker{display:block;margin:16px 0 20px;padding:14px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.analysis-picker h4{font:500 var(--t-small)/1.5 var(--sans);color:var(--ink-2);margin:0 0 10px}
.analysis-picker h4 span{color:var(--accent);margin-left:6px}
.method-choices{display:flex;flex-wrap:wrap;gap:8px}
.method-choices .method-choice{height:auto;min-height:36px;max-width:100%;padding:9px 12px;white-space:normal;text-align:left;line-height:1.4;justify-content:flex-start}
.method-choice[aria-pressed="true"]{box-shadow:inset 3px 0 var(--accent)}
.js .frame[data-detail-tab="overview"] .panels{grid-template-columns:minmax(0,1.3fr) minmax(280px,1fr)}
.js .frame[data-detail-tab="overview"] .panels>.panel{grid-column:auto}
.js .frame[data-detail-tab="metadata"] .panels,.js .frame[data-detail-tab="evidence"] .panels{grid-template-columns:minmax(0,1fr)}
.frame .image-stage{max-height:65vh}
.inline-inspector .lens,.js .frame[data-detail-tab="overview"] .blend{display:none}
.js .frame[data-detail-tab="analysis"] .panels{grid-template-columns:repeat(2,minmax(0,1fr))}
.js .frame[data-detail-tab="analysis"] .panels>.panel{grid-column:auto;order:1}
.js .frame[data-detail-tab="analysis"] .panels>.panel[id$="-coverage"]{grid-column:1/-1;order:2}
@media(max-width:760px){.inline-inspector{padding:0 10px 12px}.js .frame[data-detail-tab="overview"] .panels,.js .frame[data-detail-tab="analysis"] .panels{grid-template-columns:minmax(0,1fr)}.inline-inspector .deck-id{order:2;flex-basis:100%}.inline-inspector .deck-id b{white-space:normal}.detail-tabs{gap:5px}.detail-tabs .btn{padding:0 8px}}
@media print{.inline-inspector,.js .inline-inspector:not(.open){display:block;border:0;padding:0}.inline-inspector .panel[hidden],.inline-inspector .keyfacts[hidden]{display:block!important}.detail-tabs,.analysis-picker{display:none!important}.inline-inspector .panels{display:block}.contact{break-inside:avoid}.contact.selected{box-shadow:none}.js .inline-inspector{order:9999}.inline-inspector .frame{break-before:page}}

.gallery-layout{display:flex;gap:4px;margin-left:auto}
.contacts.list-layout{grid-template-columns:minmax(0,1fr);gap:8px}
.list-layout .contact>a{display:flex;align-items:center;min-width:0}
.list-layout .contact-image{width:112px;height:80px;flex:none;border-right:1px solid var(--line)}
.list-layout .contact-caption{display:grid;grid-template-columns:52px minmax(160px,1fr) minmax(120px,.5fr) auto;align-items:center;gap:6px 16px;flex:1;min-width:0;padding:10px 16px}
.list-layout .contact-caption b{margin:0}.list-layout .contact-caption small{margin:0}
.list-layout .contact-caption .tag{justify-self:start;margin:0}
@media(max-width:760px){.list-layout .contact-image{width:80px;height:80px}.list-layout .contact-caption{grid-template-columns:38px minmax(0,1fr);gap:3px 8px;padding:8px}.list-layout .contact-caption small,.list-layout .contact-caption .tag{grid-column:2}.gallery-layout{margin-left:0}}

"""

SCRIPT = r"""
(function(){
  var all=function(selector,within){return Array.prototype.slice.call((within||document).querySelectorAll(selector))};
  document.body.classList.add("js");

  // A section folds from its own heading, so a long report is read a part at a
  // time. Folding hides; nothing is removed, and print puts it all back.
  all("main section[id]").forEach(function(section){
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
        var pressed=!solo&&over.hidden===false&&(button.getAttribute("data-swap")==="working"?value===0:value===100);
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
        slider.value=button.getAttribute("data-swap")==="working"?0:100;
        opacity();
      });
    });
    put(null);
  });

  var frames=all(".frame"),contacts=all("[data-member]"),
      inspector=document.getElementById("image-inspector"),current=-1,
      back=document.getElementById("deck-prev"),on=document.getElementById("deck-next");
  function unfold(section){
    if(!section){return}section.classList.remove("folded");
    var button=section.querySelector(".fold");if(button){button.setAttribute("aria-expanded","true")}
  }
  function placeInspector(card){
    // Hide only for synchronous measurement, so it cannot split the thumbnail row.
    inspector.classList.remove("open");
    var top=card.offsetTop,last=card;
    contacts.forEach(function(item){if(!item.hidden&&item.offsetTop===top){last=item}});
    last.after(inspector);inspector.classList.add("open");
  }
  function detailTab(frame,tab,target){
    frame.setAttribute("data-detail-tab",tab);
    all("[data-detail-tab]",frame).forEach(function(button){button.setAttribute("aria-pressed",String(button.getAttribute("data-detail-tab")===tab))});
    var picks=all("button[data-output]",frame),selected=frame.getAttribute("data-selected-output")||(picks[0]?picks[0].getAttribute("data-output"):"");
    if(target&&picks.some(function(button){return frame.id+"-"+button.getAttribute("data-output")===target.id})){selected=target.id.slice(frame.id.length+1)}
    frame.setAttribute("data-selected-output",selected);
    picks.forEach(function(button){button.setAttribute("aria-pressed",String(tab==="analysis"&&button.getAttribute("data-output")===selected))});
    all(".panels > .panel",frame).forEach(function(panel){
      var group=panel.getAttribute("data-detail-group")||"",show=group.split(" ").indexOf(tab)>=0;
      if(show&&group==="analysis"&&selected){show=panel.id===frame.id+"-"+selected}
      panel.hidden=!show;
    });
    var facts=frame.querySelector(".keyfacts");if(facts){facts.hidden=tab!=="overview"}
  }
  all("[data-gallery-layout]").forEach(function(button){button.addEventListener("click",function(){
    var selected=document.querySelector(".contact.selected"),before=selected?selected.getBoundingClientRect().top:null;
    document.querySelector(".contacts").classList.toggle("list-layout",button.getAttribute("data-gallery-layout")==="list");
    all("[data-gallery-layout]").forEach(function(other){other.setAttribute("aria-pressed",String(other===button))});
    if(selected&&inspector.classList.contains("open")){placeInspector(selected);window.scrollBy({top:selected.getBoundingClientRect().top-before,behavior:"instant"})}
  })});
  function visibleFrames(){return frames.filter(function(frame){return contacts.some(function(card){return !card.hidden&&Number(card.getAttribute("data-member"))===Number(frame.getAttribute("data-no"))})})}
  function show(index,jump,inner){
    if(!frames.length){return}
    var frame=frames[index],card=contacts.filter(function(item){return Number(item.getAttribute("data-member"))===Number(frame.getAttribute("data-no"))})[0];
    if(!card){return}
    if(card.hidden){
      // An explicit evidence link may refer to an image outside the current filter.
      // Reset visibly rather than silently showing a card that contradicts the filter.
      document.getElementById("gallery-reset").click();
    }
    unfold(document.getElementById("gallery"));
    var before=card.getBoundingClientRect().top;
    current=index;frames.forEach(function(item){item.toggleAttribute("data-current",item===frame)});
    contacts.forEach(function(item){var selected=item===card;item.classList.toggle("selected",selected);item.querySelector("a").setAttribute("aria-expanded",String(selected))});
    placeInspector(card);
    document.getElementById("deck-at").textContent="#"+frame.getAttribute("data-no");
    document.getElementById("deck-name").textContent=frame.getAttribute("data-name");
    document.getElementById("deck-path").textContent=frame.getAttribute("data-path");
    document.getElementById("deck-format").textContent=frame.getAttribute("data-format");
    var visible=visibleFrames(),position=visible.indexOf(frame);
    back.disabled=position<=0;on.disabled=position===visible.length-1;
    var panel=inner?inner.closest("[data-detail-group]"):null;
    detailTab(frame,panel?panel.getAttribute("data-detail-group").split(" ")[0]:"overview",panel);
    openView("summary",document.querySelector('.nav a[href="#gallery"]'));
    if(jump){(inner||inspector).scrollIntoView({block:"start"})}
    else{window.scrollBy({top:card.getBoundingClientRect().top-before,behavior:"instant"})}
  }
  function closeInspector(focus){
    inspector.classList.remove("open");
    contacts.forEach(function(card){card.classList.remove("selected");card.querySelector("a").setAttribute("aria-expanded","false")});
    if(focus&&current>=0){var link=document.querySelector('.contact a[href="#'+frames[current].id+'"]');if(link){link.focus({preventScroll:true})}}
  }
  frames.forEach(function(frame){
    all("button[data-detail-tab]",frame).forEach(function(button){button.addEventListener("click",function(){detailTab(frame,button.getAttribute("data-detail-tab"))})});
    all("button[data-output]",frame).forEach(function(button){button.addEventListener("click",function(){
      frame.setAttribute("data-selected-output",button.getAttribute("data-output"));detailTab(frame,"analysis");
    })});
  });
  function adjacent(step){
    var visible=visibleFrames(),frame=visible[visible.indexOf(frames[current])+step];
    if(frame){history.pushState(null,"","#"+frame.id);show(frames.indexOf(frame),true)}
  }
  if(back){back.addEventListener("click",function(){adjacent(-1)})}
  if(on){on.addEventListener("click",function(){adjacent(1)})}
  var close=document.getElementById("inspector-close");
  if(close){close.addEventListener("click",function(){closeInspector(true);history.pushState(null,"","#gallery")})}
  document.addEventListener("keydown",function(event){
    if(event.key==="Escape"&&inspector.classList.contains("open")&&inspector.contains(event.target)){close.click()}
  });
  function fromHash(){
    var id=(location.hash||"").slice(1);
    for(var index=0;index<frames.length;index++){
      if(frames[index].id===id||id.indexOf(frames[index].id+"-")===0){show(index,true,id===frames[index].id?null:document.getElementById(id));return true}
    }
    if(inspector){closeInspector(false)}
    var destination=document.getElementById(id==="images"?"gallery":id);
    if(destination){unfold(destination.closest("section"));openView("summary",document.querySelector('.nav a[href="#'+id+'"]'));destination.scrollIntoView({block:"start"});return true}
    return false;
  }
  window.addEventListener("hashchange",fromHash);
  window.addEventListener("popstate",fromHash);
  document.addEventListener("click",function(event){
    var link=event.target.closest?event.target.closest('a[href^="#photo-"]'):null;
    if(!link){return}
    var id=link.getAttribute("href").slice(1),index=frames.findIndex(function(frame){return frame.id===id||id.indexOf(frame.id+"-")===0});
    if(index<0){return}
    event.preventDefault();history.pushState(null,"","#"+id);
    show(index,!link.closest(".contact"),id===frames[index].id?null:document.getElementById(id));
  });
  if(window.ResizeObserver&&inspector){
    var galleryWidth=0;new ResizeObserver(function(entries){
      var width=entries[0].contentRect.width;if(width===galleryWidth){return}galleryWidth=width;
      var selected=document.querySelector(".contact.selected");if(selected&&inspector.classList.contains("open")){placeInspector(selected)}
    }).observe(document.querySelector(".contacts"));
  }

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


  var navLinks=all(".nav [data-goto]");
  function openView(name,chosen){
    document.body.setAttribute("data-view","summary");
    if(chosen){navLinks.forEach(function(link){link.setAttribute("aria-current",String(link===chosen))})}
  }
  all("[data-goto]").forEach(function(link){link.addEventListener("click",function(event){
    event.preventDefault();history.pushState(null,"",link.getAttribute("href"));fromHash();
  })});
  openView("summary",navLinks[0]);
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

  // The evidence table. Without a script the table is delivered whole; this hides
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
        var fileQuery=/^#(\d+)$/.exec(query);
        var hit=fileQuery?Number(row.getAttribute("data-image"))===Number(fileQuery[1]):!plain&&!test;
        if(!hit&&!fileQuery){
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
        if(cased){cased.setAttribute("aria-pressed","false")}
        if(whole){whole.setAttribute("aria-pressed","false")}
        if(onlyBad){onlyBad.setAttribute("aria-pressed","false")}
        history.pushState(null,"","#evidence");
        block="";
        blocks.forEach(function(other,index){other.setAttribute("aria-pressed",String(index===0))});
        sift();
        var seen=document.getElementById("evidence");
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
        var use=button.querySelector("use");
        if(!use){return}
        var was=use.getAttribute("href");use.setAttribute("href","#i-check");
        setTimeout(function(){use.setAttribute("href",was)},1400);
      },function(){});
    });
  });

  var members=null,
      gallerySearch=document.getElementById("gallery-search"),
      galleryFilter=document.getElementById("gallery-filter"),
      groupNote=document.getElementById("gallery-group");
  function filterGallery(){
    closeInspector(false);
    var query=gallerySearch.value.toLowerCase(),mode=galleryFilter.value,kept=0;
    contacts.forEach(function(card){
      var hit=(!members||members.indexOf(card.getAttribute("data-member"))>=0)&&card.textContent.toLowerCase().indexOf(query)>=0;
      if(mode==="flagged"){hit=hit&&!!card.getAttribute("data-flag")}
      if(mode==="geo"){hit=hit&&card.getAttribute("data-geo")==="true"}
      if(mode==="decoded"){hit=hit&&card.getAttribute("data-decoded")==="true"}
      if(mode==="undecoded"){hit=hit&&card.getAttribute("data-decoded")==="false"}
      card.hidden=!hit;if(hit){kept++}
    });
    document.getElementById("gallery-count").textContent=kept+" of "+contacts.length+" images";
    document.getElementById("gallery-empty").hidden=kept>0;
  }
  if(gallerySearch){
    gallerySearch.addEventListener("input",filterGallery);
    galleryFilter.addEventListener("change",filterGallery);
    document.getElementById("gallery-reset").addEventListener("click",function(){
      members=null;gallerySearch.value="";galleryFilter.value="all";groupNote.hidden=true;filterGallery();
    });
    all("[data-members]").forEach(function(link){link.addEventListener("click",function(event){
      event.preventDefault();members=link.getAttribute("data-members").split(",");
      gallerySearch.value="";galleryFilter.value="all";groupNote.textContent=link.getAttribute("data-group-label");
      groupNote.hidden=false;filterGallery();openView("summary");location.hash="gallery";
      document.getElementById("gallery").scrollIntoView({block:"start"});
    })});
    filterGallery();
  }
  var timeDay=document.getElementById("time-day"),timeRows=all("[data-time-row]");
  function filterTime(){
    var period=timeDay.value,kept=0;
    timeRows.forEach(function(row){row.hidden=!!period&&!row.getAttribute("data-time-row").startsWith(period);if(!row.hidden){kept++}});
    all("[data-time-year]").forEach(function(button){button.setAttribute("aria-pressed",String(!!period&&period.startsWith(button.getAttribute("data-time-year"))))});
    document.getElementById("time-count").textContent=kept+" images";
    var list=document.querySelector(".time-list");if(list){list.scrollTop=0}
  }
  if(timeDay){
    timeDay.addEventListener("change",filterTime);
    all("[data-time-year]").forEach(function(button){button.addEventListener("click",function(){timeDay.value=button.getAttribute("data-time-year");filterTime()})});
  }
  var places=all(".place-pane");
  function choosePlace(key){
    places.forEach(function(pane){pane.classList.toggle("on",pane.id===key)});
    all("[data-place]").forEach(function(button){button.setAttribute("aria-pressed",String(button.getAttribute("data-place")===key))});
  }
  all("[data-place]").forEach(function(button){button.addEventListener("click",function(event){event.preventDefault();choosePlace(button.getAttribute("data-place"))})});
  all("[data-geo-select]").forEach(function(button){button.addEventListener("click",function(event){
    event.preventDefault();var number=button.getAttribute("data-geo-select");
    all("[data-geo-row]").forEach(function(row){row.classList.toggle("selected",row.getAttribute("data-geo-row")===number)});
    all("[data-geo-select]").forEach(function(mark){mark.classList.toggle("selected",mark.getAttribute("data-geo-select")===number)});
    var row=document.getElementById("geo-row-"+number);if(row){row.scrollIntoView({block:"nearest"})}
  })});
  if(places.length){choosePlace(places[0].id)}

  fromHash();

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

    The working image and every analytical output are written beside the page.
    The evidence path remains recorded as evidence and is never used as the
    report's mutable pixel source.
    """

    directory: Path
    url_directory: str

    def source(self, photo: PhotoResult, artifact: PhotoArtifact) -> str:
        name = f"{photo.number:03d}-{artifact.key}{_SUFFIXES.get(artifact.mime, '.bin')}"
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / name).write_bytes(artifact.data)
        return f"{quote(self.url_directory)}/{name}"


def render_photo_html(
    collection: PhotoCollection,
    *,
    output: Path | None = None,
    now: datetime | None = None,
    assets: Path | None = None,
    asset_url: str | None = None,
    case: str | None = None,
    examiner: str | None = None,
) -> str:
    """Render one complete photo-forensics report.

    With `assets` the images are written into that directory and pointed at, and
    the page is the small part; without it every image is carried inside the page
    and the report is one file. `asset_url` lets an atomic writer render into a
    staging directory while linking the final directory name. `assets` needs
    `output`, because a relative link is relative to something. `case` and
    `examiner` head the title block when given.
    """
    if assets is not None and output is None:
        raise ValueError("assets needs output: a link is relative to the page holding it")
    if asset_url is not None and assets is None:
        raise ValueError("asset_url needs assets: there is nowhere to write linked images")
    written = _Assets(assets, asset_url or assets.name) if assets is not None else None
    moment = (now or datetime.now().astimezone()).strftime("%Y-%m-%d %H:%M %Z").strip()
    title = " - ".join(
        part
        for part in (
            case,
            output.name if output else None,
            "Digital Image Examination Report",
        )
        if part
    )
    rows = _evidence_rows(collection)
    from . import photomap

    fixes = _fixes(collection)
    refs = _refs(collection)
    # Everything that speaks for the whole collection is one view; the
    # images are the other. Neither is a section of the other. What needs a
    # decision comes first and the table a reader consults comes last.
    collected = (
        _section("summary", "Summary", "", _figures(collection, rows))
        + _gallery(collection, written, refs)
        + _key_findings(collection, refs)
        + _collection_section(collection)
        + _timeline_section(collection, written)
        + (_geolocation(fixes, len(collection.photos)) if fixes else "")
        + _section(
            "evidence",
            "Evidence records",
            "",
            _evidence_table(rows),
            caution="The category states what kind of record this is, and match basis states"
            " how it was tied to the file. Neither proves that a recorded value is true."
            " Findings name measured conflicts separately.",
        )
    )
    places = [
        ("summary", "summary", "Summary"),
        ("gallery", "summary", "Images"),
        ("findings", "summary", "Findings"),
        ("collection", "summary", "Shared attributes"),
        ("timeline", "summary", "Dates"),
    ]
    if fixes:
        places.append(("geolocation", "summary", "Locations"))
    places += [("evidence", "summary", "Evidence")]
    head = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{LINKED_POLICY if written else POLICY}">'
        '<meta name="referrer" content="no-referrer">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="dark">'
        f"<title>{_e(title)}</title>{FAVICON}<style>{STYLE}{reportchrome.STYLE}</style></head><body>{ICONS}"
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
    main = f'<div class="view on" data-view="summary">{collected}</div>'
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
        + _mast(collection, rows, moment, output, written, case, examiner)
        + nav
        + f'<div class="shell"><main>{main}</main></div>'
        + top
        + footer
        + f"<script>{SCRIPT}</script></body></html>"
    )


def _mast(
    collection: PhotoCollection,
    rows: list[_EvidenceRow],
    moment: str,
    output: Path | None,
    written: _Assets | None,
    case: str | None,
    examiner: str | None,
) -> str:
    metadata = [("Case", case)] if case else []
    if examiner:
        metadata.append(("Examiner", examiner))
    metadata.append(("Generated", moment))
    if collection.redacted:
        metadata.append(("Media", "Redacted"))
    technical = [("Target", str(collection.root))]
    if output:
        technical.append(("Report", str(output)))
    technical.append(
        (
            "Media",
            "redacted"
            if collection.redacted
            else "linked beside the page"
            if written
            else "carried in the page",
        )
    )
    return reportchrome.header(
        "Image examination",
        str(collection.root),
        metadata,
        technical,
    )


def _held(photo: PhotoResult) -> list[str]:
    """Which analyses have a panel on this image."""
    keys = ["image", "fileinfo", "findings", "coverage"]
    if photo.evidence:
        keys.append("fields")
    if photo.jpeg is not None:
        keys.extend(("structure", "markers"))
    keys.extend(artifact.key for artifact in photo.artifacts if artifact.key != "main-preview")
    return keys


def _section(key: str, title: str, note: str, body: str, *, caution: str = "") -> str:
    counted = f'<span class="n">{_e(note)}</span>' if note else ""
    ask = _why(caution)
    fold = (
        f'<button class="fold" type="button" aria-expanded="true" aria-controls="{key}-body" '
        f'title="Collapse section" aria-label="Collapse {_e(title)}">'
        '<svg class="ic" aria-hidden="true"><use href="#i-chevron"/></svg></button>'
    )
    return (
        f'<section id="{key}"><div class="h">{fold}<h2>{_e(title)}</h2>{ask}{counted}</div>'
        f'<div class="sec-body" id="{key}-body">{body}</div></section>'
    )


def _why(caution: str) -> str:
    """A limitation behind a mark, beside the title it qualifies."""
    if not caution:
        return ""
    return (
        '<button class="why" type="button" aria-label="Limitations">i</button>'
        f'<div class="caution"><b>Limitations</b>{_e(caution)}</div>'
    )


def _card(
    key: str,
    title: str,
    family: str,
    body: str,
    *,
    reading: str | None = None,
    caution: str = "",
    foot: str = "",
    controls: str = "",
    flush: bool = False,
    sunk: bool = False,
    extra: str = "",
    element_id: str = "",
    show_caution: bool = False,
) -> str:
    """One analysis panel, with the anatomy every other panel also has.

    A bar that names it, a reading that says what it shows, a body, a caution
    that states the limitations, and a foot carrying the parameters. The
    caution is markup rather than something a script reveals, so it survives
    printing and a reader who never clicks anything; on screen it stands behind
    a mark in the bar, and under an analytical output it stays in view, where it
    says how to read the picture.
    """
    guide = _GUIDE.get(key)
    if reading is None:
        reading = guide.shows if guide else ""
    if not caution and guide:
        caution = guide.caution
    ask = _why(caution) if not show_caution else ""
    classes = "panel" + (f" {extra}" if extra else "")
    identifier = f' id="{_e(element_id)}"' if element_id else ""
    shape = "body" + (" flush" if flush else "") + (" sunk" if sunk else "")
    return (
        f'<section class="{classes}"{identifier}>'
        f'<div class="bar"><span class="t">{_e(title)}</span>{ask}'
        f'<span class="fam">{_e(family)}</span><span class="sp"></span>{controls}</div>'
        + (f'<div class="reading">{_e(reading)}</div>' if reading else "")
        + f'<div class="{shape}">{body}</div>'
        + (
            f'<div class="caution shown"><b>Limitations</b>{_e(caution)}</div>'
            if caution and show_caution
            else ""
        )
        + (f'<div class="foot">{foot}</div>' if foot else "")
        + "</section>"
    )


def _timeline_section(collection: PhotoCollection, written: _Assets | None = None) -> str:
    """When the images say they were taken, before anything else: the whole in one line."""
    stamped = sum(1 for photo in collection.photos if _moment(photo) is not None)
    total = len(collection.photos)
    note = f"{stamped} of {total} image{'' if total == 1 else 's'} carry a time"
    return _section("timeline", "Recorded dates", note, _times(collection, written))


def _collection_section(collection: PhotoCollection) -> str:
    """What the images share, grouped four ways."""
    makes = len({make for photo in collection.photos if (make := _first_field(photo, "Make"))})
    formats: dict[str, int] = {}
    for photo in collection.photos:
        formats[photo.format] = formats.get(photo.format, 0) + 1
    kinds = " \u00b7 ".join(
        f"{name} {count}" for name, count in sorted(formats.items(), key=lambda item: -item[1])
    )
    note = f"{len(collection.photos)} files \u00b7 {kinds} \u00b7 {makes} make{'' if makes == 1 else 's'}"
    return _section(
        "collection",
        "Shared attributes",
        note,
        _clusters(collection),
        caution="Repeated metadata values and encoding characteristics do not establish a common device, author or event.",
    )


def _key_findings(collection: PhotoCollection, refs: dict[tuple[int, int], str]) -> str:
    """Every numbered finding in the collection, each a link to the row it names."""
    by_number = {photo.number: photo for photo in collection.photos}
    rows = "".join(
        f"<tr{_flag(fact.state)}>"
        f'<td class="m"><a href="#photo-{number:03d}-{ref}">{ref}</a></td>'
        f'<td class="file"><a href="#photo-{number:03d}"><span class="m">#{number:03d}</span> {_e(photo.name)}</a></td>'
        f'<td class="k">{_e(fact.state)}</td>'
        f"<td><b>{_e(fact.label)}</b> {_e(fact.value)}</td>"
        f'<td class="m">{_e(fact.method)}</td></tr>'
        for (number, index), ref in refs.items()
        for photo in (by_number[number],)
        for fact in (photo.facts[index],)
    )
    table = (
        '<div class="scroll"><table><thead><tr>'
        '<th style="width:56px">#</th><th style="width:300px">image</th>'
        '<th style="width:84px">state</th><th>finding</th><th style="width:190px">method</th>'
        f"</tr></thead><tbody>{rows}</tbody></table></div>"
        if rows
        else '<p class="small">No conflicts or signals were found in these images.</p>'
    )
    return _section(
        "findings",
        "Key findings",
        str(len(refs)),
        _card(
            "findings-all",
            "Numbered findings",
            "disagreements the tool can support and material flagged for a reader;"
            " each row leads to its image",
            table,
            reading="",
            caution=_CAUTIONS["findings"],
            flush=bool(rows),
        ),
    )


def _figures(collection: PhotoCollection, rows: list[_EvidenceRow]) -> str:
    """The collection in six figures, each a link to the place where it is counted."""
    counted = len(collection.photos)
    working = [p.number for p in collection.photos if _first_artifact(p, "main-preview")]
    missing = [p.number for p in collection.photos if p.number not in working]
    conflicts = sum(
        1 for photo in collection.photos for fact in photo.facts if fact.state == "conflict"
    )
    signals = sum(
        1 for photo in collection.photos for fact in photo.facts if fact.state == "signal"
    )
    figures = (
        (str(counted), "image" if counted == 1 else "images", "images", "images", ""),
        (
            str(len(working)),
            "working images",
            "images",
            "images",
            "",
        ),
        (
            str(len(missing)),
            "without working image",
            "images",
            "images",
            "activity" if missing else "",
        ),
        (
            str(conflicts),
            "conflict" if conflicts == 1 else "conflicts",
            "findings",
            "summary",
            "alert" if conflicts else "",
        ),
        (
            str(signals),
            "signal" if signals == 1 else "signals",
            "findings",
            "summary",
            "activity" if signals else "",
        ),
        (f"{len(rows):,}".replace(",", " "), "recorded values", "evidence", "summary", ""),
    )
    selections = [[p.number for p in collection.photos], working, missing, [], [], []]
    descriptions = (
        "files in this examination",
        "bounded copies available to inspect",
        "pixels redacted"
        if collection.redacted
        else "a preview or metadata may still be available",
        "measured disagreements · see findings",
        "observations requiring interpretation",
        "source, category and match basis",
    )
    items = ""
    for index, (value, label, target, view, tone) in enumerate(figures):
        if index < 3:
            link = f'href="#gallery" data-members="{",".join(map(str, selections[index]))}" data-group-label="{_e(label)}"'
        else:
            link = f'href="#{target}" data-goto="{view}"'
        items += (
            f'<a class="card {tone}" {link}><span class="v">{_e(value)}</span>'
            f'<span class="k">{_e(label)}</span><span class="s">{descriptions[index]}</span></a>'
        )

    return f'<div class="cards">{items}</div>'


def _clusters(collection: PhotoCollection) -> str:
    """Group images by shared recorded attributes, without source attribution."""
    axes = (
        ("make", "camera make", lambda photo: _first_field(photo, "Make")),
        ("serial", "body serial", lambda photo: photo.serial),
        (
            "lens",
            "lens",
            lambda photo: _first_field(photo, "LensModel", "LensInfo", "LensSerialNumber"),
        ),
        ("encoder", "JPEG encoding fingerprint", lambda photo: _signature(photo)),
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
            f'<span class="k" title="{_e(name)}">'
            + (
                _e(name)
                if name == "not recorded"
                else f'<a href="#gallery" data-members="{",".join(str(photo.number) for photo in collection.photos if pick(photo) == name)}" data-group-label="{_e(label)}: {_e(name)}">{_e(name)}</a>'
            )
            + "</span>"
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
            f' aria-pressed="false">{_e(label.split()[-1] if key != "encoder" else "fingerprint")}</button>'
        )
    groups = len({_first_field(photo, "Make") or "" for photo in collection.photos})
    return _card(
        "clusters",
        "Shared attributes",
        "grouped by claimed make, body serial, lens and JPEG encoding fingerprint;"
        " select a group to see its images",
        "".join(panes),
        reading="",
        controls=f'<span class="seg needs-js" data-switch="clusters">{"".join(buttons)}</span>',
        foot=f"<span>{len(collection.photos)} files</span><span>{groups} makes</span>",
    )


def _signature(photo: PhotoResult) -> str | None:
    """A compact JPEG encoding fingerprint for collection grouping.

    It hashes quantization tables and marker order. Equal values show that those
    observed encoding attributes agree; they do not identify software, a device
    or a common source, and distinct encoders can legitimately collide.
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


def _time_value(photo: PhotoResult) -> tuple[str, str]:
    """Keep the selected timestamp's meaning and source with its value."""
    for field in ("DateTimeOriginal", "CreateDate", "DateTimeDigitized"):
        for record in photo.evidence:
            if record.fields.get(field):
                return str(record.fields[field]), f"{_source_label(record)} / {field}"
    for record in photo.evidence:
        if record.at:
            return record.at, f"{_source_label(record)} / recorded time"
    return "", ""


def _parsed_time(photo: PhotoResult) -> datetime | None:
    value, _ = _time_value(photo)
    if re.match(r"^\d{4}:\d{2}:\d{2}", value):
        value = value.replace(":", "-", 2)
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if 1826 <= moment.year <= 2200 else None


def _times(collection: PhotoCollection, written: _Assets | None = None) -> str:
    stamped = [
        (photo, moment)
        for photo in collection.photos
        if (moment := _parsed_time(photo)) is not None
    ]
    if not stamped:
        return _card(
            "times",
            "Recorded dates",
            "",
            '<p class="small">No usable recorded dates.</p>',
            reading="",
        )
    # Sort by displayed wall clock, never assign an invented zone to camera times.
    stamped.sort(key=lambda item: item[1].replace(tzinfo=None))
    days = sorted({moment.date().isoformat() for _, moment in stamped})
    years = sorted({day[:4] for day in days})
    year_counts = {year: sum(moment.year == int(year) for _, moment in stamped) for year in years}
    options = (
        '<optgroup label="Years">'
        + "".join(
            f'<option value="{year}">{year} ({year_counts[year]} images)</option>' for year in years
        )
        + '</optgroup><optgroup label="Dates">'
        + "".join(f'<option value="{day}">{day}</option>' for day in days)
        + "</optgroup>"
    )
    rows = []
    for photo, moment in stamped:
        value, source = _time_value(photo)
        day = moment.date().isoformat()
        number = f"{photo.number:03d}"
        clock = moment.strftime("%H:%M:%S") if len(value.strip()) > 10 else "time not recorded"
        zone = moment.strftime("UTC%z") if moment.tzinfo else "zone not recorded"
        artifact = _first_artifact(photo, *_PHOTOGRAPHIC)
        thumbnail = _image(artifact, "", photo, written) if artifact else ""
        rows.append(
            f'<tr id="time-{number}" data-time-row="{day}">'
            f"<td><time>{day}<br><b>{clock}</b></time><small>{zone}</small></td>"
            f'<td><a class="time-image" href="#photo-{number}">{thumbnail}<span>#{number} {_e(photo.name)}</span></a></td>'
            f'<td>{_e(source)}</td><td><a href="#evidence" data-filter="#{number}">Evidence</a></td></tr>'
        )
    controls = (
        '<label class="time-pick">Period <select id="time-day"><option value="">All recorded dates</option>'
        f'{options}</select></label><span id="time-count" class="small">{len(rows)} images</span>'
    )
    drawing = (
        '<div class="time-years" aria-label="Images by recorded year">'
        + "".join(
            f'<button type="button" class="time-year" data-time-year="{year}" aria-pressed="false">'
            f"<span>{year}</span><b>{year_counts[year]} <small>{'image' if year_counts[year] == 1 else 'images'}</small></b>"
            f'<meter min="0" max="{max(year_counts.values())}" value="{year_counts[year]}" aria-label="{year_counts[year]} images in {year}"></meter></button>'
            for year in years
        )
        + "</div>"
    )
    table = (
        '<div class="scroll time-list"><table><thead><tr><th>Recorded date / time</th>'
        "<th>Image</th><th>Source / field</th><th>Reference</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )
    return _card(
        "times",
        "Recorded dates",
        "Images by recorded year; select a year or date to read the files in order",
        drawing + '<div class="time-controls">' + controls + "</div>" + table,
        reading="",
        flush=True,
        foot="<span>Ordered by displayed clock. Times without an offset are not comparable across time zones.</span>",
        caution="A recorded date is a claim in the file, not independent proof of capture. The selected source and field are shown for every image. Other recorded dates remain in Evidence.",
    )


def _gallery(
    collection: PhotoCollection, written: _Assets | None, refs: dict[tuple[int, int], str]
) -> str:
    cards = []
    for photo in collection.photos:
        artifact = _first_artifact(photo, *_PHOTOGRAPHIC)
        picture = (
            _image(artifact, photo.name, photo, written)
            if artifact
            else f"<span>{_e(photo.format)}<small>{'pixels redacted' if collection.redacted else 'no preview available'}</small></span>"
        )
        flags = {fact.state for fact in photo.facts}
        state = "conflict" if "conflict" in flags else "signal" if "signal" in flags else ""
        cards.append(
            f'<article class="contact" data-member="{photo.number}" data-decoded="{str(bool(_first_artifact(photo, "main-preview"))).lower()}"'
            f' data-geo="{str(bool(_located(photo))).lower()}" data-flag="{state}">'
            f'<a href="#photo-{photo.number:03d}" aria-expanded="false" aria-controls="image-inspector"><div class="contact-image">{picture}</div>'
            f'<div class="contact-caption"><span class="m">#{photo.number:03d}</span>'
            f"<b>{_e(photo.name)}</b><small>{_e(photo.camera or photo.format)}</small>"
            + (f'<span class="tag {state}">{state}</span>' if state else "")
            + (
                "<small>Embedded preview only</small>"
                if artifact and not _first_artifact(photo, "main-preview")
                else ""
            )
            + (
                "<small>Some analyses not evaluated</small>"
                if any(method.status == "not evaluated" for method in photo.methods)
                else ""
            )
            + "</div></a></article>"
        )
    controls = (
        '<div class="gallery-controls needs-js"><label>Find an image '
        '<input type="search" id="gallery-search" placeholder="Name or camera"></label>'
        '<label>Show <select id="gallery-filter"><option value="all">All images</option>'
        '<option value="flagged">Conflicts and signals</option><option value="geo">With coordinates</option>'
        '<option value="decoded">Working image available</option><option value="undecoded">No working image</option></select></label>'
        '<button class="btn" id="gallery-reset" type="button">Reset</button>'
        '<span id="gallery-count" class="small"></span>'
        '<div class="gallery-layout" role="group" aria-label="Image layout">'
        '<button class="btn" type="button" data-gallery-layout="grid" aria-pressed="true">Grid</button>'
        '<button class="btn" type="button" data-gallery-layout="list" aria-pressed="false">List</button></div></div>'
        '<p id="gallery-group" class="small" hidden></p>'
    )
    return _section(
        "gallery",
        "Images",
        f"{len(cards)} in the collection",
        controls
        + '<div class="contacts">'
        + "".join(cards)
        + '<div class="inline-inspector" id="image-inspector" role="region" aria-label="Selected image examination">'
        + _workspace(collection, written, refs)
        + "</div></div>"
        '<p id="gallery-empty" hidden>No images match this selection.</p>',
    )


def _location_groups(fixes: list[Fix]) -> list[list[Fix]]:
    """Bound each local view to 25 km from its first point; never infer a route."""
    import math

    groups: list[list[Fix]] = []
    for fix in fixes:
        for group in groups:
            seed = group[0]
            lat1, lat2 = math.radians(seed.latitude), math.radians(fix.latitude)
            dlat = lat2 - lat1
            dlon = math.radians(fix.longitude - seed.longitude)
            hav = (
                math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
            )
            distance = 12_742_000 * math.asin(min(1, math.sqrt(hav)))
            if distance <= 25_000:
                group.append(fix)
                break
        else:
            groups.append([fix])
    return sorted(groups, key=lambda group: -len(group))


def _geolocation(fixes: list[Fix], total: int) -> str:
    from . import photomap

    groups = _location_groups(fixes)
    buttons, panes, marks = [], [], []
    for index, group in enumerate(groups):
        key = f"place-{index + 1}"
        seed = group[0]
        area = f"{abs(seed.latitude):.3f}°{'N' if seed.latitude >= 0 else 'S'}, {abs(seed.longitude):.3f}°{'E' if seed.longitude >= 0 else 'W'}"
        count_label = f"{len(group)} image" + ("s" if len(group) != 1 else "")
        x, y = photomap.project(seed.latitude, seed.longitude)
        marks.append(
            f'<a href="#{key}" data-place="{key}"><circle cx="{x:.2f}" cy="{y:.2f}" r="13" fill="var(--brand)"/>'
            f'<text x="{x:.2f}" y="{y + 4:.2f}" text-anchor="middle" fill="#101714" font-size="12">{len(group)}</text>'
            f"<title>Near {area}: {count_label}</title></a>"
        )
        buttons.append(
            f'<button class="btn" type="button" data-place="{key}" aria-pressed="false">'
            f"{area} <b>{count_label}</b></button>"
        )
        drawing, centre, _ = photomap.site(group)
        # Local points select the corresponding row; opening the image is a separate action.
        for fix in group:
            drawing = drawing.replace(
                f'href="#photo-{fix.number:03d}"',
                f'href="#geo-row-{fix.number:03d}" data-geo-select="{fix.number:03d}"',
            )
        rows = "".join(
            f'<li id="geo-row-{fix.number:03d}" data-geo-row="{fix.number:03d}">'
            f'<button type="button" data-geo-select="{fix.number:03d}" class="place-select">'
            f'<span class="m">#{fix.number:03d}</span><b>{_e(fix.name)}</b>'
            f"<small>{fix.latitude:.6f}, {fix.longitude:.6f}</small></button>"
            f'<a href="#photo-{fix.number:03d}">Examine image →</a>'
            f'<a href="#evidence" data-filter="#{fix.number:03d}">Evidence</a></li>'
            for fix in group
        )
        panes.append(
            f'<div class="place-pane" id="{key}"><div class="place-plot">{drawing}'
            f'<p class="small">{_e(centre)}</p></div><ol class="place-list">{rows}</ol></div>'
        )
    world = photomap.outline(photomap.window(fixes), extra="".join(marks))
    navigation = (
        '<div class="place-overview"><div class="place-world">' + world + "</div>"
        '<div><p class="place-title">Recorded locations</p>'
        f"<p>{len(fixes)} images with coordinates · {total - len(fixes)} without usable coordinates</p>"
        '<p class="small">Each view contains points within 25 km of its listed coordinate. This is a map viewing aid, not evidence of a shared event. Select an area, then an image.</p>'
        '<div class="place-buttons">' + "".join(buttons) + "</div></div></div>"
    )
    rows = "".join(
        f'<tr><td class="m"><a href="#photo-{fix.number:03d}">#{fix.number:03d}</a></td>'
        f"<td>{abs(fix.latitude):.6f} {'N' if fix.latitude >= 0 else 'S'}<small>{_dms(fix.latitude, 'lat')}</small></td>"
        f"<td>{abs(fix.longitude):.6f} {'E' if fix.longitude >= 0 else 'W'}<small>{_dms(fix.longitude, 'lon')}</small></td>"
        f"<td>{_e(fix.altitude or 'not recorded')}</td><td>{_e(fix.gps_time or 'not recorded')}</td>"
        f"<td>{_e(fix.at or 'not recorded')}</td></tr>"
        for fix in fixes
    )
    table = (
        '<div class="scroll"><table id="coord-rows"><thead><tr><th>Image</th><th>Latitude</th><th>Longitude</th><th>Altitude</th><th>GPS time</th><th>Other recorded time</th></tr></thead><tbody>'
        + rows
        + "</tbody></table></div>"
    )
    return _section(
        "geolocation",
        "Recorded locations",
        f"{len(fixes)} of {total} images carry coordinates",
        _card(
            "geolocation",
            "Recorded locations",
            "Nearby coordinates, shown together for readability",
            navigation + "".join(panes),
            reading="",
            flush=True,
            caution="Groups are for navigation, within 25 km of a group seed; they do not establish a shared event. Local plots have no basemap. Recorded coordinates do not prove a location or a route. The first available coordinate record is plotted; consult Evidence for all sources.",
            foot="<span>Regional outline: Natural Earth 1:110m · public domain</span>",
        )
        + _card(
            "coordinates",
            "Recorded coordinates",
            "Compare GPS and other recorded times",
            table,
            reading="",
            flush=True,
        ),
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


def _moment(photo: PhotoResult) -> float | None:
    """Display-clock position with second precision, without inventing a timezone."""
    moment = _parsed_time(photo)
    return moment.replace(tzinfo=timezone.utc).timestamp() if moment else None


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
        '<button class="btn" type="button" id="inspector-close">Close details</button>'
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
    # In the order the rail's tree names them: what the file is, what it says,
    # what was done to it, how it is built, what the outputs show, and the
    # marker stream last, where a long table splits nothing.
    if photo.evidence:
        panels.append(_blocks_panel(photo, frame_id))
    panels.append(_coverage_panel(photo, frame_id))
    if photo.jpeg is not None:
        panels.append(_bytemap_panel(photo, photo.jpeg, frame_id))
    panels.extend(
        _map_panel(photo, artifact, layers, written, frame_id)
        for artifact in _analytical_outputs(layers)
    )
    if photo.jpeg is not None:
        panels.append(_markers_panel(photo, photo.jpeg, frame_id))
    tabs = (
        '<div class="detail-tabs needs-js" aria-label="Image detail sections">'
        + "".join(
            f'<button class="btn" type="button" data-detail-tab="{key}" aria-pressed="{str(key == "overview").lower()}">{label}</button>'
            for key, label in (
                ("overview", "Overview"),
                ("metadata", "File details"),
                ("analysis", "Analysis"),
                ("evidence", "Evidence"),
            )
        )
        + "</div>"
    )
    outputs = _analytical_outputs(layers)
    options = "".join(
        f'<button class="btn method-choice" type="button" data-output="{_e(artifact.key)}" '
        f'aria-pressed="false" aria-controls="{frame_id}-{_e(artifact.key)}">{_e(artifact.label)}</button>'
        for artifact in outputs
    )
    selection = (
        f'<div class="analysis-picker needs-js"><h4>Analytical outputs and previews <span>{len(outputs)}</span></h4><div class="method-choices" role="group" aria-label="Analytical outputs and previews">{options}</div></div>'
        if outputs
        else '<p class="analysis-picker small">No analytical output was produced. See analyses performed below.</p>'
    )
    return (
        head
        + tabs
        + selection
        + _keyfacts(photo)
        + f'<div class="panels">{"".join(panels)}</div></article>'
    )


def _panel(
    key: str,
    frame_id: str,
    title: str,
    family: str,
    body: str,
    *,
    reading: str | None = None,
    caution: str = "",
    foot: str = "",
    controls: str = "",
    flush: bool = False,
    sunk: bool = False,
    wide: bool = False,
    extra: str = "",
    show_caution: bool = False,
) -> str:
    """One analysis panel in the image view, in the shape the summary's cards use.

    The image view had an anatomy of its own - a bar and a body, with the reading
    folded behind a button - and the case summary had another. A reader who learns
    to read one panel should be able to read every panel in the report, so there
    is one shape, and the reading is markup rather than something a script
    reveals.
    """
    classes = " ".join(part for part in ("wide" if wide else "", extra) if part)
    group = {
        "image": "overview analysis",
        "fileinfo": "metadata",
        "findings": "overview evidence",
        "fields": "evidence",
        "coverage": "analysis evidence",
        "structure": "metadata",
        "markers": "metadata",
    }.get(key, "analysis")
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
        show_caution=show_caution,
    ).replace("<section ", f'<section data-detail-group="{group}" ', 1)


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
        ("recorded time", f'<div class="v">{_e(_captured(photo) or "not recorded")}</div>'),
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
    """The working image first, followed by previews and analytical outputs."""
    if redacted:
        return []
    order = {key: index for index, key in enumerate(_PHOTOGRAPHIC)}
    return sorted(photo.artifacts, key=lambda item: order.get(item.key, len(order)))


def _analytical_outputs(layers: list[PhotoArtifact]) -> list[PhotoArtifact]:
    """Everything in the image view that is not the working image."""
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
    outputs = _analytical_outputs(layers)
    overlay = '<img class="plate-over" alt="" hidden>' if outputs else ""
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
    if outputs:
        body += (
            '<div class="lens" hidden><span class="lens-label">overlay</span>'
            '<button class="btn" type="button" data-clear aria-pressed="true">image</button>'
            + "".join(_lens_button(item, layers) for item in outputs)
            + "</div>"
            '<div class="blend" hidden>'
            '<span class="swap"><button type="button" data-swap="working" aria-pressed="false">'
            'Working image</button><button type="button" data-swap="analytical" aria-pressed="false">'
            "Analytical output</button></span>"
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
        show_caution=True,
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
    """One analytical output, framed by whether it is registered to the working image.

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
        extra=" ".join(part for part in ("sharp" if close else "", "third") if part),
        show_caution=True,
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
        f'<button class="btn icon needs-js" type="button" data-copy="sha-{photo.number:03d}" hidden'
        ' title="Copy the digest"><svg class="ic" aria-hidden="true"><use href="#i-copy"/></svg>'
        "</button>"
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
    """Which evidence sources spoke, how much each said, and what they carry.

    The values themselves are gathered once, in the Evidence table: printing all
    of them beside every image would put the same two thousand lines in the report
    twice and bury the pictures between them.
    """
    rows = []
    total = 0
    for record in photo.evidence:
        named = _source_label(record)
        carried = _record_pairs(record)
        held = len(carried)
        total += held
        carries = ", ".join(name for name, _value in carried[:9]) or "no additional values"
        if len(carried) > 9:
            carries += " \u2026"
        rows.append(
            f'<tr><td><span class="blk {_category_class(record.category)}">'
            f"{_e(record.category)}</span></td><td>{_e(named)}</td>"
            f'<td class="num">{held}</td>'
            f"<td{' class=dim' if not held else ''}>{_e(carries)}</td></tr>"
        )
    body = (
        "<table><thead><tr><th>category</th><th>source</th>"
        '<th class="num">values</th><th>carries</th></tr>'
        f"</thead><tbody>{''.join(rows)}</tbody></table>"
        if rows
        else '<p class="small">No evidence records were recorded.</p>'
    )
    return _panel(
        "fields",
        frame_id,
        "Evidence sources",
        f"{total} recorded value{'' if total == 1 else 's'} in this image",
        body,
        reading=_NOTES["fields"],
        caution=_CAUTIONS["fields"],
        controls='<a class="small" href="#evidence"'
        f' data-filter="{_e(photo.name)}">open in Evidence</a>',
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
        f'<button class="btn icon needs-js" type="button" data-copy="hex-{photo.number:03d}" hidden'
        ' title="Copy the opening bytes">'
        '<svg class="ic" aria-hidden="true"><use href="#i-copy"/></svg>'
        "</button>"
        if heads
        else ""
    )
    return _panel(
        "structure",
        frame_id,
        "File structure",
        f"{photo.size:,} bytes, in the order the encoder wrote them".replace(",", " "),
        body,
        wide=True,
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
        '<div><span class="label">JPEG encoding fingerprint</span>'
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
        wide=True,
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


@dataclass(frozen=True, slots=True)
class _EvidenceRow:
    number: int
    image: str
    category: str
    source: str
    field: str
    value: str
    match: str
    state: str


def _category_class(category: str) -> str:
    return {ORIGIN: "org", METADATA: "meta", ACTIVITY: "act"}[category]


def _source_label(record: EvidenceRecord) -> str:
    """Name both the evidence source and the decoded block when they differ."""
    source = record_label(record)
    block = BLOCK_LABELS.get(record.block or "", record.block)
    if block and block.casefold() != source.casefold():
        return f"{source} / {block}"
    return source


def _record_pairs(record: EvidenceRecord) -> list[tuple[str, str]]:
    """Every value carried by an evidence record, without losing its typed fields."""
    fixed: tuple[tuple[str, object | None], ...] = (
        ("URL", record.url),
        ("referrer", record.referrer),
        ("tool", record.tool),
        ("command", record.command),
        ("time", record.at),
        ("stated location", record.location),
        ("coordinates", record.geo),
        ("byte count", record.bytes),
        ("MIME type", record.mime),
        ("SHA-256", record.sha256),
        ("note", record.note),
        ("container", record.container),
        ("match note", record.match_note),
    )
    pairs = [(name, str(value)) for name, value in fixed if value not in (None, "")]
    pairs.extend((name, str(value)) for name, value in sorted(record.fields.items()))
    pairs.extend((f"where: {name}", str(value)) for name, value in sorted(record.where.items()))
    return pairs


def _evidence_rows(collection: PhotoCollection) -> list[_EvidenceRow]:
    """Every recorded value, retaining category, source and match basis."""
    rows = []
    for photo in collection.photos:
        state = ""
        if any(fact.state == "conflict" for fact in photo.facts):
            state = "conflict"
        elif any(fact.state == "signal" for fact in photo.facts):
            state = "signal"
        for record in photo.evidence:
            pairs = _record_pairs(record) or [("record", "source present")]
            for name, value in pairs:
                rows.append(
                    _EvidenceRow(
                        photo.number,
                        photo.name,
                        record.category,
                        _source_label(record),
                        name,
                        value,
                        record.matched_by,
                        state,
                    )
                )
    return rows


def _evidence_table(rows: list[_EvidenceRow]) -> str:
    """Every evidence value in the collection, gathered once for comparison."""
    if not rows:
        return '<p class="small">No evidence records were recorded.</p>'
    counts = {
        category: sum(row.category == category for row in rows)
        for category in (ORIGIN, METADATA, ACTIVITY)
    }
    colours = {ORIGIN: "var(--brand)", METADATA: "var(--metadata)", ACTIVITY: "var(--activity)"}
    present = [category for category in (ORIGIN, METADATA, ACTIVITY) if counts[category]]
    chips = (
        '<button class="btn" type="button" data-block="" aria-pressed="true">all categories</button>'
        + "".join(
            f'<button class="btn" type="button" data-block="{category}" aria-pressed="false">'
            f'<span class="dot" style="color:{colours[category]}"></span>'
            f"{category} {counts[category]}</button>"
            for category in present
        )
        if len(present) > 1
        else ""
    )
    body = "".join(
        f'<tr data-blk="{_e(row.category)}"'
        + (f' data-state="{_e(row.state)}"' if row.state else "")
        + f' id="evidence-{index + 1:05d}" data-image="{row.number:03d}"><td class="m"><a href="#photo-{row.number:03d}">#{row.number:03d}</a></td><td class="file"><a href="#photo-{row.number:03d}-fields">{_e(row.image)}</a>'
        + (
            f' <span class="tag {row.state}" title="File status; this value is not necessarily in conflict">file {row.state}</span>'
            if row.state
            else ""
        )
        + f'</td><td><span class="blk {_category_class(row.category)}">'
        f"{_e(row.category)}</span></td><td>{_e(row.source)}</td>"
        f'<td class="v"><a href="#evidence-{index + 1:05d}">{_e(row.field)}</a></td><td class="v">{_e(row.value)}</td>'
        f'<td class="m">{_e(row.match)}</td></tr>'
        for index, row in enumerate(rows)
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
    chipbar = f'<span class="seg needs-js">{chips}</span>' if chips else ""
    bar = (
        '<div class="meta-bar"><label class="search needs-js">'
        '<svg class="ic" aria-hidden="true"><use href="#i-search"/></svg>'
        '<input type="search" id="meta-filter"'
        ' placeholder="filter image, category, source, field or value"'
        ' aria-label="Filter the evidence table"></label>'
        f"{chipbar}{switches}"
        '<span class="sp"></span>'
        f'<span class="count" id="meta-count">showing {len(rows)} of {len(rows)}</span>'
        '<button class="btn icon needs-js" type="button" data-copy="meta-rows" hidden'
        ' title="Copy what is on screen as tab-separated text">'
        '<svg class="ic" aria-hidden="true"><use href="#i-copy"/></svg>'
        "</button></div>"
    )
    table = (
        '<div class="body flush"><div class="scroll"><table>'
        '<thead><tr><th style="width:56px">#</th>'
        '<th style="width:270px">image</th><th style="width:88px">category</th>'
        '<th style="width:160px">source</th><th style="width:160px">field</th>'
        '<th>recorded value</th><th style="width:110px">match basis</th></tr></thead>'
        f'<tbody id="meta-rows">{body}</tbody></table></div>'
        '<p class="small" id="meta-empty" style="padding:12px" hidden>No matching fields.</p>'
        "</div>"
    )
    return (
        f'<div class="panel">{bar}{table}'
        '<div class="foot"><span>without a script this table is delivered whole and printable;'
        " the filter only hides rows</span></div></div>"
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
