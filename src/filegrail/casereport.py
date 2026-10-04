"""Terminal case report with findings as trees and files as a compact table.

Local references connect the sections: `#001` a file, `F01` a finding,
`C01` a conflict and `P01` a pivot. Nothing here decides what is true;
the renderer lays out an `analysis.Case`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import __version__
from .about import _head
from .analysis import NOTHING, REVIEW, Case, CaseFile, Conflict, Finding, named, stamp
from .identify import PLACE, Identifier
from .models import ACTIVITY, CATEGORIES, METADATA, ORIGIN, EvidenceRecord, FileRecord, category
from .overview import inventory
from .report import (
    _TYPE_SECTIONS,
    _clusters,
    _display,
    _format,
    _identifiers,
    _relative,
    _size,
    named_formats,
)
from .scan import Unsearched
from .theme import BRANCH, DOUBLE_RULE, FLAG, LAST, MIDDOT, RAIL, RULE, Theme, detect

#: Where a property's value starts, measured from its label.
LABEL = 12

#: Two spaces part a label from its value inside a tree line. Wrapping reads
#: every run of spaces as one, so the pair travels through it as two
#: characters that are not spaces and turns back into spaces afterwards.
_KEPT = ""

SHOWN = 4

_LISTED: dict[str, int | None] = {
    "generated": None,
    "conflicts": None,
    "same-second": None,
    "geo": SHOWN,
}

_PER_FILE = frozenset({"generated", "signature"})

#: What each match basis means, for the ones a report actually uses.
MATCHES = {
    "embedded": "decoded from the file's own bytes",
    "file-attribute": "read from what the filesystem keeps for this exact file",
    "recorded-path": "an external store names this exact path",
    "sidecar": "a separate file written next to it names it",
    "name+size": "name and size agree; two files can share both, but not easily",
    "filename": "the name is all that matched",
    "container-member": "read from a member, or inherited from the container",
    "sync-root": "the file lies under a folder a sync client manages",
}

_TIME_LABELS = {ORIGIN: "When", METADATA: "Created", ACTIVITY: "When"}
_AUTHOR_FIELDS = ("creator", "author", "Author", "By-line", "dc:creator", "LastAuthor")
_ABSENT = {
    ORIGIN: "No origin trace found in the evidence sources available for this scan.",
    METADATA: "Nothing the file records about itself was read.",
    ACTIVITY: "No local activity trace found.",
}

#: Words a type name carries in capitals wherever it is printed.
_CAPITALS = {
    "urls": "URLs", "ip": "IP", "ipv6": "IPv6", "md5": "MD5", "sha1": "SHA-1",
    "sha256": "SHA-256", "sha512": "SHA-512", "nip": "NIP", "regon": "REGON",
    "sec": "SEC", "vat": "VAT", "ids": "IDs", "cves": "CVEs", "cwes": "CWEs",
    "github": "GitHub", "windows": "Windows", "sids": "SIDs", "bitcoin": "Bitcoin",
    "litecoin": "Litecoin", "dogecoin": "Dogecoin", "monero": "Monero",
    "ethereum": "Ethereum", "onion": "Onion",
}  # fmt: skip


class _Page:
    """Lines laid out to one width, with the report's three ways of placing text."""

    def __init__(self, theme: Theme) -> None:
        self.theme = theme
        self.width = theme.width
        self.lines: list[str] = []
        self.count = 0

    def add(self, line: str = "") -> None:
        # A separator that arrived inside a value, from the analysis, takes the
        # theme's glyph too, so an ASCII terminal never meets a middle dot.
        if not self.theme.unicode and MIDDOT in line:
            line = line.replace(MIDDOT, self.theme.glyph(MIDDOT))
        self.lines.append(line.rstrip())

    def gap(self) -> None:
        if self.lines and self.lines[-1]:
            self.lines.append("")

    def wrapped(self, text: str, indent: int, first: str | None = None) -> None:
        """`text` from column `indent`, its first line opened by `first`."""
        opening = first if first is not None else " " * indent
        for number, line in enumerate(self.theme.wrap(text, self.width - indent)):
            self.add((opening if number == 0 else " " * indent) + line)

    def head(self, mark: str, ref: str, title: str) -> int:
        """The first line of an object. Returns the column its properties use."""
        opening = f"{mark} {ref}  " if ref else f"{mark} "
        self.wrapped(title, len(opening), opening)
        return len(opening)

    def prop(self, label: str, value: str, indent: int, width: int = LABEL) -> None:
        """A label and its value; the value takes a line of its own when the
        column left for it is too narrow to read."""
        column = indent + max(width, len(label) + 2)
        if self.width - column < 16:
            self.add(" " * indent + label)
            self.wrapped(value, indent + 2)
            return
        self.wrapped(value, column, " " * indent + label.ljust(column - indent))

    def figures(self, groups: list[list[tuple[str, str]]], indent: int = 0) -> None:
        """Short labels with their numbers lined up on the right, group by group."""
        rows = [row for group in groups for row in group]
        if not rows:
            return
        left = max(len(label) for label, _ in rows) + 4
        right = max(len(value) for _, value in rows)
        for number, group in enumerate(groups):
            if number:
                self.add()
            for label, value in group:
                if indent + left + right <= self.width:
                    self.add(" " * indent + label.ljust(left) + value.rjust(right))
                else:
                    self.prop(label.strip(), value, indent)

    def section(self, name: str) -> None:
        """`01  SUMMARY ────`: the number, the name, and a rule to the edge."""
        self.count += 1
        number = f"{self.count:02d}"
        lead = f"{number}  {name}  "
        rule = self.theme.glyph(RULE) * max(0, self.width - len(lead))
        self.gap()
        self.add()
        self.add(
            self.theme.paint(number, "accent")
            + "  "
            + self.theme.bold(name)
            + "  "
            + self.theme.dim(rule)
        )
        self.add()

    def kpis(self, rows: list[tuple[str, str, str]]) -> None:
        """A label, its figure on the right of a column, and a note beside it."""
        if not rows:
            return
        left = max(len(label) for label, _, _ in rows) + 2
        right = max(len(value) for _, value, _ in rows)
        room = self.width - left - right - 3
        for label, value, note in rows:
            line = label.ljust(left) + self.theme.bold(value.rjust(right))
            if not note:
                self.add(line)
            elif room >= 16:
                parts = self.theme.wrap(note, room)
                self.add(line + "   " + self.theme.dim(parts[0]))
                for part in parts[1:]:
                    self.add(" " * (left + right + 3) + self.theme.dim(part))
            else:
                self.add(line)
                self.wrapped(self.theme.dim(note), 2)

    def double(self) -> None:
        self.add(self.theme.dim(self.theme.glyph(DOUBLE_RULE) * self.width))

    def title(self, name: str) -> None:
        """`INVESTIGATION REPORT ────`: a heading without a number, ruled to the edge."""
        rule = self.theme.glyph(RULE) * max(0, self.width - len(name) - 2)
        self.add(self.theme.bold(name) + "  " + self.theme.dim(rule))

    def tree(self, parents: tuple[bool, ...], last: bool, value: str, *, indent: int = 2) -> None:
        rail = self.theme.glyph(RAIL)
        stem = " " * indent + "".join("    " if ended else f"{rail}   " for ended in parents)
        branch = self.theme.glyph(LAST if last else BRANCH) + self.theme.glyph(RULE) * 2 + " "
        opening = stem + branch
        # Wrapped URLs and identifiers must remain copyable without tree glyphs
        # inserted into their value when whitespace is joined back together.
        continuation = " " * len(opening)
        kept = value.replace("  ", _KEPT)
        for number, line in enumerate(self.theme.wrap(kept, self.width - len(opening))):
            self.add((opening if number == 0 else continuation) + line.replace(_KEPT[0], " "))


