"""Maker notes, where the serial number of a camera body usually lives.

Standard EXIF has a place for a body serial and most cameras leave it empty,
writing it into the vendor block instead. The same block carries the shutter
count, which is the closest thing a photograph has to an odometer reading. Both
are worth the awkwardness of a format every vendor invented separately.
"""

from __future__ import annotations

import struct
from pathlib import Path

from filegrail.sources.embedded.exif import read_exif

from .photo import ifd, jpeg_with_maker_note


def nikon_note(serial: str, shutter: int) -> bytes:
    """A Nikon type-3 note: a signature, then a TIFF of its own.

    Offsets inside count from the first byte of the note rather than from the
    file's TIFF header, which is the detail that breaks a parser written for
    Canon and pointed at a Nikon.
    """
    preamble = b"Nikon\x00\x02\x10\x00\x00"
    # Offsets are counted from the inner TIFF header, which starts after the
    # preamble, so the value block is addressed in that space and not in the
    # note's. Getting this wrong is the whole reason Nikon needs its own path.
    inner_header = b"II\x2a\x00" + struct.pack("<I", 8)
    directory, values = ifd(
        [(0x001D, 2, serial.encode() + b"\x00"), (0x00A7, 4, struct.pack("<I", shutter))],
        "<",
        value_base=len(inner_header) + 2 + 2 * 12 + 4,
    )
    return preamble + inner_header + directory + values


def canon_note(endian: str, serial: int, file_number: int) -> bytes:
    """Canon writes a bare directory, with no signature and no header.

    Only values that fit in four bytes are used here, because anything longer
    is addressed in the file's own TIFF space and a fixture cannot know where
    the note will land until after it has been built.
    """
    directory, _values = ifd(
        [
            (0x0008, 4, struct.pack(endian + "I", file_number)),
            (0x000C, 4, struct.pack(endian + "I", serial)),
        ],
        endian,
        value_base=0,
    )
    return directory


def test_nikon_notes_name_the_body_and_its_shutter_count(tmp_path: Path):
    path = tmp_path / "nikon.jpg"
    jpeg_with_maker_note(path, "NIKON CORPORATION", "NIKON D300", nikon_note("3105364", 241575))

    tags = read_exif(path)

    assert tags is not None
    assert tags.maker is not None
    assert tags.maker.vendor == "Nikon"
    assert tags.maker.fields["SerialNumber"] == "3105364"
    assert tags.maker.fields["ShutterCount"] == "241575"


def test_a_note_written_in_the_other_byte_order_is_read_and_reported(tmp_path: Path):
    """A note that disagrees with its container was not written by the camera.

    The body writes both in one byte order. A note in the opposite order means
    something rewrote the TIFF around it and copied the block through
    untouched, which is worth saying out loud rather than silently repairing.
    """
    path = tmp_path / "canon.jpg"
    # The fixture's container is big-endian; this note is little-endian.
    jpeg_with_maker_note(path, "Canon", "Canon EOS 40D", canon_note("<", 1230405678, 1242489))

    tags = read_exif(path)

    assert tags is not None and tags.maker is not None
    assert tags.maker.vendor == "Canon"
    assert tags.maker.byte_order == "opposite to the container"
    assert tags.maker.fields["SerialNumber"] == "1230405678"
    assert tags.maker.fields["FileNumber"] == "124-2489"


def test_an_unreadable_note_is_counted_rather_than_invented(tmp_path: Path):
    """Garbage in the block must not become fields, and must not stop the scan."""
    path = tmp_path / "broken.jpg"
    jpeg_with_maker_note(path, "Pentax", "Pentax K-3", b"\xff" * 64)

    tags = read_exif(path)

    assert tags is not None and tags.maker is not None
    assert tags.maker.vendor == "Pentax"
    assert tags.maker.entries == 0
    assert tags.maker.fields == {}
    assert tags.maker.size == 64


def test_offsets_are_dropped_when_the_byte_order_disagrees():
    """A rewritten container leaves the note's offsets addressing the old file.

    A value short enough to sit inside its own entry survives the rewrite. One
    addressed by an offset does not: the bytes it points at now belong to
    whatever the rewrite put there. Reading them produces a field that looks
    like evidence and is not, so those entries are dropped instead.
    """
    from filegrail.sources.embedded import makernotes

    # A little-endian note inside a big-endian container. `SerialNumber` is
    # inline; `OwnerName` is addressed, and the offset is made to land on real
    # bytes inside the file so that the reader has every chance to use them.
    entries = [(0x000C, 4, struct.pack("<I", 4242)), (0x0009, 2, b"Not really the owner\x00")]
    note_at = 8
    note_length = 2 + len(entries) * 12 + 4
    note, values = ifd(entries, "<", value_base=note_at + note_length)
    tiff = b"MM\x00\x2a" + struct.pack(">I", note_at) + note + values
    assert len(note) == note_length
    assert b"Not really the owner" in tiff

    notes = makernotes.read(tiff, note_at, note_length, ">", "Canon")

    assert notes is not None
    assert notes.byte_order == "opposite to the container"
    assert notes.fields == {"SerialNumber": "4242"}
