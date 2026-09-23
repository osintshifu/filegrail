"""Render scan results.

The default rendering is styled for a terminal and degrades to the identical
layout in plain text when the output is piped or colour is unwanted, so the
same command reads well by eye and greps cleanly.

Two ideas carry the layout: a one-character left gutter groups the lines of an
entry without a box, and colour is spent only on saying which class of source
made a claim.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import __version__
from .clean import Cleaned
from .cluster import cluster as group_sources
from .correlate import (
    CONFLICTS,
    CorrelationResult,
    correlate,
)
from .explain import assessment
from .identify import PLACE, Identifier, extract
from .models import (
    ACTIVITY,
    BLOCK_LABELS,
    CATEGORY_VERBS,
    EVENT_VERBS,
    METADATA,
    ORIGIN,
    EvidenceRecord,
    FileRecord,
    category,
    label,
)
from .overview import Inventory, format_of, inventory
from .scan import Unsearched

if TYPE_CHECKING:  # both are imported where they are used, to keep startup light
    from .compare import Comparison
    from .doctor import Survey
from .theme import (
    ARROW,
    FLAG,
    LAST,
    MIDDOT,
    NOT_EQUAL,
    RAIL,
    RECORD,
    RULE,
    Theme,
    detect,
)

#: The version of each machine-readable document. It is a promise to whatever
#: consumes them, so a number moves only when a field in *that* document
#: changes meaning or leaves - adding one is not a break, and neither is a
#: release. Per document rather than one number for all of them: `clean` did
#: not change because the vocabulary around it did, and bumping it would tell
#: every consumer of `clean` to go and look at nothing.
SCHEMAS: dict[str, int] = {
    # `origins` became `evidence`, every record carries `category` and `match`,
    # `confidence` is gone, and `reconciliation` is `correlation`.
    "scan": 2,
    # The same file document, plus `conclusion` renamed to `assessment`.
    "explain": 2,
    # `acquisition` became `origin`.
    "compare": 2,
    "doctor": 1,
    "clean": 1,
}

#: Sources describing what a file says about itself, rather than where it came from.
SELF_REPORTED = frozenset(
    {"document-metadata", "device-metadata", "c2pa", "xmp", "xmp-history", "iptc"}
)


def shown(moment: str | None) -> str | None:
    """A timestamp as the report prints it: to the second, and no further.

    A source is free to record more. GTK writes microseconds into
    `recently-used.xbel` and a shortcut carries the filesystem's own precision,
    and `--json` keeps every digit of it. On screen those seven characters buy
    nothing, sit beside a dozen stamps that stop at the second, and read as an
    inconsistency rather than as precision.
    """
    if not moment:
        return None
    return f"{moment[:19]}Z" if moment.endswith("Z") else moment[:19]


def _read_from(found: EvidenceRecord, dot: str = "·") -> str:
    """`member docProps/core.xml · object 6 0 R`, or nothing."""
    return f" {dot} ".join(f"{key} {value}" for key, value in found.where.items())


def _timeline_key(moment: str | None) -> tuple[bool, float, str]:
    """Sort an ISO timestamp by its instant, with malformed values last."""
    if not moment:
        return True, 0.0, ""
    value = moment[:-1] + "+00:00" if moment.endswith("Z") else moment
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return False, parsed.timestamp(), moment
    except (OSError, OverflowError, ValueError):
        return True, 0.0, moment


def _timeline_value(moment: str | None) -> str | None:
    """Display aware timestamps in UTC so their printed order stays chronological."""
    if not moment:
        return None
    value = moment[:-1] + "+00:00" if moment.endswith("Z") else moment
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return shown(moment)
    if parsed.tzinfo is None:
        return shown(moment)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


#: Width of the label column inside an entry, so values line up across labels.
_LABEL = 10

#: Where an entry's text begins: two spaces, the gutter glyph, one space.
_INDENT = 4

#: The widest a field name may be before it stops sharing a line with its value.
#: Past this the column is eating the terminal; a longer name is not truncated,
#: it takes a line of its own.
_FIELD_NAME = 24


def _mark(theme: Theme, symbol: str, colour: str | None = None) -> str:
    """One gutter glyph, padded so every line starts its text in one column."""
    width = len(theme.glyph(ARROW))
    glyph = theme.glyph(symbol).ljust(width)
    return theme.paint(glyph, colour) if colour else theme.paint(glyph, "rail")


def _row(
    theme: Theme,
    prefix: str,
    body: str,
    right: str,
    *,
    paint: Callable[[str], str] | None = None,
    wrap: bool = True,
) -> str:
    """One line carrying a single right-aligned column.

    `prefix` and `right` arrive painted, so only their visible width matters.
    `body` arrives plain and is sized before painting - doing it afterwards
    would cut an escape sequence in half.

    `wrap=False` says the caller has already broken the text and this is one
    piece of it, so it must be left alone.
    """
    room = theme.width - _visible(prefix) - _visible(right) - 2
    if wrap:
        body = theme.clip(body, max(8, room))
    painted = paint(body) if paint else body
    gap = max(1, theme.width - _visible(prefix) - _visible(painted) - _visible(right))
    return f"{prefix}{painted}{' ' * gap}{right}"


# --- the shape every view is built from ----------------------------------------

#: A mark and the space after it. Every line in a section starts with one, so a
#: marked row and an unmarked row sit in the same column and a reader's eye
#: never has to shift left and right down a table.
_GUTTER = 2

#: How wide the labels in the opening block are: `target`, `left`, `right`.
_CHROME_LABEL = 10

#: Between two columns. Two spaces read as a gap; one reads as a wrapped word.
_GAP = 2

#: The narrowest a column carrying a value is ever made. Below this a value
#: wraps into unreadable slivers, so the table gives up a column instead.
_FLEX_FLOOR = 12


def _chrome(theme: Theme, mode: str, rows: list[tuple[str, str]]) -> list[str]:
    """The lines every view opens with.

    `filegrail 0.7.0 · scan`, a rule, and the facts about this run: what was
    looked at, and whose traces were read if they were not this machine's. One
    fact per line, wrapped rather than clipped - half a path is not a path.
    """
    said = f"{theme.bold('filegrail')} {__version__}"
    if mode:
        said += f" {theme.dim(theme.glyph(MIDDOT))} {theme.dim(mode)}"
    lines = [said, theme.rule(theme.width)]
    for name, value in rows:
        if not value:
            continue
        for index, part in enumerate(theme.wrap(value, theme.width - _CHROME_LABEL)):
            head = theme.dim(name.ljust(_CHROME_LABEL)) if index == 0 else " " * _CHROME_LABEL
            lines.append(f"{head}{part}")
    return lines


def _section(theme: Theme, name: str, *counts: str) -> list[str]:
    """`ORIGIN  ·  2 records · 2 files`, and the rule under it.

    The counts are of the section's own contents, said once here so nothing
    below repeats them. Every one of them must be of something a reader can go
    and count in the rows underneath, or it is a number to keep in agreement
    with another number.
    """
    middot = theme.glyph(MIDDOT)
    kept = [count for count in counts if count]
    said = theme.label(name.upper())
    # A count that does not fit is dropped rather than wrapped: the heading is
    # one line by construction, and the numbers are all counts of rows a reader
    # can see for themselves a moment later.
    while kept:
        joined = f"  {middot}  {f' {middot} '.join(kept)}"
        if len(name) + len(joined) <= theme.width:
            said += f"  {theme.dim(middot)}  {theme.dim(f' {middot} '.join(kept))}"
            break
        kept.pop()
    return ["", said, theme.rule(theme.width), ""]


def _laid_out(
    theme: Theme,
    head: tuple[str, ...],
    rows: Sequence[tuple[str, ...]],
    *,
    marks: list[str] | None = None,
    align: str = "",
    keep: int = 2,
    flex: int = 0,
    drop: tuple[int, ...] = (),
) -> tuple[list[str], list[list[str]]]:
    """A header in lower case, a rule the width of each column, then the rows.

    Columns give way when the window is too narrow for all of them, down to
    `keep`: from the right by default, or in the order `drop` names where the
    rightmost column is not the one that matters least. Whatever width is left
    then goes to the `flex` column - the one carrying the value a reader came
    for, which is the file in most tables and the summary where a table has
    one - and its cells wrap
    rather than being cut. Nothing here truncates: a URL with an ellipsis in it
    cannot be copied, opened or grepped for, which is most of what anybody
    wants a value in a report for.
    """
    if not rows:
        return [], []
    align = (align or "l" * len(head)).ljust(len(head), "l")
    widths = [
        max(len(head[index]), max(len(row[index]) for row in rows)) for index in range(len(head))
    ]

    # Which columns are still being printed, in the order they are printed.
    shown = list(range(len(head)))
    # `drop` names the columns that matter least, in order. Anything it does
    # not name still gives way rather than running off the edge - it just goes
    # last, from the right.
    order = [*drop, *(index for index in reversed(range(len(head))) if index not in drop)]

    def fixed() -> int:
        return sum(
            _GAP * bool(place) + widths[index] for place, index in enumerate(shown) if index != flex
        )

    # `keep` is what the table would like to keep, not a floor: a window too
    # narrow for that many columns gets fewer rather than a row that runs off
    # the edge, and the flex column is the last one standing.
    for wanted in (keep, 1):
        for index in order:
            if len(shown) <= wanted:
                break
            if _GUTTER + fixed() + _GAP + _FLEX_FLOOR <= theme.width:
                break
            if index != flex and index in shown:
                shown.remove(index)
        if _GUTTER + fixed() + _GAP + _FLEX_FLOOR <= theme.width:
            break
    room = theme.width - _GUTTER - fixed() - (_GAP if shown.index(flex) else 0)
    widths[flex] = max(_FLEX_FLOOR, min(widths[flex], room))

    def laid(cells: tuple[str, ...]) -> str:
        out = ""
        for place, index in enumerate(shown):
            value = cells[index]
            if place:
                out += " " * _GAP
            out += value.rjust(widths[index]) if align[index] == "r" else value.ljust(widths[index])
        return out.rstrip()

    # The rule under a header is the width of its column, not of its name: it
    # is what says how far the column reaches, which is exactly the question a
    # reader has when the values in it are short.
    bar = theme.glyph(RULE)
    # The header wraps like any other row: its own words can outgrow a column
    # that had to give way, and a heading running off the edge is the same bug
    # as a value doing it.
    named = list(head)
    named[flex] = theme.wrap(head[flex], widths[flex])[0]
    header = [
        theme.dim(f"{' ' * _GUTTER}{laid(tuple(named))}"),
        theme.dim(f"{' ' * _GUTTER}{laid(tuple(bar * width for width in widths))}"),
    ]
    # A value too long for its column continues under itself, aligned to the
    # column it belongs to rather than to the edge of the screen.
    indent = _GUTTER + sum(widths[index] + _GAP for index in shown[: shown.index(flex)])
    body = []
    for index, row in enumerate(rows):
        mark = (marks[index] if marks else " ") or " "
        parts = theme.wrap(row[flex], widths[flex])
        cells = list(row)
        cells[flex] = parts[0]
        group = [f"{mark} {laid(tuple(cells))}".rstrip()]
        group.extend(f"{' ' * indent}{part}" for part in parts[1:])
        body.append(group)
    return header, body


def _table(*args: Any, **kwargs: Any) -> list[str]:
    """`_laid_out`, flattened, for a table whose rows carry nothing under them."""
    header, body = _laid_out(*args, **kwargs)
    return [*header, *(line for group in body for line in group)]


def _details(theme: Theme, pairs: list[tuple[str, str]], colour: str = "body") -> list[str]:
    """The fields hanging off a record, the last of them on `└`.

    A label column of its own, so values line up under one another, and a value
    that outgrows the line continues under itself rather than being cut.
    """
    kept = [(name, value) for name, value in pairs if value]
    if not kept:
        return []
    width = max(len(name) for name, _ in kept)
    indent = _GUTTER + 2 + width + _GAP
    lines = []
    for index, (name, value) in enumerate(kept):
        rail = theme.glyph(LAST if index == len(kept) - 1 else RAIL)
        head = f"{' ' * _GUTTER}{theme.dim(rail)} {theme.dim(name.ljust(width))}{' ' * _GAP}"
        for part_index, part in enumerate(theme.wrap(value, theme.width - indent)):
            start = head if part_index == 0 else " " * indent
            lines.append(f"{start}{theme.paint(part, colour)}")
    return lines


#: What a file nothing was found for is marked with, and what a file that wants
#: a second look is marked with. Nothing else in a table carries a mark: an
#: ordinary row is the ordinary case and does not need announcing.
NOTHING, REVIEW = MIDDOT, FLAG

#: What an empty cell reads as. A dash rather than a blank, because a blank in
#: a column reads as a value somebody forgot to print.
EMPTY = "—"


def _blank(theme: Theme) -> str:
    return EMPTY if theme.unicode else "-"


def _named(record: EvidenceRecord) -> str:
    """What to call this record's source in a column.

    The most specific true name, in three steps. A metadata record names the
    block it was decoded from - `EXIF`, not `device metadata`, because the
    reader is about to go and read that block's own table. A browser download
    names the browser: four of them write the same kind of database, and
    `browser download` on every row leaves a reader to open the JSON to find
    out which. Everything else already has one specific name.
    """
    if record.block and record.block in BLOCK_LABELS:
        return BLOCK_LABELS[record.block]
    if record.source == "browser-download" and record.tool:
        return f"{record.tool.capitalize()} download"
    return label(record)


def _stamp(moment: str | None) -> str:
    """`2026-08-31 10:49:33` - the same instant, without the machine grammar."""
    return moment[:19].replace("T", " ").replace("Z", "") if moment else ""


def _format(path: str) -> str:
    """`JPEG`, not `JPG`: the format has one name and the file has many."""
    return format_of(path, Path(path).suffix.lower())


def named_formats(record: FileRecord) -> str | None:
    """`fmt/18 Acrobat PDF 1.4 - Portable Document Format 1.4`: what the bytes are."""
    if not record.formats:
        return None
    return " or ".join(
        " ".join(part for part in (found.puid, found.name, found.version) if part)
        for found in record.formats
    )


def _puids(theme: Theme, record: FileRecord) -> str:
    """`fmt/18`, or every PUID where the registry names more than one."""
    return " or ".join(found.puid for found in record.formats or ()) or _blank(theme)


def _counts(theme: Theme, rows: list[tuple[str, str]]) -> list[str]:
    """The summary block: one fact a line, the label in a column of its own."""
    width = max(len(name) for name, _ in rows)
    return [f"{' ' * _GUTTER}{theme.dim(name.ljust(width))}   {value}" for name, value in rows]


def _legend(theme: Theme, marks: list[str]) -> list[str]:
    """What the marks above mean. Printed only for the marks actually used."""
    said = []
    if theme.glyph(REVIEW) in marks:
        said.append(f"{theme.glyph(REVIEW)} needs review")
    if theme.glyph(NOTHING) in marks:
        said.append(f"{theme.glyph(NOTHING)} no evidence found")
    return ["", f"{' ' * _GUTTER}{theme.dim('   '.join(said))}"] if said else []


def _summarise(theme: Theme, record: EvidenceRecord) -> str:
    """One line of what a metadata record holds, in the order it is looked for.

    What made it, then what identifies that one machine, then who is named,
    then whether there is a fix on a map, then when it says it was made.
    Everything else is in the block's own table below; this is the line that
    says whether to go and read it.
    """
    said: list[str] = []
    if record.tool:
        said.append(record.tool)
    for name in ("BodySerialNumber", "SerialNumber", "InternalSerialNumber"):
        if serial := record.fields.get(name):
            said.append(f"serial {serial}")
            break
    for name in ("creator", "author", "Author", "By-line", "dc:creator"):
        if who := record.fields.get(name):
            said.append(who)
            break
    if record.geo:
        said.append(record.geo)
    if record.location:
        said.append(record.location)
    if moment := _stamp(shown(record.at)):
        said.append(moment)
    if said:
        return _facts_line(theme, said)
    # Nothing of the five. A record that holds a sentence and no fields says it
    # here rather than repeating the name of the column beside it.
    return record.note or label(record)


def _of(
    records: list[FileRecord], wanted: str, theme: Theme | None = None
) -> list[tuple[FileRecord, EvidenceRecord]]:
    """Every record of one category, with the file it belongs to.

    In the order the index put the files in, so that a reader working down the
    report meets them the same way twice.
    """
    ordered = _reading_order(theme, records) if theme else records
    return [
        (record, found)
        for record in ordered
        for found in record.evidence
        if category(found) == wanted
    ]


def _files_section(
    theme: Theme, records: list[FileRecord], root: Path, contents: Inventory
) -> list[str]:
    """One row a file: what it is, and what was found under each category."""
    blank = _blank(theme)
    rows: list[tuple[str, ...]] = []
    marks: list[str] = []
    for record in _reading_order(theme, records):
        rows.append(
            (
                _relative(record.path, root),
                _format(record.path),
                _size(record.size),
                _named(record.origin) if record.origin else blank,
                _named(record.metadata) if record.metadata else blank,
                _named(record.activity) if record.activity else blank,
            )
        )
        marks.append(_mark_for(theme, record))

    lines = _section(theme, "files", *_scale(contents))
    lines.extend(
        _table(theme, ("file", "type", "size", "origin", "metadata", "activity"), rows, marks=marks)
    )
    lines.extend(_legend(theme, marks))
    return lines


def _reading_order(theme: Theme, records: list[FileRecord]) -> list[FileRecord]:
    """What to open first, then the rest by size.

    A table sorted by path is a directory listing, which the shell already
    prints. The question this one answers is which file to read, and that has
    an order of its own: anything wanting a second look, then everything that
    was explained, then the files nothing was found for.
    """
    rank = {FLAG: 0, " ": 1, MIDDOT: 2}

    def order(record: FileRecord) -> tuple[int, int, str]:
        mark = _mark_for(theme, record)
        plain = {theme.glyph(FLAG): FLAG, theme.glyph(MIDDOT): MIDDOT}.get(mark, " ")
        return (rank[plain], -record.size, record.path)

    return sorted(records, key=order)


def _mark_for(theme: Theme, record: FileRecord) -> str:
    if not record.evidence:
        return theme.glyph(NOTHING)
    return theme.glyph(REVIEW) if correlate(record).contested else " "


def _scale(contents: Inventory) -> tuple[str, ...]:
    """`4 files · 4 types · 3.4 MB`, the size of what a section holds."""
    return (
        _plural(contents.files, "file"),
        _plural(len(contents.types), "type"),
        _size(contents.size),
    )


def _origin_section(
    theme: Theme, records: list[FileRecord], root: Path, *, named: bool
) -> list[str]:
    """Where each file came from, and what the record that says so holds."""
    found = _of(records, ORIGIN, theme)
    if not found:
        return []
    blank = _blank(theme)
    rows = []
    for record, one in found:
        cells: tuple[str, ...] = (_named(one), one.matched_by, _stamp(shown(one.at)) or blank)
        rows.append((_relative(record.path, root), *cells) if named else cells)
    head: tuple[str, ...] = ("source", "match", "time")
    if named:
        head = ("file", *head)

    lines = _section(
        theme,
        "origin",
        _plural(len(found), "record"),
        _plural(len({record.path for record, _ in found}), "file") if named else "",
    )
    lines.extend(
        _threaded(
            theme,
            head,
            rows,
            [
                [
                    ("url", one.url or ""),
                    ("referrer", one.referrer or ""),
                    ("command", one.command or ""),
                    ("note", one.note or ""),
                    ("match", one.match_note or ""),
                    ("where", _read_from(one)),
                ]
                for _, one in found
            ],
        )
    )
    return lines


def _metadata_section(
    theme: Theme, records: list[FileRecord], root: Path, *, named: bool
) -> list[str]:
    """What each file records about itself, one line each."""
    found = _of(records, METADATA, theme)
    if not found:
        return []
    rows = []
    for record, one in found:
        cells: tuple[str, ...] = (_named(one), _summarise(theme, one))
        rows.append((_relative(record.path, root), *cells) if named else cells)
    head: tuple[str, ...] = ("source", "summary")
    if named:
        head = ("file", *head)

    fields = sum(len(one.fields) for _, one in found)
    lines = _section(
        theme,
        "metadata",
        _plural(len(found), "source"),
        _plural(len({record.path for record, _ in found}), "file") if named else "",
        # Only where the fields themselves follow, which is the single-file
        # view: a count of something the reader cannot see under the heading is
        # a number to be taken on trust.
        "" if named else _plural(fields, "field"),
    )
    lines.extend(
        _table(
            theme,
            head,
            rows,
            marks=[theme.glyph(RECORD)] * len(rows),
            keep=len(head),
            flex=len(head) - 1,
        )
    )
    return lines


def _activity_section(
    theme: Theme, records: list[FileRecord], root: Path, *, named: bool
) -> list[str]:
    """What handled the file here, after it arrived."""
    found = _of(records, ACTIVITY, theme)
    if not found:
        return []
    blank = _blank(theme)
    rows = []
    for record, one in found:
        cells: tuple[str, ...] = (_named(one), one.matched_by, _stamp(shown(one.at)) or blank)
        rows.append((_relative(record.path, root), *cells) if named else cells)
    head: tuple[str, ...] = ("source", "match", "time")
    if named:
        head = ("file", *head)

    lines = _section(
        theme,
        "activity",
        _plural(len(found), "record"),
        _plural(len({record.path for record, _ in found}), "file") if named else "",
    )
    lines.extend(
        _threaded(
            theme,
            head,
            rows,
            [[("note", one.note or ""), ("tool", one.tool or "")] for _, one in found],
        )
    )
    return lines


def _threaded(
    theme: Theme,
    head: tuple[str, ...],
    rows: Sequence[tuple[str, ...]],
    details: Sequence[list[tuple[str, str]]],
) -> list[str]:
    """A table whose rows each carry their own fields underneath them.

    Laid out as one table first, so the columns line up down the section, and
    the fields threaded back in afterwards.
    """
    header, body = _laid_out(theme, head, rows, marks=[theme.glyph(RECORD)] * len(rows), flex=0)
    lines = list(header)
    for group, pairs in zip(body, details, strict=True):
        lines.extend(group)
        lines.extend(_details(theme, pairs))
    return lines


def _findings_section(theme: Theme, records: list[FileRecord], root: Path) -> list[str]:
    """What correlation made of the records: conflicts, corroboration, order."""
    found = [(record, finding) for record in records for finding in correlate(record).findings]
    if not found:
        return []
    blank = _blank(theme)
    rows, marks, details = [], [], []
    for record, finding in found:
        rows.append(
            (
                finding.kind.replace("_", " "),
                _relative(record.path, root),
                finding.field or blank,
                " · ".join(name for name in (finding.sources or ()) if name) or blank,
            )
        )
        marks.append(theme.glyph(REVIEW) if finding.kind in CONFLICTS else " ")
        pairs = []
        if finding.values and finding.sources:
            pairs = [
                (finding.sources[0] or "left", finding.values[0]),
                (finding.sources[1] or "right", finding.values[1]),
            ]
        elif not finding.values:
            pairs = [("", finding.text)]
        details.append(pairs)

    review = sum(1 for mark in marks if mark == theme.glyph(REVIEW))
    lines = _section(
        theme,
        "findings",
        _plural(len(found), "finding"),
        f"{review} needs review" if review else "",
    )
    header, body = _laid_out(theme, ("type", "file", "field", "sources"), rows, marks=marks, flex=1)
    lines.extend(header)
    for group, pairs in zip(body, details, strict=True):
        lines.extend(group)
        lines.extend(_details(theme, pairs))
    lines.extend(_legend(theme, marks))
    return lines


def _relationships_section(theme: Theme, records: list[FileRecord], root: Path) -> list[str]:
    """How the scanned files stand to one another.

    Not evidence about any one file: a link exists only because both files were
    scanned together, and it says something neither record says alone. Kept in
    its own section for that reason rather than hung off either file.
    """
    rows = [
        (
            link.kind,
            _relative(record.path, root),
            " · ".join(_relative(path, root) for path in link.others)
            or _plural(link.count, "file"),
        )
        for record in records
        for link in record.links
    ]
    if not rows:
        return []
    lines = _section(
        theme,
        "relationships",
        _plural(len(rows), "relation"),
        _plural(len({row[1] for row in rows}), "file"),
    )
    lines.extend(_table(theme, ("relationship", "file", "related"), rows, keep=3, flex=2))
    return lines


def _unresolved_section(theme: Theme, records: list[FileRecord], root: Path) -> list[str]:
    """The files no supported source said anything about.

    Not a list of failures. It says the sources this machine has were searched
    and held nothing that explains these files, which is a finding of its own
    and the one a reader is most likely to act on next.
    """
    if not records:
        return []
    rows = [
        (
            _relative(record.path, root),
            _format(record.path),
            _size(record.size),
            _stamp(shown(record.btime or record.mtime)),
        )
        for record in records
    ]
    lines = _section(theme, "unresolved", _plural(len(records), "file"))
    lines.extend(
        _table(
            theme,
            ("file", "type", "size", "last modified"),
            rows,
            marks=[theme.glyph(NOTHING)] * len(rows),
        )
    )
    return lines


def render_text(
    records: list[FileRecord],
    root: Path,
    *,
    verbose: bool = False,
    brief: bool = False,
    limit: int = 0,
    stats: dict[str, int] | None = None,
    theme: Theme | None = None,
    filtered: str = "",
    identify: bool = False,
    cluster: bool = False,
    content: bool = False,
    metadata: bool = True,
    home: Path | None = None,
    unsearched: Unsearched | None = None,
) -> str:
    """A scan, read from the whole directory down to the single record.

    What is here, what was found in it, then the records themselves grouped by
    the question each one answers, and last the files nothing explained. A
    section with nothing in it is not printed: an empty heading is a promise
    the scan did not keep.
    """
    theme = theme or detect()
    known = [record for record in records if record.evidence]
    unknown = [record for record in records if not record.evidence]
    found = extract(records, content=content, metadata=metadata)
    contents = inventory(records)
    named = len(records) > 1

    # A single file is its own target: the directory it happens to sit in is
    # not what was asked about.
    target = Path(records[0].path) if len(records) == 1 and not root.is_file() else root
    lines = _chrome(theme, "brief" if brief else "", [("target", _where(theme, target, home))])

    if named:
        lines.extend(_section(theme, "summary", *_scale(contents)))
        lines.extend(_counts(theme, _tally(theme, records, known, unknown, brief=brief)))
        lines.extend(_files_section(theme, records, root, contents))
    else:
        lines.extend(_one_file(theme, records[0], root) if records else [])

    if not brief:
        lines.extend(_origin_section(theme, records, root, named=named))
        lines.extend(_metadata_section(theme, records, root, named=named))
        lines.extend(_activity_section(theme, records, root, named=named))
        lines.extend(_findings_section(theme, records, root))
        lines.extend(_relationships_section(theme, records, root))
        if not named and records:
            lines.extend(_block_sections(theme, records[0]))
        if identify:
            lines.extend(_identifiers(theme, found, content=content))
        if cluster:
            lines.extend(_clusters(theme, records, root))
        if named:
            lines.extend(_unresolved_section(theme, unknown, root))

    if not brief:
        lines.extend(_gaps(theme, records, stats, filtered, root, unsearched))
    return "\n".join(lines)


def _where(theme: Theme, root: Path, home: Path | None) -> str:
    """The target, and whose traces were read when they were not this machine's."""
    said = [_display(root)]
    if home:
        said.extend([f"profile {_display(home)}", "external"])
    return _facts_line(theme, said)