@dataclass(slots=True)
class _Node:
    text: str
    children: list[_Node] = field(default_factory=list)


def _tree(
    page: _Page,
    nodes: list[_Node],
    parents: tuple[bool, ...] = (),
    *,
    indent: int = 2,
) -> None:
    for index, node in enumerate(nodes):
        last = index == len(nodes) - 1
        page.tree(parents, last, node.text, indent=indent)
        if node.children:
            _tree(page, node.children, (*parents, last), indent=indent)


def render_case(
    case: Case,
    *,
    theme: Theme | None = None,
    verbose: bool = False,
    brief: bool = False,
    limit: int = 0,
    identifiers: list[Identifier] | None = None,
    content: bool = False,
    cluster: bool = False,
    home: Path | None = None,
    unsearched: Unsearched | None = None,
    filtered: str = "",
    now: datetime | None = None,
    saved: tuple[str, Path] | None = None,
) -> str:
    """The report, top to bottom. A section with nothing in it is not printed.

    `saved` names the report file this run wrote, as its kind and its path.
    """
    page = _Page(theme or detect())
    files = {entry.record.path: entry for entry in case.files}
    records = [entry.record for entry in case.files]

    moment = _masthead(page, case, home, now, saved, brief=brief, verbose=verbose)
    _summary(page, case, records)
    _findings(page, case, files)
    _files(page, case, limit=limit)
    if not brief:
        _relationships(page, case, files)
        if cluster:
            page.lines.extend(_clusters(page.theme, records, case.root))
        _pivots(page, case, files, verbose=verbose, identifiers=identifiers, content=content)
        _details(page, case, files, verbose=verbose)
        _coverage(page, case, unsearched)
        _notes(page, records)
    if filtered:
        page.gap()
        page.add(f"{'No file matched' if not records else 'Limited to'} {filtered}.")
    page.gap()
    page.double()
    dot = page.theme.glyph(MIDDOT)
    page.add(page.theme.bold("END OF REPORT"))
    for line in page.theme.wrap(
        f" {dot} ".join(
            [
                f"filegrail {__version__}",
                moment.strftime("%Y-%m-%d %H:%M %Z").strip(),
                "no network requests",
            ]
        ),
        page.width,
    ):
        page.add(page.theme.dim(line))
    page.double()
    return "\n".join(page.lines)


