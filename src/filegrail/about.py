"""The screen a bare `filegrail` prints.

Typing a tool's name and having it silently start work on the current directory
is a surprise, and in a home directory an expensive one. So a run with no
arguments introduces the tool and says how to point it somewhere.

The shape below the wordmark is the one every modern command-line tool uses -
usage, examples, commands, options - because a reader who has used any of them
already knows how to read it in a second, and a landing screen's job is to get
someone to the right command rather than to be memorable.

What is deliberately *not* here any more: the table of evidence sources. It is a
good table and it belongs in `doctor`, where a reader is asking what this machine
can answer. On the front door it answered a question nobody had asked yet.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from . import LICENSE, REPOSITORY, TAGLINE, __version__
from .theme import MIDDOT, Theme, detect

#: Plain ASCII, so the wordmark survives a terminal that cannot print box
#: drawing and never needs a second variant.
#: The mark: two records converging on one file. It is the report's own
#: notation drawn small - `●` is a thing the tool found, `─│┌┐└┬` are the rails
#: that tie things together - so a reader meets the glyphs here and then meets
#: them again meaning the same thing four lines later.
WORDMARK = (
    " ▄▄▄▄▄▄▄▄ ",
    "▐████████▌",
    " ▀██████▀ ",
    "    ██    ",
    "  ▄▄██▄▄  ",
)

#: The same shape where no box drawing is available. Not a different mark: the
#: same one, in the characters the terminal has.
WORDMARK_ASCII = (
    " ________ ",
    "|________|",
    " \\______/ ",
    "    ||    ",
    "  __||__  ",
)


def wordmark(theme: Theme) -> tuple[str, ...]:
    return WORDMARK if theme.unicode else WORDMARK_ASCII


#: The three things the tool is for, and enough of what is under each one that
#: a reader recognises their own case instead of having to infer it. Not a
#: feature list: three lines, one per area, and the option table stays in
#: `filegrail help`.
AREAS = (
    ("metadata", ("EXIF", "XMP", "IPTC", "C2PA", "PDF", "Office", "media", "email")),
    ("provenance", ("browser history", "OS origin", "archives", "shell history")),
    ("analysis", ("conflicts", "timelines", "related files", "identifiers")),
)

USAGE = (
    ("filegrail <path> [options]", ""),
    ("filegrail <command> [options]", ""),
)

#: The two commands somebody types first.
START = (
    ("filegrail suspicious.pdf", "one file"),
    ("filegrail ~/Downloads", "a directory"),
)

#: What to reach for once the first scan has run, grouped by what is being
#: asked about rather than by which flag does it: a reader arrives knowing they
#: have a file, a directory or a kind of file, and not knowing what the tool
#: calls the thing they want.
INVESTIGATE = (
    (
        "FILE",
        (
            ("filegrail evidence.pdf", "metadata and origin"),
            ("filegrail explain evidence.pdf", "the evidence behind it"),
            ("filegrail compare a.jpg b.jpg", "two files side by side"),
            ("filegrail image photo.jpg --out image.html", "digital image examination"),
            ("filegrail evidence.pdf --hash", "with its SHA-256"),
        ),
    ),
    (
        "DIRECTORY",
        (
            ("filegrail ~/case --pivots", "investigative pivots"),
            ("filegrail ~/case --pivots --meta", "metadata pivots only"),
            ("filegrail ~/case --cluster", "shared authors, cameras"),
            ("filegrail ~/case --timeline", "dated records in order"),
            ("filegrail ~/case --unknown-only", "files of unknown origin"),
            ("filegrail ~/case --html -o case.html", "one self-contained page"),
            ("filegrail ~/case --home /mnt/user", "another user's traces"),
        ),
    ),
    (
        "FILE TYPE",
        (
            ("filegrail ~/case --type image", "images only"),
            ("filegrail ~/case --type document", "documents only"),
            ("filegrail ~/case --type mail", "mail only"),
            ("filegrail ~/case --ext jpg,pdf", "these extensions only"),
        ),
    ),
)

#: What to run before trusting a result, and before publishing one.
VERIFY = (
    ("filegrail doctor", "readable local sources"),
    ("filegrail clean image.jpg --check", "removable metadata"),
    ("filegrail clean image.jpg --out clean/", "a cleaned copy"),
)

#: Named rather than described. What each one does is a sentence away in
#: `filegrail help <command>`, and six sentences here would double the screen.
#: `help` is not in the list because it is the line underneath it.
COMMANDS = ("scan", "image", "explain", "compare", "doctor", "menu", "clean")

#: Below this the wordmark and the attributes cannot sit side by side.
_SIDE_BY_SIDE = 78

#: Below this there is no room for a description beside a command.
_MIN_DESCRIPTION = 14

#: The label column, wide enough for the longest section name and the two
#: spaces that keep it from touching the body.
_LABEL = 12


def invocation() -> str:
    """The command that will actually work in the caller's shell.

    Someone running from a checkout has no `filegrail` on their PATH. Printing
    it at them anyway is the difference between a screen that helps and one that
    is immediately proved wrong.
    """
    if Path(sys.argv[0]).stem == "filegrail" or shutil.which("filegrail"):
        return "filegrail"

    prefix = "PYTHONPATH=src " if "src" in os.environ.get("PYTHONPATH", "") else ""
    return f"{prefix}{Path(sys.executable).name} -m filegrail.cli"


def render(theme: Theme | None = None) -> str:
    theme = theme or detect()
    run = invocation()

    lines = ["", *_head(theme), ""]
    if run != "filegrail":
        lines.extend(_install(theme, run))

    # What the tool reads and what it can work out is the readme's job and the
    # `doctor` command's: a landing screen listing formats and evidence classes
    # is three blocks a reader has to get past before the first thing they can
    # actually run.
    #
    # The label column is the spine and stays fixed. The body column is sized
    # per section: forcing a seven-character command into the width of a
    # thirty-character example opens a gutter across half the screen and pushes
    # the descriptions into an ellipsis, which is the one thing this report does
    # not do anywhere else.
    lines.extend(_section(theme, "usage", USAGE))
    lines.extend(_listed(theme, "commands", COMMANDS))
    lines.append(_row(theme, "help", "filegrail help <command>"))
    lines.append("")
    lines.extend(_section(theme, "start", START))
    lines.extend(_grouped(theme, "investigate", INVESTIGATE))
    lines.extend(_section(theme, "verify", VERIFY))
    return "\n".join(lines)


def _areas(theme: Theme) -> list[str]:
    """The three lines that say what this is, before any command appears."""
    lines = []
    for label, parts in AREAS:
        said = f" {theme.glyph(MIDDOT)} ".join(parts)
        lines.extend(_wrapped(theme, label, said))
    lines.append("")
    return lines


def _listed(theme: Theme, label: str, names: tuple[str, ...]) -> list[str]:
    """One labelled line naming things, rather than a row for each of them."""
    return [*_wrapped(theme, label, f" {theme.glyph(MIDDOT)} ".join(names)), ""]


def _wrapped(theme: Theme, label: str, body: str) -> list[str]:
    """A labelled run of text over as many lines as the terminal needs.

    It wraps rather than clips because there is nowhere else to read it: the
    option table has `filegrail help`, but nothing repeats these three lines.
    """
    room = max(12, theme.width - _LABEL - 5)
    parts = theme.wrap(body, room)
    return [
        f"  {theme.label((label if index == 0 else '').ljust(_LABEL))} {theme.paint(part, 'body')}"
        for index, part in enumerate(parts)
    ]


# --- the body ----------------------------------------------------------------


def _row(
    theme: Theme,
    label: str,
    body: str,
    detail: str = "",
    column: int = 0,
    *,
    emphasise: bool = False,
) -> str:
    """One line of the two-column spine that runs the length of the screen.

    A body too wide for the window wraps under itself rather than being cut:
    a command a reader cannot copy whole is a command they cannot run.
    """
    prefix = f"  {theme.label(label.ljust(_LABEL))} "
    blank = " " * (_LABEL + 3)
    room = theme.width - _LABEL - 5

    if not detail or len(body) > column:
        parts = theme.wrap(body, room)
        head = f"{prefix}{theme.paint(parts[0], 'body')}"
        return "\n".join([head, *(f"{blank}{theme.paint(part, 'body')}" for part in parts[1:])])

    text = theme.bold(body.ljust(column)) if emphasise else theme.paint(body.ljust(column), "body")
    said = theme.wrap(detail, max(8, room - column - 2))[0]
    return f"{prefix}{text}  {theme.dim(said)}"


def _column(theme: Theme) -> int:
    """One width for every command on the screen.

    Sized once, from the longest command anywhere on it, so the descriptions
    form a single column down the page instead of a new one per block.
    """
    commands = [
        body for rows in (START, VERIFY, *(group for _, group in INVESTIGATE)) for body, _ in rows
    ]
    return min(max(len(body) for body in commands), theme.width - _LABEL - 20)


def _grouped(
    theme: Theme,
    label: str,
    groups: tuple[tuple[str, tuple[tuple[str, str], ...]], ...],
) -> list[str]:
    """A labelled block whose rows come in named groups.

    The group names sit in the body column rather than the label column: they
    name what is being asked about, which is a different question from what the
    block is for, and putting both in one column would say they were the same.
    """
    column = _column(theme)
    lines: list[str] = []
    for index, (name, group) in enumerate(groups):
        if index:
            lines.append("")
        lines.append(_row(theme, label if index == 0 else "", name, "", column))
        for body, said in group:
            lines.extend(_wrapped_row(theme, body, said, column))
    return [*lines, ""]


def _wrapped_row(theme: Theme, body: str, said: str, column: int) -> list[str]:
    """A command and its description, the description wrapping where it must.

    Never clipped. A description cut off at an ellipsis is the one thing this
    screen has in common with the reports, and neither of them does it.
    """
    room = theme.width - _LABEL - 5 - column - 2
    if room < _MIN_DESCRIPTION:
        return [_row(theme, "", body, "", column)]
    parts = theme.wrap(said, room)
    lines = [_row(theme, "", body, parts[0], column)]
    lines.extend(_row(theme, "", " " * column, part, column) for part in parts[1:])
    return lines


def _section(
    theme: Theme,
    label: str,
    rows: tuple[tuple[str, str], ...],
    *,
    emphasise: bool = False,
) -> list[str]:
    """A labelled block, with the label beside its first line rather than above.

    Above would cost a line and a blank one per section, and the label column is
    already carrying that job everywhere else on the screen.
    """
    # One column for every command on the screen, so the descriptions line up
    # down the page instead of stepping in and out block by block.
    column = _column(theme) if any(detail for _, detail in rows) else 0
    lines: list[str] = []
    for index, (body, detail) in enumerate(rows):
        head = label if index == 0 else ""
        if not detail:
            lines.append(_row(theme, head, body, "", column, emphasise=emphasise))
            continue
        wrapped = _wrapped_row(theme, body, detail, column)
        lines.append(_row(theme, head, body, detail, column, emphasise=emphasise))
        lines.extend(wrapped[1:])
    lines.append("")
    return lines


def _install(theme: Theme, run: str) -> list[str]:
    """What makes the examples below work, said once and never repeated."""
    return [
        _row(theme, "install", "pipx install filegrail", "to get the bare command", 22),
        _row(theme, "", f"alias filegrail='{run}'"),
        "",
    ]


def _rows() -> tuple[tuple[str, str], ...]:
    return (
        ("repo", REPOSITORY.split("//", 1)[-1]),
        ("license", LICENSE),
        ("version", __version__),
    )


def _head(theme: Theme) -> list[str]:
    """The mark, and beside it what the tool is, what it is for and where it lives.

    Three lines and three facts: a landing screen has about that much of a
    reader's attention, and the option tables are a `filegrail help` away.
    """
    mark = [theme.paint(line, "brand") for line in wordmark(theme)]
    beside = [
        f"{theme.bold('FILEGRAIL')} {__version__}",
        theme.label("LOCAL FILE INTELLIGENCE"),
        theme.dim(TAGLINE),
        theme.dim(REPOSITORY.split("//", 1)[-1]),
        "",
    ]
    gutter = max(len(line) for line in wordmark(theme)) + 3

    out = []
    for index in range(len(mark)):
        left = f" {mark[index]}"
        pad = max(1, gutter - _visible(left))
        out.append(f"{left}{' ' * pad}{beside[index]}".rstrip())
    return out


# --- blocks ------------------------------------------------------------------


def _block(theme: Theme, rule: str, heading: str, rows: tuple[tuple[str, str], ...]) -> list[str]:
    lines = [rule, "", f"  {theme.label(heading)}", ""]

    width = max(len(command) for command, _ in rows)
    room = theme.width - 4 - width - 2

    for command, description in rows:
        text = theme.paint(command.ljust(width) if room >= _MIN_DESCRIPTION else command, "body")
        if room < _MIN_DESCRIPTION:
            lines.append(f"    {text}")
            continue
        lines.append(f"    {text}  {theme.dim(theme.clip(description, room))}")
    lines.append("")
    return lines


def _note(theme: Theme, text: str) -> str:
    return f"    {theme.dim(theme.clip(text, theme.width - 4))}"


def _visible(text: str) -> int:
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
