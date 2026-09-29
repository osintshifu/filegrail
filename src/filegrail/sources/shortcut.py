"""The Windows Recent folder, which keeps a shortcut per file that was opened.

A `.lnk` under `AppData/Roaming/Microsoft/Windows/Recent` is the counterpart of
a `recently-used.xbel` entry, and it answers the same question at the same
strength: something on that machine handled this file. Opening a file proves
contact and not origin - the file may have arrived by any route at all
beforehand - so the claim is ranked with the desktop's list rather than with a
download record.

What a shortcut adds is *where the file was when it was opened*. It records the
volume it sat on, by type, serial number and label, and a network share by
name; and, where the tracker block survives, the NetBIOS name of the machine
that created the link. That supports a statement nothing else here can make -
this file was opened from a disk that is not this one - which is still a fact
about handling and not about arrival, however suggestive it reads.

The format is [MS-SHLLINK]. Nothing available writes a `.lnk`, so the fixtures
behind this are built to the specification; the folder walk around it is not in
that position.
"""

from __future__ import annotations

import struct
from pathlib import Path

from ..models import EvidenceRecord
from ..util import basename, iso

RECENT_LINKS = "AppData/Roaming/Microsoft/Windows/Recent"

_HEADER_SIZE = 0x4C

#: 00021401-0000-0000-C000-000000000046, in the mixed-endian order a GUID is
#: stored in. Checked as well as the header size, which collides by accident far
#: more often than a class identifier does.
_CLSID = bytes.fromhex("0114020000000000C000000000000046")

_HAS_TARGET_ID_LIST = 0x00000001
_HAS_LINK_INFO = 0x00000002

_VOLUME_ID_AND_LOCAL_BASE_PATH = 0x00000001
_COMMON_NETWORK_RELATIVE_LINK = 0x00000002

#: [MS-SHLLINK] borrows these from GetDriveType. Only the ones worth saying out
#: loud are named; anything else is reported by number rather than guessed at.
_DRIVE_TYPES = {
    0: "unknown",
    1: "no root directory",
    2: "removable",
    3: "fixed",
    4: "network",
    5: "optical",
    6: "RAM disk",
}

#: Volumes whose presence is the interesting part of the finding.
_ELSEWHERE = {"removable", "optical", "network"}

_TRACKER_SIGNATURE = 0xA0000003

#: A Recent folder that has been in use for years holds a few thousand links.
#: Well past that is not a folder, it is a way to make a scan take all day.
_MAX_LINKS = 20_000

#: A shell link is a header, some strings and a few small blocks. Anything this
#: size is not one, and is not worth reading into memory to find out.
_MAX_LINK = 1024 * 1024


def collect_windows_recent(
    home: Path | None = None, stats: dict[str, int] | None = None
) -> dict[str, list[EvidenceRecord]]:
    """Map the file name a shortcut points at -> what it recorded about opening it.

    Indexed by name rather than by path because the path in the shortcut was
    written by Windows and the scan may be running anywhere. Where the recorded
    path does happen to match, the caller can still see it in `OpenedFrom`.
    """
    home = home or Path.home()
    folder = home / RECENT_LINKS
    if not folder.is_dir():
        if stats is not None:
            stats.update(
                windows_recent_artifacts_found=0,
                windows_recent_artifacts_read=0,
                windows_recent_records=0,
            )
        return {}

    found: dict[str, list[EvidenceRecord]] = {}
    records = 0
    try:
        paths = sorted(folder.iterdir())
    except OSError:
        if stats is not None:
            stats.update(
                windows_recent_artifacts_found=1,
                windows_recent_artifacts_read=0,
                windows_recent_records=0,
            )
        return {}
    for index, path in enumerate(paths):
        if index >= _MAX_LINKS:
            break
        if not path.is_file() or path.suffix.lower() != ".lnk":
            continue
        try:
            if path.stat().st_size > _MAX_LINK:
                continue
            raw = path.read_bytes()
        except OSError:
            continue

        origin = read_link(raw, opened=_opened(path))
        if origin is None:
            continue
        records += 1
        name = basename(str(origin.fields.get("OpenedFrom") or ""))
        # A shortcut with no recorded path still names its target in the file
        # name Windows gave it: `report.docx.lnk`.
        found.setdefault(name or path.stem, []).append(origin)
    if stats is not None:
        stats.update(
            windows_recent_artifacts_found=1,
            windows_recent_artifacts_read=1,
            windows_recent_records=records,
        )
    return found


def read_shortcuts(
    path: Path, size: int, shortcuts: dict[str, list[EvidenceRecord]]
) -> list[EvidenceRecord]:
    """Attach whichever shortcuts point at this file.

    An exact path match is taken as one; anything else is a name match and is
    marked as one, with the size the shortcut recorded checked against the file
    the same way a download record's is.
    """
    found = []
    for origin in shortcuts.get(path.name, []):
        if origin.fields.get("OpenedFrom") == str(path):
            found.append(origin)
        else:
            from ..scan import matched_by_name

            # No reason given: the claim's own note already says where the
            # file was opened from, and repeating it makes a third clause out
            # of what the first one said.
            found.append(matched_by_name(origin, size, ""))
    return found


