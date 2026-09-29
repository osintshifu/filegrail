"""Terminal styling.

Hand-rolled rather than delegated to a library, because the tool takes no
runtime dependencies. Styling is applied only when the output is actually a
terminal that wants it: piping to a file, `NO_COLOR`, `TERM=dumb` and an
explicit `--no-color` all fall back to plain text with the same layout.

The palette has one rule: **colour encodes how the tool knows, never what it
found.** Every colour here names a class of evidence, so a reader learns five of
them once and can then triage a folder by eye.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from typing import TextIO

RESET = "\x1b[0m"

#: Colour depth, resolved once from the environment.
TRUECOLOR = 3
ANSI_256 = 2
ANSI_16 = 1
NONE = 0

#: Every colour as (hex, 256-colour code, 16-colour code). Chosen to stay legible
#: on both light and dark backgrounds, which rules out the saturated end.
_PALETTE = {
    # One colour per category, in the order a report prints them.
    "origin": ("5faf87", 71, 32),
    "metadata": ("5f87af", 68, 34),
    "activity": ("d7af5f", 179, 33),
    # Neutrals.
    "body": ("d0d0d0", 252, 37),
    "muted": ("8a8a8a", 245, 90),
    "faint": ("585858", 240, 90),
    "rail": ("3a3a3a", 237, 90),
    # Reserved for a claim the source itself flagged as incomplete.
    "warning": ("d7875f", 173, 33),
    # The mark and the accents of the page furniture: section numbers, the
    # masthead, a value the reader is pointed at.
    "brand": ("5fa89a", 72, 32),
    "accent": ("7fb5a8", 115, 36),
}

#: Which colour a source is painted in. Keyed by the category the record
#: belongs to, so the palette says the same thing the report is organised
#: around: how the file got here, what it says about itself, what happened to
#: it afterwards. It used to be keyed by a six-way strength scale, which meant
#: the colours quietly asserted an ordering the model no longer makes.
EVIDENCE = {
    "origin": "origin",
    "metadata": "metadata",
    "activity": "activity",
}

#: The categories in the order entries are printed in.
EVIDENCE_ORDER = ("origin", "metadata", "activity")


BAR_FULL = "▰"
BAR_EMPTY = "▱"
BULLET = "●"
ARROW = "←"
RAIL = "│"
BRANCH = "├"
LAST = "└"
FLAG = "!"
#: Coverage states: a store read in full, in part, and one not found.
FULL = "●"
HALF = "◐"
RING = "○"
RULE = "─"

#: Opens and closes a whole report, which a single rule under a heading must
#: not be mistaken for.
DOUBLE_RULE = "═"

#: Between two sources that state one field differently.
BOTH_WAYS = "↔"
MIDDOT = "·"
ELLIPSIS = "…"

#: Starts a record in a table: the row is a thing, the lines under it are
#: what that thing holds. It carries no analytic meaning.
RECORD = "\u203a"

#: Between two values that disagree. `vs` reads as a comparison somebody is
#: making; this reads as the two not being the same thing.
NOT_EQUAL = "≠"

_ASCII = {
    RECORD: ">",
    NOT_EQUAL: "!=",
    BAR_FULL: "#",
    BAR_EMPTY: ".",
    BULLET: "*",
    ARROW: "<-",
    RAIL: "|",
    BRANCH: "+",
    LAST: "\\",
    FLAG: "!",
    FULL: "*",
    HALF: "~",
    RING: "o",
    RULE: "-",
    DOUBLE_RULE: "=",
    BOTH_WAYS: "<->",
    # Not "|": the rail already claims that glyph, and a separator that looks
    # like a gutter destroys the one alignment cue the ASCII layout has.
    MIDDOT: "-",
    ELLIPSIS: "...",
}


@dataclass(frozen=True, slots=True)
class Theme:
    colour: bool
    unicode: bool
    width: int
    depth: int = ANSI_256

    # -- colour --

    def paint(self, text: str, name: str, *, bold: bool = False) -> str:
        if not self.colour or not text:
            return text
        entry = _PALETTE.get(name)
        if entry is None:
            return text

        hex_value, code_256, code_16 = entry
        if self.depth >= TRUECOLOR:
            red, green, blue = (int(hex_value[i : i + 2], 16) for i in (0, 2, 4))
            sequence = f"\x1b[38;2;{red};{green};{blue}m"
        elif self.depth >= ANSI_256:
            sequence = f"\x1b[38;5;{code_256}m"
        else:
            sequence = f"\x1b[{code_16}m"

        prefix = "\x1b[1m" if bold else ""
        return f"{prefix}{sequence}{text}{RESET}"

    def evidence(self, source: str) -> str:
        """The palette entry for a source, by the category it belongs to.

        Imported here rather than taken from a second table: one place decides
        what a source is about, and the colours follow it.
        """
        from .models import SOURCE_CATEGORIES

        return EVIDENCE.get(SOURCE_CATEGORIES.get(source, ""), "faint")

    def dim(self, text: str) -> str:
        return self.paint(text, "faint")

    def label(self, text: str) -> str:
        return self.paint(text, "muted")

    def rail_glyph(self, symbol: str = RAIL) -> str:
        return self.paint(self.glyph(symbol), "rail")

    def wrap(self, value: str, width: int) -> list[str]:
        """Break `value` into lines no wider than `width`, losing nothing.

        Truncation is not an option here: a provenance report exists to be read,
        and a value cut off at an ellipsis is one the reader now has to fetch
        another way. Words are kept whole where they fit; a single token longer
        than the line - a URL, a hash - is split, because the alternative is a
        line that overflows the terminal.
        """
        collapsed = " ".join(value.split())
        if width < 8:
            width = 8

        lines: list[str] = []
        current = ""
        for word in collapsed.split(" "):
            while len(word) > width:
                if current:
                    lines.append(current)
                    current = ""
                lines.append(word[:width])
                word = word[width:]
            if not current:
                current = word
            elif len(current) + 1 + len(word) <= width:
                current += f" {word}"
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [""]

    def bold(self, text: str) -> str:
        return f"\x1b[1m{text}{RESET}" if self.colour and text else text

    # -- glyphs --

    def glyph(self, symbol: str) -> str:
        return symbol if self.unicode else _ASCII.get(symbol, symbol)

    def clip(self, value: str, limit: int) -> str:
        """Collapse whitespace and truncate, with an ellipsis this theme can print."""
        collapsed = " ".join(value.split())
        if limit < 8 or len(collapsed) <= limit:
            return collapsed
        mark = self.glyph(ELLIPSIS)
        return collapsed[: limit - len(mark)] + mark

    def rule(self, width: int | None = None) -> str:
        return self.dim(self.glyph(RULE) * (width or self.width))

    # -- meters --

    def coverage(self, done: int, total: int, slots: int = 12) -> str:
        """The run's own progress. Body colour, because it is not a claim."""
        filled = round(done / total * slots) if total else 0
        if done and not filled:
            filled = 1
        return self.paint(self.glyph(BAR_FULL) * filled, "body") + self.dim(
            self.glyph(BAR_EMPTY) * (slots - filled)
        )