def _tally(
    theme: Theme,
    records: list[FileRecord],
    known: list[FileRecord],
    unknown: list[FileRecord],
    *,
    brief: bool,
) -> list[tuple[str, str]]:
    """The counts under `SUMMARY`, each of something countable further down."""
    review = sum(1 for record in records if _mark_for(theme, record) == theme.glyph(REVIEW))
    if brief:
        return [
            ("with evidence", str(len(known))),
            ("unresolved", str(len(unknown))),
            ("needs review", str(review)),
        ]
    findings = sum(len(correlate(record).findings) for record in records)
    said = str(findings)
    if review:
        said = _facts_line(theme, [said, f"{review} needs review"])
    return [
        ("with evidence", str(len(known))),
        ("unresolved", str(len(unknown))),
        ("origin records", str(len(_of(records, ORIGIN)))),
        ("metadata sources", str(len(_of(records, METADATA)))),
        ("activity records", str(len(_of(records, ACTIVITY)))),
        ("findings", said),
    ]


def _one_file(theme: Theme, record: FileRecord, root: Path) -> list[str]:
    """The head of a single-file report: what the file is and where it lies."""
    lines = _section(
        theme,
        "file",
        _relative(record.path, root),
        _format(record.path),
        _size(record.size),
    )
    lines.extend(
        _counts(
            theme,
            [("path", record.path), ("mtime", _stamp(shown(record.btime or record.mtime)))]
            + ([("format", said)] if (said := named_formats(record)) else []),
        )
    )
    return lines


