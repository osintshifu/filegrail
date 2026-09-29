"""What this machine can be asked, before anything is asked of it.

`no recorded origin` has two very different meanings. It can mean the evidence
was searched and the file was not in it, which is a finding. Or it can mean the
evidence was never there to search - no browser profile readable, no extended
attributes on this filesystem, a shell that keeps no timestamps - which is not a
finding about the file at all.

The report cannot tell those apart on its own, and a reader who assumes the
first when the second is true has said something the tool never supported.
So this says up front what could be searched, and how far back it reaches.
"""

from __future__ import annotations

import os
import platform
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .sources.browser import (
    CHROMIUM_PROFILE_GLOBS,
    FIREFOX_PROFILE_GLOBS,
    _chromium_downloads,
    _firefox_downloads,
    _profiles,
)
from .sources.quarantine import QUARANTINE_DB, collect_quarantine_events
from .sources.recent import RECENT_FILES, collect_recent_files
from .sources.shell import HISTORY_FILES, _parse_history
from .sources.shortcut import RECENT_LINKS, collect_windows_recent
from .sources.sync import collect_sync_roots
from .sources.torrent import TORRENT_STORES, collect_torrents
from .sources.trash import TRASH_DIRECTORY, collect_trash
from .util import birth_time, iso, xattrs_readable


def counted(number: int, noun: str) -> str:
    """`1 shortcut`, `4 shortcuts`. Every noun this file counts is regular."""
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


AVAILABLE = "available"
UNAVAILABLE = "unavailable"
UNSUPPORTED = "not supported here"
PARTIAL = "partial"

#: Every source that reads a user's home directory, and the checks that report
#: it. Kept as a mapping rather than left implicit, because this file promises
#: to say what could be searched: a source a scan consults and the survey never
#: mentions makes that promise one it keeps only sometimes, which is worse than
#: not making it. A test holds this against `sources` itself.
HOME_SOURCES = {
    "collect_browser_downloads": ("Chromium family downloads", "Firefox downloads"),
    "collect_shell_history": ("Shell history",),
    "collect_recent_files": ("Recent documents",),
    "collect_quarantine_events": ("macOS quarantine database",),
    "collect_windows_recent": ("Windows Recent shortcuts",),
    "collect_torrents": ("Torrent client stores",),
    "collect_sync_roots": ("Sync client folders",),
    "collect_trash": ("Deleted files",),
}


#: What a check was looking at. An artifact is a store some other program
#: wrote; the filesystem is what this one is mounted on; a parser is code in
#: this tool. A row saying `unavailable` means something different in each
#: case, and a reader who cannot tell them apart cannot act on any of them.
ARTIFACT = "artifact"
FILESYSTEM = "filesystem"
PARSER = "parser"


@dataclass(slots=True)
class Check:
    name: str
    state: str
    detail: str = ""

    #: One of `artifact`, `filesystem`, `parser`.
    kind: str = ARTIFACT


@dataclass(slots=True)
class Survey:
    checks: list[Check] = field(default_factory=list)
    horizon: list[Check] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "sources": [
                {"name": c.name, "kind": c.kind, "state": c.state, "detail": c.detail}
                for c in self.checks
            ],
            "horizon": [{"name": c.name, "detail": c.detail} for c in self.horizon],
        }


def survey(home: Path | None = None) -> Survey:
    home = home or Path.home()
    found = Survey()
    found.checks.extend(_browsers(home, found))
    found.checks.extend(_os_origin())
    found.checks.append(_shell(home, found))
    found.checks.append(_recent(home, found))
    found.checks.append(_quarantine(home, found))
    found.checks.append(_trash(home, found))
    found.checks.append(_shortcuts(home))
    found.checks.append(_torrents(home))
    found.checks.append(_synced(home))
    found.checks.append(_birth_times())
    found.checks.append(_c2pa())
    return found


# --- browsers ----------------------------------------------------------------


def _browsers(home: Path, found: Survey) -> list[Check]:
    """Every readable profile, with how far back its records reach.

    The oldest surviving record is the honest limit of what this machine can
    answer. Chromium prunes at about ninety days, so a file older than the
    horizon cannot be resolved however good the tool is.
    """
    checks: list[Check] = []
    readers = (
        ("Chromium family", CHROMIUM_PROFILE_GLOBS, _chromium_downloads),
        ("Firefox", FIREFOX_PROFILE_GLOBS, _firefox_downloads),
    )

    for label, globs, reader in readers:
        profiles = list(_profiles(home, globs))
        if not profiles:
            checks.append(Check(f"{label} downloads", UNAVAILABLE, "no profile found"))
            continue

        records = 0
        readable = 0
        oldest: str | None = None
        for profile in profiles:
            try:
                seen = list(reader(profile))
            except (sqlite3.Error, OSError):
                continue
            readable += 1
            records += len(seen)
            for _target, origin in seen:
                if origin.at and (oldest is None or origin.at < oldest):
                    oldest = origin.at

        state = AVAILABLE if readable else UNAVAILABLE
        if readable and readable < len(profiles):
            state = PARTIAL
        detail = (
            f"{counted(records, 'record')} across {readable} of {counted(len(profiles), 'profile')}"
        )
        checks.append(Check(f"{label} downloads", state, detail))

        if oldest:
            found.horizon.append(Check(f"{label} oldest record", AVAILABLE, oldest[:10]))
    return checks


