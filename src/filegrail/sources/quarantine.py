"""What macOS wrote down when something downloaded the file.

LaunchServices records a download in two places. It tags the file itself with
`com.apple.quarantine`, four semicolon-separated fields naming the flags, the
moment, the application and an event identifier; and it writes a row into
`com.apple.LaunchServices.QuarantineEventsV2` under the user's home saying what
that identifier stands for - the URL the bytes came from and the page that
linked to it.

Those are two halves of one record rather than two witnesses, so they are
reported as one claim. Emitting both would read as corroboration, and a
subsystem agreeing with itself corroborates nothing.

Two epochs, which is the trap in the format. The attribute counts seconds from
1970 and writes them in hexadecimal; the database counts them from 2001, the
way every Core Foundation timestamp does. Reading either with the other's
epoch puts the download decades from where it happened.

The attribute is named `com.apple.quarantine` on macOS. Nothing outside the
`user.` namespace can be written on Linux, so a file copied out of an image
carries it as `user.com.apple.quarantine` where it survives at all - both
spellings are read, since the point of the exercise is often a volume being
examined from somewhere else.
"""

from __future__ import annotations

import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ..models import FILE_ATTRIBUTE, EvidenceRecord
from ..util import iso, read_xattr

QUARANTINE_DB = "Library/Preferences/com.apple.LaunchServices.QuarantineEventsV2"

_ATTRIBUTES = ("com.apple.quarantine", "user.com.apple.quarantine")

#: Core Foundation counts from here, and so does the database.
_EPOCH_2001 = datetime(2001, 1, 1, tzinfo=timezone.utc)

#: A download history this long is a machine in daily use for years. Reading it
#: is cheap; what is not wanted is an unbounded index built from a crafted file.
_MAX_EVENTS = 50_000

#: The database records no path, so there is nothing to say a file has moved
#: away from - only the URL, whose last segment is what a download usually
#: became.
_AGAINST_THE_URL = "the database recorded the URL and no path to match instead"

_QUERY = """
    SELECT LSQuarantineEventIdentifier,
           LSQuarantineTimeStamp,
           LSQuarantineAgentName,
           LSQuarantineDataURLString,
           LSQuarantineOriginURLString
      FROM LSQuarantineEvent
"""


@dataclass(slots=True)
class Events:
    """Every download the database remembers, indexed both ways it can be found.

    By identifier for a file that still carries its attribute, and by the last
    segment of the recorded URL for one that does not - which is the ordinary
    case for a file copied out of an image, since a copy rarely keeps its
    extended attributes.
    """

    by_uuid: dict[str, EvidenceRecord] = field(default_factory=dict)
    by_name: dict[str, list[EvidenceRecord]] = field(default_factory=dict)


def collect_quarantine_events(
    home: Path | None = None, stats: dict[str, int] | None = None
) -> Events:
    """Read the LaunchServices quarantine database, if there is one."""
    home = home or Path.home()
    path = home / QUARANTINE_DB
    found = Events()
    if not path.is_file():
        if stats is not None:
            stats.update(
                quarantine_artifacts_found=0,
                quarantine_artifacts_read=0,
                quarantine_records=0,
            )
        return found

    try:
        rows = _rows(path)
    except (sqlite3.Error, OSError):
        if stats is not None:
            stats.update(
                quarantine_artifacts_found=1,
                quarantine_artifacts_read=0,
                quarantine_records=0,
            )
        return found

    if stats is not None:
        stats.update(
            quarantine_artifacts_found=1,
            quarantine_artifacts_read=1,
            quarantine_records=len(rows),
        )

    for identifier, stamp, agent, url, origin_url in rows:
        claim = EvidenceRecord(
            source="macos-quarantine",
            url=url or None,
            referrer=origin_url or None,
            tool=agent or None,
            at=_moment(stamp),
        )
        if identifier:
            found.by_uuid[str(identifier).upper()] = claim
        if name := _name(url):
            found.by_name.setdefault(name, []).append(claim)
    return found


def read_quarantine(path: Path, events: Events) -> list[EvidenceRecord]:
    """Return what macOS recorded about this file arriving, as one claim."""
    tagged = _attribute(path)
    if tagged is None:
        return _by_name(path, events)

    stamp, agent, identifier = tagged
    known = events.by_uuid.get(identifier.upper()) if identifier else None
    return [
        EvidenceRecord(
            source="macos-quarantine",
            # The database holds the URL; the attribute never does. Where both
            # name the application the attribute is preferred, because it was
            # written onto this file rather than onto an event it points at.
            url=known.url if known else None,
            referrer=known.referrer if known else None,
            tool=agent or (known.tool if known else None),
            at=_moment_from_attribute(stamp) or (known.at if known else None),
            note="quarantined on download"
            if known
            else "quarantined on download; the event is no longer in the database",
            fields={"EventIdentifier": identifier} if identifier else {},
            match=FILE_ATTRIBUTE,
        )
    ]


def _by_name(path: Path, events: Events) -> list[EvidenceRecord]:
    """A file whose attribute did not survive, matched on the recorded URL.

    The same fallback a browser download already gets and marked the same way,
    because it carries the same weakness: another file of that name would match
    just as well, and the database records no size to check it against.
    """
    from ..scan import matched_by_name

    candidates = events.by_name.get(path.name)
    if not candidates:
        return []
    try:
        size = path.stat().st_size
    except OSError:
        return []
    return [matched_by_name(candidate, size, _AGAINST_THE_URL) for candidate in candidates]


def _attribute(path: Path) -> tuple[str, str, str] | None:
    """The moment, the application and the event identifier, or None.

    Four fields or nothing. Half a record read as a whole one would put the
    flag word where the application's name belongs.
    """
    for name in _ATTRIBUTES:
        raw = read_xattr(path, name)
        if raw is None:
            continue
        parts = raw.decode("utf-8", "replace").split(";")
        if len(parts) < 4:
            return None
        return parts[1], parts[2], parts[3]
    return None


def _moment_from_attribute(stamp: str) -> str | None:
    """Hexadecimal seconds since 1970, as the attribute writes them."""
    try:
        return iso(int(stamp, 16))
    except ValueError:
        return None


def _moment(stamp: object) -> str | None:
    """Seconds since 2001, as Core Foundation and the database write them."""
    if not isinstance(stamp, (int, float)):
        return None
    try:
        when = _EPOCH_2001 + timedelta(seconds=float(stamp))
    except (OverflowError, ValueError):
        return None
    return when.isoformat().replace("+00:00", "Z")


def _name(url: str | None) -> str | None:
    """The file name a URL ends in, which is what a download usually became."""
    if not url:
        return None
    tail = unquote(urlparse(url).path).rsplit("/", 1)[-1]
    return tail or None


def _rows(path: Path) -> list[tuple[Any, ...]]:
    """Read the database without touching it.

    The file is copied first and opened read-only. A live profile has a
    write-ahead log beside it, and opening that in place would have SQLite
    write to a file this tool has no business modifying.
    """
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "quarantine.sqlite"
        copy.write_bytes(path.read_bytes())
        connection = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        try:
            return connection.execute(_QUERY).fetchmany(_MAX_EVENTS)
        finally:
            connection.close()
