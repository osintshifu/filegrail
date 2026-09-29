"""Print the notes for one release, out of CHANGELOG.md.

    python tools/release_notes.py v0.22.1

The release workflow publishes them as the GitHub release, so a release page
and the changelog cannot say different things about the same version.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def notes(version: str) -> str:
    """The changelog's section for `version`, with how to upgrade to it."""
    text = CHANGELOG.read_text(encoding="utf-8")
    section = re.search(rf"^## {re.escape(version)} - [^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    if section is None:
        raise SystemExit(f"CHANGELOG.md has no section for {version}")
    return (
        _unwrapped(section.group(1).strip())
        + "\n\n```bash\npipx install --upgrade filegrail\n```\n\n"
        + "Full detail in [CHANGELOG.md]"
        + "(https://github.com/osintshifu/filegrail/blob/master/CHANGELOG.md).\n"
    )


def _unwrapped(markdown: str) -> str:
    """Every paragraph and list item on one line.

    The changelog is wrapped for reading in a terminal, and a GitHub release
    page turns each of those line breaks into a visible one.
    """
    lines: list[str] = []
    for line in markdown.splitlines():
        starts_block = not line.strip() or line.startswith(("#", "- "))
        continues = lines and lines[-1].strip() and not lines[-1].startswith("#")
        if starts_block or not continues:
            lines.append(line)
        else:
            lines[-1] += " " + line.strip()
    return "\n".join(lines)


if __name__ == "__main__":
    print(notes(sys.argv[1].removeprefix("v")), end="")
