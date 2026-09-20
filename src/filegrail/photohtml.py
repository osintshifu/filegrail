"""Self-contained HTML renderer for photo-forensics findings."""

# The embedded stylesheet is deliberately compact because it is written verbatim
# into every report. Splitting CSS declarations to satisfy Python's line length
# would increase every generated artifact without improving the stylesheet.
# ruff: noqa: E501

from __future__ import annotations

import base64
from datetime import datetime
from html import escape
from pathlib import Path

from . import __version__
from .models import EvidenceRecord
from .photo import PhotoArtifact, PhotoCollection, PhotoFact, PhotoResult
from .photojpeg import JpegAnalysis

POLICY = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)

STYLE = r"""
:root{color-scheme:light;--table:#E7ECEE;--sleeve:#17232B;--paper:#FAFBFB;
--cyan:#287D8C;--amber:#A96721;--red:#A23F3F;--ink:#17232B;--muted:#607078;
--line:#B8C3C7;--white:#fff;--mono:ui-monospace,SFMono-Regular,Consolas,monospace;
--sans:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--table);
color:var(--ink);font-family:var(--sans);line-height:1.45}a{color:var(--cyan)}
a:focus-visible,summary:focus-visible{outline:3px solid var(--cyan);outline-offset:3px}
.lab-header{background:var(--sleeve);color:var(--white);padding:28px max(24px,5vw) 24px;
border-bottom:5px solid var(--cyan)}.brand{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}
.brand h1{font:700 clamp(1.6rem,4vw,3.2rem)/1 Georgia,serif;margin:0;letter-spacing:-.03em}
.brand p{margin:0;color:#BDD0D4;text-transform:uppercase;letter-spacing:.16em;font-size:.72rem}
.case-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));margin-top:28px;
border-top:1px solid #43535C;border-left:1px solid #43535C}.case-fact{padding:12px 14px;
border-right:1px solid #43535C;border-bottom:1px solid #43535C;min-width:0}
.case-fact b,.eyebrow{display:block;color:#91C6CF;text-transform:uppercase;letter-spacing:.12em;
font-size:.68rem}.case-fact span{display:block;overflow-wrap:anywhere;font-family:var(--mono);font-size:.82rem}
main{width:min(1500px,94vw);margin:30px auto 80px}.section-head{display:flex;align-items:end;
justify-content:space-between;gap:20px;border-bottom:2px solid var(--ink);margin:38px 0 16px}
.section-head h2{font:700 clamp(1.35rem,2.4vw,2rem)/1.1 Georgia,serif;margin:0 0 9px}
.section-head p{margin:0 0 9px;color:var(--muted);font-size:.86rem}.summary-grid{display:grid;
grid-template-columns:repeat(5,minmax(0,1fr));background:var(--paper);border:1px solid var(--line)}
.summary-item{padding:18px;border-right:1px solid var(--line)}.summary-item:last-child{border:0}
.summary-item b{display:block;font:700 1.45rem/1 Georgia,serif}.summary-item span{color:var(--muted);
font-size:.72rem;text-transform:uppercase;letter-spacing:.1em}.contact-sheet{display:grid;
grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px}.contact{display:block;
background:var(--sleeve);color:var(--white);padding:10px;text-decoration:none;border:1px solid #34454E}
.contact img{display:block;width:100%;height:150px;object-fit:contain;background:#0D151A}
.contact span{display:block;margin-top:9px;font-family:var(--mono);font-size:.75rem;overflow-wrap:anywhere}
.empty{background:var(--paper);border:1px solid var(--line);padding:26px;color:var(--muted)}
.camera-groups{background:var(--paper);border:1px solid var(--line);padding:16px 20px;margin-top:14px}
.camera-groups h3{font:700 1rem Georgia,serif;margin:0 0 8px}.camera-groups code{font-family:var(--mono)}
.camera-groups ul{margin:0;padding-left:20px}.plate{background:var(--paper);border:1px solid var(--line);
margin-top:30px}.plate-head{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:16px;
padding:14px 18px;border-bottom:1px solid var(--line)}.plate-number{font:700 1.25rem var(--mono);color:var(--cyan)}
.plate-title{min-width:0}.plate-title h2{font:700 1.25rem Georgia,serif;margin:0;overflow-wrap:anywhere}
.plate-title p{font:.73rem var(--mono);color:var(--muted);margin:3px 0 0;overflow-wrap:anywhere}
.format-stamp{border:1px solid var(--cyan);color:var(--cyan);padding:5px 8px;font:.7rem var(--mono)}
.plate-body{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(320px,.75fr)}
.image-stage{position:relative;background:var(--sleeve);min-height:390px;padding:30px;display:grid;
place-items:center;border-right:1px solid var(--line)}.stage-images{display:grid;grid-template-columns:1fr;
gap:18px;width:100%;height:100%}.stage-figure{margin:0;display:flex;flex-direction:column;
justify-content:center;align-items:center;min-height:260px}
.stage-figure img{display:block;max-width:100%;max-height:580px;object-fit:contain}.stage-figure figcaption{
align-self:start;color:#BCD0D5;font-size:.72rem;margin-top:8px}.registration-corner{position:absolute;
width:24px;height:24px;border-color:#80BBC6;border-style:solid;pointer-events:none}
.corner-tl{top:14px;left:14px;border-width:1px 0 0 1px}.corner-tr{top:14px;right:14px;
border-width:1px 1px 0 0}.corner-bl{bottom:14px;left:14px;border-width:0 0 1px 1px}
.corner-br{bottom:14px;right:14px;border-width:0 1px 1px 0}.redacted-stage{color:#C9D4D7;
max-width:32rem;text-align:center}.evidence-rail{padding:22px;min-width:0}.rail-block{border-bottom:1px solid var(--line);
padding:0 0 18px;margin:0 0 18px}.rail-block:last-child{border:0;margin:0;padding:0}.rail-block h3{
font:700 .8rem var(--sans);text-transform:uppercase;letter-spacing:.12em;margin:0 0 10px}
.identity{display:grid;grid-template-columns:max-content 1fr;gap:6px 14px;margin:0;font-size:.82rem}
.identity dt{color:var(--muted)}.identity dd{margin:0;overflow-wrap:anywhere}.mono{font-family:var(--mono)}
.findings,.methods,.metadata{list-style:none;padding:0;margin:0;display:grid;gap:8px}.finding,.method,.metadata li{
border-left:4px solid var(--cyan);padding:8px 10px;background:#F0F4F5;font-size:.8rem}
.finding strong,.method strong{display:block}.finding span,.method span{color:var(--muted)}
.finding strong,.finding span,.method strong,.method span,.metadata b,.metadata span{overflow-wrap:anywhere}
.finding.conflict{border-color:var(--red);background:#F8ECEC}.finding.signal{border-color:var(--amber);
background:#F8F0E5}.method.not-evaluated,.method.failed{border-color:var(--amber)}
.method.evaluated{border-color:var(--cyan)}.method.not-applicable{border-color:var(--line)}
.metadata b{font-family:var(--mono);font-size:.72rem}.metadata span{overflow-wrap:anywhere}
.diagnostics{padding:0 18px 20px}.diagnostic{border-top:1px solid var(--line)}.diagnostic summary{
cursor:pointer;display:flex;justify-content:space-between;gap:20px;padding:14px 2px;font-weight:700}
.diagnostic summary small{color:var(--muted);font-weight:400}.diagnostic figure{margin:0 0 18px;
display:grid;grid-template-columns:minmax(0,1fr) minmax(220px,.38fr);gap:18px;align-items:start}
.diagnostic img{display:block;max-width:100%;max-height:620px;object-fit:contain;background:var(--sleeve);
padding:12px}.method-note{font-size:.8rem}.method-note dt{color:var(--muted)}.method-note dd{margin:0 0 9px;
overflow-wrap:anywhere}.report-notes{font-size:.84rem;color:var(--muted);max-width:75rem}
.structure-body{padding:0 0 18px;display:grid;gap:18px}.table-wrap{max-width:100%;overflow:auto}
.structure table{width:100%;border-collapse:collapse;font-size:.76rem}.structure th,.structure td{
text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}.structure th{color:var(--muted)}
.structure h4{margin:0 0 6px;font:700 .78rem var(--sans);text-transform:uppercase;letter-spacing:.08em}
.matrix{margin:0;overflow:auto;padding:10px;background:var(--sleeve);color:#DCE7E9;font:11px/1.45 var(--mono)}
.structure-facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}
.structure-facts div{border-left:3px solid var(--cyan);padding:7px 9px;background:#F0F4F5;font-size:.78rem}
@media(max-width:1000px){.case-strip{grid-template-columns:repeat(2,minmax(0,1fr))}
.summary-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.plate-body{grid-template-columns:1fr}
.image-stage{border-right:0;border-bottom:1px solid var(--line)}}
@media(max-width:760px){main{width:min(100% - 24px,1500px);margin-top:16px}.lab-header{padding:22px 18px}
.case-strip,.summary-grid{grid-template-columns:1fr}.summary-item{border-right:0;border-bottom:1px solid var(--line)}
.plate-head{grid-template-columns:auto 1fr}.format-stamp{grid-column:2}.image-stage{min-height:260px;padding:24px}
.stage-figure{min-height:180px}.evidence-rail{padding:17px}.diagnostic figure{grid-template-columns:1fr}
.diagnostic summary{display:block}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
@media print{body{background:#fff;font-size:10pt}.lab-header{background:#fff;color:#000;border-color:#000;
padding:12mm 0}.case-fact b,.eyebrow{color:#000}main{width:100%;margin:0}.contact-sheet{display:none}
.plate{break-before:page;border-color:#777}.image-stage{background:#fff;min-height:0}.stage-figure figcaption{color:#000}
.diagnostic{break-inside:avoid}.diagnostic details,.diagnostic[open]{display:block}a{color:#000;text-decoration:none}}
"""