# --- the rest ----------------------------------------------------------------


def _os_origin() -> list[Check]:
    """Which of the per-file download attributes can be read at all here.

    Two answers rather than one off Windows. A machine keeps its own platform's
    attribute, and it can also be reading a Windows volume mounted from an
    image - where the zone stream arrives as an extended attribute and is
    readable on exactly the same terms as any other. Whether such a volume
    happens to be mounted is a fact about the run; this reports what could be
    searched.
    """
    system = platform.system()

    if system == "Windows":
        return [Check("Windows Zone.Identifier", AVAILABLE, "alternate data streams")]

    carried = (
        Check("Mounted Zone.Identifier", AVAILABLE, "user.Zone.Identifier on an NTFS mount")
        if xattrs_readable()
        else Check("Mounted Zone.Identifier", UNSUPPORTED, "no extended attributes")
    )

    if system == "Darwin":
        state = AVAILABLE if xattrs_readable() else UNAVAILABLE
        return [Check("macOS where-from", state, "kMDItemWhereFroms"), carried]
    if not xattrs_readable():
        return [Check("XDG origin attribute", UNSUPPORTED, "no extended attributes"), carried]

    # Reading the attribute needs the filesystem to carry it, which varies per
    # mount rather than per platform, so it is tested rather than assumed.
    try:
        with tempfile.NamedTemporaryFile() as probe:
            os.setxattr(probe.name, "user.filegrail.probe", b"1")
            os.getxattr(probe.name, "user.filegrail.probe")
    except OSError:
        return [
            Check("XDG origin attribute", UNAVAILABLE, "filesystem rejects user xattrs"),
            carried,
        ]
    return [
        Check(
            "XDG origin attribute",
            AVAILABLE,
            "written by KDE tools and wget --xattr, but not by Firefox",
        ),
        carried,
    ]


def _shell(home: Path, found: Survey) -> Check:
    """Which history files exist, and whether any of them kept timestamps."""
    present = [name for name in HISTORY_FILES if (home / name).is_file()]
    if not present:
        return Check("Shell history", UNAVAILABLE, "no history file found")

    timed = False
    oldest: float | None = None
    for name in present:
        try:
            head = (home / name).read_text(encoding="utf-8", errors="replace")[:20000]
        except OSError:
            continue
        if head.lstrip().startswith((": 1", "#1")):
            timed = True
        for when, _command in _parse_history(home / name):
            if when is not None and (oldest is None or when < oldest):
                oldest = when

    # Only where the shell was configured to keep times. Ordering survives
    # without them, but a date does not, and one would have to be invented.
    if oldest is not None:
        stamp = iso(oldest)
        if stamp:
            found.horizon.append(Check("Shell history oldest command", AVAILABLE, stamp[:10]))

    names = ", ".join(Path(name).name for name in present)
    if timed:
        return Check("Shell history", AVAILABLE, f"{names}, with timestamps")
    return Check("Shell history", PARTIAL, f"{names}, without timestamps")


def _recent(home: Path, found: Survey) -> Check:
    """The desktop's record of which application opened which file.

    A scan reads this every time, so a survey that leaves it out understates
    what could be found. It answers a different question from the rest - what
    handled the file here, not how it arrived - and it is the only source of
    that kind, which is why its absence is worth stating rather than implying.
    """
    where = [name for name in RECENT_FILES if (home / name).is_file()]
    if not where:
        return Check("Recent documents", UNAVAILABLE, "no list found")

    opened = collect_recent_files(home)
    if not opened:
        return Check("Recent documents", PARTIAL, "a list is present but nothing could be read")

    oldest: str | None = None
    for origins in opened.values():
        for origin in origins:
            if origin.at and (oldest is None or origin.at < oldest):
                oldest = origin.at
    if oldest:
        found.horizon.append(Check("Recent documents oldest entry", AVAILABLE, oldest[:10]))

    return Check(
        "Recent documents",
        AVAILABLE,
        f"{counted(len(opened), 'file')} in {', '.join(Path(name).name for name in where)}",
    )


