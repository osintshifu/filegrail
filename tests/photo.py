"""A minimal JPEG carrying real EXIF, for tests that need one.

Shared rather than copied, so the one place that knows how an Exif APP1 segment
is laid out stays one place. Every offset is computed from the structure, never
counted by hand.
"""

from __future__ import annotations

import struct
from pathlib import Path


def jpeg_with_exif(path: Path, make: str, model: str, taken: str) -> None:
    """Build a minimal JPEG carrying an Exif APP1 segment with three ASCII tags."""
    entries = [(0x010F, make), (0x0110, model), (0x0132, taken)]

    header = b"MM\x00\x2a" + struct.pack(">I", 8)
    values = b""
    value_base = 8 + 2 + len(entries) * 12 + 4
    directory = struct.pack(">H", len(entries))
    for tag, text in entries:
        raw = text.encode("ascii") + b"\x00"
        directory += struct.pack(">HHI", tag, 2, len(raw))
        directory += struct.pack(">I", value_base + len(values))
        values += raw
    tiff = header + directory + struct.pack(">I", 0) + values

    app1 = b"Exif\x00\x00" + tiff
    path.write_bytes(
        b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + b"\xff\xd9"
    )


def ifd(entries: list[tuple[int, int, bytes]], endian: str, value_base: int) -> tuple[bytes, bytes]:
    """Encode one IFD and the value block that follows it.

    `entries` are `(tag, type, encoded value)`. A value of four bytes or fewer
    is inlined the way TIFF requires; anything longer is appended to the value
    block and addressed from `value_base`, which is where that block will sit
    once the caller has placed it. Returning both halves separately is what
    lets the caller decide, because a maker note counts its offsets from its
    own first byte while an ordinary directory counts them from the TIFF header.
    """
    counts = {1: 1, 2: 1, 3: 2, 4: 4, 7: 1, 13: 4}
    directory = struct.pack(endian + "H", len(entries))
    values = b""
    for tag, kind, raw in entries:
        count = len(raw) // counts[kind]
        directory += struct.pack(endian + "HHI", tag, kind, count)
        if len(raw) <= 4:
            directory += raw.ljust(4, b"\x00")
        else:
            directory += struct.pack(endian + "I", value_base + len(values))
            values += raw
    return directory + struct.pack(endian + "I", 0), values


def jpeg_with_maker_note(path: Path, make: str, model: str, note: bytes) -> None:
    """Build a JPEG whose Exif IFD carries `note` verbatim as tag 0x927C.

    The note is written byte for byte, so a test can hand this a real vendor
    layout and know that nothing between it and the parser rewrote it.
    """
    endian = ">"
    header = b"MM\x00\x2a" + struct.pack(endian + "I", 8)

    # The Exif IFD is laid out first because IFD0 has to point at it, and its
    # own position depends on how long IFD0 turns out to be.
    zeroth_entries = [(0x010F, 2, make.encode() + b"\x00"), (0x0110, 2, model.encode() + b"\x00")]
    zeroth_size = 2 + (len(zeroth_entries) + 1) * 12 + 4
    zeroth_values_at = 8 + zeroth_size
    zeroth_values_len = sum(len(raw) for _tag, _kind, raw in zeroth_entries if len(raw) > 4)
    exif_ifd_at = zeroth_values_at + zeroth_values_len

    exif_size = 2 + 1 * 12 + 4
    exif_directory, exif_values = ifd(
        [(0x927C, 7, note)], endian, value_base=exif_ifd_at + exif_size
    )

    zeroth_directory, zeroth_values = ifd(
        [*zeroth_entries, (0x8769, 4, struct.pack(endian + "I", exif_ifd_at))],
        endian,
        value_base=zeroth_values_at,
    )
    tiff = header + zeroth_directory + zeroth_values + exif_directory + exif_values

    app1 = b"Exif\x00\x00" + tiff
    path.write_bytes(
        b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + b"\xff\xd9"
    )
