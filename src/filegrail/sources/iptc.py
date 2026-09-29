"""IPTC IIM: the press byline that predates XMP and still travels with photographs.

IIM is what a newsroom writes into a picture: who took it, who is to be
credited, where it was taken and under what terms it may be used. Modern tools
maintain the same facts in XMP and leave the IIM block behind unchanged, which
is a weakness as a claim and an asset as evidence - a stale byline is a record
of an earlier state of the file.

The block travels inside a Photoshop image-resource block, so one search for
that structure serves JPEG, TIFF and PSD alike.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from ..models import EvidenceRecord
from .embedded.photoshop import find_resource

#: The image-resource block that holds an IIM datastream.
_IPTC_RESOURCE = 0x0404

#: The TIFF tag that holds an IIM datastream with no Photoshop block around it.
#: There is no marker to search for in that case - a datastream begins `\x1c\x02`,
#: which is two bytes and would match almost anything - so it is reached through
#: the directory instead.
_TIFF_IPTC_TAG = 0x83BB
_TIFF_MAGIC = (b"MM\x00\x2a", b"II\x2a\x00")

#: Record 1, dataset 90 declares the coded character set. `ESC % G` is the only
#: value in circulation and means UTF-8; anything else, or nothing at all, means
#: the single-byte text the standard was written for.
_CHARACTER_SET = (1, 90)
_UTF8_ESCAPE = b"\x1b%G"

#: How much of each end of a file to search, and how large a block may be.
_WINDOW = 4 * 1024 * 1024
_MAX_BLOCK = 1024 * 1024

#: A directory longer than this is not one this reader is going to make sense of.
_MAX_ENTRIES = 512

#: Datasets of the application record. Everything else keeps its number, the way
#: an unnamed EXIF tag keeps its hex code: a name a reader cannot look up is
#: worse than a number they can.
_DATASETS = {
    0: "RecordVersion",
    5: "ObjectName",
    7: "EditStatus",
    10: "Urgency",
    15: "Category",
    20: "SupplementalCategory",
    22: "FixtureIdentifier",
    25: "Keywords",
    26: "ContentLocationCode",
    27: "ContentLocationName",
    30: "ReleaseDate",
    35: "ReleaseTime",
    40: "SpecialInstructions",
    45: "ReferenceService",
    47: "ReferenceDate",
    50: "ReferenceNumber",
    55: "DateCreated",
    60: "TimeCreated",
    62: "DigitalCreationDate",
    63: "DigitalCreationTime",
    65: "OriginatingProgram",
    70: "ProgramVersion",
    75: "ObjectCycle",
    80: "By-line",
    85: "By-lineTitle",
    90: "City",
    92: "Sub-location",
    95: "Province-State",
    100: "Country-PrimaryLocationCode",
    101: "Country-PrimaryLocationName",
    103: "OriginalTransmissionReference",
    105: "Headline",
    110: "Credit",
    115: "Source",
    116: "CopyrightNotice",
    118: "Contact",
    120: "Caption-Abstract",
    122: "Writer-Editor",
    131: "ImageOrientation",
    135: "LanguageIdentifier",
}


def read_iptc(path: Path) -> EvidenceRecord | None:
    """Return what the file's IPTC block claims, or None."""
    block = _block(path)
    if not block:
        return None

    fields = _datasets(block)
    if not fields:
        return None

    return EvidenceRecord(
        source="iptc",
        block="iptc",
        tool=_tool(fields),
        at=_moment(fields.get("DateCreated"), fields.get("TimeCreated")),
        location=_place(fields),
        note=_note(fields) or None,
        fields=fields,
    )


# --- finding the block -------------------------------------------------------


def _block(path: Path) -> bytes:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            head = handle.read(_WINDOW)
            found = _find(head) or _tiff_tag(head)
            if not found and size > _WINDOW:
                handle.seek(max(0, size - _WINDOW))
                found = _find(handle.read(_WINDOW))
    except OSError:
        return b""
    return found


def _find(data: bytes) -> bytes:
    """The payload of the first 8BIM resource that holds an IIM datastream."""
    found = find_resource(data, _IPTC_RESOURCE)
    return found if len(found) <= _MAX_BLOCK else b""


def _tiff_tag(data: bytes) -> bytes:
    """The IIM datastream held directly in a TIFF tag, if the file is a TIFF.

    Only the first directory is read. A datastream lives beside the image
    description in IFD0; walking sub-directories to look for a second one would
    buy nothing but a way to be wrong about which of them is the file's.
    """
    if data[:4] not in _TIFF_MAGIC:
        return b""
    endian = ">" if data[:2] == b"MM" else "<"

    try:
        (offset,) = struct.unpack_from(endian + "I", data, 4)
        (count,) = struct.unpack_from(endian + "H", data, offset)
        for index in range(min(count, _MAX_ENTRIES)):
            entry = offset + 2 + index * 12
            tag, kind, length, at = struct.unpack_from(endian + "HHII", data, entry)
            # Writers type the tag UNDEFINED or BYTE, and some LONG; the
            # count is then in four-byte units.
            size = length * (4 if kind == 4 else 1)
            if tag == _TIFF_IPTC_TAG and 0 < size <= _MAX_BLOCK:
                return data[at : at + size]
    except struct.error:
        return b""
    return b""


