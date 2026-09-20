"""Vendor maker notes, read for the few fields that say where a file came from.

Standard EXIF reserves a tag for the body serial number and most cameras leave
it empty, writing it into this block instead. Beside it sits the shutter count,
which is the nearest thing a photograph carries to an odometer reading, and the
name the owner typed into the camera once and forgot.

Every vendor invented this block separately, so there is no format here, only a
handful of conventions. Three of them differ in the one thing a parser cannot
guess: what the offsets inside are counted from. Canon counts from the start of
the file's TIFF header, Fujifilm from the first byte of the note, and Nikon
gives the note a TIFF header of its own and counts from that. Point a reader
written for one at another and it walks into unrelated bytes, which is why the
scheme is decided from the signature before a single entry is read.

Only fields with evidential weight are named. Sharpening, white balance and
scene mode describe the picture; this tool is about where the picture came
from. Everything else is counted and left alone rather than guessed at.
"""

from __future__ import annotations

import mmap
import struct
from dataclasses import dataclass, field

from ...preview import EmbeddedPreview, jpeg_dimensions

Raw = bytes | mmap.mmap

_MAX_ENTRIES = 256
_MAX_VALUE = 4096
_MAX_NOTE = 1024 * 1024

_BYTE = 1
_ASCII = 2
_SHORT = 3
_LONG = 4
_UNDEFINED = 7
_WIDTHS = {_BYTE: 1, _ASCII: 1, _SHORT: 2, _LONG: 4, 5: 8, 6: 1, _UNDEFINED: 1, 9: 4, 10: 8}

#: Where the offsets inside a note are counted from, named the way the report
#: prints it. A reader that gets this wrong still parses, which is why it is
#: reported rather than assumed.
TIFF_RELATIVE = "offsets from the TIFF header"
NOTE_RELATIVE = "offsets from the start of the note"
NIKON_TIFF = "own TIFF header inside the note"
IMAGE_ONLY = "an image rather than a directory"

#: Canon. The serial is a plain integer the body stamps on every frame; the
#: owner name is typed in once by a person. `FileNumber` counts frames within a
#: folder and rolls over, so it dates a frame within a card rather than a body.
_CANON = {
    0x0007: ("FirmwareVersion", "text"),
    0x0008: ("FileNumber", "file-number"),
    0x0009: ("OwnerName", "text"),
    0x000C: ("SerialNumber", "number"),
    0x0095: ("LensModel", "text"),
    0x0096: ("InternalSerialNumber", "text"),
}

#: Makes whose own name is two words. Taking the first word alone would file
#: every Konica Minolta under Konica, and the vendor is what a reader groups by.
_TWO_WORD_MAKES = ("Konica Minolta", "Eastman Kodak", "Hewlett Packard")

#: Apple. Both identifiers are UUIDs the phone assigns, and neither appears in
#: standard EXIF. `ContentIdentifier` is the more interesting of the two: the
#: still and the short film of a Live Photo carry the same one, so it is what
#: says two files are one exposure.
_APPLE = {
    0x0020: ("ImageUniqueID", "text"),
    0x002B: ("ContentIdentifier", "text"),
}

#: Panasonic. The serial is stamped by the factory and encodes the body's build
#: date, which is why it is longer than a counter. The field it sits in is wider
#: than the text and the camera pads the front of it rather than the end.
_PANASONIC = {
    0x0025: ("InternalSerialNumber", "text"),
}

#: A signature, where the directory begins after it, whose space its offsets
#: are counted in, and the fields worth naming. Every row is confirmed against
#: a photograph from a camera that writes it.
_SIGNATURES: tuple[tuple[bytes, int, str, dict[int, tuple[str, str]]], ...] = (
    (b"Apple iOS\x00", 14, NOTE_RELATIVE, _APPLE),
    (b"OLYMPUS\x00II", 12, NOTE_RELATIVE, {}),
    (b"OLYMP\x00", 8, TIFF_RELATIVE, {}),
    (b"Panasonic\x00", 12, TIFF_RELATIVE, _PANASONIC),
    (b"Nikon\x00\x01", 8, TIFF_RELATIVE, {}),
)

#: What the note's byte order says. A camera writes the note in the same order
#: as the file around it, so a disagreement means the file was rewritten by
#: something that copied the block through without re-encoding it.
SAME_ORDER = "same as the container"
OPPOSITE_ORDER = "opposite to the container"

#: Nikon. Both serial tags are read because which one a body writes depends on
#: its generation, and a body that writes neither is common among compacts.
_NIKON = {
    0x001D: ("SerialNumber", "text"),
    0x00A0: ("SerialNumber", "text"),
    0x00A7: ("ShutterCount", "number"),
    0x0083: ("LensType", "number"),
    0x0093: ("ImageAdjustment", "text"),
}


