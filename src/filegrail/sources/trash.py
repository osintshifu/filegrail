"""Where a file was before somebody threw it away.

The freedesktop trash specification keeps a deleted file and the record of its
deletion side by side: the bytes go into `files/` and a small text record with
the same name goes into `info/`, holding the path the file was deleted from and
the moment it happened. Nothing else on a Linux desktop writes down where a
file used to be.

That pairing is the whole reason this reader is worth having. Every other
source of this kind is matched to a file by name or by path and can be wrong
about which file it means; here the record *is* the trash's bookkeeping for
this exact file, and the implementation that moved the bytes wrote it.

Three layouts, one rule. The home trash lives under `$XDG_DATA_HOME/Trash`, and
a file deleted from another volume goes to a trash on that volume - either
`$topdir/.Trash-$uid` or `$topdir/.Trash/$uid`. All three keep `files/` and
`info/` as siblings, so a record is found from the file itself and no home
directory has to be known: point this at a mounted image's trash and it reads.

**What it does not say.** A trash record is `activity`, not origin. It
proves this machine held the file at a path and then removed it from there; it
says nothing at all about where the bytes came from before that.

The moment carries no time zone. The specification writes it in the local time
of the machine that did the deleting and records that machine's offset nowhere,
so the exact instant is not recoverable from the trash alone. It is read as UTC
here, the same choice this project makes for EXIF, and the record keeps the
string as it was written so a reader who knows the machine can correct it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from ..models import EvidenceRecord

#: The home trash, relative to a home directory. Volume trashes are not listed:
#: they are found from the deleted file rather than from a profile.
TRASH_DIRECTORY = ".local/share/Trash"

#: The two directories the specification requires, and the extension it gives
#: to a record. A file in `files/` is paired with `info/<its name>.trashinfo`.
_FILES = "files"
_INFO = "info"
_RECORD = ".trashinfo"

#: The first line of a record. A file in `info/` that does not begin with this
#: is not one, whatever it is called.
_HEADER = "[Trash Info]"

#: A record is a header and two short lines. Anything larger is not one, and
#: this reads whatever is in a directory a scan was pointed at.
_MAX_RECORD_BYTES = 8192

#: How many records a survey reads out of one trash. A desktop in daily use
#: accumulates thousands; an unbounded index built from a directory anybody can
#: write into is a different thing.
_MAX_RECORDS = 20_000


def read_trash(path: Path) -> EvidenceRecord | None:
    """What the trash recorded when this file was moved into it, if anything."""
    record = _record_for(path)
    if record is None:
        return None
    return _record(record, path.name)


def collect_trash(home: Path | None = None) -> list[EvidenceRecord]:
    """Every record in the home trash, for a survey of what it holds.

    A list rather than an index by path, because nothing is matched against it.
    A record whose file is still in the trash is read from the file itself; a
    record whose path is now occupied says the thing standing there is *not*
    what was deleted, which is an inference this does not draw for the reader.
    """
    home = home or Path.home()
    info = home / TRASH_DIRECTORY / _INFO
    if not info.is_dir():
        return []

    found: list[EvidenceRecord] = []
    try:
        records = sorted(info.iterdir())
    except OSError:
        return []
    for record in records[:_MAX_RECORDS]:
        if record.suffix != _RECORD:
            continue
        origin = _record(record, record.name[: -len(_RECORD)])
        if origin is not None:
            found.append(origin)
    return found


def _record_for(path: Path) -> Path | None:
    """The record belonging to a file that is sitting in a trash.

    The parent has to be `files` before anything is looked for. Without that a
    directory holding `a.txt` beside an `info/a.txt.trashinfo` somebody wrote
    by hand would be read as a trash, and the point of this reader is that the
    pairing is the trash's own and not a guess.
    """
    if path.parent.name != _FILES:
        return None
    record = path.parent.parent / _INFO / f"{path.name}{_RECORD}"
    return record if record.is_file() else None


def _record(record: Path, name: str) -> EvidenceRecord | None:
    fields = _fields(record)
    if fields is None:
        return None

    original = _original(fields.get("Path", ""), record)
    written = fields.get("DeletionDate", "")
    if not original and not written:
        return None

    kept = {name: value for name, value in (("Path", original), ("DeletionDate", written)) if value}
    return EvidenceRecord(
        source="freedesktop-trash",
        at=_deleted(written),
        note=f"deleted from {original}" if original else f"deleted, as {name}",
        fields=kept,
    )


def _fields(record: Path) -> dict[str, str] | None:
    """The keys of one record, or None where the file is not one.

    The first value of a repeated key wins, which is what the specification
    says to do with a record that names `Path` twice.
    """
    try:
        with record.open("rb") as handle:
            raw = handle.read(_MAX_RECORD_BYTES)
    except OSError:
        return None

    lines = raw.decode("utf-8", "replace").splitlines()
    if not lines or lines[0].strip() != _HEADER:
        return None

    found: dict[str, str] = {}
    for line in lines[1:]:
        label, separator, value = line.partition("=")
        if separator and label.strip() not in found:
            found[label.strip()] = value.strip()
    return found


def _original(value: str, record: Path) -> str:
    """The path the file was deleted from.

    Percent-encoded, as the specification requires, and relative when the trash
    is on a volume other than the one the desktop's home is on - relative to the
    top of that volume, which is the directory the trash itself sits in. Joining
    it to the wrong root would turn a real path into a plausible wrong one,
    which is worse than the relative form nobody can misread.
    """
    if not value:
        return ""
    decoded = unquote(value)
    if decoded.startswith("/"):
        return decoded
    top = _topdir(record.parent.parent)
    return str(top / decoded) if top is not None else decoded


def _topdir(root: Path) -> Path | None:
    """The volume a per-volume trash belongs to, or None for the home trash.

    `$topdir/.Trash-$uid` is the one a desktop creates for itself;
    `$topdir/.Trash/$uid` is the one an administrator creates, which puts the
    user's directory one level further down.
    """
    if root.name.startswith(".Trash-"):
        return root.parent
    if root.parent.name == ".Trash":
        return root.parent.parent
    return None


def _deleted(value: str) -> str | None:
    """The moment, read as UTC because the record does not say otherwise.

    See the module docstring: the specification writes local time and records
    no offset, so this is the deleting machine's wall clock and may be hours
    from the true instant. The unconverted string stays in the record's fields.
    """
    try:
        parsed = datetime.strptime(value.strip()[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