def render_photo_html(
    collection: PhotoCollection,
    *,
    output: Path | None = None,
    now: datetime | None = None,
) -> str:
    """Render one complete photo-forensics report with no external resources."""
    moment = (now or datetime.now().astimezone()).strftime("%Y-%m-%d %H:%M %Z").strip()
    title = f"{output.name} - FileGrail Photo Lab" if output else "FileGrail Photo Lab"
    head = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{POLICY}">'
        '<meta name="referrer" content="no-referrer">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_e(title)}</title><style>{STYLE}</style></head><body>"
    )
    case_facts = [
        ("target", collection.root),
        ("analysed", moment),
        ("report", str(output) if output else "in-memory render"),
        ("mode", "redacted" if collection.redacted else "full media"),
    ]
    masthead = (
        '<header class="lab-header" id="top"><div class="brand">'
        f"<h1>FileGrail Photo Lab</h1><p>v{_e(__version__)} / structural and pixel evidence</p>"
        '</div><div class="case-strip">'
        + "".join(
            f'<div class="case-fact"><b>{_e(label)}</b><span>{_e(value)}</span></div>'
            for label, value in case_facts
        )
        + "</div></header>"
    )
    body = ["<main>", _summary(collection), _contact_sheet(collection)]
    body.extend(_plate(photo, collection.redacted) for photo in collection.photos)
    body.append(_notes(collection))
    body.append("</main></body></html>")
    return head + masthead + "".join(body)