@dataclass(frozen=True, slots=True)
class MakerNotes:
    """One vendor block: who wrote it, how it is laid out, what it named."""

    vendor: str
    scheme: str
    entries: int
    size: int
    fields: dict[str, str] = field(default_factory=dict)
    byte_order: str = SAME_ORDER

    #: A picture carried in the block itself, where the vendor put one there
    #: instead of a directory. Frequently larger than the EXIF thumbnail, and
    #: kept out of the serialised fields the same way every other preview is.
    preview: EmbeddedPreview | None = None


def read(data: Raw, at: int, size: int, endian: str, make: str | None) -> MakerNotes | None:
    """Decode the maker note lying at `at` inside the TIFF block `data`."""
    if at <= 0 or size <= 0 or size > _MAX_NOTE or at + size > len(data):
        return None
    note = bytes(data[at : at + size])
    if len(note) < 8:
        return None

    if note.startswith(b"Nikon\x00") and len(note) > 18 and note[6] == 2:
        return _nikon(note)
    if note.startswith(b"FUJIFILM"):
        return _fujifilm(note)

    vendor = _vendor(make)
    for signature, skip, scheme, table in _SIGNATURES:
        if note.startswith(signature):
            return _signed(vendor, note, data, at, size, skip, scheme, table, endian)
    if note.startswith(b"\xff\xd8\xff"):
        # Not a directory at all. A few compacts write a whole JPEG here, and
        # it is usually several times the size of the EXIF thumbnail.
        return MakerNotes(vendor, IMAGE_ONLY, 0, size, preview=_image(note))
    # Canon writes the directory at the first byte and addresses its values in
    # the file's own TIFF space, so the whole block has to stay in reach. Every
    # other vendor without a signature is tried the same way: a directory is
    # what is almost always there, and one that does not decode reads as none.
    order = _byte_order(data, at, endian, len(data))
    if order is None:
        return MakerNotes(vendor, TIFF_RELATIVE, 0, size)
    note_endian, byte_order = order
    entries = _entries(
        data,
        at,
        note_endian,
        base=0,
        limit=len(data),
        # An offset inside a note whose byte order was not rewritten addresses
        # the file as it stood before the rewrite. Whatever lies there now is
        # not the value, so only what fits inside an entry is believed.
        trust_offsets=byte_order == SAME_ORDER,
    )
    table = _CANON if vendor == "Canon" else {}
    return _notes(vendor, TIFF_RELATIVE, entries, size, table, note_endian, byte_order)


def _signed(
    vendor: str,
    note: bytes,
    data: Raw,
    at: int,
    size: int,
    skip: int,
    scheme: str,
    table: dict[int, tuple[str, str]],
    endian: str,
) -> MakerNotes:
    """Read a note whose signature says where its directory is.

    A note-relative layout carries its own byte-order mark in the two bytes
    before the directory, because the vendor does not promise to match the file
    around it. A TIFF-relative one has no mark and no choice: its offsets only
    mean anything in the container's order.
    """
    if scheme == NOTE_RELATIVE:
        mark = note[skip - 2 : skip]
        inner = "<" if mark == b"II" else ">" if mark == b"MM" else endian
        entries = _entries(note, skip, inner, base=0, limit=len(note))
        return _notes(vendor, scheme, entries, size, table, inner)
    entries = _entries(data, at + skip, endian, base=0, limit=len(data))
    return _notes(vendor, scheme, entries, size, table, endian)


def _nikon(note: bytes) -> MakerNotes | None:
    """`Nikon\\0` version 2: a ten-byte preamble, then a TIFF of its own."""
    inner = note[10:]
    if inner[:2] == b"II":
        endian = "<"
    elif inner[:2] == b"MM":
        endian = ">"
    else:
        return None
    (first,) = struct.unpack_from(endian + "I", inner, 4)
    entries = _entries(inner, first, endian, base=0, limit=len(inner))
    return _notes("Nikon", NIKON_TIFF, entries, len(note), _NIKON, endian)


def _fujifilm(note: bytes) -> MakerNotes | None:
    """`FUJIFILM`, a pointer, and a directory addressed from the note itself."""
    (first,) = struct.unpack_from("<I", note, 8)
    entries = _entries(note, first, "<", base=0, limit=len(note))
    return _notes("Fujifilm", NOTE_RELATIVE, entries, len(note), {}, "<")


def _image(note: bytes) -> EmbeddedPreview | None:
    """The JPEG a note consists of, trimmed to its own end marker.

    The declared length of the block is rounded up by some writers, so the
    trailing padding is dropped rather than carried into the preview. A JPEG
    with no end marker is not returned at all: an image this reader cannot see
    the end of is one it cannot say it read.
    """
    end = note.rfind(b"\xff\xd9")
    if end < 0:
        return None
    data = note[: end + 2]
    size = jpeg_dimensions(data)
    if size is None:
        return None
    return EmbeddedPreview("maker note", "image/jpeg", data, size[0], size[1])


