"""The record a download tool leaves beside the file it fetched.

`yt-dlp --write-info-json` writes `<name>.info.json` next to `<name>.<ext>`,
and that document names the page the media came from, who published it, and
the moment the fetch ran. It is an origin record in the plainest sense:
the program that got the bytes wrote down where it got them.

It is trusted less than the attribute an operating system attaches to the file
itself. A sidecar is a separate file paired to the media by name alone, so a
copy that brings one and not the other, or a rename, breaks the pairing in a
way an extended attribute cannot be broken - and nothing in the document
proves it describes the file it happens to sit beside.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models import EvidenceRecord

#: What yt-dlp appends to the output name, whatever the media extension is.
SUFFIX = ".info.json"

#: These documents carry every available format, thumbnail and heatmap point,
#: so a real one runs to a hundred kilobytes and a playlist's runs further.
#: Read with a bound, like every other parser here: a file this size is not
#: worth loading without a limit, and one much larger is not this.
_MAX_BYTES = 4 * 1024 * 1024

#: The page the media was published on, preferred over the address the user
#: happened to type: a playlist or a short link resolves to the same video,
#: and the canonical page is the one another record can be compared against.
_URL_FIELDS = ("webpage_url", "original_url", "url")

#: Worth keeping, in the order a reader wants them. `formats`, `thumbnails`
#: and the rest of the bulk are left where they are.
_KEPT = (
    "id",
    "title",
    "uploader",
    "uploader_id",
    "uploader_url",
    "channel",
    "channel_url",
    "upload_date",
    "duration_string",
    "license",
    "extractor",
    "original_url",
)


def read_sidecar(path: Path) -> EvidenceRecord | None:
    """What a download tool recorded beside this file, if anything did."""
    beside = path.with_suffix(SUFFIX)
    try:
        if not beside.is_file() or beside.stat().st_size > _MAX_BYTES:
            return None
        document = json.loads(beside.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict):
        return None

    url = _first(document, _URL_FIELDS)
    if not url:
        return None  # without an address it says nothing about where this came from

    fields = {name: value for name in _KEPT if (value := _text(document.get(name)))}
    site = _text(document.get("extractor"))
    return EvidenceRecord(
        source="ytdlp-sidecar",
        url=url,
        tool=_tool(document),
        at=_fetched(document),
        note=f"downloaded from {site}" if site else None,
        fields=fields,
    )


def _tool(document: dict[str, Any]) -> str:
    """`yt-dlp 2026.08.19`, where the document says which version wrote it."""
    version = document.get("_version")
    named = _text(version.get("version")) if isinstance(version, dict) else None
    return f"yt-dlp {named}" if named else "yt-dlp"


def _fetched(document: dict[str, Any]) -> str | None:
    """When the download ran - not when the video was published.

    `epoch` is the moment yt-dlp wrote the document, which is the moment the
    file reached this machine. `upload_date` and `timestamp` say when the video
    became available, which can be years earlier and is a fact about the video
    rather than about its arrival here. This claim is about the arrival, so
    reading the publication date into it would date the arrival wrongly and
    put the file on the timeline before it existed on this machine.
    """
    epoch = document.get("epoch")
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch <= 0:
        return None
    try:
        moment = datetime.fromtimestamp(epoch, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return moment.isoformat().replace("+00:00", "Z")


def _first(document: dict[str, Any], names: tuple[str, ...]) -> str | None:
    for name in names:
        if value := _text(document.get(name)):
            return value
    return None


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None