def _summary(collection: PhotoCollection) -> str:
    items = "".join(
        f'<div class="summary-item"><b>{_e(value)}</b><span>{_e(label)}</span></div>'
        for label, value in collection.summary
    )
    return (
        '<section aria-labelledby="summary-title"><div class="section-head">'
        '<h2 id="summary-title">Collection</h2><p>Facts counted from the files in this report.</p>'
        f'</div><div class="summary-grid">{items}</div></section>'
    )


def _contact_sheet(collection: PhotoCollection) -> str:
    heading = (
        '<section aria-labelledby="contact-title"><div class="section-head">'
        '<h2 id="contact-title">Contact sheet</h2><p>One index entry per analysed photograph.</p>'
        "</div>"
    )
    if not collection.photos:
        return (
            heading
            + '<p class="empty">No supported photographs were included in this report.</p></section>'
        )
    cards = []
    for photo in collection.photos:
        artifact = _first_artifact(photo, "main-preview", "embedded-preview")
        image = (
            _image(artifact, photo.name) if artifact else '<div class="empty">Media omitted</div>'
        )
        cards.append(
            f'<a class="contact" href="#photo-{photo.number:03d}">{image}'
            f"<span>#{photo.number:03d} / {_e(photo.name)}</span></a>"
        )
    groups = ""
    if collection.camera_groups:
        entries = []
        for serial, paths in collection.camera_groups:
            files = ", ".join(_e(Path(path).name) for path in paths)
            entries.append(f"<li><code>{_e(serial)}</code> / {files}</li>")
        groups = (
            '<aside class="camera-groups"><h3>Repeated camera body serials</h3><ul>'
            + "".join(entries)
            + "</ul></aside>"
        )
    return (
        heading + '<div class="contact-sheet">' + "".join(cards) + "</div>" + groups + "</section>"
    )


