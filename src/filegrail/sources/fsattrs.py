"""Per-file origin metadata written by the operating system.

Three platforms solve the same problem in three ways:

    Windows   Zone.Identifier alternate data stream (HostUrl, ReferrerUrl)
    macOS     com.apple.metadata:kMDItemWhereFroms (binary plist: [url, referrer])
    Linux     user.xdg.origin.url / user.xdg.referrer.url extended attributes

Coverage is uneven. Windows tags essentially every browser download. macOS tags
Safari and Chrome downloads. On Linux the attribute is written only by some
desktop tools and by wget/curl when explicitly asked, so it is frequently
absent - which is why the browser history is the primary source, not this.

The first of the three is not only readable on Windows. Mount a Windows volume
anywhere else and its named data streams arrive as extended attributes, so the
richest of these records is available in exactly the case `--home` was built
for: a profile read off an image rather than off the machine underfoot.
"""

from __future__ import annotations

import configparser
import os
import plistlib
from pathlib import Path

from ..models import EvidenceRecord
from ..util import read_xattr

_LINUX_ORIGIN = "user.xdg.origin.url"
_LINUX_REFERRER = "user.xdg.referrer.url"
_MACOS_WHEREFROMS = "com.apple.metadata:kMDItemWhereFroms"

#: How the zone stream reaches a machine that is not Windows. `ntfs-3g` maps
#: named data streams into the `user.` namespace and does that by default
#: (`streams_interface=xattr`); Samba's `vfs_streams_xattr` stores the same
#: stream under a prefix of its own. Neither is exotic - between them they are
#: what an examiner sees after mounting a Windows volume read-only on anything
#: else, which is the case `--home` exists for.
_ZONE_XATTRS = ("user.Zone.Identifier", "user.DosStream.Zone.Identifier:$DATA")


def read_file_attributes(path: Path) -> list[EvidenceRecord]:
    """Return what the filesystem's own attributes say about where this came from."""
    found: list[EvidenceRecord] = []
    for reader in (_read_zone_identifier, _read_macos_wherefroms, _read_xdg_xattrs):
        try:
            record = reader(path)
        except (OSError, ValueError):
            continue
        if record is not None:
            found.append(record)
    return found


def _read_zone_identifier(path: Path) -> EvidenceRecord | None:
    """Read the NTFS Zone.Identifier stream, however this machine exposes it.

    Windows carries it as an alternate data stream on the file itself. Off
    Windows the same bytes arrive as an extended attribute, and that is the
    case worth having: this is the richest thing Windows writes down about a
    download, and reading it only on Windows put it out of reach of the one
    workflow built to want it - a profile read off a mounted image.
    """
    raw = _zone_stream(path)
    if raw is None:
        return None

    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(raw)
    except configparser.Error:
        return None

    if not parser.has_section("ZoneTransfer"):
        return None
    section = parser["ZoneTransfer"]
    host = section.get("HostUrl") or None
    referrer = section.get("ReferrerUrl") or None
    if not host and not referrer:
        return None

    zone = section.get("ZoneId")
    return EvidenceRecord(
        source="windows-zone-identifier",
        url=host,
        referrer=referrer,
        note=f"ZoneId={zone}" if zone else None,
    )


def _zone_stream(path: Path) -> str | None:
    """The zone stream's text, from the file's own stream or from an attribute.

    The named-stream syntax is only asked for on Windows. A colon is a legal
    character in a POSIX file name, so trying it elsewhere could open a file
    that merely happens to be called that and report a zone for the wrong one.
    """
    if os.name == "nt":
        try:
            return Path(f"{path}:Zone.Identifier").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    for name in _ZONE_XATTRS:
        carried = read_xattr(path, name)
        if carried is not None:
            return carried.decode("utf-8", "replace")
    return None


def _read_macos_wherefroms(path: Path) -> EvidenceRecord | None:
    """Read the macOS 'where from' metadata attribute.

    Under its own name on macOS, and under the `user.` namespace where a copy
    carries it onto a system that has no other namespace to put it in.
    """
    raw = read_xattr(path, _MACOS_WHEREFROMS) or read_xattr(path, f"user.{_MACOS_WHEREFROMS}")
    if raw is None:
        return None

    values = plistlib.loads(raw)
    if not isinstance(values, list) or not values:
        return None

    url = values[0] or None
    referrer = values[1] if len(values) > 1 and values[1] else None
    return EvidenceRecord(source="macos-wherefroms", url=url, referrer=referrer)


def _read_xdg_xattrs(path: Path) -> EvidenceRecord | None:
    """Read the freedesktop.org origin extended attributes."""

    def get(name: str) -> str | None:
        raw = read_xattr(path, name)
        return raw.decode("utf-8", "replace") or None if raw is not None else None

    url = get(_LINUX_ORIGIN)
    referrer = get(_LINUX_REFERRER)
    if not url and not referrer:
        return None
    return EvidenceRecord(source="xdg-xattr", url=url, referrer=referrer)
