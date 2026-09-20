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
_SUBDIRECTORY = 13

#: Every field type TIFF defines, by how many bytes one of them takes. The
#: signed and floating ones are here because a type this table has no width for
#: loses its entry without saying so, and the note then reads as smaller than
#: the camera wrote it.
_WIDTHS = {
    _BYTE: 1,
    _ASCII: 1,
    _SHORT: 2,
    _LONG: 4,
    5: 8,  # RATIONAL
    6: 1,  # SBYTE
    _UNDEFINED: 1,
    8: 2,  # SSHORT
    9: 4,  # SLONG
    10: 8,  # SRATIONAL
    11: 4,  # FLOAT
    12: 8,  # DOUBLE
    _SUBDIRECTORY: 4,
}

#: Where the offsets inside a note are counted from, named the way the report
#: prints it. A reader that gets this wrong still parses, which is why it is
#: reported rather than assumed.
TIFF_RELATIVE = "offsets from the TIFF header"
NOTE_RELATIVE = "offsets from the start of the note"
NIKON_TIFF = "own TIFF header inside the note"
IMAGE_ONLY = "an image rather than a directory"
FIXED_STRUCTURE = "a fixed structure rather than a directory"

#: Reconyx trail cameras write a structure instead of a directory: every field
#: at a known sixteen-bit word, no tags and no offsets, and the version number
#: it opens with is the only thing to recognise it by. These files carry no make
#: of their own, so what the camera says about itself it says only here.
_RECONYX_VERSION = 0xF101
_RECONYX_LABEL = 0x2B
_RECONYX_LENGTH = _RECONYX_LABEL * 2 + 44
_RECONYX_SERIAL = 0x15
_RECONYX_MOMENT = 0x0B

#: What made the camera take the picture, which for a camera left in a wood is
#: the difference between something walking past and a clock going off.
_RECONYX_TRIGGER = {"T": "time lapse", "M": "motion detection", "P": "point and shoot"}

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

#: Konica Minolta. The body writes a full preview among the image data and only
#: a pointer to it here, which is the pair below. Nothing else in the block
#: identifies the camera, and the two tags are one fact rather than two fields.
_MINOLTA_PREVIEW_AT = 0x0088
_MINOLTA_PREVIEW_LENGTH = 0x0089

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

#: Olympus. Nothing in the note's own directory identifies anything. The body
#: serial, the lens serial and the lens model are one directory down, in the
#: block the vendor calls Equipment. The lens serial is worth as much as the
#: body's and sometimes more, because a lens is sold on and photographed with
#: again under a different owner.
_OLYMPUS_EQUIPMENT = {
    0x0101: ("SerialNumber", "text"),
    0x0102: ("InternalSerialNumber", "text"),
    0x0202: ("LensSerialNumber", "text"),
    0x0203: ("LensModel", "text"),
}
_OLYMPUS_SUBDIRECTORIES = {0x2010: _OLYMPUS_EQUIPMENT}

#: Panasonic. The serial is stamped by the factory and encodes the body's build
#: date, which is why it is longer than a counter. The field it sits in is wider
#: than the text and the camera pads the front of it rather than the end.
_PANASONIC = {
    0x0025: ("InternalSerialNumber", "text"),
}


@dataclass(frozen=True, slots=True)
class _Layout:
    """How one vendor's signed note is put together.

    `directory` and `mark` are counted from the note's first byte. A note whose
    offsets are its own carries a byte-order mark, because the vendor does not
    promise to match the file around it; where that mark sits differs by vendor
    and one of them keeps it inside the signature itself.
    """

    signature: bytes
    directory: int
    scheme: str
    fields: dict[int, tuple[str, str]] = field(default_factory=dict)
    mark: int | None = None
    subdirectories: dict[int, dict[int, tuple[str, str]]] = field(default_factory=dict)