def _plate(photo: PhotoResult, redacted: bool) -> str:
    head = (
        f'<article class="plate" id="photo-{photo.number:03d}"><header class="plate-head">'
        f'<span class="plate-number">#{photo.number:03d}</span><div class="plate-title">'
        f"<h2>{_e(photo.name)}</h2><p>{_e(photo.path)}</p></div>"
        f'<span class="format-stamp">{_e(photo.format)}</span></header>'
    )
    stage = _stage(photo, redacted)
    rail = _rail(photo)
    diagnostics = _diagnostics(photo)
    return head + f'<div class="plate-body">{stage}{rail}</div>{diagnostics}</article>'


def _stage(photo: PhotoResult, redacted: bool) -> str:
    corners = "".join(
        f'<i class="registration-corner corner-{place}" aria-hidden="true"></i>'
        for place in ("tl", "tr", "bl", "br")
    )
    if redacted or not photo.artifacts:
        content = (
            '<p class="redacted-stage">No pixel-bearing image is embedded in this redacted report.</p>'
            if redacted
            else '<p class="redacted-stage">No decodable report preview was produced.</p>'
        )
    else:
        figures = []
        for key in ("main-preview", "embedded-preview"):
            artifact = _first_artifact(photo, key)
            if artifact:
                figures.append(
                    '<figure class="stage-figure">'
                    + _image(artifact, f"{photo.name}: {artifact.label}")
                    + f"<figcaption>{_e(artifact.label)} / {_e(artifact.method)}</figcaption></figure>"
                )
        content = '<div class="stage-images">' + "".join(figures) + "</div>"
    return f'<section class="image-stage" aria-label="Image stage">{corners}{content}</section>'