def _name(entry: CaseFile) -> str:
    return Path(entry.record.path).name


def _masthead(
    page: _Page,
    case: Case,
    home: Path | None,
    now: datetime | None,
    saved: tuple[str, Path] | None,
    *,
    brief: bool,
    verbose: bool,
) -> datetime:
    """The start screen's banner, then what was scanned and which report was written."""
    theme = page.theme
    dot = theme.glyph(MIDDOT)
    page.add()
    for line in _head(theme):
        page.add(line)
    page.add()
    mode = f" {dot} BRIEF" if brief else f" {dot} VERBOSE" if verbose else ""
    page.title(f"INVESTIGATION REPORT{mode}")
    page.add()
    records = [entry.record for entry in case.files]
    contents = inventory(records)
    moment = now or datetime.now().astimezone()
    page.prop("Target", _display(case.root), 0)
    if home:
        page.prop("Profile", f"{_display(home)} {dot} external", 0)
    page.prop(
        "Scanned",
        f" {dot} ".join(
            [
                moment.strftime("%Y-%m-%d %H:%M %Z").strip(),
                f"{len(records):,} files",
                f"{len(contents.types):,} types",
                _size(contents.size),
            ]
        ),
        0,
    )
    if saved is None:
        page.prop("Report", "terminal only", 0)
    elif LABEL + len(said := f"{saved[0]} {dot} {_display(saved[1])}") <= page.width:
        page.prop("Report", said, 0)
    else:
        # A path too long for the line goes under it whole, rather than
        # leaving the separator at the end of a line on its own.
        page.prop("Report", saved[0], 0)
        page.wrapped(_display(saved[1]), LABEL)
    return moment


