"""What a `.torrent` file says about the files it distributes.

A torrent is a container in the same sense an archive is: it lists its members
by name and exact size, so a file on disk matching both was very likely part of
it. Unlike an archive it carries an origin of its own rather than one to
inherit - the trackers it was announced to, the client that wrote it, and an
info hash that names the content independently of any of them.

The claim is deliberately undated. A torrent's creation date says when the
torrent was made, which can be years before anything in it was fetched, so
reading it as an arrival would put the file on the timeline at a moment nothing
recorded. The date is reported as what it is instead.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..bencode import BencodeError, loads, value_span
from ..models import EvidenceRecord

SUFFIX = ".torrent"

#: Where the clients keep their own copy of every torrent they have loaded.
#: This is the ordinary case: the file on disk rarely has a `.torrent` beside
#: it, and the client has kept one all along.
TORRENT_STORES = [
    ".local/share/qBittorrent/BT_backup",
    ".local/share/data/qBittorrent/BT_backup",
    "Library/Application Support/qBittorrent/BT_backup",
    "AppData/Local/qBittorrent/BT_backup",
    "AppData/Roaming/qBittorrent/BT_backup",
    ".config/transmission/torrents",
    ".config/transmission-daemon/torrents",
    "Library/Application Support/Transmission/Torrents",
    "AppData/Local/transmission/torrents",
    ".config/deluge/state",
]

#: A store this size is a client that has seen thousands of torrents. Reading
#: all of them is not what this is for.
_MAX_STORED = 5_000

#: A torrent listing a whole filesystem is not what this pairs against, and the
#: list is walked in full before anything is matched.
_MAX_MEMBERS = 20_000

#: `pieces` alone is twenty bytes per piece, so a torrent for a large release
#: is legitimately some megabytes. Well beyond that is not one.
_MAX_BYTES = 32 * 1024 * 1024


@dataclass(slots=True)
class Torrent:
    """What one torrent claims, and which files it would explain."""

    record: EvidenceRecord

    #: {member base name: every size listed for it}, the same shape the archive
    #: reader produces, because the pairing that follows is the same pairing.
    members: dict[str, set[int]]


def collect_torrents(
    home: Path | None = None, stats: dict[str, int] | None = None
) -> list[Torrent]:
    """Every torrent the local clients have kept, from their own stores."""
    home = home or Path.home()
    found: list[Torrent] = []
    stores_found = 0
    stores_read = 0
    artifacts_found = 0
    artifacts_read = 0
    for relative in TORRENT_STORES:
        store = home / relative
        if not store.is_dir():
            continue
        stores_found += 1
        try:
            stored = sorted(store.glob(f"*{SUFFIX}"))
        except OSError:
            continue
        stores_read += 1
        for path in stored:
            if len(found) >= _MAX_STORED:
                if stats is not None:
                    stats.update(
                        torrent_artifacts_found=artifacts_found,
                        torrent_artifacts_read=artifacts_read,
                        torrent_records=len(found),
                        torrent_stores_found=stores_found,
                        torrent_stores_read=stores_read,
                    )
                return found
            artifacts_found += 1
            torrent = read_torrent(path)
            if torrent is not None:
                artifacts_read += 1
                found.append(torrent)
    if stats is not None:
        stats.update(
            torrent_artifacts_found=artifacts_found,
            torrent_artifacts_read=artifacts_read,
            torrent_records=len(found),
            torrent_stores_found=stores_found,
            torrent_stores_read=stores_read,
        )
    return found


def is_torrent(path: Path) -> bool:
    return path.suffix.lower() == SUFFIX


def read_torrent(path: Path) -> Torrent | None:
    """Read one `.torrent`, or None where it is not one."""
    try:
        if path.stat().st_size > _MAX_BYTES:
            return None
        raw = path.read_bytes()
        document = loads(raw)
    except (OSError, BencodeError):
        return None
    if not isinstance(document, dict):
        return None

    info = document.get(b"info")
    if not isinstance(info, dict):
        return None

    members = _members(info)
    if not members:
        return None

    return Torrent(record=_record(path, raw, document, info), members=members)


def _members(info: dict[bytes, Any]) -> dict[str, set[int]]:
    """Every file the torrent lists, by base name, with the sizes given."""
    members: dict[str, set[int]] = {}

    def record(name: str, size: object) -> None:
        if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
            members.setdefault(Path(name).name, set()).add(size)

    files = info.get(b"files")
    if isinstance(files, list):
        for entry in files[:_MAX_MEMBERS]:
            if not isinstance(entry, dict):
                continue
            parts = entry.get(b"path")
            if isinstance(parts, list) and parts:
                record(_text(parts[-1]) or "", entry.get(b"length"))
        return {name: sizes for name, sizes in members.items() if name}

    # A single-file torrent names the file itself rather than listing one.
    record(_text(info.get(b"name")) or "", info.get(b"length"))
    return {name: sizes for name, sizes in members.items() if name}


def _record(
    path: Path, raw: bytes, document: dict[bytes, Any], info: dict[bytes, Any]
) -> EvidenceRecord:
    name = _text(info.get(b"name"))
    fields: dict[str, str] = {}
    if name:
        fields["torrent"] = name

    trackers = _trackers(document)
    if trackers:
        fields["trackers"] = ", ".join(trackers)

    made = _moment(document.get(b"creation date"))
    if made:
        fields["created"] = made
    comment = _text(document.get(b"comment"))
    if comment:
        fields["comment"] = comment

    return EvidenceRecord(
        source="torrent",
        url=_magnet(raw, name),
        tool=_text(document.get(b"created by")),
        note=f"listed in the torrent {name}" if name else "listed in a torrent",
        container=str(path),
        fields=fields,
    )


def _magnet(raw: bytes, name: str | None) -> str | None:
    """The magnet address for this content, from the info hash.

    The hash is taken over the `info` value exactly as the author wrote it,
    which is why the bytes are located rather than re-encoded: a re-encoding
    differs from the original wherever the author was not canonical, and that
    is precisely where a hash computed from it would name the wrong content.
    """
    span = value_span(raw, b"info")
    if span is None:
        return None
    digest = hashlib.sha1(raw[span[0] : span[1]]).hexdigest()  # noqa: S324 - BitTorrent v1
    address = f"magnet:?xt=urn:btih:{digest}"
    return f"{address}&dn={quote(name)}" if name else address


def _trackers(document: dict[bytes, Any]) -> list[str]:
    """`announce`, plus every tier of `announce-list`, in the order written."""
    found: list[str] = []

    def add(value: object) -> None:
        text = _text(value)
        if text and text not in found:
            found.append(text)

    add(document.get(b"announce"))
    tiers = document.get(b"announce-list")
    if isinstance(tiers, list):
        for tier in tiers:
            if isinstance(tier, list):
                for entry in tier:
                    add(entry)
    return found


def _moment(value: object) -> str | None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def _text(value: object) -> str | None:
    if isinstance(value, bytes):
        decoded = value.decode("utf-8", "replace").strip()
        return decoded or None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