def _rail(photo: PhotoResult) -> str:
    dimensions = (
        f"{photo.width} x {photo.height} px" if photo.width and photo.height else "unavailable"
    )
    identity = [
        ("size", _size(photo.size)),
        ("dimensions", dimensions),
        ("modified", photo.mtime),
        ("SHA-256", photo.sha256 or "not calculated"),
        ("camera", photo.camera or "not recorded"),
        ("body serial", photo.serial or "not recorded"),
    ]
    identity_html = "".join(
        f'<dt>{_e(label)}</dt><dd class="{"mono" if label in {"SHA-256", "modified"} else ""}">'
        f"{_e(value)}</dd>"
        for label, value in identity
    )
    findings = "".join(_finding(fact) for fact in photo.facts) or "<li>No structural findings.</li>"
    methods = "".join(
        f'<li class="method {_status(method.status)}"><strong>{_e(method.name)}</strong>'
        f"<span>{_e(method.status)} / {_e(method.detail)}</span></li>"
        for method in photo.methods
    )
    metadata = "".join(_evidence(record) for record in photo.evidence)
    return (
        '<aside class="evidence-rail"><section class="rail-block"><h3>Identity</h3>'
        f'<dl class="identity">{identity_html}</dl></section>'
        '<section class="rail-block"><h3>Findings</h3>'
        f'<ul class="findings">{findings}</ul></section>'
        '<section class="rail-block"><h3>Method coverage</h3>'
        f'<ul class="methods">{methods}</ul></section>'
        '<section class="rail-block"><h3>Recorded metadata</h3>'
        f'<ul class="metadata">{metadata or "<li>No metadata evidence recorded.</li>"}</ul></section></aside>'
    )


def _finding(fact: PhotoFact) -> str:
    detail = f" / {_e(fact.detail)}" if fact.detail else ""
    return (
        f'<li class="finding {_status(fact.state)}"><strong>{_e(fact.label)}</strong>'
        f"<span>{_e(fact.value)} / {_e(fact.method)}{detail}</span></li>"
    )


def _evidence(record: EvidenceRecord) -> str:
    values = []
    for label, value in (("time", record.at), ("location", record.geo)):
        if value:
            values.append(f"<b>{_e(label)}</b> <span>{_e(value)}</span>")
    for name, value in sorted(record.fields.items()):
        values.append(f"<b>{_e(name)}</b> <span>{_e(value)}</span>")
    detail = "<br>".join(values) if values else "no decoded fields"
    return f"<li><b>{_e(record.source)}</b><br>{detail}</li>"


def _diagnostics(photo: PhotoResult) -> str:
    artifacts = [
        artifact
        for artifact in photo.artifacts
        if artifact.key not in {"main-preview", "embedded-preview"}
    ]
    if not artifacts and photo.jpeg is None:
        return ""
    items = [_jpeg_structure(photo.jpeg)] if photo.jpeg is not None else []
    for artifact in artifacts:
        dimensions = (
            f"{artifact.width} x {artifact.height} px"
            if artifact.width and artifact.height
            else "unavailable"
        )
        note = (
            '<dl class="method-note">'
            f"<dt>method</dt><dd>{_e(artifact.method)}</dd>"
            f"<dt>parameters</dt><dd>{_e(artifact.parameters or 'none')}</dd>"
            f"<dt>artifact</dt><dd>{_e(dimensions)} / {_size(len(artifact.data))}</dd></dl>"
        )
        items.append(
            '<details class="diagnostic" open><summary>'
            f"{_e(artifact.label)}<small>{_e(artifact.method)}</small></summary><figure>"
            + _image(artifact, f"{photo.name}: {artifact.label}")
            + note
            + "</figure></details>"
        )
    return (
        '<section class="diagnostics" aria-label="Derived diagnostics">'
        + "".join(items)
        + "</section>"
    )