def _summary(page: _Page, case: Case, records: list[FileRecord]) -> None:
    """The figures the HTML report opens with, in the same order, one line each."""
    theme = page.theme
    contents = inventory(records)
    flag, dot = theme.glyph(FLAG), theme.glyph(MIDDOT)
    holding = {name: [entry for entry in case.files if entry.found[name]] for name in CATEGORIES}
    review = [entry for entry in case.files if entry.state == REVIEW]
    quiet = [entry for entry in case.files if entry.state == NOTHING]
    fields = sum(len(conflict.differences) for conflict in case.conflicts)

    rows: list[tuple[str, str, str]] = [
        (
            "Files scanned",
            f"{len(records):,}",
            f"{len(contents.types):,} types {dot} {_size(contents.size)}",
        )
    ]
    for name in CATEGORIES:
        entries = holding[name]
        if entries:
            sources = sorted({found for entry in entries for found in entry.found[name]})
            rows.append((f"With {name}", f"{len(entries):,}", f" {dot} ".join(sources)))
    if case.pivots is not None and case.pivots.total:
        said = f"{case.pivots.across:,} in more than one file"
        if case.pivots.cross_corpus:
            said += f" {dot} {case.pivots.cross_corpus:,} in both corpora"
        rows.append(("Pivots", f"{case.pivots.total:,}", said))
    if review:
        said = f"{len(case.conflicts)} conflicts {dot} {fields} fields" if case.conflicts else ""
        rows.append((f"{flag} Need review", f"{len(review):,}", said))
    declared = {
        item.path
        for finding in case.findings
        if finding.kind == "generated"
        for item in finding.items
    }
    if declared:
        rows.append(("Declared AI source", f"{len(declared):,}", "signature not verified"))
    if quiet:
        rows.append(
            ("No evidence found", f"{len(quiet):,}", "absence is not proof; see report notes")
        )
    stores = [source for source in case.coverage if source.store]
    if stores:
        found = sum(1 for source in stores if source.state == "found")
        said = f"history begins {case.begins}" if case.begins else ""
        rows.append(("Trace stores found", f"{found}/{len(stores)}", said))

    page.section("SUMMARY")
    page.kpis(rows)
    states = {entry.state for entry in case.files}
    marks = [(flag, "needs review", REVIEW), (dot, "no evidence found", NOTHING)]
    legend = [f"{mark}  {meaning}" for mark, meaning, state in marks if state in states]
    if legend:
        page.add()
        page.add(theme.dim("    ".join(legend)))


def _findings(page: _Page, case: Case, files: dict[str, CaseFile]) -> None:
    if not case.findings:
        return
    page.section("KEY FINDINGS")
    for finding in case.findings:
        mark = page.theme.glyph(FLAG if finding.notable else MIDDOT)
        title = finding.title
        if finding.kind in {"generated", "signature", "conflicts", "geo"}:
            unit = "file" if len(finding.items) == 1 else "files"
            title += f" · {len(finding.items)} {unit}"
        page.head(mark, finding.ref, title)
        _tree(page, _finding_nodes(case, finding, files))
        page.gap()


def _conflict_nodes(conflict: Conflict) -> list[_Node]:
    nodes = []
    for difference in conflict.differences:
        values = [_Node(f"{source or 'Value'}  {value}") for source, value in difference.values]
        if difference.delta:
            first = difference.values[0][0] or "the first"
            second = difference.values[-1][0] or "the second"
            values.append(_Node(f"Difference  {second} is {difference.delta} than {first}"))
        nodes.append(_Node(difference.field, values))
    return nodes


def _finding_nodes(case: Case, finding: Finding, files: dict[str, CaseFile]) -> list[_Node]:
    if finding.kind == "conflicts":
        return [
            _Node(
                f"{files[conflict.path].ref}  {_name(files[conflict.path])}",
                _conflict_nodes(conflict),
            )
            for conflict in case.conflicts
        ]
    if finding.kind in {"generated", "signature"}:
        return [
            _Node(
                f"{files[item.path].ref}  {_name(files[item.path])}",
                [_Node(f"{_capital(label)}  {value}") for label, value in item.facts],
            )
            for item in finding.items
        ]
    facts = [
        _Node(f"{_capital(label)}  {value}")
        for label, value in finding.facts
        if label != "files" or finding.kind == "no-trace"
    ]
    if finding.kind == "geo":
        for item in finding.items:
            entry = files[item.path]
            coordinates = ", ".join(
                dict.fromkeys(found.geo for found in entry.record.evidence if found.geo)
            )
            facts.append(_Node(f"{entry.ref}  {_name(entry)}  {coordinates}"))
        return facts
    if finding.kind in {"author", "camera", "lens"} and len(finding.items) > 6:
        refs = " ".join(files[item.path].ref for item in finding.items)
        facts.append(_Node(f"Files  {refs}"))
    elif finding.kind != "no-trace":
        facts.append(
            _Node(
                f"Files ({len(finding.items)})",
                [
                    _Node(f"{files[item.path].ref}  {_name(files[item.path])}")
                    for item in finding.items
                ],
            )
        )
    if finding.see:
        facts.append(_Node(f"See  {finding.see}"))
    return facts


