"""Bounded binary previews carried inside evidence files."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EmbeddedPreview:
    """One validated raster preview, kept outside serialised evidence fields."""

    source: str
    mime: str
    data: bytes
    width: int | None = None
    height: int | None = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """Read JPEG dimensions from a bounded marker walk without decoding pixels."""
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    cursor = 2
    while cursor + 4 <= len(data):
        if data[cursor] != 0xFF:
            return None
        while cursor < len(data) and data[cursor] == 0xFF:
            cursor += 1
        if cursor >= len(data):
            return None
        marker = data[cursor]
        cursor += 1
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        if cursor + 2 > len(data):
            return None
        length = struct.unpack_from(">H", data, cursor)[0]
        if length < 2 or cursor + length > len(data):
            return None
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            if length < 7:
                return None
            height, width = struct.unpack_from(">HH", data, cursor + 3)
            return (width, height) if width and height else None
        if marker == 0xDA:
            return None
        cursor += length
    return None