#: Every row is confirmed against a photograph from a camera that writes it.
_SIGNATURES: tuple[_Layout, ...] = (
    _Layout(b"Apple iOS\x00", 14, NOTE_RELATIVE, _APPLE, mark=12),
    _Layout(
        b"OLYMPUS\x00II",
        12,
        NOTE_RELATIVE,
        mark=8,
        subdirectories=_OLYMPUS_SUBDIRECTORIES,
    ),
    _Layout(b"OLYMP\x00", 8, TIFF_RELATIVE),
    _Layout(b"Panasonic\x00", 12, TIFF_RELATIVE, _PANASONIC),
    _Layout(b"Nikon\x00\x01", 8, TIFF_RELATIVE),
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
class _Directory:
    """One directory as found: what it said it held, and what came out of it.

    Two unrelated things stop an entry becoming a field, and a reader told only
    how many were lost cannot tell which happened. `undecoded` is this reader's
    own limit: a type it has no width for, a block too large to be a field, an
    offset resolving outside the data. It says nothing about the file.

    `distrusted` is a refusal. The note's byte order disagrees with the file
    around it, so the block was moved after the camera wrote it and the offsets
    inside address a layout that is gone. Whatever lies at them now belongs to
    the rewrite, and reading it would turn somebody else's bytes into a camera
    field. That one says a great deal about the file.
    """

    declared: int
    values: dict[int, tuple[int, bytes]] = field(default_factory=dict)
    undecoded: int = 0
    distrusted: int = 0


@dataclass(frozen=True, slots=True)
class MakerNotes:
    """One vendor block: who wrote it, how it is laid out, what it named."""

    vendor: str
    scheme: str
    entries: int
    size: int
    fields: dict[str, str] = field(default_factory=dict)
    byte_order: str = SAME_ORDER

    #: Entries this reader could not read, and entries it would not: its own
    #: limits against a block that was moved after it was written. Reported
    #: apart because only the second is evidence about the file.
    undecoded: int = 0
    distrusted: int = 0

    #: A picture carried in the block itself, where the vendor put one there
    #: instead of a directory. Frequently larger than the EXIF thumbnail, and
    #: kept out of the serialised fields the same way every other preview is.
    preview: EmbeddedPreview | None = None

    #: A preview the note points at rather than carries, as its offset from the
    #: TIFF header and its length. The bytes are elsewhere in the file, or were:
    #: a file re-saved smaller keeps the pointer and loses the picture.
    declared_preview: tuple[int, int] | None = None


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
    if len(note) >= _RECONYX_LENGTH and _word(note, 0) == _RECONYX_VERSION:
        return _reconyx(note)

    vendor = _vendor(make)
    for layout in _SIGNATURES:
        if note.startswith(layout.signature):
            return _signed(vendor, note, data, at, size, layout, endian)
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
    return _notes(
        vendor,
        TIFF_RELATIVE,
        entries,
        size,
        _CANON if vendor == "Canon" else {},
        note_endian,
        byte_order,
        declared=_declared_preview(entries, note_endian),
    )


def _declared_preview(directory: _Directory, endian: str) -> tuple[int, int] | None:
    """The preview a note points at, as an offset from the TIFF header.

    Both halves have to be there for the pointer to mean anything, and a length
    of zero is how a body that took no preview says so.
    """
    at = directory.values.get(_MINOLTA_PREVIEW_AT)
    length = directory.values.get(_MINOLTA_PREVIEW_LENGTH)
    if at is None or length is None:
        return None
    offset = _number(at[1], at[0], endian)
    size = _number(length[1], length[0], endian)
    if not offset or not size or not offset.isdigit() or not size.isdigit():
        return None
    return (int(offset), int(size)) if int(size) else None


def _signed(
    vendor: str, note: bytes, data: Raw, at: int, size: int, layout: _Layout, endian: str
) -> MakerNotes:
    """Read a note whose signature says where its directory is.

    A note-relative layout is read in the order it declares for itself and is
    addressed from its own first byte. A TIFF-relative one has no mark and no
    choice: its offsets only mean anything in the container's order and its
    space.
    """
    if layout.scheme == NOTE_RELATIVE:
        inner = _mark(note, layout.mark, endian)
        entries = _entries(note, layout.directory, inner, base=0, limit=len(note))
        extra = _subdirectories(note, entries, inner, len(note), layout.subdirectories)
        return _notes(vendor, layout.scheme, entries, size, layout.fields, inner, extra=extra)
    entries = _entries(data, at + layout.directory, endian, base=0, limit=len(data))
    extra = _subdirectories(data, entries, endian, len(data), layout.subdirectories)
    return _notes(vendor, layout.scheme, entries, size, layout.fields, endian, extra=extra)


def _mark(note: bytes, mark: int | None, endian: str) -> str:
    """The byte order a note declares for itself, or the container's."""
    if mark is None:
        return endian
    found = note[mark : mark + 2]
    return "<" if found == b"II" else ">" if found == b"MM" else endian


def _subdirectories(
    data: Raw,
    directory: _Directory,
    endian: str,
    limit: int,
    tables: dict[int, dict[int, tuple[str, str]]],
) -> dict[str, str]:
    """Named fields from the sub-directories a vendor groups them into.

    Where a value would be there is a pointer to another directory. Its tags
    repeat the numbers used by the note's own directory and mean something else,
    so each is named from its own table rather than the two being read as one.
    """
    fields: dict[str, str] = {}
    for tag, table in tables.items():
        found = directory.values.get(tag)
        if found is None or len(found[1]) < 4:
            continue
        (inner,) = struct.unpack_from(endian + "I", found[1], 0)
        fields.update(_named(_entries(data, inner, endian, base=0, limit=limit), table, endian))
    return fields


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


def _word(note: bytes, index: int) -> int:
    """One of the sixteen-bit words a fixed structure is measured in."""
    (value,) = struct.unpack_from("<H", note, index * 2)
    return int(value)


def _reconyx(note: bytes) -> MakerNotes:
    """The HyperFire structure, read at the words the camera fixes it to.

    `EventNumber` counts what tripped the camera and `Sequence` numbers the
    frames within one trip, so together they place a photograph inside a
    deployment. The clock reading is the camera's own and is kept beside the one
    EXIF carries rather than merged with it: two readings that disagree are the
    finding, and merging them would be the one thing that hides it.
    """
    moment = [_word(note, _RECONYX_MOMENT + step) for step in range(6)]
    seconds, minutes, hours, month, day, year = moment
    fields = {
        "SerialNumber": _wide_text(note[_RECONYX_SERIAL * 2 : _RECONYX_SERIAL * 2 + 30]),
        "UserLabel": _text(note[_RECONYX_LABEL * 2 : _RECONYX_LENGTH]),
        "FirmwareVersion": ".".join(str(_word(note, index)) for index in (1, 2, 3)),
        "EventNumber": str(_word(note, 0x09) * 0x10000 + _word(note, 0x0A)),
        "Sequence": f"{_word(note, 0x07)} of {_word(note, 0x08)}",
        "TriggerMode": _RECONYX_TRIGGER.get(chr(_word(note, 0x06))),
        "DateTimeOriginal": (
            f"{year:04d}:{month:02d}:{day:02d} {hours:02d}:{minutes:02d}:{seconds:02d}"
        ),
    }
    named = {label: value for label, value in fields.items() if value}
    return MakerNotes("Reconyx", FIXED_STRUCTURE, 0, len(note), named)


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
    directory: _Directory,
    size: int,
    table: dict[int, tuple[str, str]],
    endian: str,
    byte_order: str = SAME_ORDER,
    extra: dict[str, str] | None = None,
    declared: tuple[int, int] | None = None,
) -> MakerNotes:
    fields = _named(directory, table, endian)
    for label, value in (extra or {}).items():
        fields.setdefault(label, value)
    return MakerNotes(
        vendor,
        scheme,
        directory.declared,
        size,
        fields,
        byte_order,
        undecoded=directory.undecoded,
        distrusted=directory.distrusted,
        declared_preview=declared,
    )