#: What a report is laid out to when it is not going to a terminal. Seventy-two
#: is what a file survives being quoted in mail, pasted into a ticket, read in a
#: side pane and diffed at - the same number, for the same reason, that git uses
#: for the body of a commit message.
ARCHIVE_WIDTH = 72


def detect(stream: TextIO | None = None, *, colour: bool | None = None) -> Theme:
    """Choose a theme from the environment, honouring the usual overrides."""
    stream = stream or sys.stdout

    if colour is None:
        colour = _wants_colour(stream)

    encoding = (getattr(stream, "encoding", None) or "").lower()
    unicode_ok = "utf" in encoding or os.environ.get("LANG", "").lower().find("utf") >= 0

    width = _width(stream)

    return Theme(
        colour=colour,
        unicode=unicode_ok,
        width=width,
        depth=_depth() if colour else NONE,
    )


def _width(stream: TextIO) -> int:
    """How wide to lay the report out.

    A terminal is asked how wide it is. Anything else is not a terminal and
    outlives one: a redirected report is quoted in mail, pasted into a ticket,
    read in a side pane and diffed, and the width of the machine that produced
    it is of no interest to any of those. Baking that width in makes every rule
    wrap the moment the file is opened somewhere narrower, and a wrapped rule
    is a stray line of dashes that reads as damage rather than as a divider.

    `COLUMNS` still wins in both cases, for somebody who wants a wide file on
    purpose - `shutil.get_terminal_size` reads it first, so asking about it
    here is only about knowing whether it was set at all.
    """
    try:
        terminal = bool(stream.isatty())
    except (AttributeError, ValueError):
        terminal = False
    if not terminal and not os.environ.get("COLUMNS"):
        return ARCHIVE_WIDTH
    return max(48, min(shutil.get_terminal_size(fallback=(88, 24)).columns, 110))


def _depth() -> int:
    """How many colours the terminal will honour."""
    if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return TRUECOLOR
    term = os.environ.get("TERM", "").lower()
    if "256" in term or "truecolor" in term:
        return ANSI_256
    if term in ("dumb", ""):
        return ANSI_16
    return ANSI_256


def _wants_colour(stream: TextIO) -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM", "").lower() in ("dumb", ""):
        return bool(os.environ.get("FORCE_COLOR"))
    if os.environ.get("FORCE_COLOR"):
        return True
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False