def _block_sections(theme: Theme, record: FileRecord) -> list[str]:
    """Every metadata block this file carries, field by field.

    One section per block rather than one long table: `EXIF` and `XMP` are
    different standards with different field names, and a reader looking for a
    tag knows which of the two it belongs to.
    """
    lines: list[str] = []
    for found in record.evidence:
        if category(found) != METADATA or not found.fields:
            continue
        rows = [(name, str(value)) for name, value in found.fields.items()]
        lines.extend(_section(theme, _named(found), _plural(len(rows), "field")))
        lines.extend(_table(theme, ("field", "value"), rows))
    return lines


def _listing(theme: Theme, values: list[str]) -> list[str]:
    """Bare lines hanging off a record, the last on `└`. No label column: these
    are all the same kind of thing, and a column of identical labels is noise."""
    lines = []
    for index, value in enumerate(values):
        rail = theme.glyph(LAST if index == len(values) - 1 else RAIL)
        for part_index, part in enumerate(theme.wrap(value, theme.width - _GUTTER - 2)):
            head = f"{' ' * _GUTTER}{theme.dim(rail)} " if part_index == 0 else " " * (_GUTTER + 2)
            lines.append(f"{head}{theme.dim(part)}")
    return lines


#: What each axis is called where a cluster names it. The word says what the
#: shared value identifies, because the three do not identify equally well and
#: one label for all of them would flatten that away: a body serial is one
#: machine, a model is a product line, an author is a name somebody typed.
_AXIS_LABELS = {"device": "camera serial", "model": "camera model", "author": "author"}


