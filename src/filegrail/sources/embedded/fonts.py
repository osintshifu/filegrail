"""Fonts: what the SFNT tables say about who made a typeface.

A font names its maker more plainly than most files do. The `name` table
carries the foundry, the designer, the version string and often a licence
with a URL in it; the `head` table keeps the moment the font was created and
last modified; `OS/2` holds the four-letter vendor identifier a foundry
registers. A WOFF wraps the same tables in compression and may add a block of
XML metadata with the credits written out in full.

Tables are read by their directory offsets, one at a time, and only the four
that answer the question are read at all.
"""

from __future__ import annotations

import struct
import xml.etree.ElementTree as ElementTree
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO

from ..compression import decompress_zlib

SUFFIXES = {".ttf", ".otf", ".ttc", ".otc", ".woff"}

_SFNT_VERSIONS = {b"\x00\x01\x00\x00": "TrueType", b"true": "TrueType", b"OTTO": "CFF OpenType"}
_COLLECTION = b"ttcf"
_WOFF = b"wOFF"

_WANTED = (b"name", b"head", b"OS/2", b"fvar")
_MAX_TABLES = 64
_MAX_TABLE = 4 * 1024 * 1024
_MAX_NAMES = 512
_MAX_TEXT = 1024
_MAX_AXES = 16
_MAX_CREDITS = 8
_MAX_META = 1024 * 1024

_EPOCH_1904 = datetime(1904, 1, 1, tzinfo=timezone.utc)

#: The `name` table identifiers with something to say about provenance. The
#: sample text, the compatible-full name and the WWS names are left out.
NAME_IDS = {
    0: "Copyright",
    1: "Family",
    2: "Subfamily",
    3: "UniqueID",
    4: "FullName",
    5: "Version",
    6: "PostScriptName",
    7: "Trademark",
    8: "Manufacturer",
    9: "Designer",
    10: "Description",
    11: "VendorURL",
    12: "DesignerURL",
    13: "License",
    14: "LicenseURL",
    16: "TypographicFamily",
    17: "TypographicSubfamily",
}

_EMBEDDING = {0: "installable", 2: "restricted", 4: "preview and print", 8: "editable"}


@dataclass(slots=True)
class Font:
    """What one font file records about its own making."""

    container: str
    names: dict[str, str] = field(default_factory=dict)
    created: str | None = None
    modified: str | None = None
    revision: str | None = None
    vendor_id: str | None = None
    embedding: str | None = None
    axes: list[tuple[str, float, float, float]] = field(default_factory=list)
    fonts: int = 1
    meta: dict[str, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.names or self.created or self.vendor_id or self.meta)


def read_font(path: Path) -> Font | None:
    """Return what a font says about its own making, or None."""
    try:
        with path.open("rb") as handle:
            return _read(handle)
    except (OSError, struct.error, ValueError, zlib.error):
        return None


def _read(handle: BinaryIO) -> Font | None:
    magic = handle.read(4)
    if magic == _WOFF:
        return _woff(handle)
    if magic == _COLLECTION:
        header = handle.read(8)
        if len(header) < 8:
            return None
        _, count = struct.unpack(">II", header)
        offsets = handle.read(4 * min(count, 1))
        if len(offsets) < 4:
            return None
        (first,) = struct.unpack(">I", offsets)
        handle.seek(first)
        magic = handle.read(4)
        font = _sfnt(handle, magic)
        if font is not None:
            font.fonts = count
        return font
    return _sfnt(handle, magic)


def _sfnt(handle: BinaryIO, magic: bytes) -> Font | None:
    container = _SFNT_VERSIONS.get(magic)
    if container is None:
        return None
    header = handle.read(8)
    if len(header) < 8:
        return None
    (count,) = struct.unpack_from(">H", header, 0)
    if count > _MAX_TABLES:
        return None
    directory = handle.read(16 * count)
    font = Font(container=container)
    for at in range(0, len(directory) - 15, 16):
        tag, _, offset, length = struct.unpack_from(">4sIII", directory, at)
        if tag not in _WANTED or not length or length > _MAX_TABLE:
            continue
        handle.seek(offset)
        _absorb(tag, handle.read(length), font)
    return font if font else None


def _woff(handle: BinaryIO) -> Font | None:
    header = handle.read(40)
    if len(header) < 40:
        return None
    flavor = header[:4]
    count, _, _, _, _, meta_at, meta_length, meta_original = struct.unpack_from(
        ">HHIHHIII", header, 8
    )
    if count > _MAX_TABLES:
        return None
    directory = handle.read(20 * count)
    kind = _SFNT_VERSIONS.get(flavor, "TrueType")
    font = Font(container=f"WOFF ({kind})")
    for at in range(0, len(directory) - 19, 20):
        tag, offset, compressed, original, _ = struct.unpack_from(">4sIIII", directory, at)
        if (
            tag not in _WANTED
            or not original
            or original > _MAX_TABLE
            or compressed > _MAX_TABLE
            or compressed > original
        ):
            continue
        handle.seek(offset)
        data = handle.read(compressed)
        if len(data) != compressed:
            continue
        if compressed < original:
            inflated = decompress_zlib(data, original)
            if inflated is None:
                continue
            data = inflated
        _absorb(tag, data, font)
    if meta_at and meta_length and meta_length <= _MAX_META and 0 < meta_original <= _MAX_META:
        handle.seek(meta_at)
        packed = handle.read(meta_length)
        if len(packed) != meta_length:
            return font if font else None
        metadata = decompress_zlib(packed, meta_original) if meta_length < meta_original else packed
        if metadata:
            font.meta = _metadata(metadata)
    return font if font else None