def _byte_order(data: Raw, at: int, endian: str, limit: int) -> tuple[str, str] | None:
    """Decide which byte order the directory at `at` is written in.

    A directory read in the wrong order gives an entry count in the thousands
    and offsets that point nowhere, so the count is the test. The container's
    order is tried first: reading a valid note the wrong way round is not
    possible, but reading noise as a plausible count is, and the camera's own
    order is the answer that does not need explaining.
    """
    for candidate, verdict in (
        (endian, SAME_ORDER),
        ("<" if endian == ">" else ">", OPPOSITE_ORDER),
    ):
        if at + 2 > limit:
            return None
        try:
            (count,) = struct.unpack_from(candidate + "H", data, at)
        except struct.error:
            return None
        if 0 < count <= _MAX_ENTRIES and at + 2 + count * 12 <= limit:
            return candidate, verdict
    return None


def _vendor(make: str | None) -> str:
    """The make, as a vendor a reader can group by."""
    if not make or not make.strip():
        return "unknown"
    cleaned = " ".join(make.split())
    for known in _TWO_WORD_MAKES:
        if cleaned.upper().startswith(known.upper()):
            return known
    first = cleaned.split()[0]
    return first.title() if first.isalpha() else first


def _notes(
    vendor: str,
    scheme: str,
    entries: dict[int, tuple[int, bytes]],
    size: int,
    table: dict[int, tuple[str, str]],
    endian: str,
    byte_order: str = SAME_ORDER,
) -> MakerNotes:
    fields: dict[str, str] = {}
    for tag, (kind, raw) in entries.items():
        named = table.get(tag)
        if named is None:
            continue
        label, shape = named
        if shape == "text":
            value = _text(raw)
        elif shape == "file-number":
            value = _file_number(raw, kind, endian)
        else:
            value = _number(raw, kind, endian)
        if value and label not in fields:
            fields[label] = value
    return MakerNotes(vendor, scheme, len(entries), size, fields, byte_order)


def _entries(
    data: Raw, offset: int, endian: str, base: int, limit: int, trust_offsets: bool = True
) -> dict[int, tuple[int, bytes]]:
    """Walk one directory, returning each entry's type and its raw bytes."""
    if offset <= 0 or offset + 2 > limit:
        return {}
    try:
        (count,) = struct.unpack_from(endian + "H", data, offset)
    except struct.error:
        return {}
    if count == 0 or count > _MAX_ENTRIES or offset + 2 + count * 12 > limit:
        return {}

    found: dict[int, tuple[int, bytes]] = {}
    for index in range(count):
        entry = offset + 2 + index * 12
        try:
            tag, kind, length = struct.unpack_from(endian + "HHI", data, entry)
        except struct.error:
            break
        width = _WIDTHS.get(kind)
        if width is None or length == 0:
            continue
        size = width * length
        if size > _MAX_VALUE:
            continue
        if size <= 4:
            found[tag] = (kind, bytes(data[entry + 8 : entry + 8 + size]))
            continue
        if not trust_offsets:
            continue
        (at,) = struct.unpack_from(endian + "I", data, entry + 8)
        at += base
        if at <= 0 or at + size > limit:
            continue
        found[tag] = (kind, bytes(data[at : at + size]))
    return found


def _text(raw: bytes) -> str | None:
    """The text in a field, whichever end the vendor padded.

    A field is declared wider than the string it holds and the padding is
    conventionally at the end. Panasonic puts it at the front, so stopping at
    the first null byte returns nothing for the one field that names the body.
    """
    value = raw.strip(b"\x00").split(b"\x00")[0].decode("utf-8", "replace").strip()
    return value if value and value.isprintable() else None


def _file_number(raw: bytes, kind: int, endian: str) -> str | None:
    """Canon's frame counter, as the camera's own folder and frame.

    The value packs a directory number and a frame number into one integer:
    `1242489` is frame 2489 in folder 124, which is how the card itself names
    the file. Printed as one number it reads as a serial, which it is not.
    """
    value = _number(raw, kind, endian)
    if value is None or not value.isdigit() or len(value) < 5:
        return value
    return f"{value[:-4]}-{value[-4:]}"


def _number(raw: bytes, kind: int, endian: str) -> str | None:
    code = {_BYTE: "B", _SHORT: "H", _LONG: "I"}.get(kind)
    if code is None or len(raw) < struct.calcsize(code):
        return _text(raw)
    (value,) = struct.unpack_from(endian + code, raw, 0)
    return str(value)
