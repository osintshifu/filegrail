"""ID3v2 frames, for MP3 and the tags other audio formats borrowed from it.

Only the frames that say how the file came to exist are read: the encoder, the
software that wrote it, the recording date and the credited artist.

The tag is read from bytes as well as from a path, because WAV carries the very
same tag inside a RIFF chunk instead of at the start of the file.
"""

from __future__ import annotations

import struct
from pathlib import Path

#: Files that open with the tag. WAV does not - it keeps one in a chunk,
#: which is the RIFF reader's business.
SUFFIXES = {".mp3", ".aac", ".tta"}

_MAX_TAG = 2 * 1024 * 1024
_MAX_FRAMES = 256

#: Frame identifier -> what it means here. v2.3/v2.4 first, then the v2.2 forms.
FRAMES = {
    b"TSSE": "encoder",  # settings used for encoding
    b"TENC": "encoder",  # encoded by
    b"TSSA": "encoder",
    b"TDRC": "date",  # recording time (v2.4)
    b"TYER": "date",  # year (v2.3)
    b"TDAT": "date",
    b"TPE1": "artist",
    b"TIT2": "title",
    b"TSS": "encoder",
    b"TEN": "encoder",
    b"TYE": "date",
    b"TP1": "artist",
    b"TT2": "title",
}


def read_id3(path: Path) -> dict[str, str]:
    """Return the interesting ID3 frames of a file that opens with a tag."""
    try:
        with path.open("rb") as handle:
            header = handle.read(10)
            if len(header) < 10 or header[:3] != b"ID3":
                return {}
            size = _synchsafe(header[6:10])
            if size <= 0 or size > _MAX_TAG:
                return {}
            return read_tag(header + handle.read(size))
    except (OSError, struct.error, ValueError):
        return {}


def read_tag(raw: bytes) -> dict[str, str]:
    """Return the interesting frames of a complete ID3v2 tag, header included."""
    if len(raw) < 10 or raw[:3] != b"ID3":
        return {}
    size = _synchsafe(raw[6:10])
    if size <= 0 or size > _MAX_TAG:
        return {}
    try:
        return _parse_frames(raw[10 : 10 + size], raw[3])
    except (struct.error, ValueError):
        return {}


def _synchsafe(raw: bytes) -> int:
    """ID3 sizes use seven bits per byte so they cannot look like a sync word."""
    value = 0
    for byte in raw:
        value = value << 7 | (byte & 0x7F)
    return value


def _parse_frames(body: bytes, major: int) -> dict[str, str]:
    found: dict[str, str] = {}
    offset = 0
    identifier_size, header_size = (3, 6) if major == 2 else (4, 10)

    for _ in range(_MAX_FRAMES):
        if offset + header_size > len(body):
            break
        identifier = body[offset : offset + identifier_size]
        if not identifier.strip(b"\x00"):
            break

        if major == 2:
            size = int.from_bytes(body[offset + 3 : offset + 6], "big")
        elif major == 4:
            size = _synchsafe(body[offset + 4 : offset + 8])
        else:
            (size,) = struct.unpack_from(">I", body, offset + 4)

        payload = body[offset + header_size : offset + header_size + size]
        offset += header_size + size
        if size <= 0 or offset > len(body):
            break

        meaning = FRAMES.get(identifier)
        if meaning and meaning not in found:
            text = _decode(payload)
            if text:
                found[meaning] = text

    return found


def _decode(payload: bytes) -> str | None:
    """A text frame opens with a byte naming its encoding."""
    if not payload:
        return None
    encodings = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}
    encoding = encodings.get(payload[0], "latin-1")
    try:
        text = payload[1:].decode(encoding, "replace")
    except (LookupError, ValueError):
        return None
    return text.strip().strip("\x00").strip() or None