def read_link(raw: bytes, opened: str | None = None) -> EvidenceRecord | None:
    """Return what one shell link recorded, or None if it is not one."""
    if len(raw) < _HEADER_SIZE:
        return None
    (size,) = struct.unpack_from("<I", raw, 0)
    if size != _HEADER_SIZE or raw[4:20] != _CLSID:
        return None

    try:
        flags, _attributes = struct.unpack_from("<II", raw, 20)
        target_size, _icon, _show = struct.unpack_from("<III", raw, 52)
        (written,) = struct.unpack_from("<Q", raw, 44)
    except struct.error:
        return None

    at = _HEADER_SIZE
    if flags & _HAS_TARGET_ID_LIST:
        # Not parsed. It describes the target as a shell namespace path, which
        # says nothing the LinkInfo does not say more plainly.
        try:
            (id_size,) = struct.unpack_from("<H", raw, at)
        except struct.error:
            return None
        at += 2 + id_size

    fields: dict[str, str] = {}
    if flags & _HAS_LINK_INFO:
        info = _link_info(raw, at)
        if info is None:
            return None
        fields.update(info)

    if target_size:
        fields["TargetSize"] = str(target_size)
    if stamp := _moment(written):
        fields["TargetWritten"] = stamp
    if not fields:
        return None
    if tracked := _tracker(raw):
        fields["MachineID"] = tracked

    return EvidenceRecord(
        source="windows-recent",
        at=opened,
        bytes=target_size or None,
        note=_note(fields),
        fields=fields,
    )


def _note(fields: dict[str, str]) -> str:
    """One line saying what was opened and, where it matters, from where."""
    where = fields.get("Volume")
    if share := fields.get("NetworkShare"):
        return f"opened from the network share {share}"
    if where in _ELSEWHERE:
        label = fields.get("VolumeLabel")
        named = f" labelled {label}" if label else ""
        return f"opened from a {where} volume{named}, which may not be this machine's disk"
    return "opened on this desktop"


def _link_info(raw: bytes, at: int) -> dict[str, str] | None:
    """The volume and path halves of a LinkInfo, whichever are present.

    Every offset in the structure is measured from its own start, so they are
    resolved against `at` rather than against the file.
    """
    try:
        size, header, flags = struct.unpack_from("<III", raw, at)
        volume_offset, local_offset, network_offset, _suffix = struct.unpack_from(
            "<IIII", raw, at + 12
        )
    except struct.error:
        return None
    if size < header or at + size > len(raw):
        return None

    found: dict[str, str] = {}
    if flags & _VOLUME_ID_AND_LOCAL_BASE_PATH:
        found.update(_volume(raw, at + volume_offset) or {})
        if path := _ansi(raw, at + local_offset, at + size):
            found["OpenedFrom"] = path
    if flags & _COMMON_NETWORK_RELATIVE_LINK:
        if share := _network(raw, at + network_offset, at + size):
            found["NetworkShare"] = share
            found.setdefault("OpenedFrom", share)
            found["Volume"] = "network"
    return found or None


def _volume(raw: bytes, at: int) -> dict[str, str] | None:
    """The VolumeID: what kind of disk it was, its serial and its label."""
    try:
        size, drive, serial, label_offset = struct.unpack_from("<IIII", raw, at)
    except struct.error:
        return None
    if size < 0x10 or at + size > len(raw):
        return None

    found = {"Volume": _DRIVE_TYPES.get(drive, f"type {drive}")}
    if serial:
        # Quoted as eight hexadecimal digits everywhere Windows shows it.
        found["VolumeSerial"] = f"{serial:08X}"
    if label := _ansi(raw, at + label_offset, at + size):
        found["VolumeLabel"] = label
    return found


def _network(raw: bytes, at: int, end: int) -> str | None:
    """The CommonNetworkRelativeLink's share name."""
    try:
        size, _flags, name_offset = struct.unpack_from("<III", raw, at)
    except struct.error:
        return None
    if size < 0x14 or at + size > end:
        return None
    return _ansi(raw, at + name_offset, at + size)


def _tracker(raw: bytes) -> str | None:
    """The NetBIOS name of the machine the shortcut was created on.

    Found by its signature rather than by walking the ExtraData chain: the
    chain is a sequence of sized blocks and one bad size loses every block
    after it, while the signature is four bytes that do not otherwise occur.
    """
    marker = struct.pack("<I", _TRACKER_SIGNATURE)
    at = raw.find(marker)
    if at < 4 or at + 4 + 12 + 16 > len(raw):
        return None
    (block,) = struct.unpack_from("<I", raw, at - 4)
    if block < 0x60:
        return None
    name = raw[at + 12 : at + 12 + 16].split(b"\x00", 1)[0]
    return name.decode("latin-1", "replace").strip() or None


def _ansi(raw: bytes, at: int, end: int) -> str | None:
    """A null-terminated string, read no further than the structure it is in."""
    if not 0 <= at < end or end > len(raw):
        return None
    text = raw[at:end].split(b"\x00", 1)[0]
    return text.decode("latin-1", "replace") or None


def _moment(value: int) -> str | None:
    """A FILETIME, which counts 100-nanosecond ticks from 1601."""
    if not value:
        return None
    return iso(value / 10_000_000 - 11_644_473_600)


def _opened(path: Path) -> str | None:
    """When the shortcut was last written, which is when the file was opened.

    Windows rewrites the link on every open, so its own timestamp is the
    reading - the times inside it belong to the target, not to the opening.
    """
    try:
        return iso(path.stat().st_mtime)
    except OSError:
        return None