def _clusters(theme: Theme, records: list[FileRecord], root: Path) -> list[str]:
    """Values more than one scanned file shares, and which files share them.

    A group of one is left out: it says a file has an author, which the file
    already said. What this is for is the second file, and the shape of a
    directory that appears once the repeats are counted.
    """
    groups = [group for group in group_sources(records) if len(group.paths) > 1]
    if not groups:
        return []

    rows = [
        (
            _AXIS_LABELS.get(group.axis, group.axis),
            group.name,
            str(len(group.paths)),
            group.basis,
        )
        for group in groups
    ]
    covered = len({path for group in groups for path in group.paths})
    lines = _section(theme, "clusters", _plural(len(groups), "group"), _plural(covered, "file"))
    header, body = _laid_out(
        theme,
        ("attribute", "value", "files", "basis"),
        rows,
        marks=[theme.glyph(RECORD)] * len(rows),
        align="llrl",
        keep=3,
        flex=1,
    )
    lines.extend(header)
    for lines_of_row, group in zip(body, groups, strict=True):
        lines.extend(lines_of_row)
        lines.extend(_listing(theme, [_relative(path, root) for path in group.paths]))
    return lines


def _gaps(
    theme: Theme,
    records: list[FileRecord],
    stats: dict[str, int] | None,
    filtered: str,
    root: Path | None,
    unsearched: Unsearched | None,
) -> list[str]:
    """What the scan could not look at, and how far back what it did look at reaches.

    A directory that could not be read is a hole in the evidence rather than a
    file with nothing in it, and the two must never be reported as one thing. A
    browser history that was pruned is the same kind of hole: files older than
    it cannot be resolved from it however long anybody stares at the report.
    """
    rows: list[tuple[str, ...]] = []
    if unsearched:
        for path in unsearched.unreadable:
            rows.append((_relative(path, root) if root else path, "could not be read"))
        for path in unsearched.by_name:
            rows.append((_relative(path, root) if root else path, "skipped by name"))
    # The reach of the browser history is a gap only where something went
    # unresolved. On a scan that explained everything it is a fact about a
    # store nobody needed, which is not worth a section.
    unresolved = any(not record.evidence for record in records)
    if stats and stats.get("browser_profiles") and unresolved:
        reach = _plural(stats.get("browser_records", 0), "download record")
        across = _plural(stats["browser_profiles"], "profile")
        rows.append(("browser history", f"{reach} across {across}"))
    elif stats is not None and unresolved and not stats.get("browser_profiles"):
        rows.append(("browser history", "no profile could be read"))

    lines: list[str] = []
    if rows:
        lines.extend(_section(theme, "scan gaps", _plural(len(rows), "item")))
        lines.extend(
            _table(theme, ("what", "detail"), rows, marks=[theme.glyph(NOTHING)] * len(rows))
        )
    if filtered:
        said = "No file matched" if not records else "Limited to"
        lines.extend(["", f"{' ' * _GUTTER}{theme.dim(f'{said} {filtered}.')}"])
    return lines


