"""APEv2 tags, as Monkey's Audio, Musepack, WavPack and OptimFROG carry them.

The tag sits at the end of the file behind a 32-byte footer that names it,
which is why a reader that only looks at the front of a file never sees one.
Every item is a key and a value; the keys are whatever the writer chose, and
the ones that matter here name the encoder, the artist and the year.

An ID3v1 tag may sit after the footer. It is stepped over, not read: a 128-byte
block of fixed fields says nothing an APE item does not say better.
"""

from __future__ import annotations

import struct
from pathlib import Path

SUFFIXES = {".ape", ".mpc", ".wv", ".ofr"}

_PREAMBLE = b"APETAGEX"
_FOOTER = 32
_ID3V1 = 128
_MAX_TAG = 16 * 1024 * 1024
_MAX_ITEMS = 64
_MAX_KEY = 255
_MAX_VALUE = 4096

#: Item flags: bit 0 says the item has no footer/header relation worth
#: reading here; bits 1-2 give the value's type, and only text is decoded.
_TYPE_MASK = 0x06
_TYPE_TEXT = 0x00


def read_ape(path: Path) -> dict[str, str]:
    """Return the text items of an APEv2 tag at the end of the file."""
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, 2)
            for tail in (_FOOTER, _FOOTER + _ID3V1):
                if size < tail:
                    continue
                handle.seek(size - tail)
                footer = handle.read(_FOOTER)
                if footer[:8] != _PREAMBLE:
                    continue
                version, tag_size, count, _ = struct.unpack_from("<IIII", footer, 8)
                if version < 2000 or tag_size < _FOOTER or tag_size > _MAX_TAG:
                    return {}
                start = size - tail - (tag_size - _FOOTER)
                if start < 0:
                    return {}
                handle.seek(start)
                return _items(handle.read(tag_size - _FOOTER), count)
    except (OSError, struct.error, ValueError):
        return {}
    return {}


def _items(data: bytes, count: int) -> dict[str, str]:
    found: dict[str, str] = {}
    at = 0
    for _ in range(min(count, _MAX_ITEMS)):
        if at + 8 > len(data):
            break
        length, flags = struct.unpack_from("<II", data, at)
        at += 8
        stop = data.find(b"\x00", at)
        if stop < 0 or stop - at > _MAX_KEY:
            break
        key = data[at:stop].decode("ascii", "replace")
        at = stop + 1
        if at + length > len(data):
            break
        if flags & _TYPE_MASK == _TYPE_TEXT:
            value = data[at : at + min(length, _MAX_VALUE)].decode("utf-8", "replace")
            value = " ".join(value.replace("\x00", " / ").split())
            if key and value and key not in found:
                found[key] = value
        at += length
    return found
