"""The investigation report as one self-contained HTML page.

The same `analysis.Case` the terminal report lays out, with the same sections,
numbers and findings, for a reader who wants to click from a file to its
conflict and back, search a large case, or print it. Dark on screen, with a
print stylesheet for paper.

The page is built to be opened on the machine that holds the case and forwarded
from there, so it can say nothing to anybody else by being opened:

- a Content-Security-Policy that allows no network request of any kind, so even
  a value that slipped past escaping could not fetch anything;
- no external stylesheet, script, font or image, and no `url()` anywhere; the
  mark in the masthead and the tab icon are inline drawings;
- the only links are to anchors in the page itself - a URL found in a file is
  printed as text, never as something to follow;
- no data embedded in a script: what the page holds is what it shows, so a
  redacted scan cannot leave the value it redacted behind in hidden JSON.

Every value that came out of a file - a name, a path, a field, a URL - is
escaped before it is written.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path

from . import __version__, reportchrome
from .analysis import NOTHING, REVIEW, Case, CaseFile, Conflict, Finding, Pivots, named
from .casereport import _ABSENT, _LISTED, _PER_FILE, _capital, _facts, _type_name
from .graph import Graph, Node, Relationship, build_graph, identifier_node_id
from .graphlayout import HEIGHT, WIDTH, Picture, picture
from .htmlicons import FAVICON, ICONS, MARK_SMALL
from .htmlscript import SCRIPT
from .htmlstyle import STYLE
from .identify import PLACE, Identifier
from .models import (
    CATEGORIES,
    CATEGORY_VERBS,
    CONTAINER_MEMBER,
    EMBEDDED,
    EVENT_VERBS,
    FILE_ATTRIBUTE,
    FILENAME,
    NAME_AND_SIZE,
    RECORDED_PATH,
    SIDECAR,
    SYNC_ROOT,
    EvidenceRecord,
    category,
)
from .overview import inventory
from .report import (
    _format,
    _read_from,
    _relative,
    _size,
    _stamp,
    _timeline_key,
    _timeline_value,
    shown,
)
from .scan import Unsearched

#: Nothing leaves the page: no fetch, no image, no font, no frame, no form.
POLICY = (
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
    "img-src data:; base-uri 'none'; form-action 'none'"
)


#: Files a pivot names before the rest go behind a summary: enough to see the
#: shape of the group, few enough to keep the row a row.
_HOLDERS = 6

#: Places a pivot shows of the twenty it keeps. Grouping them by file and
#: source collapses the repeats, so more of them fit in fewer lines.
_SAMPLE = 8

#: Bases that tie a record to this exact file rather than to a name it shares.
_STRONG = frozenset({EMBEDDED, FILE_ATTRIBUTE, RECORDED_PATH})

#: Compact definitions for the match bases that actually occur in the report.
_MATCH_NOTES = {
    EMBEDDED: "file bytes",
    FILE_ATTRIBUTE: "filesystem metadata for this file",
    RECORDED_PATH: "exact path in an external store",
    SIDECAR: "adjacent sidecar file",
    NAME_AND_SIZE: "same name and size; not unique",
    FILENAME: "same filename only",
    CONTAINER_MEMBER: "container membership",
    SYNC_ROOT: "managed sync folder",
}

#: In the order they are read. Coverage comes right after the findings: a
#: finding of "no trace" is read differently once it is known which stores
#: were there to search. Conflicts are a result; file detail is the material
#: behind every result, so it comes last before the notes.
_SECTIONS = (
    ("summary", "Summary", "Summary"),
    ("findings", "Key findings", "Findings"),
    ("coverage", "Evidence coverage", "Coverage"),
    ("timeline", "Timeline", "Timeline"),
    ("files", "Files", "Files"),
    ("relationships", "Relationships", "Related"),
    ("pivots", "Investigative pivots", "Pivots"),
    ("conflicts", "Conflicts", "Conflicts"),
    ("detail", "File detail", "Detail"),
    ("notes", "Report notes", "Notes"),
)


def render_html(
    case: Case,
    *,
    verbose: bool = False,
    identifiers: list[Identifier] | None = None,
    content: bool = False,
    metadata: bool = True,
    home: Path | None = None,
    unsearched: Unsearched | None = None,
    filtered: str = "",
    redacted: bool = False,
    output: Path | None = None,
    now: datetime | None = None,
) -> str:
    """The whole page. A section with nothing in it is not written."""
    files = {entry.record.path: entry for entry in case.files}
    moment = (now or datetime.now().astimezone()).strftime("%Y-%m-%d %H:%M %Z").strip()
    detailed = {entry.record.path for entry in case.files if _wants_detail(entry)}
    panes = (
        {kind for kind, _count in case.pivots.by_type}
        if case.pivots is not None and identifiers is not None and case.pivots.total
        else set()
    )
    records = [entry.record for entry in case.files]
    graph = build_graph(records, identifiers or [])
    pivot_refs = (
        {identifier_node_id(entry): ref for ref, entry in case.pivots.shared}
        if panes and case.pivots is not None
        else {}
    )
    relationship_count = len(graph.relationships)
    coverage = _coverage(case, unsearched)
    conflicts = _conflicts(case, files, detailed)
    linkable = frozenset(
        name for name, body in (("coverage", coverage), ("conflicts", conflicts)) if body
    )
    sections = {
        "summary": _summary(case, relationship_count),
        "findings": _findings(case, files, linkable),
        "coverage": coverage,
        "timeline": _timeline(case, files),
        "conflicts": conflicts,
        "files": _files(case, detailed, panes),
        "relationships": _relationships(graph, files, pivot_refs),
        "pivots": _pivots(case, files, identifiers),
        "detail": _details(case, files, detailed),
        "notes": _notes(case),
    }
    counted = _counts(case, detailed, relationship_count)
    present = [(key, title, short) for key, title, short in _SECTIONS if sections[key]]

    options = [
        ("--pivots", identifiers is not None),
        ("--content", identifiers is not None and content and not metadata),
        ("--meta", identifiers is not None and metadata and not content),
        ("--redact", redacted),
        ("--verbose", verbose),
    ]
    enabled = " ".join(name for name, on in options if on) or "none"
    facts = [("target", str(case.root))]
    if home:
        facts.append(("profile", f"{home} · external"))
    contents = inventory(records)
    facts.append(("scanned", f"{moment} · {len(records):,} files · {_size(contents.size)}"))
    facts.append(("options", enabled))
    if output is not None:
        facts.append(("report", str(output)))

    head = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f'<meta http-equiv="Content-Security-Policy" content="{POLICY}">',
        '<meta name="referrer" content="no-referrer">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="color-scheme" content="dark light">',
        f"<title>filegrail · {_e(Path(case.root).name or str(case.root))}</title>",
        FAVICON,
        f"<style>{STYLE}{reportchrome.STYLE}</style>",
        "</head>",
        "<body>",
        ICONS,
    ]
    masthead = [
        reportchrome.header(
            "File investigation",
            str(case.root),
            [("Generated", moment), ("Files", f"{len(records):,}"), ("Size", _size(contents.size))]
            + ([("Media", "Redacted")] if redacted else []),
            facts,
        )
    ]
    links = "".join(
        f'<a href="#{key}">{_e(short)}'
        + (f" <b>{counted[key]}</b>" if counted.get(key) else "")
        + "</a>"
        for key, _title, short in present
    )
    upwards = (
        '<a class="home" href="#top" title="Back to the top" '
        f'aria-label="Back to the top">{MARK_SMALL}</a>'
    )
    nav = [
        f'<nav class="nav">{upwards}{links}<span class="sp"></span>',
        '<label class="search"><input id="search" type="search" '
        'placeholder="search paths, values, fields" aria-label="Search the report" '
        'autocomplete="off" spellcheck="false">'
        '<svg class="ic" aria-hidden="true"><use href="#i-search"/></svg>'
        '<span class="hits" id="hits"></span><kbd>/</kbd></label>',
        '<div class="mast-actions">',
        '<button class="btn icon" id="print" type="button" title="Print / PDF" '
        'aria-label="Print / PDF"><svg class="ic" aria-hidden="true">'
        '<use href="#i-print"/></svg></button>',
        "</div>",
        "</nav>",
    ]
    body = ["<main>"]
    for key, title, _short in present:
        body.append(
            _section(
                key,
                title,
                sections[key],
                _note(key, case, detailed, relationship_count),
            )
        )
    if filtered:
        said = "No file matched" if not case.files else "Limited to"
        body.append(f'<p class="note">{_e(said)} {_e(filtered)}.</p>')
    body.append("</main>")
    body.append(
        '<button class="btn icon to-top" id="to-top" type="button" title="Back to top" '
        'aria-label="Back to top" hidden><svg class="ic" aria-hidden="true">'
        '<use href="#i-up"/></svg></button>'
    )
    footer = [
        "<footer>",
        f"<span>filegrail v{_e(__version__)} · Apache-2.0</span>",
        f"<span>generated {_e(moment)}</span>",
        "<span>this page makes no network requests</span>",
        "</footer>",
    ]
    tail = [f"<script>{SCRIPT}</script>", "</body>", "</html>"]
    return "\n".join(head + masthead + nav + body + footer + tail) + "\n"


# --- the frame -------------------------------------------------------------------


def _counts(case: Case, detailed: set[str], relationship_count: int) -> dict[str, str]:
    """The number the nav prints beside a section, where a number helps."""
    said = {
        "findings": f"{len(case.findings)}" if case.findings else "",
        "files": f"{len(case.files)}" if case.files else "",
        "detail": f"{len(detailed)}" if detailed else "",
        "conflicts": f"{len(case.conflicts)}" if case.conflicts else "",
        "relationships": f"{relationship_count}" if relationship_count else "",
        "timeline": f"{_dated(case)}" if _dated(case) else "",
    }
    if case.pivots is not None and case.pivots.total:
        said["pivots"] = f"{case.pivots.total}"
    return said


def _note(key: str, case: Case, detailed: set[str], relationship_count: int) -> str:
    """What the section heading says beside its name: the count, and what it counts."""
    if key == "findings" and case.findings:
        return f"{len(case.findings)}"
    if key == "files" and case.files:
        return f'{len(case.files):,} <b>· showing <span id="shown">{len(case.files):,}</span></b>'
    if key == "detail" and detailed:
        return f"{len(detailed):,} <b>· files with evidence</b>"
    if key == "conflicts" and case.conflicts:
        return f"{len(case.conflicts)}"
    if key == "relationships" and relationship_count:
        return f'<span id="relationship-shown">{relationship_count:,}</span> <b>· graph edges</b>'
    if key == "timeline" and _dated(case):
        files = len(
            {entry.record.path for entry in case.files for f in entry.record.evidence if f.at}
        )
        return f"{_dated(case):,} <b>· dated records in {files:,} files</b>"
    if key == "pivots" and case.pivots is not None:
        return f"{case.pivots.total:,} <b>· {case.pivots.across:,} in more than one file</b>"
    if key == "coverage":
        stores = [source for source in case.coverage if source.store]
        if stores:
            found = sum(1 for source in stores if source.state == "found")
            return f"{found} <b>of {len(stores)} trace stores</b>"
    return ""


def _section(key: str, title: str, body: str, note: str) -> str:
    """A section: its heading, the count beside it, and what it holds.

    The heading is also the handle that folds the section to one line, so a
    long report can be read a section at a time.
    """
    counted = f'<span class="n">{note}</span>' if note else ""
    fold = (
        f'<button class="fold" type="button" aria-expanded="true" aria-controls="{key}-body" '
        f'title="Collapse section" aria-label="Collapse {_e(title)}">'
        '<svg class="ic" aria-hidden="true"><use href="#i-chevron"/></svg></button>'
    )
    return (
        f'<section id="{key}"><div class="h">{fold}<h2>{_e(title)}</h2>{counted}</div>'
        f'<div class="sec-body" id="{key}-body">{body}</div></section>'
    )


def _copyable_table(table: str) -> str:
    """A table with one screen-only action in its top right corner: copy the visible rows as TSV."""
    return (
        '<div class="table-block"><div class="table-actions">'
        '<button class="btn icon table-copy" type="button" title="Copy table">'
        '<svg class="ic" aria-hidden="true"><use href="#i-copy"/></svg>'
        '<span class="vh table-copy-label">Copy table</span></button></div>'
        f"{table}</div>"
    )


# --- pieces ----------------------------------------------------------------------


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _anchor(ref: str) -> str:
    """The id a report number is found under: `#001` is `file-001`."""
    return f"file-{ref[1:]}" if ref.startswith("#") else ref


def _link(ref: str) -> str:
    """A finding or conflict number, framed the way its paragraph frames it."""
    return f'<a class="rid {_e(ref[:1].lower())}" href="#{_anchor(ref)}">{_e(ref)}</a>'


def _fields(
    pairs: list[tuple[str, str]],
    css: str = "fields",
    copy: bool | frozenset[str] = False,
    plain: frozenset[str] = frozenset(),
) -> str:
    """Labels and their values. Values `copy` names - or all but `plain` - get a copy button."""
    rows = []
    for label, value in pairs:
        wanted = (copy is True and label not in plain) or (
            isinstance(copy, frozenset) and label in copy
        )
        rows.append(f"<dt>{_e(label)}</dt><dd>{_value(value) if wanted else _e(value)}</dd>")
    return f'<dl class="{css}">{"".join(rows)}</dl>'


#: `Ingredient[1]:title`, `Signature[2]:Reason`, `RichEntry[3]`: one entry of a
#: numbered group, with or without a field of its own.
_NUMBERED = re.compile(r"^([A-Za-z][\w ]*?)\[(\d+)\](?::(.+))?$")


def _grouped(pairs: list[tuple[str, str]]) -> str:
    """Decoded fields, with numbered ones gathered under their group.

    A signature's name, date and reason belong together, and fourteen Rich
    header entries are one list, not fourteen labels that differ by a digit.
    Every value keeps its copy button.
    """
    groups: dict[str, dict[str, list[tuple[str, str]]]] = {}
    order: list[tuple[str, str, str]] = []
    for label, value in pairs:
        match = _NUMBERED.match(label)
        if match is None:
            order.append(("plain", label, value))
            continue
        prefix, number, field = match.group(1), match.group(2), match.group(3) or ""
        if prefix not in groups:
            groups[prefix] = {}
            order.append(("group", prefix, ""))
        groups[prefix].setdefault(number, []).append((field, value))

    rows = []
    for kind, label, value in order:
        if kind == "plain":
            rows.append(f"<dt>{_e(label)}</dt><dd>{_value(value)}</dd>")
            continue
        numbered = groups[label]
        if all(not field for entries in numbered.values() for field, _ in entries):
            items = "".join(
                f"<li>{_value(value)}</li>" for entries in numbered.values() for _, value in entries
            )
            rows.append(f'<dt>{_e(label)}</dt><dd><ol class="numbered">{items}</ol></dd>')
            continue
        for number, entries in numbered.items():
            inner = "".join(
                f"<dt>{_e(field or 'value')}</dt><dd>{_value(value)}</dd>"
                for field, value in entries
            )
            rows.append(f'<dt>{_e(label)} {number}</dt><dd><dl class="sub">{inner}</dl></dd>')
    return f'<dl class="fields">{"".join(rows)}</dl>'


def _value(value: str) -> str:
    """A value and a button that copies it: the text shown, never a second copy of it."""
    return (
        f'<span class="v">{_e(value)}</span>'
        '<button class="copy" type="button" title="copy" aria-label="copy">'
        '<svg class="ic" aria-hidden="true"><use href="#i-copy"/></svg>'
        '<svg class="ic ok" aria-hidden="true"><use href="#i-check"/></svg>'
        '<svg class="ic no" aria-hidden="true"><use href="#i-x"/></svg></button>'
    )


def _name(entry: CaseFile) -> str:
    return Path(entry.record.path).name


def _file_link(entry: CaseFile) -> str:
    """The number and the name as one link: four characters make a poor target."""
    return (
        f'<a href="#{_anchor(entry.ref)}"><span class="ref">{_e(entry.ref)}</span> '
        f"{_e(_name(entry))}</a>"
    )


def _match(found: EvidenceRecord) -> str:
    """The basis a record was tied to the file by, and whether it is an exact one."""
    strong = " strong" if found.matched_by in _STRONG else ""
    return f'<span class="pill match{strong}">{_e(found.matched_by)}</span>'


def _card(
    value: str,
    label: str,
    said: str = "",
    section: str | None = None,
    chosen: str = "",
    css: str = "",
) -> str:
    """One number in the summary, and what it opens when it opens something."""
    inner = f'<span class="v">{value}</span><span class="k">{_e(label)}</span>'
    if said:
        inner += f'<span class="s">{_e(said)}</span>'
    classes = f"card {css}".strip()
    if section is None:
        return f'<div class="{classes}">{inner}</div>'
    picked = f' data-filter="{chosen}"' if chosen else ""
    return f'<a class="{classes}" href="#{section}"{picked}>{inner}</a>'


def _sources(entries: list[CaseFile], name: str) -> str:
    """What is behind a category card: the sources that account for most of it."""
    counted: Counter[str] = Counter()
    for entry in entries:
        counted.update(entry.found[name])
    return " · ".join(label for label, _times in counted.most_common(3))


def _summary(case: Case, relationship_count: int) -> str:
    if not case.files:
        return ""
    records = [entry.record for entry in case.files]
    contents = inventory(records)
    holding = {name: [entry for entry in case.files if entry.found[name]] for name in CATEGORIES}
    review = [entry for entry in case.files if entry.state == REVIEW]
    quiet = [entry for entry in case.files if entry.state == NOTHING]
    fields = sum(len(conflict.differences) for conflict in case.conflicts)
    files = "files" if case.files else None

    cards = [
        _card(
            f"{len(records):,}",
            "files scanned",
            f"{len(contents.types):,} types · {_size(contents.size)}",
            files,
            "all",
        )
    ]
    for name in CATEGORIES:
        entries = holding[name]
        if not entries:
            continue
        cards.append(
            _card(f"{len(entries):,}", f"with {name}", _sources(entries, name), files, name, name)
        )
    if case.pivots is not None and case.pivots.total:
        said = f"{case.pivots.across:,} in more than one file"
        if case.pivots.cross_corpus:
            said += f" · {case.pivots.cross_corpus:,} in both corpora"
        cards.append(_card(f"{case.pivots.total:,}", "pivots", said, "pivots", "", "accent"))
    if relationship_count:
        cards.append(
            _card(
                f"{relationship_count:,}",
                "relationships",
                "evidence-backed graph edges",
                "relationships",
            )
        )
    if review:
        said = f"{len(case.conflicts)} conflicts · {fields} fields" if case.conflicts else ""
        cards.append(_card(f"{len(review):,}", "need review", said, files, "flag", "alert"))
    if quiet:
        cards.append(
            _card(
                f"{len(quiet):,}",
                "no evidence found",
                "see coverage before reading as absence",
                files,
                "none",
            )
        )
    stores = [source for source in case.coverage if source.store]
    if stores:
        found = sum(1 for source in stores if source.state == "found")
        said = f"history begins {case.begins}" if case.begins else ""
        cards.append(
            _card(
                f'{found}<span class="of">/{len(stores)}</span>',
                "trace stores found",
                said,
                "coverage",
            )
        )
    legend = (
        '<div class="legend">'
        '<span class="cat origin">origin · how it got here</span>'
        '<span class="cat metadata">metadata · what it says about itself</span>'
        '<span class="cat activity">activity · what happened to it here</span>'
        '<span><span class="flag">!</span> needs review</span>'
        "</div>"
    )
    return f'<div class="cards">{"".join(cards)}</div>{legend}'


def _findings(case: Case, files: dict[str, CaseFile], linkable: frozenset[str]) -> str:
    if not case.findings:
        return ""
    listed = "".join(_finding(case, finding, files, linkable) for finding in case.findings)
    return f'<div class="findings">{listed}</div>'


def _finding(
    case: Case, finding: Finding, files: dict[str, CaseFile], linkable: frozenset[str]
) -> str:
    warn = " warn" if finding.notable else ""
    facts = [(label, value) for label, value in finding.facts]
    if finding.kind in _PER_FILE:
        facts = [fact for fact in facts if fact[0] != "files"]
    parts = [
        f'<div class="find{warn}" id="{finding.ref}">',
        f'<a class="fid" href="#{finding.ref}">{finding.ref}</a><div>',
        f'<div class="head"><div class="t{warn}">{_e(finding.title)}</div>'
        f'<span class="kind">{_e(finding.kind.replace("-", " "))}</span></div>',
    ]
    if facts:
        parts.append(_fields([(_capital(label), value) for label, value in facts]))
    if finding.kind in _PER_FILE:
        for item in finding.items:
            entry = files[item.path]
            pairs = [(_capital(label), value) for label, value in item.facts]
            parts.append(
                f'<div class="files">{_file_link(entry)}</div>{_fields(pairs)}'
                if pairs
                else f'<div class="files">{_file_link(entry)}</div>'
            )
    elif finding.items:
        listed = " ".join(_file_link(files[item.path]) for item in finding.items)
        if finding.kind in _LISTED:
            parts.append(f'<div class="files">{listed}</div>')
        else:
            parts.append(
                f"<details><summary>{len(finding.items)} files</summary>"
                f'<div class="files">{listed}</div></details>'
            )
    if finding.kind == "no-trace":
        said = "This does not mean the files were never downloaded or transferred."
        if case.begins:
            said += f" Available trace history begins on {case.begins}."
        parts.append(f'<div class="note">{_e(said)}</div>')
    if finding.see:
        target = "conflicts" if finding.see == "CONFLICTS" else "coverage"
        # A pointer to a section the page does not have is a dead link.
        named = (
            f'<a href="#{target}">{_e(finding.see.lower())}</a>'
            if target in linkable
            else _e(finding.see.lower())
        )
        parts.append(f'<div class="note">See {named}.</div>')
    parts.append("</div></div>")
    return "".join(parts)


def _files(case: Case, detailed: set[str], panes: set[str]) -> str:
    if not case.files:
        return ""
    kinds = {finding.ref: finding.kind for finding in case.findings}
    rows = []
    for entry in case.files:
        record = entry.record
        marks = ["flag"] if entry.state == REVIEW else []
        marks += [name for name in CATEGORIES if entry.found[name]]
        if entry.state == NOTHING:
            marks.append("none")
        number = _e(entry.ref)
        opens = (
            f'<a href="#detail-{entry.ref[1:]}">{number}</a>' if record.path in detailed else number
        )
        flag = '<span class="flag">!</span>' if entry.state == REVIEW else ""
        dots = '<span class="dots" title="origin · metadata · activity">' + "".join(
            f'<i class="{name[0]}"></i>' if entry.found[name] else "<i></i>" for name in CATEGORIES
        )
        origin = record.origin
        arrived = (
            f'<span class="cat origin">{_e(named(origin))}</span> {_match(origin)}'
            if origin is not None
            else '<span class="dim">·</span>'
        )
        rows.append(
            f'<tr id="{_anchor(entry.ref)}" data-f="{" ".join(marks)}">'
            f'<td class="id">{opens}</td><td>{flag}</td>'
            f'<td class="path">{_value(_relative(record.path, case.root))}</td>'
            f"<td>{_e(_format(record.path))}</td>"
            f'<td class="num" data-value="{record.size}">{_e(_size(record.size))}</td>'
            f'<td class="dim">{_e(_stamp(shown(record.mtime)))}</td>'
            f"<td>{dots}</span></td><td>{arrived}</td>"
            f"<td>{_found_in(entry, kinds, panes)}</td></tr>"
        )
    table = _copyable_table(
        '<div class="wrap"><table class="tbl index" id="index"><thead><tr>'
        '<th data-sort="text">#</th><th></th><th data-sort="text">path</th>'
        '<th data-sort="text">type</th><th data-sort="num" class="num">size</th>'
        '<th data-sort="text">modified</th><th>evidence</th>'
        '<th data-sort="text">origin</th>'
        '<th data-sort="text">findings &amp; pivots</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )
    return f'<div class="chips">{_chips(case)}</div>{table}'


def _chips(case: Case) -> str:
    """The filters over the file index, each with what it would leave."""
    counted = [("all", "all", len(case.files))]
    review = sum(1 for entry in case.files if entry.state == REVIEW)
    if review:
        counted.append(("flag", "needs review", review))
    for name in CATEGORIES:
        held = sum(1 for entry in case.files if entry.found[name])
        if held:
            counted.append((name, name, held))
    quiet = sum(1 for entry in case.files if entry.state == NOTHING)
    if quiet:
        counted.append(("none", "no evidence", quiet))
    return "".join(
        f'<button type="button" class="chip{" on" if key == "all" else ""}" '
        f'data-filter="{key}">{_e(label)} <b>{times:,}</b></button>'
        for key, label, times in counted
    )


def _found_in(entry: CaseFile, kinds: dict[str, str], panes: set[str]) -> str:
    """The findings and conflicts a file is named in, then the pivot types found in it.

    Each of them leads somewhere: a finding to its paragraph, a pivot type to
    the tab that lists every pivot of that type and the files it was found in.
    """
    said = [_link(ref) for ref in entry.findings if kinds[ref] != "no-trace"]
    said += [_link(ref) for ref in entry.conflicts]
    found = [
        f'<a href="#pivots-type-{kind}">{_e(_type_name(kind))}</a>'
        if kind in panes
        else _e(_type_name(kind))
        for kind in entry.pivots
    ]
    pivots = f'<span class="dim">{" · ".join(found)}</span>' if found else ""
    return " ".join(said + ([pivots] if pivots else []))


#: Dated records the timeline lists before it says how many more there were.
_MAX_EVENTS = 3000


def _dated(case: Case) -> int:
    return sum(1 for entry in case.files for found in entry.record.evidence if found.at)


def _timeline(case: Case, files: dict[str, CaseFile]) -> str:
    """Every dated record in the scan on one spine, as the terminal `--timeline`.

    One line per record, grouped under the day it fell on: the clock, a node
    on the spine in the record's category colour, the verb, the file, the
    source and what it said. A day heading stays at the top while its records
    scroll past, and a long silence between two days is written on the spine.
    A file nothing said anything about has no place here: nothing happened at
    a time nobody recorded.
    """
    events = sorted(
        (
            (found.at, entry, found)
            for entry in case.files
            for found in entry.record.evidence
            if found.at
        ),
        key=lambda event: _timeline_key(event[0]),
    )
    if not events:
        return ""
    counts = Counter(category(found) for _, _, found in events)
    chips = [
        '<button type="button" class="chip on" data-tl="all" aria-pressed="true">all '
        f"<b>{len(events):,}</b></button>"
    ]
    chips.extend(
        f'<button type="button" class="chip" data-tl="{_e(kind)}" aria-pressed="false">'
        f'<i class="f-{_e(kind)}"></i>{_e(kind)} <b>{counts[kind]:,}</b></button>'
        for kind in CATEGORIES
        if counts[kind]
    )
    items = []
    day: str | None = None
    for at, entry, found in events[:_MAX_EVENTS]:
        stamp = _stamp(_timeline_value(at)) if at else ""
        invalid, moment, _ = _timeline_key(at)
        moment_attr = "" if invalid else f' data-moment="{moment:.3f}"'
        today, _, clock = stamp.partition(" ")
        if today != day:
            if day is not None and (silence := _silence(day, today)):
                items.append(f'<li class="tl-gap"><span>{_e(silence)}</span></li>')
            day = today
            items.append(
                f'<li class="tl-day"><time datetime="{_e(day)}">{_e(day)}</time>'
                f'<span class="wd">{_e(_weekday(day))}</span></li>'
            )
        kind = category(found)
        verb = EVENT_VERBS.get(found.source, CATEGORY_VERBS[kind])
        detail = found.url or found.tool or found.note or ""
        said = f'<span class="detail">{_e(_clip(detail, 120))}</span>' if detail else ""
        items.append(
            f'<li class="ev event" data-f="{_e(kind)}"{moment_attr}>'
            f'<time datetime="{_e(at or "")}">{_e(clock or stamp)}</time>'
            '<span class="node" aria-hidden="true"></span>'
            f'<span class="verb" title="{_e(kind)}">{_e(verb)}</span>'
            f'<span class="txt">{_file_link(entry)}'
            f'<span class="src">{_e(named(found))} {_match(found)}</span>{said}</span></li>'
        )
    note = ""
    if len(events) > _MAX_EVENTS:
        note = (
            f'<p class="note">Showing the first {_MAX_EVENTS:,} of {len(events):,} dated records; '
            "the rest are in the JSON and in each file's detail.</p>"
        )
    return (
        f'<div class="chips tl-chips" aria-label="Timeline category filters">{"".join(chips)}'
        '<span class="tl-shown" id="timeline-shown"></span></div>'
        f'<ol class="tl" id="timeline-list">{"".join(items)}</ol>{note}'
    )


#: A silence shorter than this between two days is just the next day.
_SILENCE_DAYS = 30


def _silence(earlier: str, later: str) -> str:
    """`7 years later`, said on the spine where a case goes quiet for that long."""
    try:
        gap = (datetime.fromisoformat(later) - datetime.fromisoformat(earlier)).days
    except ValueError:
        return ""
    if gap < _SILENCE_DAYS:
        return ""
    if gap >= 365:
        count, unit = gap // 365, "year"
    elif gap >= 60:
        count, unit = gap // 30, "month"
    else:
        count, unit = gap, "day"
    return f"{count} {unit}{'s' if count != 1 else ''} later"


def _weekday(day: str) -> str:
    try:
        return datetime.fromisoformat(day).strftime("%A")
    except ValueError:
        return ""


def _clip(value: str, width: int) -> str:
    return value if len(value) <= width else value[: width - 1] + "…"


def _relationships(graph: Graph, files: dict[str, CaseFile], pivot_refs: dict[str, str]) -> str:
    """An offline explorer over the same graph JSON and exports use."""
    if not graph.relationships:
        return ""

    nodes = {node.id: node for node in graph.nodes}
    connected = {edge.source for edge in graph.relationships} | {
        edge.target for edge in graph.relationships
    }
    kinds = Counter(edge.kind for edge in graph.relationships)
    kind_types: dict[str, set[str]] = {}
    for edge in graph.relationships:
        kind_types.setdefault(edge.kind, set()).add(nodes[edge.target].type)
    kind_markers = {
        kind: next(iter(types)) if len(types) == 1 else "mixed"
        for kind, types in kind_types.items()
    }
    chips = ['<button type="button" class="chip on" data-rel-kind="all">all</button>']
    chips.extend(
        f'<button type="button" class="chip" data-rel-kind="{_e(kind)}">'
        f'<i class="t-{_e(kind_markers[kind])} f-{_family(kind_markers[kind])}">'
        f"</i>{_e(kind)} <b>{count:,}</b></button>"
        for kind, count in sorted(kinds.items())
    )

    rows = []
    ordered = sorted(
        graph.relationships,
        key=lambda edge: (edge.kind.casefold(), edge.source, edge.target),
    )
    for edge in ordered:
        source = nodes[edge.source]
        target = nodes[edge.target]
        occurrence = "occurrence" if edge.count == 1 else "occurrences"
        often = f'<span class="dim">{edge.count:,} {occurrence}</span>'
        rows.append(
            f'<tr class="relationship" data-source="{_e(edge.source)}" '
            f'data-target="{_e(edge.target)}" data-kind="{_e(edge.kind)}">'
            f"<td>{_relationship_node(source, files)}</td>"
            '<td class="arrow" aria-label="points to">'
            '<svg class="ic" aria-hidden="true"><use href="#i-arrow"/></svg></td>'
            f'<td class="kind">{_e(edge.kind)}{often}</td>'
            f"<td>{_relationship_node(target, files)}</td>"
            f"<td>{_relationship_evidence(edge)}</td></tr>"
        )

    controls = (
        '<div class="graph-toolbar"><div class="rel-controls">'
        '<label for="relationship-find" class="rel-find">Find node'
        '<input id="relationship-find" type="search" '
        'placeholder="type a name, path or value" '
        'autocomplete="off" spellcheck="false"></label>'
        '<label for="relationship-node">Focus node'
        '<select id="relationship-node"><option value="">All connected nodes</option>'
        f"{_relationship_options(graph, connected, files)}</select></label>"
        '</div><div class="graph-arrange" role="group" aria-label="Graph arrangement">'
        '<label for="graph-layout">Layout<select id="graph-layout">'
        '<option value="force">Force-directed</option>'
        '<option value="rings">Files inside, identifiers around</option>'
        '<option value="columns">Columns by type</option></select></label>'
        '<label for="graph-spacing">Spacing<span class="range">'
        '<input id="graph-spacing" type="range" min="60" max="260" step="10" value="100">'
        '<output id="graph-spacing-value" aria-live="polite">100%</output></span></label>'
        '<label for="graph-labels">Labels<select id="graph-labels">'
        '<option value="auto">Main nodes</option><option value="all">Every node</option>'
        '<option value="none">None</option></select></label>'
        '</div><div class="graph-tools" role="group" aria-label="Graph view controls">'
        '<button class="btn icon" id="graph-zoom-out" type="button" '
        'title="Zoom out" aria-label="Zoom out">−</button>'
        '<output id="graph-zoom-value" aria-live="polite">100%</output>'
        '<button class="btn icon" id="graph-zoom-in" type="button" '
        'title="Zoom in" aria-label="Zoom in">+</button>'
        '<button class="btn compact" id="graph-fit" type="button" '
        'title="Frame the focused or filtered nodes, or the whole graph">Fit</button>'
        '<button class="btn compact" id="graph-export" type="button" '
        'title="Export the current graph view as SVG">Export SVG</button>'
        '<button class="btn icon" id="graph-reset" type="button" '
        'title="Reset view, filters and arrangement" aria-label="Reset graph">'
        '<svg class="ic" aria-hidden="true"><use href="#i-refresh"/></svg></button>'
        '<button class="btn icon" id="graph-full" type="button" aria-pressed="false" '
        'title="Full screen (Esc leaves)" aria-label="Full screen">'
        '<svg class="ic in" aria-hidden="true"><use href="#i-expand"/></svg>'
        '<svg class="ic out" aria-hidden="true"><use href="#i-collapse"/></svg></button>'
        "</div></div>"
        '<div class="graph-filterbar">'
        f'<div class="rel-kinds" aria-label="Relationship type filters">{"".join(chips)}</div>'
        "</div>"
    )
    table = _copyable_table(
        '<div class="wrap"><table class="tbl relationships" id="relationship-table">'
        '<thead><tr><th data-sort="text">from</th><th></th>'
        '<th data-sort="text">relation</th><th data-sort="text">to</th>'
        f"<th>evidence</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )
    table_tools = (
        '<div class="relationship-table-tools">'
        '<label for="relationship-table-find"><span class="vh">Filter results</span>'
        '<input id="relationship-table-find" type="search" '
        'placeholder="from, relation, to or evidence" autocomplete="off" spellcheck="false">'
        "</label>"
        '<label for="relationship-kind"><span class="vh">Relation type</span>'
        '<select id="relationship-kind"><option value="all">All relation types</option>'
        + "".join(
            f'<option value="{_e(kind)}">{_e(kind)} · {count:,}</option>'
            for kind, count in sorted(kinds.items())
        )
        + "</select></label>"
        '<label for="relationship-sort"><span class="vh">Sort by</span>'
        '<select id="relationship-sort">'
        '<option value="relation-asc">Relation A–Z</option>'
        '<option value="relation-desc">Relation Z–A</option>'
        '<option value="from-asc">From A–Z</option>'
        '<option value="from-desc">From Z–A</option>'
        '<option value="to-asc">To A–Z</option>'
        '<option value="to-desc">To Z–A</option>'
        "</select></label>"
        '<button class="btn compact" id="relationship-table-clear" type="button">'
        "Clear filters</button></div>"
    )
    return (
        '<div class="graph-panel">'
        + controls
        + _figure(picture(graph), files, pivot_refs)
        + '</div><div class="relationship-bar"><h3>Relationship evidence</h3>'
        + table_tools
        + "</div>"
        + table
    )


#: Nodes that get a label in the picture; the rest name themselves on hover.
_MAX_LABELS = 48

#: The colour a node takes, by what it stands for: a file, a person, a device,
#: an address on a network, money, or a key such as a hash or a token.
_FAMILIES = {
    "file": "file",
    "person": "person",
    "org": "person",
    "handle": "person",
    "telegram": "person",
    "device": "device",
    "lens": "device",
    "camera_model": "device",
    "mac": "device",
    "vin": "device",
    "email": "address",
    "domain": "address",
    "url": "address",
    "host": "address",
    "ipv4": "address",
    "ipv6": "address",
    "onion": "address",
    "geo": "address",
    "iban": "money",
    "bic": "money",
    "btc": "money",
    "nip": "money",
    "regon": "money",
    "ssn": "money",
}


def _family(kind: str) -> str:
    return _FAMILIES.get(kind, "key")


_LABELLED_TYPES = frozenset({"file", "person", "org", "handle", "device", "lens", "camera_model"})


def _figure(drawn: Picture | None, files: dict[str, CaseFile], pivot_refs: dict[str, str]) -> str:
    """The graph as a picture: the connected part of it, up to a fixed size.

    Clicking a node focuses it in the explorer below, so the picture is a way
    into the table rather than a substitute for it.
    """
    if drawn is None:
        return ""
    # Files, people and devices are labelled; an identifier is labelled only
    # where it ties two or more files together. The rest name themselves on hover, which
    # keeps a crowd of one-off addresses from writing over each other.
    files_touched: Counter[int] = Counter()
    for a, b, _ in drawn.edges:
        if drawn.nodes[b].type == "file":
            files_touched[a] += 1
        if drawn.nodes[a].type == "file":
            files_touched[b] += 1
    worth = [
        node
        for at, node in enumerate(drawn.nodes)
        if node.type in _LABELLED_TYPES or files_touched[at] >= 2
    ]
    labelled = {
        node.id for node in sorted(worth, key=lambda item: (-item.degree, item.id))[:_MAX_LABELS]
    }
    lines = "".join(
        f'<line class="e" data-source="{_e(drawn.nodes[a].id)}" data-kind="{_e(kind)}" '
        f'data-target="{_e(drawn.nodes[b].id)}" x1="{drawn.nodes[a].x}" y1="{drawn.nodes[a].y}" '
        f'x2="{drawn.nodes[b].x}" y2="{drawn.nodes[b].y}"><title>{_e(kind)}</title></line>'
        for a, b, kind in drawn.edges
    )
    marks = []
    for node in drawn.nodes:
        radius = round(min(4 + 1.6 * math.sqrt(node.degree), 14), 1)
        held = files.get(node.value) if node.type == "file" else None
        label = f"{held.ref} {_name(held)}" if held else _clip(node.value, 28)
        title = f"{_node_type(node.type)} · {node.value} · {node.degree:,} relationships"
        data = (
            f' data-node-type="{_e(_node_type(node.type))}"'
            f' data-node-value="{_e(node.value)}" data-node-degree="{node.degree}"'
        )
        if held is not None:
            record = held.record
            evidence = sum(len(found) for found in held.found.values())
            origin = named(record.origin) if record.origin is not None else "none"
            link = f"#detail-{held.ref[1:]}" if _wants_detail(held) else f"#{_anchor(held.ref)}"
            data += (
                f' data-file-ref="{_e(held.ref)}" data-file-name="{_e(_name(held))}"'
                f' data-file-path="{_e(record.path)}" data-file-format="{_e(_format(record.path))}"'
                f' data-file-size="{_e(_size(record.size))}"'
                f' data-file-modified="{_e(_stamp(shown(record.mtime)))}"'
                f' data-file-evidence="{evidence}" data-file-state="{_e(held.state)}"'
                f' data-file-origin="{_e(origin)}" data-file-link="{_e(link)}"'
            )
        elif node.id in pivot_refs:
            data += f' data-pivot-link="#{_e(pivot_refs[node.id])}"'
        aux = "" if node.id in labelled else ' class="aux"'
        text = f'<text{aux} x="{node.x}" y="{node.y + radius + 11}">{_e(label)}</text>'
        marks.append(
            f'<g class="node t-{_e(node.type)} f-{_family(node.type)}" '
            f'data-graph-node="{_e(node.id)}" '
            f'data-rel-focus="{_e(node.id)}"{data} tabindex="0" role="button">'
            f'<circle class="halo" cx="{node.x}" cy="{node.y}" r="{radius + 5}"/>'
            f'<circle cx="{node.x}" cy="{node.y}" r="{radius}"/>{text}'
            f"<title>{_e(title)}</title></g>"
        )
    # The picture is capped; a reader should hear when the table holds more.
    caption = (
        f"<figcaption>{drawn.left_out:,} more connected nodes are in the table below</figcaption>"
        if drawn.left_out
        else ""
    )
    return (
        '<figure class="graph"><div class="graph-canvas">'
        f'<svg id="evidence-graph" viewBox="0 0 {WIDTH} {HEIGHT}" '
        'role="img" aria-label="Evidence graph" tabindex="0">'
        + '<g class="graph-viewport">'
        + f'<g class="edges">{lines}</g><g class="nodes">{"".join(marks)}</g></g></svg>'
        '<aside class="graph-detail" id="graph-detail" hidden>'
        '<div class="graph-detail-head"><span id="graph-detail-type"></span>'
        '<button type="button" id="graph-detail-close" aria-label="Close node details">×</button>'
        '</div><strong id="graph-detail-value"></strong><dl>'
        '<div><dt>Relationships</dt><dd id="graph-detail-degree"></dd></div>'
        '<div class="file-only"><dt>File</dt><dd id="graph-detail-file"></dd></div>'
        '<div class="file-only"><dt>Path</dt><dd id="graph-detail-path"></dd></div>'
        '<div class="file-only"><dt>Format</dt><dd id="graph-detail-format"></dd></div>'
        '<div class="file-only"><dt>Size</dt><dd id="graph-detail-size"></dd></div>'
        '<div class="file-only"><dt>Modified</dt><dd id="graph-detail-modified"></dd></div>'
        '<div class="file-only"><dt>Evidence</dt><dd id="graph-detail-evidence"></dd></div>'
        '<div class="file-only"><dt>State</dt><dd id="graph-detail-state"></dd></div>'
        '<div class="file-only"><dt>Origin</dt><dd id="graph-detail-origin"></dd></div>'
        '</dl><div class="graph-detail-connected"><h4>Connected to</h4>'
        '<ul id="graph-detail-connected"></ul></div>'
        '<div class="graph-detail-actions">'
        '<a class="btn compact file-only" id="graph-detail-open">Open file detail</a>'
        '<a class="btn compact pivot-only" id="graph-detail-pivot" hidden>Open pivot</a>'
        "</div></aside></div>"
        f"{caption}</figure>"
    )


def _relationship_options(graph: Graph, connected: set[str], files: dict[str, CaseFile]) -> str:
    degrees = Counter(
        node_id for edge in graph.relationships for node_id in (edge.source, edge.target)
    )
    groups: dict[str, list[Node]] = {}
    for node in graph.nodes:
        if node.id in connected:
            groups.setdefault(node.type, []).append(node)

    order = {"file": 0, "person": 1, "device": 2, "lens": 3, "camera_model": 4}
    rendered = []
    for kind, nodes in sorted(groups.items(), key=lambda item: (order.get(item[0], 5), item[0])):
        options = []
        for node in sorted(nodes, key=lambda item: (-degrees[item.id], item.value.casefold())):
            value = _relationship_option_label(node, files)
            options.append(
                f'<option value="{_e(node.id)}">{_e(value)} · {degrees[node.id]:,}</option>'
            )
        label = {
            "camera_model": "camera models",
            "device": "camera bodies",
            "lens": "lenses",
            "file": "files",
            "person": "people",
        }.get(kind, _type_name(kind).lower())
        rendered.append(f'<optgroup label="{_e(label)}">{"".join(options)}</optgroup>')
    return "".join(rendered)


def _relationship_option_label(node: Node, files: dict[str, CaseFile]) -> str:
    if node.type == "file" and node.value in files:
        entry = files[node.value]
        return f"{entry.ref} {_name(entry)}"
    return node.value


def _node_type(kind: str) -> str:
    return {
        "bic": "BIC",
        "camera_model": "camera model",
        "cve": "CVE",
        "cwe": "CWE",
        "device": "camera body",
        "email": "email",
        "file": "file",
        "ghsa": "GHSA",
        "ipv4": "IPv4",
        "ipv6": "IPv6",
        "md5": "MD5",
        "person": "person",
        "sha1": "SHA-1",
        "sha256": "SHA-256",
        "sha512": "SHA-512",
        "url": "URL",
    }.get(kind, kind.replace("_", " "))


def _relationship_node(node: Node, files: dict[str, CaseFile]) -> str:
    if node.type == "file" and node.value in files:
        value = _file_link(files[node.value])
    else:
        value = _value(node.value)
    focus = (
        f'<button class="rel-focus" type="button" data-rel-focus="{_e(node.id)}" '
        f'title="Focus this node" aria-label="Focus {_e(node.value)}">'
        '<svg class="ic" aria-hidden="true"><use href="#i-focus"/></svg></button>'
    )
    return (
        '<div class="rel-node">'
        f'<span class="pill"><i class="f-{_family(node.type)}"></i>{_e(_node_type(node.type))}'
        f"</span>{value}{focus}</div>"
    )


def _relationship_evidence(edge: Relationship) -> str:
    proofs = []
    for proof in edge.evidence:
        facts = [
            ("source", proof.source),
            ("place", proof.place),
            ("corpus", proof.corpus),
        ]
        if proof.category is not None:
            facts.append(("category", proof.category))
        if proof.match is not None:
            facts.append(("match", proof.match))
        if proof.at is not None:
            facts.append(("time", proof.at))
        if proof.count != 1:
            facts.append(("occurrences", f"{proof.count:,}"))
        # A derived relationship was never written in any file: it follows from
        # the value. It is marked so it cannot be read as an observation, and it
        # says which rule was applied to what.
        derived = proof.rule is not None
        if derived:
            facts.append(("rule", proof.rule or ""))
            facts.append(("premise", proof.premise or ""))
        mark = ' <span class="rel-derived">not observed, derived</span>' if derived else ""
        proofs.append(
            f'<div class="rel-proof{" derived" if derived else ""}">{mark}{_fields(facts)}</div>'
        )
    count = len(proofs)
    label = "evidence item" if count == 1 else "evidence items"
    return f"<details><summary>{count:,} {label}</summary>{''.join(proofs)}</details>"


def _pivots(case: Case, files: dict[str, CaseFile], identifiers: list[Identifier] | None) -> str:
    """Every pivot, one tab a type, each with the files it was found in and where."""
    pivots = case.pivots
    if pivots is None or not pivots.total or identifiers is None:
        return ""
    kinds: dict[str, list[Identifier]] = {}
    for entry in identifiers:
        kinds.setdefault(entry.type, []).append(entry)
    refs = {f"{entry.type}\0{entry.normalized}": ref for ref, entry in pivots.shared}
    across = sorted(
        (entry for entry in identifiers if entry.files > 1),
        key=lambda entry: (-entry.files, -entry.count, entry.type, entry.normalized),
    )

    panels: list[tuple[str, str, int, str]] = []
    if across:
        table = _pivot_table(across, files, refs, across=True)
        panels.append(("pivots-across", "Across files", len(across), table))
    if pivots.dense:
        panels.append(
            ("pivots-dense", "High-density files", len(pivots.dense), _dense(pivots, files))
        )
    for kind, count in pivots.by_type:
        table = _pivot_table(kinds[kind], files, refs, across=False)
        panels.append((f"pivots-type-{kind}", _type_name(kind), count, table))

    tabs = "".join(
        f'<button type="button" role="tab" data-panel="{key}" '
        f'class="{"on" if number == 0 else ""}" '
        f'aria-selected="{"true" if number == 0 else "false"}">'
        f"{_e(label)} <b>{count:,}</b></button>"
        for number, (key, label, count, _table) in enumerate(panels)
    )
    shown_panels = "".join(
        f'<div class="pane{" on" if number == 0 else ""}" id="{key}" role="tabpanel" '
        f'data-label="{_e(label)}">{table}</div>'
        for number, (key, label, _count, table) in enumerate(panels)
    )
    return f'<div class="tabs" role="tablist">{tabs}</div>{shown_panels}'


def _pivot_table(
    entries: list[Identifier], files: dict[str, CaseFile], refs: dict[str, str], *, across: bool
) -> str:
    rows = []
    for entry in entries:
        ref = refs.get(f"{entry.type}\0{entry.normalized}")
        holders = sorted(
            entry.holders.items(),
            key=lambda pair: (-pair[1], files[pair[0]].ref if pair[0] in files else pair[0]),
        )
        named_here = [_holder(files, path, times) for path, times in holders[:_HOLDERS]]
        found_in = " ".join(named_here)
        left = len(holders) - len(named_here)
        if left:
            rest = " ".join(_holder(files, path, times) for path, times in holders[_HOLDERS:])
            found_in += f"<details><summary>+{left:,} more</summary>{rest}</details>"
        places = _places(entry.where[:_SAMPLE])
        # The number is an anchor once, in the table across files; the same
        # pivot listed again under its type must not carry the id a second time.
        opening = f'<tr class="pivot" id="{ref}">' if ref and across else '<tr class="pivot">'
        number = f'<span class="pid">{_e(ref)}</span>' if ref else ""
        leading = (
            f'<td class="id">{number}</td>'
            f'<td class="kind"><i class="f-{_family(entry.type)}"></i>'
            f"{_e(_type_name(entry.type))}</td>"
            if across
            else ""
        )
        corpus = "both" if len(entry.corpora) > 1 else next(iter(entry.corpora), "")
        rows.append(
            opening + leading + f'<td class="val">{_value(entry.value)}</td>'
            f'<td class="corpus"><span class="pill corpus {corpus}">{corpus}</span></td>'
            f'<td class="num" data-value="{entry.files}">{entry.files:,}</td>'
            f'<td class="num" data-value="{entry.count}">{entry.count:,}</td>'
            f'<td class="where">{places}</td><td class="found">{found_in}</td></tr>'
        )
    heads = '<th data-sort="text">#</th><th data-sort="text">type</th>' if across else ""
    return _copyable_table(
        f'<div class="wrap"><table class="tbl pivots"><thead><tr>{heads}'
        '<th data-sort="text">value</th><th data-sort="text">corpus</th>'
        '<th data-sort="num" class="num">files</th>'
        '<th data-sort="num" class="num">times</th><th>where (sample)</th>'
        f"<th>found in</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def _places(sample: list[str]) -> str:
    """Where a value was found, one line a file and source.

    A value sitting five times in one file says that file's name once and then
    the five spots inside it, rather than five lines that differ by a number.
    """
    grouped: dict[tuple[str, str], list[str]] = {}
    for place in sample:
        held, _, rest = place.partition(PLACE)
        source, _, spot = rest.partition(PLACE)
        grouped.setdefault((held, source), []).append(spot)
    lines = []
    for (held, source), spots in grouped.items():
        said = PLACE.join(part for part in (held, source) if part)
        kept = [spot for spot in spots if spot]
        if kept:
            said += PLACE + _spots(kept)
        lines.append(_e(said))
    return "<br>".join(lines)


def _spots(spots: list[str]) -> str:
    """`lines 2, 3, 4` where the spots are numbered the same way, else as they are."""
    if len(spots) > 1:
        heads = {spot.rsplit(" ", 1)[0] for spot in spots}
        tails = [spot.rsplit(" ", 1)[-1] for spot in spots]
        head = heads.pop() if len(heads) == 1 else None
        if head and head.isalpha() and head.islower() and all(t.isdigit() for t in tails):
            return f"{head}s {', '.join(tails)}"
    return ", ".join(spots)


def _holder(files: dict[str, CaseFile], path: str, times: int) -> str:
    """A file a pivot was found in, as a link to it, and how often when more than once."""
    held = files.get(path)
    name = _file_link(held) if held else _e(Path(path).name)
    often = f" ×{times:,}" if times > 1 else ""
    return f'<span class="holder">{name}{often}</span>'


def _dense(pivots: Pivots, files: dict[str, CaseFile]) -> str:
    rows = []
    for dense in pivots.dense:
        held = files.get(dense.path)
        name = _file_link(held) if held else _e(dense.path)
        kinds = " · ".join(f"{_type_name(kind)} {count:,}" for kind, count in dense.by_type)
        rows.append(
            f'<tr class="pivot"><td class="path">{name}</td>'
            f'<td class="num" data-value="{dense.places}">{dense.places:,}</td>'
            f"<td>{_e(kinds)}</td></tr>"
        )
    return _copyable_table(
        '<div class="wrap"><table class="tbl"><thead><tr><th data-sort="text">file</th>'
        '<th data-sort="num" class="num">places</th><th>by type</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _wants_detail(entry: CaseFile) -> bool:
    """A file gets a block of its own when there is something to read in it.

    Metadata counts. A document that names its author, a font that names its
    foundry and an executable that names its build machine have each said
    something worth reading, whether or not a download record sits beside it.
    """
    return entry.state != NOTHING


def _details(case: Case, files: dict[str, CaseFile], detailed: set[str]) -> str:
    findings = {finding.ref: finding for finding in case.findings}
    conflicts = {conflict.ref: conflict for conflict in case.conflicts}
    parts = []
    for entry in case.files:
        if entry.record.path not in detailed:
            continue
        parts.append(_detail(case, entry, files, findings, conflicts))
    return "".join(parts)


def _detail(
    case: Case,
    entry: CaseFile,
    files: dict[str, CaseFile],
    findings: dict[str, Finding],
    conflicts: dict[str, Conflict],
) -> str:
    record = entry.record
    body = []
    for name in CATEGORIES:
        held = [found for found in record.evidence if category(found) == name]
        if not held:
            body.append(
                f'<div class="rec silent"><span class="cat none">{_e(name)}</span>'
                f'<div><div class="note">{_e(_ABSENT[name])}</div></div></div>'
            )
            continue
        for found in held:
            # Every decoded field, as the terminal report shows them: a page
            # has room, and the field an investigation turns on is rarely the
            # one a summary would have picked.
            facts = [
                (label, value)
                for label, value in _facts(found, name, verbose=True)
                if label != "Match"
            ]
            body.append(
                f'<div class="rec"><span class="cat {name}">{_e(name)}</span>'
                f'<div><div class="src">{_e(named(found))} {_match(found)}</div>'
                + (f'<div class="note">{_e(found.note)}</div>' if found.note else "")
                + (
                    f'<div class="note">read from {_e(_read_from(found))}</div>'
                    if found.where
                    else ""
                )
                + "</div>"
                + (_grouped(facts) if facts else "")
                + "</div>"
            )
    notes = []
    for ref in entry.conflicts:
        conflict = conflicts[ref]
        fields = " · ".join(difference.field for difference in conflict.differences)
        notes.append(f"{_e(' and '.join(conflict.sources))} disagree on {_e(fields)} {_link(ref)}")
    for ref in entry.findings:
        finding = findings[ref]
        if finding.kind in ("conflicts", "no-trace"):
            continue
        others = [files[item.path] for item in finding.items if item.path != record.path]
        said = f"{_e(finding.title)} {_link(ref)}"
        if others and len(others) <= 6:
            said += ": " + " · ".join(_file_link(other) for other in others)
        elif others:
            said += f": with {len(others)} other files"
        notes.append(said)
    if notes:
        body.append(
            '<div class="extra"><span class="k">related</span><ul>'
            + "".join(f"<li>{note}</li>" for note in notes)
            + "</ul></div>"
        )
    flag = ' <span class="flag">!</span>' if entry.state == REVIEW else ""
    refs = " ".join(_link(ref) for ref in entry.findings + entry.conflicts)
    meta = f"{_e(_size(record.size))} · {_e(_format(record.path))}"
    review = " review" if entry.state == REVIEW else ""
    return (
        f'<details class="file{review}" id="detail-{entry.ref[1:]}"'
        f"{' open' if entry.state == REVIEW else ''}>"
        f'<summary><span class="id">{_e(entry.ref)}</span>'
        f'<span class="name">{_e(_relative(record.path, case.root))}{flag}</span>'
        f'<span class="meta">{meta} {refs}'
        '<svg class="chev" aria-hidden="true"><use href="#i-chevron"/></svg></span></summary>'
        f"{''.join(body)}</details>"
    )


def _coverage(case: Case, unsearched: Unsearched | None) -> str:
    missed = [(path, "could not be read") for path in (unsearched.unreadable if unsearched else [])]
    missed += [(path, "skipped by name") for path in (unsearched.by_name if unsearched else [])]
    if not case.coverage and not missed:
        return ""
    states = {"found": "origin", "readable": "origin", "partial": "activity"}
    rows = []
    for source in case.coverage:
        state = states.get(source.state, "none")
        rows.append(
            f'<tr><td class="path">{_e(source.name)}</td>'
            f'<td><span class="cat {state}">{_e(source.state)}</span></td>'
            f"<td>{_e(source.detail)}</td>"
            f'<td class="dim">{_e(source.since or "·")}</td></tr>'
        )
    for path, why in missed:
        rows.append(
            f'<tr><td class="path">{_e(_relative(path, case.root))}</td>'
            f'<td><span class="cat none">{_e(why)}</span></td>'
            f'<td class="dim">·</td><td class="dim">·</td></tr>'
        )
    table = _copyable_table(
        '<div class="wrap"><table class="tbl"><thead><tr><th data-sort="text">source</th>'
        '<th data-sort="text">state</th><th>coverage</th><th data-sort="text">earliest record</th>'
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )
    if case.begins:
        said = f"Observable trace history begins on {case.begins}."
        return f'{table}<p class="note">{_e(said)}</p>'
    return table


def _conflicts(case: Case, files: dict[str, CaseFile], detailed: set[str]) -> str:
    return "".join(_conflict(conflict, files, detailed) for conflict in case.conflicts)


def _conflict(conflict: Conflict, files: dict[str, CaseFile], detailed: set[str]) -> str:
    entry = files[conflict.path]
    detail = f' <a href="#detail-{entry.ref[1:]}">detail</a>' if conflict.path in detailed else ""
    fields = " · ".join(difference.field for difference in conflict.differences)
    said = f"{' and '.join(conflict.sources) or 'Two records'} disagree on {fields}"
    parts = [
        f'<div class="conf" id="{conflict.ref}">',
        f'<a class="cid" href="#{conflict.ref}">{conflict.ref}</a><div>',
        f'<div class="t">{_file_link(entry)} · {_e(said)}{detail}</div>',
    ]
    for difference in conflict.differences:
        pair = "".join(
            f'<div><div class="src">{_e(source or "value")}</div>'
            f'<div class="v">{_value(value)}</div></div>'
            for source, value in difference.values
        )
        parts.append(
            f'<div class="field">{_e(difference.field)}</div><div class="pair">{pair}</div>'
        )
        if difference.delta:
            first = difference.values[0][0] or "the first"
            second = difference.values[-1][0] or "the second"
            parts.append(
                f'<div class="delta">{_e(f"{second} is {difference.delta} than {first}")}</div>'
            )
    parts.append("</div></div>")
    return "".join(parts)


def _notes(case: Case) -> str:
    records = [entry.record for entry in case.files]
    parts = [
        "<h3>Categories</h3>",
        _fields(
            [
                ("origin", "how it arrived here"),
                ("metadata", "what the file says about itself"),
                ("activity", "what happened to it here"),
            ]
        ),
    ]
    used = {found.matched_by for record in records for found in record.evidence}
    bases = [(basis, meaning) for basis, meaning in _MATCH_NOTES.items() if basis in used]
    if bases:
        parts.extend(("<h3>Match basis</h3>", _fields(bases)))
    return "".join(parts)