#: Which evidence class each identifier type is drawn in. A coordinate is the
#: one that becomes a marker on a map, so it keeps the colour the report already
#: uses for a location.
_IDENTIFIER_COLOURS = {
    "geo": "activity",
    "email": "recorded",
    "domain": "inherited",
    "url": "inherited",
    "ipv4": "origin",
}


#: What each identifier type is called where it heads its own table. Plural,
#: because the heading is over a list.
_TYPE_SECTIONS = {
    "url": "urls",
    "domain": "domains",
    "hostname": "hostnames",
    "email": "emails",
    "message_id": "message ids",
    "ipv4": "ip addresses",
    "ipv6": "ipv6 addresses",
    "geo": "coordinates",
    "md5": "md5",
    "sha1": "sha1",
    "sha256": "sha256",
    "sha512": "sha512",
    "btc": "bitcoin addresses",
    "bch": "bitcoin cash addresses",
    "ltc": "litecoin addresses",
    "doge": "dogecoin addresses",
    "xmr": "monero addresses",
    "eth": "ethereum addresses",
    "vin": "vehicle ids",
    "iban": "bank accounts",
    "bic": "bank codes",
    "nip": "nip",
    "regon": "regon",
    "ssn": "social security numbers",
    "ein": "employer ids",
    "aba": "routing numbers",
    "crn": "company numbers",
    "cik": "sec filer ids",
    "vat": "vat ids",
    "asn": "autonomous systems",
    "onion": "onion addresses",
    "mac": "hardware addresses",
    "sid": "windows sids",
    "secret": "credentials",
    "person": "people",
    "org": "organisations",
    "handle": "accounts",
    "postcode": "postcodes",
    "tracker": "trackers",
    "cve": "cves",
    "cwe": "cwes",
    "ghsa": "github advisories",
    "registry": "registry keys",
    "path": "paths",
    "executable": "executables",
}


def _shown(entry: Identifier) -> str:
    """The value as the report prints it: a digest of a known address says so."""
    return f"{entry.normalized} (digest of {entry.of})" if entry.of else entry.normalized


def _places(entry: Identifier) -> list[tuple[str, str, str]]:
    """Each place a value was seen, split back into file, source and field."""
    found = []
    for place in entry.where:
        parts = place.split(PLACE)
        while len(parts) < 3:
            parts.append("")
        found.append((parts[0], parts[1], PLACE.join(parts[2:])))
    return found


def _values(theme: Theme, rows: Sequence[tuple[str, ...]]) -> list[str]:
    """One value and everywhere it was seen, as a table or as blocks.

    A table while the values are short enough to sit in a column beside the
    places. A URL is usually not: at seventy-two columns a table leaves it
    about half a line, and a URL broken across two lines cannot be copied,
    opened or grepped for - which is most of what anybody wants one for. Where
    that happens the value takes the line and the places hang underneath it,
    which is the same shape the rest of the report uses for a record.
    """
    head = ("value", "file", "source", "field / location")
    beside = (
        theme.width
        - _GUTTER
        - sum(
            _GAP + max(len(name), max((len(row[index]) for row in rows), default=0))
            for index, name in enumerate(head)
            if index
        )
    )
    if max(len(row[0]) for row in rows) <= beside:
        return _table(theme, head, rows, keep=3, flex=0)

    lines = []
    for value, file, source, field in rows:
        wrapped = theme.wrap(value, theme.width - _GUTTER)
        lines.append(f"{theme.glyph(RECORD)} {theme.paint(wrapped[0], 'metadata')}")
        for part in wrapped[1:]:
            lines.append(f"{' ' * _GUTTER}{theme.paint(part, 'metadata')}")
        lines.extend(
            _details(theme, [("file", file), ("source", source), ("where", field)], "body")
        )
    return lines