def _jpeg_structure(jpeg: JpegAnalysis) -> str:
    marker_rows = "".join(
        f"<tr><td>{index}</td><td>{_e(marker.name)}</td>"
        f'<td class="mono">0x{marker.offset:08X}</td><td>{marker.length}</td></tr>'
        for index, marker in enumerate(jpeg.markers, 1)
    )
    components = "".join(
        f"<tr><td>{identifier}</td><td>{horizontal} x {vertical}</td><td>{table}</td></tr>"
        for identifier, horizontal, vertical, table in jpeg.components
    )
    tables = []
    for table in jpeg.quantization:
        rows = [
            " ".join(f"{value:3d}" for value in table.values[index : index + 8])
            for index in range(0, len(table.values), 8)
        ]
        tables.append(
            f"<div><h4>DQT {table.identifier} / {table.precision}-bit</h4>"
            f'<pre class="matrix">{_e(chr(10).join(rows))}</pre></div>'
        )
    huffman = (
        ", ".join(
            f"{table.table_class} {table.identifier}: {table.symbols} symbols"
            for table in jpeg.huffman
        )
        or "none recorded"
    )
    comments = " | ".join(jpeg.comments) or "none recorded"
    quality = "not estimated"
    if jpeg.quality:
        basis = "exact IJG match" if jpeg.quality.exact else "nearest IJG estimate"
        quality = f"{jpeg.quality.quality} / {basis} / distance {jpeg.quality.distance}"
    frame = (
        " / ".join(
            part
            for part in (
                jpeg.encoding,
                f"{jpeg.precision}-bit" if jpeg.precision is not None else None,
                f"{jpeg.width} x {jpeg.height} px" if jpeg.width and jpeg.height else None,
            )
            if part
        )
        or "frame not decoded"
    )
    structural_facts = (
        ("frame", frame),
        ("scans", str(jpeg.scans)),
        ("restart interval", str(jpeg.restart_interval or "not recorded")),
        ("EOI", f"0x{jpeg.eoi_offset:08X}" if jpeg.eoi_offset is not None else "not found"),
        ("trailing bytes", str(jpeg.trailing_bytes)),
        ("quality tables", quality),
        ("Huffman tables", huffman),
        ("comments", comments),
    )
    fact_html = "".join(
        f"<div><strong>{_e(label)}</strong><br>{_e(value)}</div>"
        for label, value in structural_facts
    )
    component_table = (
        '<div class="table-wrap"><h4>Frame components</h4><table><thead><tr>'
        "<th>ID</th><th>sampling</th><th>DQT</th></tr></thead>"
        f"<tbody>{components}</tbody></table></div>"
        if components
        else ""
    )
    return (
        '<details class="diagnostic structure"><summary>JPEG marker stream'
        '<small>offsets, frame and coding tables</small></summary><div class="structure-body">'
        f'<div class="structure-facts">{fact_html}</div>'
        '<div class="table-wrap"><h4>Markers</h4><table><thead><tr>'
        "<th>#</th><th>marker</th><th>offset</th><th>bytes</th></tr></thead>"
        f"<tbody>{marker_rows}</tbody></table></div>{component_table}"
        + "".join(tables)
        + "</div></details>"
    )


def _notes(collection: PhotoCollection) -> str:
    redaction = (
        " Pixel-bearing previews and diagnostics were omitted by redaction."
        if collection.redacted
        else ""
    )
    # Every map names its own encoding, but the consequence belongs here: a
    # reader looking for fine texture in an ELA map has to know that some of it
    # can come from the report rather than from the photograph.
    encoding = (
        " Photographs and continuous-tone maps are embedded as JPEG so the report stays one"
        " portable file, and fine texture in a map can come from that encoding. Histograms"
        " and bit planes are stored losslessly."
        if any(photo.artifacts for photo in collection.photos)
        else ""
    )
    return (
        '<section class="report-notes" aria-labelledby="notes-title"><div class="section-head">'
        '<h2 id="notes-title">Interpretation boundary</h2></div><p>'
        "This report records observable file structure, metadata and declared image transformations. "
        "A conflict is a mechanically supported disagreement. A signal identifies material for review. "
        "Neither state establishes that a photograph is authentic or manipulated."
        + encoding
        + redaction
        + "</p></section>"
    )


def _first_artifact(photo: PhotoResult, *keys: str) -> PhotoArtifact | None:
    return next((item for key in keys for item in photo.artifacts if item.key == key), None)


def _image(artifact: PhotoArtifact, alt: str) -> str:
    encoded = base64.b64encode(artifact.data).decode("ascii")
    width = f' width="{artifact.width}"' if artifact.width else ""
    height = f' height="{artifact.height}"' if artifact.height else ""
    return (
        f'<img src="data:{_e(artifact.mime)};base64,{encoded}" alt="{_e(alt)}"'
        f'{width}{height} loading="lazy">'
    )


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
