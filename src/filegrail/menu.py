"""An interactive front end for people who do not want to memorise flags.

It is deliberately not a TUI. There is no curses, no redraw, no cursor
addressing - just printed text and `input()` - which keeps the promise of zero
runtime dependencies, works over SSH and on Windows, and cannot leave a terminal
in a broken state if it dies half way.

Two rules shape it:

**It teaches the command line rather than replacing it.** Every action prints
the `filegrail` invocation it is about to run. A menu that leaves you dependent
on the menu is worse than no menu; this one should make itself unnecessary in a
week.

**The folder is chosen once.** Picking an action and then being asked where to
point it is the friction that makes menus tiresome, so the target is state, it
is always on screen, and its size is shown before anything scans it.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from .scan import iter_files
from .theme import Theme, detect

#: Past this, a scan is slow enough to be worth warning about first.
_LARGE = 5_000

#: Counting stops here; the exact number stops mattering long before it.
_COUNT_CAP = 50_000


@dataclass(frozen=True, slots=True)
class Action:
    key: str
    label: str
    flags: tuple[str, ...]


ACTIONS = (
    Action("1", "trace every file", ()),
    Action("2", "only the files nothing explains", ("--unknown-only",)),
    Action("3", "chronological view", ("--timeline",)),
    Action("4", "every claim, not just the strongest", ("--verbose",)),
    Action("5", "summarise, without every field", ("--brief",)),
    Action("7", "investigative pivots", ("--pivots",)),
    Action("9", "who and what made these files", ("--cluster",)),
    Action("i", "images only", ("--type", "image")),
    Action("d", "documents only", ("--type", "document")),
    Action("s", "what this machine can be asked", ("doctor",)),
    Action("e", "explain one file (point it at a file)", ("explain",)),
    Action("6", "add a SHA-256 for each file", ("--hash",)),
    Action("8", "redacted JSON, safe to share", ("--redact", "--json")),
)

_QUIT = {"q", "quit", "exit"}
_HELP = {"h", "help", "?"}
_FOLDER = {"f", "folder", "cd"}


def run(
    start: Path,
    *,
    execute: Callable[[list[str]], int],
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
    theme: Theme | None = None,
) -> int:
    """Loop until the reader asks to stop.

    `execute` runs one argv through the ordinary command line, so there is no
    second code path here that could drift away from what `filegrail` does.
    """
    theme = theme or detect()
    target = start.resolve()

    while True:
        try:
            _screen(write, theme, target)
            choice = read("  ▸ ").strip()
        except (EOFError, KeyboardInterrupt):
            write("")
            return 0

        lowered = choice.lower()

        if lowered in _QUIT:
            return 0

        if lowered in _HELP:
            _pause(write, read, theme, _help_text())
            continue

        if lowered in _FOLDER or (choice and not _match(lowered)):
            # A bare path typed at the prompt means "look here instead": it is
            # what someone reaches for before they find the `f` key.
            typed = choice if lowered not in _FOLDER else None
            chosen = _ask_folder(read, write, theme, typed)
            if chosen is not None:
                target = chosen
            continue

        action = _match(lowered) or ACTIONS[0]  # bare Enter runs the obvious one
        _invoke(write, read, theme, execute, action, target)


# --- screens -----------------------------------------------------------------


def _screen(write: Callable[[str], None], theme: Theme, target: Path) -> None:
    rule = f"  {theme.rule(theme.width - 2)}"
    write("")
    write(f"  {theme.bold('filegrail')}  {theme.dim('interactive')}")
    write(rule)
    write("")

    count = _count(target)
    size = theme.dim(_files(count))
    write(f"  {theme.label('folder')}   {theme.paint(_short(target), 'body')}   {size}")
    if count >= _LARGE:
        write(f"  {theme.dim('          that is a lot of files; a scan will take a while')}")
    write("")

    for action in ACTIONS:
        write(f"  {theme.bold(action.key)}  {action.label}")
    write("")
    write(
        f"  {theme.bold('f')}  change folder     "
        f"{theme.bold('h')}  help     "
        f"{theme.bold('q')}  quit"
    )
    write(rule)
    write("")


def _invoke(
    write: Callable[[str], None],
    read: Callable[[str], str],
    theme: Theme,
    execute: Callable[[list[str]], int],
    action: Action,
    target: Path,
) -> None:
    # A command word leads; a bare scan keeps the path first.
    argv = (
        [*action.flags, str(target)]
        if action.flags and not action.flags[0].startswith("-")
        else [str(target), *action.flags]
    )
    write("")
    write(f"  {theme.dim('running')}  {theme.paint(_command(target, action), 'recorded')}")
    write(f"  {theme.rule(theme.width - 2)}")

    try:
        execute(argv)
    except KeyboardInterrupt:
        write("")
        write(f"  {theme.dim('stopped')}")

    _pause(write, read, theme, None)


def _pause(
    write: Callable[[str], None],
    read: Callable[[str], str],
    theme: Theme,
    body: str | None,
) -> None:
    """Wait before redrawing, so the result is not swept away by the menu."""
    if body is not None:
        write("")
        write(body)
    write("")
    try:
        read(f"  {theme.dim('press Enter to go back')} ")
    except (EOFError, KeyboardInterrupt):
        raise SystemExit(0) from None


def _help_text() -> str:
    from .cli import build_parser

    return build_parser().format_help().rstrip()


# --- input -------------------------------------------------------------------


def _match(choice: str) -> Action | None:
    for action in ACTIONS:
        if choice == action.key:
            return action
    return None


def _ask_folder(
    read: Callable[[str], str],
    write: Callable[[str], None],
    theme: Theme,
    typed: str | None,
) -> Path | None:
    """Resolve a folder, saying plainly when it does not exist."""
    raw = typed
    if raw is None:
        try:
            raw = read(f"  {theme.label('folder')}  ").strip()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit(0) from None
    if not raw:
        return None

    candidate = Path(raw).expanduser()
    if not candidate.exists():
        write("")
        write(f"  {theme.paint('no such file or directory:', 'warning')} {raw}")
        write("")
        return None
    return candidate.resolve()


# --- shared ------------------------------------------------------------------


def _count(target: Path) -> int:
    """How many files a scan would visit, capped so counting stays cheap."""
    total = 0
    try:
        for _ in iter_files(target):
            total += 1
            if total >= _COUNT_CAP:
                break
    except OSError:
        return 0
    return total


def _files(count: int) -> str:
    if count >= _COUNT_CAP:
        return f"{_COUNT_CAP:,}+ files"
    return f"{count:,} file" + ("" if count == 1 else "s")


def _short(target: Path) -> str:
    try:
        return "~/" + str(target.relative_to(Path.home()))
    except ValueError:
        return str(target)


def _command(target: Path, action: Action) -> str:
    if action.flags and not action.flags[0].startswith("-"):
        return " ".join(["filegrail", *action.flags, _short(target)])
    return " ".join(["filegrail", _short(target), *action.flags])


def available(stream: TextIO | None = None) -> bool:
    """Whether a menu can be shown at all.

    Redirected output must never reach the loop: `filegrail menu > out.txt`
    would otherwise block on a prompt nobody can see.
    """
    stream = stream or sys.stdout
    try:
        return bool(stream.isatty()) and bool(sys.stdin.isatty())
    except (AttributeError, ValueError):
        return False