def _identifiers(theme: Theme, found: list[Identifier], *, content: bool = False) -> list[str]:
    """Every value the scan can be pivoted on, grouped by what kind it is.

    One row per place rather than per value: an address in a download record
    and the same address in the body of the document are two facts, and the
    pairing of them is the thing reading content exists to find. The last
    section names those pairings on their own, because a reader scanning for
    them should not have to compare two tables by eye.
    """
    if not found:
        return []

    occurrences = sum(entry.count for entry in found)
    crossed = [entry for entry in found if len({source for _, source, _ in _places(entry)}) > 1]
    # No trailing blank: the type sections open with one of their own, and two
    # in a row read as something missing between them.
    lines = _section(
        theme,
        "identifiers",
        _plural(len(found), "unique value"),
        _plural(occurrences, "occurrence"),
        _plural(len(crossed), "cross-source") if crossed else "",
    )[:-1]

    # Every type present, in the table's order and then any the table has not
    # heard of, under its own name: a value that reaches `--json` and not the
    # report is a lead nobody sees.
    present = {entry.type for entry in found}
    kinds = [kind for kind in _TYPE_SECTIONS if kind in present]
    kinds += sorted(present - set(_TYPE_SECTIONS))
    for kind in kinds:
        heading = _TYPE_SECTIONS.get(kind, kind)
        entries = [entry for entry in found if entry.type == kind]
        seen_at: list[tuple[str, ...]] = [
            (_shown(entry), file, source, field)
            for entry in entries
            for file, source, field in _places(entry)
        ]
        seen = sum(entry.count for entry in entries)
        lines.extend(
            _section(
                theme,
                heading,
                _plural(len(entries), "unique value"),
                _plural(seen, "occurrence"),
            )
        )
        lines.extend(_values(theme, seen_at))

    if crossed:
        rows: list[tuple[str, ...]] = []
        for entry in crossed:
            sources = sorted({source for _, source, _ in _places(entry)})
            files = sorted({file for file, _, _ in _places(entry)})
            rows.append((_shown(entry), " · ".join(sources), " · ".join(files)))
        lines.extend(_section(theme, "cross-source matches", _plural(len(rows), "value")))
        lines.extend(_table(theme, ("value", "sources", "files"), rows, keep=3, flex=0))
    return lines


def render_timeline(
    records: list[FileRecord],
    root: Path,
    *,
    theme: Theme | None = None,
    home: Path | None = None,
) -> str:
    """Every dated record in the scan, on one axis.

    A file nothing said anything about has no place here. It is a real finding
    and the scan reports it, but it is not an event: nothing happened at a time
    nobody recorded, and a row for it would be a date invented to fill a column.
    """
    theme = theme or detect()
    events = [
        (found.at, record, found) for record in records for found in record.evidence if found.at
    ]
    events.sort(key=lambda event: _timeline_key(event[0]))

    lines = _chrome(theme, "timeline", [("target", _where(theme, root, home))])
    if not events:
        lines.extend(_section(theme, "timeline", "no dated record"))
        return "\n".join(lines)

    rows: list[tuple[str, ...]] = [
        (
            _stamp(_timeline_value(at)),
            category(found),
            _relative(record.path, root),
            _named(found),
            EVENT_VERBS.get(found.source, CATEGORY_VERBS[category(found)]),
        )
        for at, record, found in events
    ]
    lines.extend(
        _section(
            theme,
            "timeline",
            _plural(len(rows), "event"),
            _plural(len({record.path for _, record, _ in events}), "file"),
        )
    )
    lines.extend(
        _table(
            theme,
            ("time", "category", "file", "source", "event"),
            rows,
            keep=3,
            flex=2,
            # What gives way first is the category: the colour already carries
            # it and the source name implies it, while the verb is the one
            # column that says what actually happened.
            drop=(1, 3, 4),
        )
    )
    return "\n".join(lines)


def _relative(path: str, root: Path) -> str:
    try:
        return str(Path(path).relative_to(root))
    except ValueError:
        return path


def _size(value: int) -> str:
    for unit, threshold in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if value >= threshold:
            return f"{value / threshold:.1f} {unit}"
    return f"{value} B"


def _display(root: Path) -> str:
    try:
        return "~/" + str(root.relative_to(Path.home()))
    except ValueError:
        return str(root)


def _visible(text: str) -> int:
    """Length of `text` as printed, ignoring escape sequences."""
    length = 0
    index = 0
    while index < len(text):
        if text[index] == "\x1b":
            terminator = text.find("m", index)
            index = len(text) if terminator < 0 else terminator + 1
            continue
        length += 1
        index += 1
    return length


def _moment(value: str | None) -> str:
    """A timestamp trimmed to the second.

    Filesystem times carry microseconds, which are noise in a column meant to be
    compared by eye and never precise enough to be evidence on their own.
    """
    if not value:
        return ""
    head = value[:19]
    return f"{head}Z" if value.endswith("Z") else head


def _plural(count: int, noun: str, plural: str | None = None) -> str:
    """`3 files`, and `2 directories` for the nouns an -s does not pluralise."""
    if count == 1:
        return f"{count} {noun}"
    return f"{count} {plural or noun + 's'}"


def _facts_line(theme: Theme, facts: list[str]) -> str:
    return theme.glyph(MIDDOT).join(f" {fact} " for fact in facts).strip()


#: The label column of the banner, wide enough for the longest of its rows.
_BANNER_LABEL = 8

#: Below this the version cannot sit beside the wordmark and takes its own line.
_VERSION_BESIDE = 52

#: Which line of the wordmark the version sits on. The third, where the mark is
#: at its widest and the eye is already.
_VERSION_LINE = 2


def _labelled(theme: Theme, name: str, value: str) -> list[str]:
    """One banner row: a fixed label column, and a value that wraps under it.

    The target wraps rather than clips for the reason every path in this report
    does - half a mount path still looks like a path, and a reader who cannot
    see what was scanned cannot check anything below it.
    """
    head = f"  {theme.label(name.ljust(_BANNER_LABEL))}  "
    room = max(8, theme.width - _BANNER_LABEL - 6)
    parts = theme.wrap(value, room)
    return [
        f"{head if index == 0 else ' ' * (_BANNER_LABEL + 4)}{theme.paint(part, 'body')}"
        for index, part in enumerate(parts)
    ]


def _wrapped(theme: Theme, text: str, indent: str, paint: Callable[[str], str]) -> list[str]:
    """One run of text over as many lines as the terminal needs for all of it."""
    return [f"{indent}{paint(part)}" for part in theme.wrap(text, theme.width - len(indent) - 2)]


#: What the table of sources calls its three columns. `category` rather than a
#: strength: what a source is about is a fact, and how much it is worth is the
#: reader's judgement rather than this tool's arithmetic.
_SOURCE_HEAD = ("source", "category", "files")

#: What the inventory grid calls its three columns.
_TYPE_HEAD = ("type", "files", "size")


#: What the findings table calls its two columns. The count used to carry the
#: word `files` on every row, which is the column name said eight times.
_SUMMARY_HEAD = ("what was read", "files")


#: How many directories are named before the rest become a count. A tree of
#: source repositories can hold hundreds of skipped names, and a report that
#: spends a page on them buries what it found.
_NAMED_DIRECTORIES = 8


