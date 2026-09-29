"""The investigation report: a case read in the order an analyst asks about it.

What was analysed, what the records establish together, which files to open,
which values lead somewhere else and the detail of the files that need it -
and then what this machine could be searched for and what contradicts itself.

Every object starts on a line of its own with a mark and a number, so the left
edge alone says where one ends and the next begins, and no name is ever broken
inside a table column. The numbers are local to one report and are how its
sections point at each other: `#001` a file, `F01` a finding, `C01` a conflict,
`P01` a pivot.

Nothing here decides what is true. It lays out an `analysis.Case`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import __version__
from .analysis import NOTHING, REVIEW, Case, CaseFile, Finding, named, stamp
from .graph import build_graph
from .identify import PLACE, Identifier
from .models import ACTIVITY, CATEGORIES, METADATA, ORIGIN, EvidenceRecord, FileRecord, category
from .overview import inventory
from .report import (
    _TYPE_SECTIONS,
    _blank,
    _clusters,
    _display,
    _format,
    _identifiers,
    _relative,
    _size,
    named_formats,
)
from .scan import Unsearched
from .theme import BOTH_WAYS, DOUBLE_RULE, FLAG, FULL, HALF, MIDDOT, RING, RULE, Theme, detect

#: Where a property's value starts, measured from its label.
LABEL = 12

#: How many files a finding names before it says how many more there are.
SHOWN = 4

#: Findings that name files one by one, and how many of them; None is all.
_LISTED: dict[str, int | None] = {
    "generated": None,
    "conflicts": None,
    "same-second": None,
    "geo": SHOWN,
}

#: Findings whose items carry facts of their own. They are printed under each
#: file rather than once for the finding, because they are what that file in
#: particular was found to say.
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
) -> str:
    """The report, top to bottom. A section with nothing in it is not printed."""
    page = _Page(theme or detect())
    files = {entry.record.path: entry for entry in case.files}
    records = [entry.record for entry in case.files]

    moment = _masthead(page, case, home, now, brief=brief, verbose=verbose)
    _summary(page, case, records, identifiers)
    _findings(page, case, files)
    _files(page, case, verbose=verbose, limit=limit, compact=brief)
    if not brief:
        _relationships(page, case, files)
        if cluster:
            page.lines.extend(_clusters(page.theme, records, case.root))
        _pivots(page, case, files, verbose=verbose, identifiers=identifiers, content=content)
        _details(page, case, files, verbose=verbose)
        _coverage(page, case, unsearched)
        _conflicts(page, case, files)
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


def _mark(page: _Page, entry: CaseFile) -> str:
    if entry.state == REVIEW:
        return page.theme.glyph(FLAG)
    if entry.state == NOTHING:
        return page.theme.glyph(MIDDOT)
    return " "


def _name(entry: CaseFile) -> str:
    return Path(entry.record.path).name


def _folder(case: Case, record: FileRecord) -> str | None:
    """Where under the target a file lies, or None when it lies in the target itself."""
    relative = Path(_relative(record.path, case.root))
    return str(relative) if relative.parent != Path(".") else None


#: The mark in half blocks, five lines high: a cup on its stem. Painted in the
#: brand colour and printed only where the terminal can draw it.
_GRAIL = (
    " ▄▄▄▄▄▄▄▄ ",
    "▐████████▌",
    " ▀██████▀ ",
    "    ██    ",
    "  ▄▄██▄▄  ",
)


def _masthead(
    page: _Page, case: Case, home: Path | None, now: datetime | None, *, brief: bool, verbose: bool
) -> datetime:
    theme = page.theme
    dot = theme.glyph(MIDDOT)
    mode = f"  {dot}  brief" if brief else f"  {dot}  verbose" if verbose else ""
    words = [
        theme.bold(f"FILEGRAIL {__version__}"),
        theme.label("LOCAL FILE INTELLIGENCE"),
        f"Investigation report{mode}",
    ]
    if theme.unicode:
        page.add()
        for row, art in enumerate(_GRAIL):
            said = words[row] if row < len(words) else ""
            page.add(theme.paint(art, "brand") + "    " + said)
    else:
        for said in words:
            page.add(said)
    page.add()
    page.double()
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
    return moment


def _summary(
    page: _Page, case: Case, records: list[FileRecord], identifiers: list[Identifier] | None
) -> None:
    """The figures the HTML report opens with, in the same order, one line each."""
    theme = page.theme
    contents = inventory(records)
    flag, dot = theme.glyph(FLAG), theme.glyph(MIDDOT)
    holding = {name: [entry for entry in case.files if entry.found[name]] for name in CATEGORIES}
    review = [entry for entry in case.files if entry.state == REVIEW]
    quiet = [entry for entry in case.files if entry.state == NOTHING]
    fields = sum(len(conflict.differences) for conflict in case.conflicts)
    edges = len(build_graph(records, identifiers or []).relationships)

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
    if edges:
        rows.append(("Relationships", f"{edges:,}", "evidence-backed graph edges"))
    if review:
        said = f"{len(case.conflicts)} conflicts {dot} {fields} fields" if case.conflicts else ""
        rows.append((f"{flag} Need review", f"{len(review):,}", said))
    if quiet:
        rows.append(
            ("No evidence found", f"{len(quiet):,}", "see coverage before reading as absence")
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
        indent = page.head(mark, finding.ref, finding.title)
        page.add()
        facts = finding.facts
        if finding.kind in _PER_FILE:
            facts = [fact for fact in facts if fact[0] != "files"]
        labels = [label for label, _ in facts]
        labels += [label for item in finding.items for label, _ in item.facts]
        width = _width(labels)
        for label, value in facts:
            page.prop(_capital(label), value, indent, width)
        _items(page, case, finding, files, indent, width)
        if finding.kind == "no-trace":
            page.add()
            page.wrapped(
                "This does not mean the files were never downloaded or transferred.", indent
            )
            if case.begins:
                page.wrapped(f"Available trace history begins on {case.begins}.", indent)
        if finding.see:
            page.add()
            page.prop("See", finding.see, indent, width)
        page.gap()


def _items(
    page: _Page,
    case: Case,
    finding: Finding,
    files: dict[str, CaseFile],
    indent: int,
    width: int,
) -> None:
    if finding.kind in _PER_FILE:
        for item in finding.items:
            entry = files[item.path]
            opening = " " * indent + "File".ljust(width) + f"{entry.ref}  "
            page.wrapped(_name(entry), len(opening), opening)
            for label, value in item.facts:
                page.prop(_capital(label), value, indent, width)
        return
    if finding.kind not in _LISTED:
        return
    most = _LISTED[finding.kind]
    shown = finding.items if most is None else finding.items[:most]
    page.add()
    for item in shown:
        entry = files[item.path]
        opening = " " * indent + f"{entry.ref}  "
        page.wrapped(_name(entry), len(opening), opening)
        if (folder := _folder(case, entry.record)) and finding.kind != "conflicts":
            page.prop("path", folder, len(opening), width=6)
    if len(finding.items) > len(shown):
        page.add(" " * indent + f"+{len(finding.items) - len(shown)} more")


def _coverage(page: _Page, case: Case, unsearched: Unsearched | None) -> None:
    missed = [(path, "could not be read") for path in (unsearched.unreadable if unsearched else [])]
    missed += [(path, "skipped by name") for path in (unsearched.by_name if unsearched else [])]
    if not case.coverage and not missed:
        return
    page.section("EVIDENCE COVERAGE")
    theme = page.theme
    for source in case.coverage:
        if source.state in ("found", "readable"):
            mark = theme.paint(theme.glyph(FULL), "origin")
        elif source.state == "partial":
            mark = theme.paint(theme.glyph(HALF), "activity")
        else:
            mark = theme.dim(theme.glyph(RING))
        indent = page.head(mark, "", source.name)
        page.prop("Status", source.state, indent)
        if source.detail:
            page.prop("Detail", source.detail, indent)
        if source.since:
            page.prop("Since", source.since, indent)
        page.gap()
    for path, why in missed:
        indent = page.head(theme.dim(theme.glyph(RING)), "", _relative(path, case.root))
        page.prop("Status", why, indent)
        page.gap()
    if case.coverage:
        page.add("NOTE")
        page.add()
        if case.begins:
            page.wrapped(f"Observable trace history begins on {case.begins}.", 4)
        page.wrapped(
            "Absence of origin evidence is not proof that a file was never downloaded, "
            "copied or otherwise transferred to this machine.",
            4,
        )


def _conflicts(page: _Page, case: Case, files: dict[str, CaseFile]) -> None:
    if not case.conflicts:
        return
    page.section("CONFLICTS")
    both = f" {page.theme.glyph(BOTH_WAYS)} "
    for conflict in case.conflicts:
        entry = files[conflict.path]
        opening = f"{page.theme.glyph(FLAG)} {conflict.ref}  {entry.ref}  "
        page.wrapped(_name(entry), len(opening), opening)
        indent = 2 + len(conflict.ref) + 2
        page.add()
        page.prop("Sources", both.join(conflict.sources), indent)
        page.prop("Fields", str(len(conflict.differences)), indent)
        for difference in conflict.differences:
            page.add()
            page.wrapped(difference.field, indent)
            width = max([len(source) for source, _ in difference.values] + [len("Difference")]) + 3
            for source, value in difference.values:
                page.prop(source or "Value", value, indent + 2, width=width)
            if difference.delta:
                first = difference.values[0][0] or "the first"
                second = difference.values[-1][0] or "the second"
                said = f"{second} is {difference.delta} than {first}"
                page.prop("Difference", said, indent + 2, width=width)
        page.gap()


def _files(page: _Page, case: Case, *, verbose: bool, limit: int, compact: bool) -> None:
    """The index: one line per file, the same shape for every file.

    A file that wants reading in full - a conflict, an arrival, a local trace,
    a finding that needs a second look - is marked, and opens as a block under
    `-v`; the index itself keeps one rhythm so the eye can run down it.
    """
    if not case.files:
        return
    kinds = {finding.ref: finding.kind for finding in case.findings}
    page.section("FILES")
    listed = hidden = 0
    for entry in case.files:
        if entry.state == NOTHING:
            if limit and listed >= limit:
                hidden += 1
                continue
            listed += 1
        if verbose and not compact:
            _file_block(page, case, entry, kinds)
        else:
            _file_line(page, case, entry, kinds)
    if hidden:
        page.gap()
        page.wrapped(f"+{hidden} more files with no evidence found; --limit 0 lists them all.", 2)


def _references(entry: CaseFile, kinds: dict[str, str], dot: str) -> list[tuple[str, str]]:
    findings = [ref for ref in entry.findings if kinds[ref] != "no-trace"]
    said = []
    if findings:
        said.append(("findings", f" {dot} ".join(findings)))
    if entry.conflicts:
        said.append(("conflicts", f" {dot} ".join(entry.conflicts)))
    if entry.pivots:
        said.append(("pivots", f" {dot} ".join(entry.pivots)))
    return said


def _file_block(page: _Page, case: Case, entry: CaseFile, kinds: dict[str, str]) -> None:
    page.gap()
    indent = page.head(_mark(page, entry), entry.ref, _name(entry))
    if folder := _folder(case, entry.record):
        page.prop("path", folder, indent)
    page.prop("type", _format(entry.record.path), indent)
    if said := named_formats(entry.record):
        page.prop("format", said, indent)
    page.prop("size", _size(entry.record.size), indent)
    page.add()
    if entry.state == NOTHING:
        page.prop("evidence", "none found", indent)
    else:
        blank = _blank(page.theme)
        dot = page.theme.glyph(MIDDOT)
        for name in CATEGORIES:
            page.prop(name, f" {dot} ".join(entry.found[name]) or blank, indent)
    references = _references(entry, kinds, page.theme.glyph(MIDDOT))
    if references:
        page.add()
        for label, value in references:
            page.prop(label, value, indent)
    page.gap()


def _file_line(page: _Page, case: Case, entry: CaseFile, kinds: dict[str, str]) -> None:
    dot = page.theme.glyph(MIDDOT)
    found = [name for category_ in CATEGORIES for name in entry.found[category_]]
    facts = [_format(entry.record.path), _size(entry.record.size)]
    facts.append(f" {dot} ".join(found) if found else "no evidence found")
    facts += [value for label, value in _references(entry, kinds, dot) if label != "pivots"]
    if folder := _folder(case, entry.record):
        facts.append(f"in {Path(folder).parent}")
    # Two lines for every file, whatever fits: the name, then what is known
    # of it. One shape lets the eye run down the index.
    opening = f"{_mark(page, entry)} {entry.ref}  "
    said = f" {dot} ".join(facts)
    page.wrapped(_name(entry), len(opening), opening)
    for wrapped in page.theme.wrap(said, page.width - len(opening)):
        page.add(" " * len(opening) + page.theme.dim(wrapped))


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
            page.prop("Files", f"{entry.files:,}", indent)
            sources = dict.fromkeys(
                place.split(PLACE)[1] for place in entry.where if PLACE in place
            )
            page.prop("Sources", f" {page.theme.glyph(MIDDOT)} ".join(sources), indent)
            page.gap()

    if pivots.dense:
        page.gap()
        page.add("HIGH-DENSITY FILES")
        page.add()
        for dense in pivots.dense:
            held = files.get(dense.path)
            indent = page.head(" ", held.ref if held else "", Path(dense.path).name)
            page.prop("Pivot locations", f"{dense.places:,}", indent, width=18)
            page.add()
            for kind, count in dense.by_type:
                page.prop(_type_name(kind), f"{count:,}", indent, width=18)
            page.gap()

    if verbose and identifiers:
        page.lines.extend(_identifiers(page.theme, identifiers, content=content))
    else:
        page.gap()
        page.wrapped("Full pivot lists: add -v, or use --json.", 0)


def _details(page: _Page, case: Case, files: dict[str, CaseFile], *, verbose: bool) -> None:
    # What wants a second look, and every file whose arrival or handling here
    # was recorded: where a file came from is what the report is for.
    chosen = [
        entry
        for entry in case.files
        if entry.state == REVIEW
        or entry.found[ORIGIN]
        or entry.found[ACTIVITY]
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
        indent = page.head(_mark(page, entry), entry.ref, _name(entry))
        page.prop("Type", _format(record.path), indent)
        if said := named_formats(record):
            page.prop("Format", said, indent)
        page.prop("Size", _size(record.size), indent)
        if folder := _folder(case, record):
            page.prop("Path", folder, indent)

        for name in CATEGORIES:
            held = [found for found in record.evidence if category(found) == name]
            page.add()
            page.add(" " * 4 + name.upper())
            if not held:
                page.wrapped(_ABSENT[name], 8)
                continue
            for found in held:
                page.add(" " * 6 + named(found))
                facts = _facts(found, name, verbose=verbose)
                width = _width([label for label, _ in facts])
                for label, value in facts:
                    page.prop(label, value, 8, width)

        notes = []
        for ref in entry.conflicts:
            conflict = conflicts[ref]
            fields = f" {page.theme.glyph(MIDDOT)} ".join(
                difference.field for difference in conflict.differences
            )
            notes.append(
                (
                    page.theme.glyph(FLAG),
                    f"{' and '.join(conflict.sources)} disagree on {fields} ({ref})",
                )
            )
        for ref in entry.findings:
            finding = findings[ref]
            if finding.kind in ("conflicts", "no-trace"):
                continue
            others = [files[item.path] for item in finding.items if item.path != record.path]
            said = f"{finding.title} ({ref})"
            if others and len(others) <= SHOWN:
                said += ": " + f" {page.theme.glyph(MIDDOT)} ".join(
                    f"{other.ref} {_name(other)}" for other in others
                )
            elif others:
                said += f": with {len(others)} other files"
            notes.append((page.theme.glyph(MIDDOT), said))
        if notes:
            page.add()
            page.add("    ANALYTICAL NOTES")
            for mark, said in notes:
                page.wrapped(said, 8, f"      {mark} ")
        page.gap()


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