def _trash(home: Path, found: Survey) -> Check:
    """What the desktop's trash still holds, and how far back it reaches.

    Reported like the rest even though a scan does not consult it by profile:
    the records are read from the deleted files themselves, so what this says
    is how much there is to find if the trash is scanned - which is a thing an
    examiner would otherwise have to go and look for by hand.
    """
    if not (home / TRASH_DIRECTORY).is_dir():
        return Check("Deleted files", UNAVAILABLE, "no trash directory")

    thrown = collect_trash(home)
    if not thrown:
        # Says what is there rather than why. A trash that was emptied and one
        # whose records nothing here can read both answer the question a survey
        # asks - nothing to be found - and this cannot tell them apart without
        # claiming to know which.
        return Check("Deleted files", UNAVAILABLE, "the trash holds no readable record")

    oldest = min((origin.at for origin in thrown if origin.at), default=None)
    if oldest:
        found.horizon.append(Check("Deleted files oldest record", AVAILABLE, oldest[:10]))

    return Check(
        "Deleted files",
        AVAILABLE,
        f"{counted(len(thrown), 'file')} in the trash, with the path each came from",
    )


def _quarantine(home: Path, found: Survey) -> Check:
    """The LaunchServices record of what was downloaded and from where.

    A home directory rather than a platform: the database is the reason this
    can be asked of a copied macOS profile from anywhere, which is exactly the
    case where saying whether it was there matters most.
    """
    events = collect_quarantine_events(home)
    if not (home / QUARANTINE_DB).is_file():
        return Check("macOS quarantine database", UNAVAILABLE, "no database in this profile")
    if not events.by_uuid and not events.by_name:
        return Check("macOS quarantine database", PARTIAL, "present but nothing could be read")

    moments = sorted(claim.at for claim in events.by_uuid.values() if claim.at)
    if moments:
        found.horizon.append(Check("macOS quarantine oldest download", AVAILABLE, moments[0][:10]))
    return Check("macOS quarantine database", AVAILABLE, counted(len(events.by_uuid), "download"))


def _shortcuts(home: Path) -> Check:
    """The Windows Recent folder, which keeps a shortcut per file opened.

    No horizon: a shortcut is rewritten every time the file is opened, so the
    oldest one says when the least-recently-used file was last touched, which
    is not a limit on what the folder can answer.
    """
    if not (home / RECENT_LINKS).is_dir():
        return Check("Windows Recent shortcuts", UNAVAILABLE, "no Recent folder in this profile")

    found = collect_windows_recent(home)
    if not found:
        return Check(
            "Windows Recent shortcuts", PARTIAL, "a Recent folder with nothing readable in it"
        )
    total = sum(len(claims) for claims in found.values())
    return Check("Windows Recent shortcuts", AVAILABLE, counted(total, "shortcut"))


def _torrents(home: Path) -> Check:
    """The copy a torrent client keeps of everything it has ever loaded.

    No horizon. A torrent's creation date says when the torrent was made, not
    when anything in it was fetched, so the oldest one in the store bounds
    nothing about what this machine can answer.
    """
    where = [name for name in TORRENT_STORES if (home / name).is_dir()]
    if not where:
        return Check("Torrent client stores", UNAVAILABLE, "no client store found")

    found = collect_torrents(home)
    if not found:
        return Check("Torrent client stores", PARTIAL, "a store with nothing readable in it")
    return Check("Torrent client stores", AVAILABLE, counted(len(found), "torrent"))


def _synced(home: Path) -> Check:
    """Which folders a sync client says it keeps in step, and with what.

    No horizon: a configuration says what is being synced now and keeps no
    record of when anything was, so there is no reach to report.
    """
    roots = collect_sync_roots(home)
    if not roots:
        return Check("Sync client folders", UNAVAILABLE, "no client configuration found")
    named = ", ".join(sorted({root.client for root in roots}))
    return Check("Sync client folders", AVAILABLE, f"{counted(len(roots), 'folder')} - {named}")


def _birth_times() -> Check:
    """Creation time is a filesystem feature, not an operating system one."""
    try:
        with tempfile.NamedTemporaryFile() as probe:
            found = birth_time(Path(probe.name))
    except OSError:
        found = None
    if found is None:
        return Check(
            "Creation timestamps", UNAVAILABLE, "filesystem does not record them", FILESYSTEM
        )
    detail = "statx" if sys.platform == "linux" else "stat"
    return Check("Creation timestamps", AVAILABLE, detail, FILESYSTEM)


def _c2pa() -> Check:
    return Check(
        "C2PA signature check",
        PARTIAL,
        "manifests are read and their hash binding recomputed; "
        "validating the certificate chain needs a crypto library",
        PARSER,
    )