def explain_empty_result(stats: dict[str, int] | None, theme: Theme | None = None) -> list[str]:
    """Say why nothing matched, so zero does not read as a malfunction."""
    theme = theme or detect()
    if stats is None:
        return []

    profiles = stats.get("browser_profiles", 0)
    downloads = stats.get("browser_records", 0)

    # Wrapped rather than broken by hand. These sentences carry two counts out
    # of the machine being scanned, and a profile with six figures of download
    # history pushed the first one past the edge of any window.
    if profiles == 0:
        said = "No browser profile was readable, so the strongest source was unavailable."
    else:
        said = (
            f"There was little to match against: {_plural(downloads, 'download record')} "
            f"across {_plural(profiles, 'browser profile')}. Browsers prune download "
            "history (Chromium keeps about 90 days by default) and clearing history or "
            "migrating a profile discards it, so files older than the surviving history "
            "cannot be resolved."
        )
    return ["", *_wrapped(theme, said, " " * _INDENT, theme.dim)]


def _file_json(record: FileRecord) -> dict[str, object]:
    """One file, with the correlation attached when it says anything."""
    data = record.to_dict()
    result = correlate(record)
    if result.notable:
        data["correlation"] = result.to_dict()
    return data


def render_explain(record: FileRecord, theme: Theme | None = None, home: Path | None = None) -> str:
    """Everything one file rests on, and what comparing it against itself found.

    The same sections a scan prints, for one file and without the index: what
    was found, where each record came from, how it was tied to this file, and
    last what correlation made of them. There is no prose reading of it here -
    an assessment written in sentences is this tool's opinion, and the command
    exists to show the material the opinion would rest on.
    """
    theme = theme or detect()
    result = correlate(record)
    root = Path(record.path).parent

    lines = _chrome(theme, "explain", [("target", _where(theme, Path(record.path), home))])
    origins = _of([record], ORIGIN)
    said = _of([record], METADATA)
    handled = _of([record], ACTIVITY)

    lines.extend(_section(theme, "summary", _plural(len(record.evidence), "evidence record")))
    lines.extend(
        _counts(
            theme,
            [
                ("origin records", str(len(origins))),
                ("metadata sources", str(len(said))),
                ("activity records", str(len(handled))),
                ("correlation", str(len(result.findings))),
            ],
        )
    )
    lines.extend(_origin_section(theme, [record], root, named=False))
    lines.extend(_metadata_section(theme, [record], root, named=False))
    lines.extend(_activity_section(theme, [record], root, named=False))
    lines.extend(_correlation_section(theme, result))
    lines.extend(_block_sections(theme, record))
    return "\n".join(lines)


def _correlation_section(theme: Theme, result: CorrelationResult) -> list[str]:
    """What comparing the records against each other produced.

    Every row is something two records jointly say, or fail to say. A file with
    one record of each kind has nothing to correlate and gets no section: an
    empty table under this heading would read as a check that came back clean,
    which is a different statement from one that was never possible.
    """
    if not result.findings:
        return []
    blank = _blank(theme)
    rows = []
    marks = []
    for finding in result.findings:
        value = ""
        if finding.values:
            value = (
                f"{finding.values[0]} {theme.glyph(NOT_EQUAL)} {finding.values[1]}"
                if finding.kind in CONFLICTS
                else finding.values[0]
            )
        rows.append(
            (
                finding.kind.replace("_", " "),
                finding.field or blank,
                " · ".join(name for name in (finding.sources or ()) if name) or blank,
                value or finding.text,
            )
        )
        marks.append(theme.glyph(REVIEW) if finding.kind in CONFLICTS else " ")

    review = sum(1 for mark in marks if mark != " ")
    lines = _section(
        theme,
        "correlation",
        _plural(len(rows), "result"),
        f"{review} needs review" if review else "",
    )
    lines.extend(
        _table(
            theme,
            ("result", "field", "sources", "value"),
            rows,
            marks=marks,
            keep=4,
            flex=3,
        )
    )
    lines.extend(_legend(theme, marks))
    return lines


#: Which shared field means which relation between two files. A body serial is
#: one physical machine; a document id is one document however many times it
#: was exported; a name in an author field is a name somebody typed.
_RELATIONS = {
    "BodySerialNumber": "same device",
    "SerialNumber": "same device",
    "InternalSerialNumber": "same device",
    "xmpMM:DocumentID": "same document",
    "xmpMM:OriginalDocumentID": "common ancestor",
    "creator": "same author",
    "Author": "same author",
    "dc:creator": "same author",
}


def render_compare(
    left: FileRecord,
    right: FileRecord,
    found: Comparison,
    theme: Theme | None = None,
) -> str:
    """Two files against each other: what they are, what they say, what follows.

    The fields come first as two columns with nothing decided about them, and
    what follows from them is a section of its own. A `result` column beside
    the values would say the same thing twice on one screen.
    """
    theme = theme or detect()
    names = (Path(left.path).name, Path(right.path).name)
    blank = _blank(theme)

    lines = _chrome(theme, "compare", [("left", left.path), ("right", right.path)])

    lines.extend(_section(theme, "files", _plural(2, "file")))
    lines.extend(
        _table(
            theme,
            ("field", *names),
            [
                ("type", _format(left.path), _format(right.path)),
                ("format", _puids(theme, left), _puids(theme, right)),
                ("size", _size(left.size), _size(right.size)),
            ],
            keep=3,
        )
    )

    compared = [(name, value, value) for name, value in found.shared]
    compared += [(name, one, other) for name, one, other in found.differing]
    if compared:
        lines.extend(_section(theme, "metadata", _plural(len(compared), "compared field")))
        lines.extend(_table(theme, ("field", *names), compared, keep=3, flex=1))

    lines.extend(_section(theme, "origin", _plural(len(found.origin), "record")))
    lines.extend(
        _table(
            theme,
            ("file", "source"),
            [(name, route) for name, route in found.origin] or [(names[0], blank)],
            keep=2,
            flex=1,
        )
    )

    results: list[tuple[str, ...]] = [("match", name, value) for name, value in found.shared]
    results += [
        ("difference", name, f"{one} {theme.glyph(NOT_EQUAL)} {other}")
        for name, one, other in found.differing
    ]
    if found.interval:
        results.append(("interval", "created", f"{found.interval} apart"))
    if results:
        lines.extend(_section(theme, "correlation", _plural(len(results), "result")))
        lines.extend(
            _table(
                theme,
                ("result", "field", "value"),
                results,
                marks=[
                    theme.glyph(REVIEW) if kind == "difference" else " " for kind, _, _ in results
                ],
                keep=3,
                flex=2,
            )
        )

    relations = [
        (_RELATIONS[name], f"{names[0]} {theme.glyph(MIDDOT)} {names[1]}", f"{name} {value}")
        for name, value in found.shared
        if name in _RELATIONS
    ]
    if relations:
        lines.extend(_section(theme, "relationships", _plural(len(relations), "relation")))
        lines.extend(_table(theme, ("relationship", "files", "basis"), relations, keep=3, flex=2))
    return "\n".join(lines)