# --- reading the block -------------------------------------------------------


def _datasets(block: bytes) -> dict[str, str]:
    raw = list(_walk(block))
    encoding = _encoding(raw)

    found: dict[str, str] = {}
    for record, number, value in raw:
        if record != 2 or not value:
            continue

        # Dataset 0 is the one entry of the application record that is not text:
        # a 16-bit version, which decoded as characters is a control byte.
        if number == 0:
            found["RecordVersion"] = str(int.from_bytes(value[:2], "big"))
            continue

        text = value.decode(encoding, "replace").strip("\x00").strip()
        if not text:
            continue
        name = _DATASETS.get(number, f"2:{number}")
        # Keywords and the category datasets repeat rather than holding a list.
        found[name] = f"{found[name]}, {text}" if name in found else text
    return found


def _moment(date: str | None, time: str | None) -> str | None:
    """IIM splits a timestamp: CCYYMMDD in one dataset, HHMMSS+HHMM in another.

    The date alone is still a fact, so a missing or unreadable time leaves the
    day standing at midnight UTC rather than discarding what was recorded.
    """
    if not date or len(date) < 8 or not date[:8].isdigit():
        return None
    stamp = f"{date[:4]}-{date[4:6]}-{date[6:8]}"

    clock = (time or "").strip()
    if len(clock) >= 6 and clock[:6].isdigit():
        stamp += f"T{clock[0:2]}:{clock[2:4]}:{clock[4:6]}"
        zone = clock[6:]
        stamp += f"{zone[:3]}:{zone[3:5]}" if len(zone) == 5 and zone[0] in "+-" else "+00:00"
    else:
        stamp += "T00:00:00+00:00"

    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _tool(fields: dict[str, str]) -> str | None:
    """The program that wrote the block, with its version where one is given."""
    said = (fields.get("OriginatingProgram"), fields.get("ProgramVersion"))
    return " ".join(part for part in said if part) or None


#: The place, narrowest first, the way an address is written.
_PLACE = ("Sub-location", "City", "Province-State", "Country-PrimaryLocationName")


def _place(fields: dict[str, str]) -> str | None:
    """The place as a name, which is all IIM records.

    It goes to `location` and never to `geo`: a newsroom typed it, and a typed
    name is not a fix anybody decoded.
    """
    return ", ".join(part for name in _PLACE if (part := fields.get(name))) or None


def _walk(block: bytes) -> Iterator[tuple[int, int, bytes]]:
    """Yield (record, dataset, value) for each entry, in the order written.

    A length with its top bit set is not a length: the remaining bits count how
    many bytes the real length occupies, which is how IIM carries a caption
    longer than 32767 bytes. Reading it as an ordinary length loses the reader's
    place in the stream, and with it every dataset that follows - so this is not
    a rare field skipped but a block truncated at the first long value.
    """
    at = 0
    while at + 5 <= len(block):
        if block[at] != 0x1C:
            return
        record, number = block[at + 1], block[at + 2]
        (length,) = struct.unpack_from(">H", block, at + 3)
        at += 5

        if length & 0x8000:
            size = length & 0x7FFF
            if not 0 < size <= 8 or at + size > len(block):
                return
            length = int.from_bytes(block[at : at + size], "big")
            at += size

        if length > len(block) - at:
            return  # the block claims more than it holds; the rest is not readable
        yield record, number, block[at : at + length]
        at += length


def _encoding(raw: list[tuple[int, int, bytes]]) -> str:
    """UTF-8 only when the block says so.

    IIM predates Unicode, and a block that does not declare UTF-8 holds
    single-byte text. Decoding that as UTF-8 turns every accent into a
    replacement character, which loses a byline rather than reading one; latin-1
    decodes any byte to something, so nothing is dropped either way.
    """
    for record, number, value in raw:
        if (record, number) == _CHARACTER_SET:
            return "utf-8" if _UTF8_ESCAPE in value else "latin-1"
    return "latin-1"


def _note(fields: dict[str, str]) -> str:
    said = []
    if fields.get("By-line"):
        said.append(f"by-line {fields['By-line']}")
    if fields.get("Credit"):
        said.append(f"credit {fields['Credit']}")
    if fields.get("CopyrightNotice"):
        said.append(fields["CopyrightNotice"])
    return "; ".join(said)
