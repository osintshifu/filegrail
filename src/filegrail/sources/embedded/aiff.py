"""AIFF and AIFF-C: the Macintosh cousin of WAV.

The same idea as RIFF with the byte order reversed: a `FORM` holding chunks.
Four of them carry text an author or a tool wrote - `NAME`, `AUTH`, `(c) ` and
`ANNO` - and an `ID3 ` chunk holds the tag MP3 made familiar, exactly as WAV
keeps one in `id3 `. `COMM` says what the sound is: channels, rate and, in an
AIFF-C, the compression it was stored with.

The walk seeks over sound data instead of reading it.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from . import id3

SUFFIXES = {".aif", ".aiff", ".aifc"}

_FORM = b"FORM"
_KINDS = (b"AIFF", b"AIFC")
_MAX_CHUNKS = 1024
_MAX_PAYLOAD = 2 * 1024 * 1024
_MAX_TEXT = 4096
_MAX_ANNOTATIONS = 8

TEXT_CHUNKS = {b"NAME": "Name", b"AUTH": "Author", b"(c) ": "Copyright", b"ANNO": "Annotation"}


@dataclass(slots=True)
class Aiff:
    """What an AIFF says about its own making."""

    #: The text chunks, under the names above; a repeated annotation is numbered.
    info: dict[str, str] = field(default_factory=dict)

    #: Frames from an embedded ID3 tag, keyed by meaning as the tag reader
    #: returns them.
    frames: dict[str, str] = field(default_factory=dict)

    #: The `COMM` chunk, where one was read.
    sound: dict[str, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.info or self.frames or self.sound)


def read_aiff(path: Path) -> Aiff | None:
    try:
        with path.open("rb") as handle:
            head = handle.read(12)
            if len(head) < 12 or head[:4] != _FORM or head[8:12] not in _KINDS:
                return None
            (declared,) = struct.unpack(">I", head[4:8])
            end = min(12 + declared - 4, handle.seek(0, 2)) if declared >= 4 else 12
            found = Aiff()
            _walk(handle, 12, end, found)
    except (OSError, struct.error, ValueError):
        return None
    return found if found else None


def _walk(handle: BinaryIO, offset: int, end: int, found: Aiff) -> None:
    annotations = 0
    for _ in range(_MAX_CHUNKS):
        if offset + 8 > end:
            return
        handle.seek(offset)
        header = handle.read(8)
        if len(header) < 8:
            return
        chunk_id, size = struct.unpack(">4sI", header)
        body = offset + 8
        if body + size > end:
            size = end - body  # a truncated last chunk is still readable
        if chunk_id in TEXT_CHUNKS and size <= _MAX_PAYLOAD:
            text = _text(handle.read(min(size, _MAX_TEXT)))
            name = TEXT_CHUNKS[chunk_id]
            if chunk_id == b"ANNO":
                annotations += 1
                if annotations > _MAX_ANNOTATIONS:
                    text = None
                elif annotations > 1:
                    name = f"{name}[{annotations}]"
            if text:
                found.info.setdefault(name, text)
        elif chunk_id == b"ID3 " and size <= _MAX_PAYLOAD:
            found.frames = id3.read_tag(handle.read(size)) or found.frames
        elif chunk_id == b"COMM" and 18 <= size <= _MAX_PAYLOAD:
            found.sound = _comm(handle.read(min(size, 256)))
        offset = body + size + (size & 1)


def _comm(data: bytes) -> dict[str, str]:
    channels, frames, bits = struct.unpack_from(">hIh", data, 0)
    rate = _extended(data[8:18])
    sound = {"Channels": str(channels), "SampleSize": f"{bits} bit"}
    if rate:
        sound["SampleRate"] = f"{rate:g} Hz"
    if frames and rate:
        sound["Duration"] = f"{frames / rate:.1f} s"
    if len(data) >= 23:  # AIFF-C: a compression type and a Pascal string name
        kind = data[18:22].decode("ascii", "replace").strip()
        length = data[22]
        name = data[23 : 23 + length].decode("mac_roman", "replace").strip()
        sound["Compression"] = f"{name} ({kind})" if name and name != kind else kind
    return sound


def _extended(raw: bytes) -> float | None:
    """An 80-bit IEEE 754 extended float, which is how AIFF writes a rate."""
    if len(raw) < 10:
        return None
    sign_exponent = int(struct.unpack(">H", raw[:2])[0])
    mantissa = int(struct.unpack(">Q", raw[2:10])[0])
    exponent = sign_exponent & 0x7FFF
    if exponent == 0 and mantissa == 0:
        return None
    if exponent == 0x7FFF:
        return None  # infinity or not a number
    value = float(mantissa) * 2.0 ** (exponent - 16383 - 63)
    return -value if sign_exponent & 0x8000 else value


def _text(raw: bytes) -> str | None:
    text = raw.decode("utf-8", "replace") if _is_utf8(raw) else raw.decode("mac_roman", "replace")
    text = " ".join(text.replace("\x00", " ").split())
    return text[:_MAX_TEXT] or None


def _is_utf8(raw: bytes) -> bool:
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True