def render_doctor(found: Survey, theme: Theme | None = None, home: Path | None = None) -> str:
    """What this machine can be asked, before anybody asks it.

    `available` here is the technical reach of a store, not a judgement about
    evidence: a source that is available and held nothing has answered, and one
    that is unavailable never got the question.
    """
    theme = theme or detect()
    said = _facts_line(theme, [_display(home), "external"]) if home else ""
    lines = _chrome(theme, "doctor", [("profile", said)])

    states: dict[str, int] = {}
    for check in found.checks:
        states[check.state] = states.get(check.state, 0) + 1

    lines.extend(_section(theme, "summary", _plural(len(found.checks), "source")))
    lines.extend(_counts(theme, [(state, str(states[state])) for state in sorted(states)]))

    lines.extend(
        _section(
            theme,
            "sources",
            _plural(len(found.checks), "source"),
            *(f"{count} {state}" for state, count in sorted(states.items())),
        )
    )
    lines.extend(
        _table(
            theme,
            ("source", "type", "status", "coverage / detail"),
            [(check.name, check.kind, check.state, check.detail) for check in found.checks],
            keep=3,
            flex=3,
            drop=(1, 3),
        )
    )

    from .doctor import PARSER, PARTIAL

    limits = [
        (check.name.replace(" oldest", ""), f"no record before {check.detail}")
        for check in found.horizon
    ]
    limits += [
        (check.name, check.detail)
        for check in found.checks
        if check.state == PARTIAL and check.kind == PARSER
    ]
    if limits:
        lines.extend(_section(theme, "limitations", _plural(len(limits), "item")))
        lines.extend(_table(theme, ("source", "limitation"), limits, keep=2, flex=1))
    return "\n".join(lines)


def render_clean(
    results: list[Cleaned],
    source: Path,
    destination: Path | None,
    *,
    theme: Theme | None = None,
    check: bool = False,
) -> str:
    """What each file would give up, and what would still be readable after.

    Under `--check` nothing was written, so nothing is said to have been: the
    same rows, in the conditional, and the exit code printed with them because
    that is what a pipeline acts on.
    """
    theme = theme or detect()
    blank = _blank(theme)
    cleaned = [item for item in results if item.removed]
    survived = [item for item in cleaned if item.remaining]

    lines = _chrome(
        theme,
        "clean --check" if check else "clean",
        [
            ("target", _display(source)),
            (
                "mode",
                "check only · nothing written"
                if check
                else f"copies to {_display(destination)}"
                if destination
                else "",
            ),
        ],
    )

    lines.extend(_section(theme, "summary", _plural(len(results), "file")))
    lines.extend(
        _counts(
            theme,
            [
                ("cleanable", str(len(cleaned))),
                ("unsupported", str(len(results) - len(cleaned))),
                ("would remain" if check else "still readable", str(len(survived))),
                ("exit", "1" if survived else "0"),
            ],
        )
    )

    rows, marks = [], []
    for item in results:
        stripped = [BLOCK_LABELS.get(block, block) for block in item.removed]
        if item.remaining:
            result = "review"
        elif item.removed:
            result = "would clean" if check else "cleaned"
        else:
            result = "unsupported"
        rows.append(
            (
                _relative(str(item.path), source),
                _format(str(item.path)),
                " · ".join(stripped) or blank,
                result,
            )
        )
        marks.append(theme.glyph(REVIEW) if item.remaining else " ")

    lines.extend(
        _section(
            theme,
            "results",
            _plural(len(results), "file"),
            f"{len(cleaned)} cleanable",
            f"{len(results) - len(cleaned)} unsupported",
        )
    )
    lines.extend(_table(theme, ("file", "format", "metadata", "result"), rows, marks=marks, keep=3))
    lines.extend(_legend(theme, marks))

    if survived:
        remaining = [
            (_relative(str(item.path), source), BLOCK_LABELS.get(block, block))
            for item in survived
            for block in item.remaining
        ]
        lines.extend(
            _section(
                theme,
                "remaining metadata",
                _plural(len(remaining), "block"),
                _plural(len(survived), "file"),
            )
        )
        lines.extend(
            _table(
                theme,
                ("file", "source"),
                remaining,
                marks=[theme.glyph(REVIEW)] * len(remaining),
                keep=2,
            )
        )
    return "\n".join(lines)


def document(shape: str, payload: dict[str, object]) -> str:
    """Render one machine-readable document, stamped with what it is.

    The stamp goes first so that reading the head of a piped document is enough
    to identify it, and it is two fields because they answer two questions. The
    schema says how to read what follows; the version says which build wrote
    it, which is what a bug report needs.

    The schema number is a contract rather than a build number, so it moves
    only when a field changes meaning or leaves - never merely because the
    release did.
    """
    stamped: dict[str, object] = {
        "schema": f"filegrail.{shape}/{SCHEMAS[shape]}",
        "filegrail_version": __version__,
    }
    stamped.update(payload)
    return json.dumps(stamped, ensure_ascii=False, indent=2)


def _whose(home: Path | None) -> dict[str, object]:
    """Name the profile the evidence came from, when it is not this machine's.

    Absent by default, because a key that is always there says nothing. Present
    means these claims describe another machine, which a consumer has to know
    before it files them against the one it is running on.
    """
    return {"home": str(home)} if home else {}


def render_json_doctor(found: Survey, home: Path | None = None) -> str:
    return document("doctor", {**_whose(home), **found.to_dict()})


def render_json_explain(record: FileRecord, home: Path | None = None) -> str:
    result = correlate(record)
    return document(
        "explain",
        {
            **_whose(home),
            "file": record.to_dict(),
            "correlation": result.to_dict(),
            "assessment": assessment(record, result, home),
        },
    )


def render_json_compare(left: FileRecord, right: FileRecord, home: Path | None = None) -> str:
    from .compare import compare

    return document("compare", {**_whose(home), **compare(left, right).to_dict()})


def render_json(
    records: list[FileRecord],
    root: Path,
    *,
    identify: bool = False,
    content: bool = False,
    metadata: bool = True,
    cluster: bool = False,
    home: Path | None = None,
    unsearched: Unsearched | None = None,
    run: dict[str, object] | None = None,
    coverage: dict[str, object] | None = None,
    found: list[Identifier] | None = None,
) -> str:
    """The scan as JSON. `found` is the scan's identifiers where the caller
    already extracted them, so they are not searched for twice."""
    payload: dict[str, object] = {
        "root": str(root),
        **_whose(home),
        "files": [_file_json(record) for record in records],
        "summary": {
            "total": len(records),
            "with_origin": sum(
                1
                for record in records
                if any(category(found) == ORIGIN for found in record.evidence)
            ),
        },
    }
    if run is not None:
        payload["run"] = run
    if coverage is not None:
        payload["coverage"] = coverage
    payload["unsearched"] = (unsearched or Unsearched()).to_dict()
    identifiers = []
    if identify:
        identifiers = (
            found if found is not None else extract(records, content=content, metadata=metadata)
        )
        payload["identifiers"] = [entry.to_dict() for entry in identifiers]
    if identify or any(
        record.sha256 or record.links or any(found.container for found in record.evidence)
        for record in records
    ):
        from .graph import build_graph

        payload["graph"] = build_graph(records, identifiers).to_dict()
    if cluster:
        payload["shared_attributes"] = [group.to_dict() for group in group_sources(records)]

    return document("scan", payload)


def render_json_clean(
    results: list[Cleaned], source: Path, destination: Path | None, *, check: bool = False
) -> str:
    found: dict[str, object] = {"root": str(source)}
    if check:
        # Said outright rather than left to be inferred from an absent
        # `written`: every count below is in the conditional, and a reader that
        # takes them for a record of what happened has been misled.
        found["checked"] = True
    if destination is not None:
        found["destination"] = str(destination)
    found["files"] = [item.to_dict() for item in results]
    found["summary"] = {
        "total": len(results),
        "cleaned": sum(1 for item in results if item.removed),
        "still_readable": sum(1 for item in results if item.remaining),
    }
    return document("clean", found)
