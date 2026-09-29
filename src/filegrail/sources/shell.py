"""Shell history as a weak, corroborating origin source.

A command that names a file is evidence that the command touched it, not proof
that the command produced it. A fetch command is read as an origin record and
everything else as activity, and neither displaces a browser or an
operating-system record.

Timestamps are only available when the shell was configured to store them
(HISTTIMEFORMAT for bash, EXTENDED_HISTORY for zsh). Plain bash history has no
times at all, so ordering is all that can be recovered.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from ..models import FETCH_TOOLS as _FETCH_TOOLS
from ..models import EvidenceRecord
from ..util import iso

HISTORY_FILES = [
    ".bash_history",
    ".zsh_history",
    ".local/share/fish/fish_history",
]

_BASH_TIMESTAMP = re.compile(r"^#(\d{9,11})$")
_ZSH_ENTRY = re.compile(r"^: (\d{9,11}):\d+;(.*)$", re.DOTALL)

# Shorter names produce too many unrelated substring matches to be useful.
_MIN_SUBSTRING_NAME = 6


def _parse_history(path: Path, *, raise_errors: bool = False) -> list[tuple[float | None, str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        if raise_errors:
            raise
        return []

    entries: list[tuple[float | None, str]] = []

    if path.name == "fish_history":
        timestamp: float | None = None
        for line in text.splitlines():
            if line.startswith("- cmd: "):
                entries.append((None, line[len("- cmd: ") :].strip()))
            elif line.strip().startswith("when: ") and entries:
                try:
                    timestamp = float(line.split("when:", 1)[1].strip())
                    entries[-1] = (timestamp, entries[-1][1])
                except ValueError:
                    pass
        return entries

    pending: float | None = None
    for line in text.splitlines():
        zsh = _ZSH_ENTRY.match(line)
        if zsh:
            entries.append((float(zsh.group(1)), zsh.group(2).strip()))
            continue
        stamp = _BASH_TIMESTAMP.match(line.strip())
        if stamp:
            pending = float(stamp.group(1))
            continue
        if line.strip():
            entries.append((pending, line.strip()))
            pending = None
    return entries


def _match_names(names: set[str], words: list[str], command: str) -> set[str]:
    """Match file names against a command, conservatively.

    Exact argument matches are always accepted. Substring matches are only
    considered for names distinctive enough not to fire on unrelated commands,
    which rules out short names and names without an extension: "tmp" would
    otherwise match every command that mentions /tmp.
    """
    matched = {name for name in names if name in words}
    matched |= {Path(word).name for word in words if Path(word).name in names}

    for name in names - matched:
        if len(name) >= _MIN_SUBSTRING_NAME and "." in name and name in command:
            matched.add(name)
    return matched


def collect_shell_history(
    names: set[str], home: Path | None = None, stats: dict[str, int] | None = None
) -> dict[str, list[EvidenceRecord]]:
    """Map file name -> commands that mention it.

    Matching is by file name rather than full path because history rarely
    contains absolute paths. That makes it ambiguous, which is reflected in the
    presentation rank this source is given.
    """
    home = home or Path.home()
    artifacts_found = 0
    artifacts_read = 0
    entries_read = 0
    found: dict[str, list[EvidenceRecord]] = {}
    for relative in HISTORY_FILES:
        path = home / relative
        if not path.is_file():
            continue
        artifacts_found += 1
        try:
            entries = _parse_history(path, raise_errors=True)
        except OSError:
            continue
        artifacts_read += 1
        entries_read += len(entries)
        for timestamp, command in entries:
            try:
                words = shlex.split(command)
            except ValueError:
                words = command.split()
            if not words:
                continue

            program = Path(words[0]).name
            matched = _match_names(names, words, command)
            if not matched:
                continue

            for name in matched:
                found.setdefault(name, []).append(
                    EvidenceRecord(
                        source="shell-history",
                        tool=program,
                        command=command if len(command) <= 300 else command[:297] + "...",
                        at=iso(timestamp),
                        note=None if program in _FETCH_TOOLS else "command mentions the file",
                    )
                )
    if stats is not None:
        stats.update(
            shell_artifacts_found=artifacts_found,
            shell_artifacts_read=artifacts_read,
            shell_records=entries_read,
        )
    return found