def _named(directory: _Directory, table: dict[int, tuple[str, str]], endian: str) -> dict[str, str]:
    """The fields one directory names, by the table that describes it."""
    fields: dict[str, str] = {}
    for tag, (kind, raw) in directory.values.items():
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
    return fields


def _entries(
    data: Raw, offset: int, endian: str, base: int, limit: int, trust_offsets: bool = True
) -> _Directory:
    """Walk one directory, returning each entry's type and its raw bytes."""
    if offset <= 0 or offset + 2 > limit:
        return _Directory(0)
    try:
        (count,) = struct.unpack_from(endian + "H", data, offset)
    except struct.error:
        return _Directory(0)
    if count == 0 or count > _MAX_ENTRIES or offset + 2 + count * 12 > limit:
        return _Directory(0)

    found: dict[int, tuple[int, bytes]] = {}
    undecoded = distrusted = 0
    for index in range(count):
        entry = offset + 2 + index * 12
        try:
            tag, kind, length = struct.unpack_from(endian + "HHI", data, entry)
        except struct.error:
            break
        width = _WIDTHS.get(kind)
        if width is None or length == 0:
            undecoded += 1
            continue
        size = width * length
        if size > _MAX_VALUE:
            # A block this big is a data dump rather than a field, whatever the
            # vendor calls it, and nothing here names one.
            undecoded += 1
            continue
        if size <= 4:
            found[tag] = (kind, bytes(data[entry + 8 : entry + 8 + size]))
            continue
        if not trust_offsets:
            distrusted += 1
            continue
        (at,) = struct.unpack_from(endian + "I", data, entry + 8)
        at += base
        if at <= 0 or at + size > limit:
            undecoded += 1
            continue
        found[tag] = (kind, bytes(data[at : at + size]))
    return _Directory(count, found, undecoded, distrusted)


def _text(raw: bytes) -> str | None:
    """The text in a field, whichever end the vendor padded.

    A field is declared wider than the string it holds and the padding is
    conventionally at the end. Panasonic puts it at the front, so stopping at
    the first null byte returns nothing for the one field that names the body.
    """
    return _printable(raw.strip(b"\x00").split(b"\x00")[0].decode("utf-8", "replace"))


def _wide_text(raw: bytes) -> str | None:
    """Text a vendor wrote two bytes to the character."""
    return _printable(raw.decode("utf-16-le", "replace").split("\x00")[0])


def _printable(value: str) -> str | None:
    """The value, if it reads as text somebody wrote.

    Decoding with replacement never fails, and the replacement character is
    itself printable, so a printability test alone lets four bytes of binary
    through as a lens name. A field is read as itself or not at all: no value is
    a true answer where mojibake is not.
    """
    value = value.strip()
    if not value or "�" in value or not value.isprintable():
        return None
    return value


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