# --- the tables --------------------------------------------------------------


def _absorb(tag: bytes, data: bytes, font: Font) -> None:
    if tag == b"name":
        font.names = _names(data)
    elif tag == b"head" and len(data) >= 36:
        (revision,) = struct.unpack_from(">I", data, 4)
        font.revision = f"{revision / 65536:.3f}"
        created, modified = struct.unpack_from(">qq", data, 20)
        font.created = _long_datetime(created)
        font.modified = _long_datetime(modified)
    elif tag == b"OS/2" and len(data) >= 62:
        (rights,) = struct.unpack_from(">H", data, 8)
        font.embedding = _EMBEDDING.get(rights & 0x0F, f"0x{rights:04x}")
        vendor = data[58:62].decode("ascii", "replace").strip("\x00 ")
        font.vendor_id = vendor or None
    elif tag == b"fvar" and len(data) >= 16:
        _, _, axes_at, _, axis_count, axis_size = struct.unpack_from(">HHHHHH", data, 0)
        if axis_size < 20:
            return
        for index in range(min(axis_count, _MAX_AXES)):
            at = axes_at + index * axis_size
            if at + 20 > len(data):
                break
            axis, low, default, high = struct.unpack_from(">4sIII", data, at)
            font.axes.append(
                (
                    axis.decode("ascii", "replace").strip(),
                    _fixed(low),
                    _fixed(default),
                    _fixed(high),
                )
            )


def _names(data: bytes) -> dict[str, str]:
    """The `name` table, one value per identifier.

    A font repeats every name for several platforms and languages. Windows
    English is preferred, then any Unicode or Windows record, then Macintosh,
    so the value reported is the one most viewers would show.
    """
    if len(data) < 6:
        return {}
    _, count, strings_at = struct.unpack_from(">HHH", data, 0)
    best: dict[int, tuple[int, str]] = {}
    for index in range(min(count, _MAX_NAMES)):
        at = 6 + index * 12
        if at + 12 > len(data):
            break
        platform, encoding, language, name_id, length, offset = struct.unpack_from(
            ">HHHHHH", data, at
        )
        label = NAME_IDS.get(name_id)
        if label is None:
            continue
        start = strings_at + offset
        raw = data[start : start + length]
        if len(raw) < length:
            continue
        if platform in (0, 3):
            text = raw.decode("utf-16-be", "replace")
            rank = 3 if platform == 3 and language == 0x409 else 2
        elif platform == 1 and encoding == 0:
            text = raw.decode("mac_roman", "replace")
            rank = 1
        else:
            continue
        text = " ".join(text.split())[:_MAX_TEXT]
        if text and rank > best.get(name_id, (0, ""))[0]:
            best[name_id] = (rank, text)
    return {NAME_IDS[name_id]: text for name_id, (_, text) in sorted(best.items())}


def _metadata(raw: bytes) -> dict[str, str]:
    """The WOFF extended metadata block: credits written out as XML."""
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return {}
    found: dict[str, str] = {}

    def keep(name: str, value: str | None) -> None:
        if value and name not in found:
            found[name] = " ".join(value.split())[:_MAX_TEXT]

    if (unique := root.find("uniqueid")) is not None:
        keep("meta:uniqueid", unique.get("id"))
    if (vendor := root.find("vendor")) is not None:
        keep("meta:vendor", vendor.get("name"))
        keep("meta:vendorURL", vendor.get("url"))
    for index, credit in enumerate(root.iter("credit"), 1):
        if index > _MAX_CREDITS:
            break
        keep(f"meta:credit[{index}]:name", credit.get("name"))
        keep(f"meta:credit[{index}]:url", credit.get("url"))
        keep(f"meta:credit[{index}]:role", credit.get("role"))
    for tag in ("description", "copyright", "trademark"):
        element = root.find(tag)
        if element is not None and (text := element.find("text")) is not None:
            keep(f"meta:{tag}", text.text)
    if (licence := root.find("license")) is not None:
        keep("meta:licenseURL", licence.get("url"))
        keep("meta:licenseID", licence.get("id"))
        if (text := licence.find("text")) is not None:
            keep("meta:license", text.text)
    if (licensee := root.find("licensee")) is not None:
        keep("meta:licensee", licensee.get("name"))
    return found


def _long_datetime(seconds: int) -> str | None:
    """`LONGDATETIME`: seconds since 1904, which a zero says nobody set."""
    if seconds <= 0:
        return None
    try:
        moment = _EPOCH_1904 + timedelta(seconds=seconds)
    except OverflowError:
        return None
    if moment > datetime.now(timezone.utc) + timedelta(days=1):
        return None
    return moment.isoformat().replace("+00:00", "Z")


def _fixed(value: int) -> float:
    return round(value / 65536, 3)