def _coverage(page: _Page, case: Case, unsearched: Unsearched | None) -> None:
    missed = [(path, "could not be read") for path in (unsearched.unreadable if unsearched else [])]
    missed += [(path, "skipped by name") for path in (unsearched.by_name if unsearched else [])]
    missed += [
        (path, "contents read in part") for path in (unsearched.partly_read if unsearched else [])
    ]
    if not case.coverage and not missed:
        return
    page.section("EVIDENCE COVERAGE")
    if case.coverage:
        source_width = min(32, max(16, page.width // 3))
        status_width = 13
        detail_width = page.width - source_width - status_width - 4
        header = f"{'SOURCE':<{source_width}}  {'STATUS':<{status_width}}  DETAIL"
        page.add(page.theme.label(header))
        page.add(page.theme.rule())
        for source in case.coverage:
            detail = source.detail
            if source.since:
                detail = f"{detail}; since {source.since}" if detail else f"since {source.since}"
            columns = [
                page.theme.wrap(source.name, source_width),
                page.theme.wrap(source.state, status_width),
                page.theme.wrap(detail or "", detail_width),
            ]
            for row in range(max(map(len, columns))):
                page.add(
                    f"{columns[0][row] if row < len(columns[0]) else '':<{source_width}}  "
                    f"{columns[1][row] if row < len(columns[1]) else '':<{status_width}}  "
                    f"{columns[2][row] if row < len(columns[2]) else ''}"
                )
    if missed:
        page.add()
        page.add("UNSEARCHED")
        _tree(
            page,
            [_Node(f"{_relative(path, case.root)}  {why}") for path, why in missed],
        )


def _files(page: _Page, case: Case, *, limit: int) -> None:
    """One row per file where it fits, with names and signals never truncated."""
    if not case.files:
        return
    page.section("FILES")
    findings = {finding.ref: finding for finding in case.findings}
    conflicts = {conflict.ref: conflict for conflict in case.conflicts}
    groups = (
        ("NEEDS REVIEW", [entry for entry in case.files if entry.state == REVIEW]),
        (
            "WITH EVIDENCE",
            [entry for entry in case.files if entry.state not in {REVIEW, NOTHING}],
        ),
        ("NO EVIDENCE FOUND", [entry for entry in case.files if entry.state == NOTHING]),
    )
    ref_width = max(len(entry.ref) for entry in case.files)
    type_width, size_width = 7, 9
    wide = page.width >= 88
    signal_width = 22 if wide else 0
    file_width = (
        page.width - ref_width - type_width - size_width - signal_width - (8 if wide else 6)
    )
    for title, entries in groups:
        if not entries:
            continue
        shown = entries[:limit] if title == "NO EVIDENCE FOUND" and limit else entries
        page.gap()
        note = (
            f" ({len(entries)}; showing {len(shown)})"
            if len(shown) < len(entries)
            else f" ({len(entries)})"
        )
        page.add(page.theme.bold(title + note))
        header = (
            f"{'ID':<{ref_width}}  {'FILE':<{file_width}}  "
            f"{'TYPE':<{type_width}}  {'SIZE':<{size_width}}"
        )
        if wide:
            header += "  SIGNALS"
        page.add(page.theme.label(header))
        page.add(page.theme.rule())
        for entry in shown:
            signal = _file_signal(entry, findings, conflicts)
            columns = [
                page.theme.wrap(_relative(entry.record.path, case.root), file_width),
                page.theme.wrap(_format(entry.record.path), type_width),
                page.theme.wrap(_size(entry.record.size), size_width),
            ]
            if wide:
                columns.append(page.theme.wrap(signal, signal_width))
            for row in range(max(map(len, columns))):
                line = (
                    f"{entry.ref if row == 0 else '':<{ref_width}}  "
                    f"{columns[0][row] if row < len(columns[0]) else '':<{file_width}}  "
                    f"{columns[1][row] if row < len(columns[1]) else '':<{type_width}}  "
                    f"{columns[2][row] if row < len(columns[2]) else '':<{size_width}}"
                )
                if wide and row < len(columns[3]):
                    line += f"  {columns[3][row]}"
                page.add(line)
            if signal and not wide:
                page.wrapped(signal, ref_width + 2)
    quiet = groups[-1][1]
    if limit and len(quiet) > limit:
        page.add(f"+{len(quiet) - limit} more; --limit 0 lists every file.")


def _file_signal(
    entry: CaseFile, findings: dict[str, Finding], conflicts: dict[str, Conflict]
) -> str:
    labels = []
    for ref in entry.conflicts:
        fields = ", ".join(difference.field for difference in conflicts[ref].differences)
        labels.append(f"conflict: {fields}")
    named_findings = {
        "generated": "declared AI source",
        "signature": "extension mismatch",
        "same-second": "same-second creation",
        "author": "shared author",
        "camera": "shared camera",
        "lens": "shared lens",
        "geo": "location",
    }
    for ref in entry.findings:
        kind = findings[ref].kind
        if kind in named_findings:
            labels.append(named_findings[kind])
    if not labels and entry.state != NOTHING:
        labels = [source for category_ in CATEGORIES for source in entry.found[category_]]
    return "; ".join(dict.fromkeys(labels))


def _relationships(page: _Page, case: Case, files: dict[str, CaseFile]) -> None:
    linked = [entry for entry in case.files if entry.record.links]
    if not linked:
        return
    page.section("XMP LINEAGE")
    for entry in linked:
        indent = page.head(" ", entry.ref, _name(entry))
        for link in entry.record.links:
            others = [files[path] for path in link.others if path in files]
            said = f" {page.theme.glyph(MIDDOT)} ".join(
                f"{other.ref} {_name(other)}" for other in others
            )
            page.prop(link.kind, said or f"{link.count} files", indent, width=16)
        page.gap()


def _pivots(
    page: _Page,
    case: Case,
    files: dict[str, CaseFile],
    *,
    verbose: bool,
    identifiers: list[Identifier] | None,
    content: bool,
) -> None:
    pivots = case.pivots
    if pivots is None or not pivots.total:
        return
    page.section("INVESTIGATIVE PIVOTS")
    page.add("BY TYPE")
    page.add()
    page.figures([[(_type_name(kind), f"{count:,}") for kind, count in pivots.by_type]], indent=2)

    if pivots.shared:
        page.gap()
        page.add("CROSS-FILE PIVOTS")
        page.add()
        for ref, entry in pivots.shared:
            indent = page.head(" ", ref, entry.type.upper())
            page.prop("Value", entry.value, indent)
            sources = dict.fromkeys(
                place.split(PLACE)[1] for place in entry.where if PLACE in place
            )
            page.prop("Sources", f" {page.theme.glyph(MIDDOT)} ".join(sources), indent)
            page.prop("Files", f"{entry.files:,}", indent)
            holders = {path for path in entry.holders if path in files}
            listed = [
                _Node(f"{held.ref}  {_relative(held.record.path, case.root)}")
                for held in case.files
                if held.record.path in holders
            ]
            _tree(page, listed, indent=indent)
            page.gap()

    if pivots.dense:
        page.gap()
        page.add("FILES WITH MOST PIVOT OCCURRENCES")
        page.add()
        nodes = []
        for dense in pivots.dense:
            held = files.get(dense.path)
            ref = held.ref if held else ""
            path = _relative(dense.path, case.root)
            children = [
                _Node(f"Pivot occurrences  {dense.places:,}"),
                *[_Node(f"{_type_name(kind)}  {count:,}") for kind, count in dense.by_type],
            ]
            nodes.append(_Node(f"{ref}  {path}", children))
        _tree(page, nodes)

    if verbose and identifiers:
        page.lines.extend(_identifiers(page.theme, identifiers, content=content))
    else:
        page.gap()
        page.wrapped("Full identifier occurrences: add -v, or use --json.", 0)


def _details(page: _Page, case: Case, files: dict[str, CaseFile], *, verbose: bool) -> None:
    notable = {finding.ref for finding in case.findings if finding.notable}
    chosen = [
        entry
        for entry in case.files
        if entry.state == REVIEW
        or entry.found[ORIGIN]
        or entry.found[ACTIVITY]
        or any(ref in notable for ref in entry.findings)
        or (verbose and entry.state != NOTHING)
    ]
    if not chosen:
        return
    findings = {finding.ref: finding for finding in case.findings}
    conflicts = {conflict.ref: conflict for conflict in case.conflicts}
    page.section("FILE DETAIL")
    for entry in chosen:
        record = entry.record
        page.gap()
        opening = f"{entry.ref}  "
        page.wrapped(_relative(record.path, case.root), len(opening), opening)
        header = f"{_format(record.path)}  {page.theme.glyph(MIDDOT)}  {_size(record.size)}"
        if said := named_formats(record):
            header += f"  {page.theme.glyph(MIDDOT)}  {said}"
        page.wrapped(header, 2)
        nodes = []
        if notes := _detail_findings(entry, findings, conflicts, files):
            nodes.append(_Node("Findings", notes))
        for name in CATEGORIES:
            held = [found for found in record.evidence if category(found) == name]
            if not held:
                children = [_Node(_ABSENT[name])]
            else:
                children = [
                    _Node(
                        named(found),
                        [
                            _Node(f"{label}  {value}")
                            for label, value in _facts(found, name, verbose=verbose)
                        ],
                    )
                    for found in held
                ]
            nodes.append(_Node(name.upper(), children))
        _tree(page, nodes)


def _detail_findings(
    entry: CaseFile,
    findings: dict[str, Finding],
    conflicts: dict[str, Conflict],
    files: dict[str, CaseFile],
) -> list[_Node]:
    nodes = [_Node(f"Conflict ({ref})", _conflict_nodes(conflicts[ref])) for ref in entry.conflicts]
    for ref in entry.findings:
        finding = findings[ref]
        if finding.kind in {"conflicts", "no-trace"}:
            continue
        facts = [
            _Node(f"{_capital(label)}  {value}")
            for label, value in finding.facts
            if label != "files"
        ]
        for item in finding.items:
            if item.path == entry.record.path:
                facts.extend(_Node(f"{_capital(label)}  {value}") for label, value in item.facts)
                break
        others = [files[item.path] for item in finding.items if item.path != entry.record.path]
        if others:
            if len(others) <= SHOWN:
                facts.extend(_Node(f"Also  {other.ref}  {_name(other)}") for other in others)
            else:
                facts.append(_Node("Also  " + " ".join(other.ref for other in others)))
        nodes.append(_Node(f"{finding.title} ({ref})", facts))
    return nodes


def _facts(found: EvidenceRecord, name: str, *, verbose: bool) -> list[tuple[str, str]]:
    said: list[tuple[str, str]] = []
    if found.tool:
        said.append(("Software" if name == METADATA else "Tool", found.tool))
    for field_name in _AUTHOR_FIELDS:
        if who := found.fields.get(field_name):
            said.append(("Author", str(who)))
            break
    if found.url:
        said.append(("URL", found.url))
    if found.referrer:
        said.append(("Referrer", found.referrer))
    if found.command:
        said.append(("Command", found.command))
    if found.at:
        timed = "When" if found.block == "xmp-history" else _TIME_LABELS[name]
        said.append((timed, stamp(found.at)))
    if found.geo:
        said.append(("Location", found.geo))
    if found.location:
        said.append(("Place", found.location))
    author = next((value for label, value in said if label == "Author"), None)
    if found.note and found.note != f"author {author}":
        said.append(("Note", found.note))
    said.append(("Match", found.matched_by))
    if verbose:
        said += [(key, str(value)) for key, value in found.fields.items() if value]
    return said


def _notes(page: _Page, records: list[FileRecord]) -> None:
    dot = page.theme.glyph(MIDDOT)
    page.section("REPORT NOTES")
    page.add("Evidence categories")
    page.prop("Origin", "How a file reached the examined environment.", 2)
    page.prop("Metadata", "What the file records about itself.", 2)
    page.prop("Activity", "What happened to the file locally.", 2)

    used = {found.matched_by for record in records for found in record.evidence}
    if used:
        page.add()
        page.add("Match basis")
        for basis, meaning in MATCHES.items():
            if basis in used:
                page.prop(basis, meaning, 2, width=18)

    page.add()
    page.add("Interpretation")
    for said in (
        "No origin evidence is not proof that a file was never downloaded or transferred.",
        "Recorded authors, organizations, devices and identifiers are values the files "
        "carry, not verified identity.",
    ):
        page.wrapped(said, 4, f"  {dot} ")


def _width(labels: list[str]) -> int:
    """One label column for a whole object, so its values line up."""
    return min(24, max([LABEL, *(len(label) + 2 for label in labels)]))


def _capital(label: str) -> str:
    return label[:1].upper() + label[1:]


def _type_name(kind: str) -> str:
    words = _TYPE_SECTIONS.get(kind, kind).split()
    shown = [_CAPITALS.get(word, word) for word in words]
    return _capital(" ".join(shown))
