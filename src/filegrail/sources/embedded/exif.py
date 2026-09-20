"""TIFF/EXIF metadata, and the containers that carry it.

EXIF is a TIFF header, so one reader serves every container that embeds one:

    JPEG    APP1 segment beginning ``Exif\\x00\\x00``
    TIFF    the file is the TIFF header, including DNG, NEF, CR2 and ARW
    WebP    the ``EXIF`` chunk of the RIFF container
    HEIC    an ``Exif`` item inside the ISO base media container

Beyond the producing device this reads the **GPS IFD**, because where a
photograph was taken is provenance in the strictest sense, and it is routinely
the single most consequential fact a file carries.
"""

from __future__ import annotations

import mmap
import struct
from pathlib import Path

from ...preview import EmbeddedPreview, jpeg_dimensions
from . import jpeg

#: What the parser reads from: a block lifted out of a container, or a whole
#: file mapped into memory. It only takes lengths, slices and packed fields,
#: and both answer to all three.
Raw = bytes | mmap.mmap

JPEG_SUFFIXES = {".jpg", ".jpeg", ".jpe"}
TIFF_SUFFIXES = {".tif", ".tiff", ".dng", ".nef", ".cr2", ".arw", ".orf", ".rw2"}
WEBP_SUFFIXES = {".webp"}
HEIF_SUFFIXES = {".heic", ".heif", ".avif"}
SUFFIXES = JPEG_SUFFIXES | TIFF_SUFFIXES | WEBP_SUFFIXES | HEIF_SUFFIXES

# Tags worth reading. Everything else is exposure trivia, not provenance.
MAKE = 0x010F
MODEL = 0x0110
SOFTWARE = 0x0131
DATETIME = 0x0132
ARTIST = 0x013B
COPYRIGHT = 0x8298
EXIF_IFD = 0x8769
GPS_IFD = 0x8825
SUB_IFDS = 0x014A
INTEROP_IFD = 0xA005
DATETIME_ORIGINAL = 0x9003
LENS_MODEL = 0xA434

THUMBNAIL_COMPRESSION = 0x0103
THUMBNAIL_OFFSET = 0x0201
THUMBNAIL_LENGTH = 0x0202

GPS_LATITUDE_REF = 0x0001
GPS_LATITUDE = 0x0002
GPS_LONGITUDE_REF = 0x0003
GPS_LONGITUDE = 0x0004
GPS_ALTITUDE = 0x0006
GPS_DATESTAMP = 0x001D

#: Named so a report can print them. Everything decoded is kept; these are the
#: ones an investigation asks for by name, and several are worth more than the
#: camera model: a body serial ties an image to one physical device, and the GPS
#: timestamp is independent of the camera clock, so a disagreement between them
#: is itself a finding.
TAG_NAMES = {
    0x0100: "ImageWidth",
    0x0101: "ImageLength",
    0x010E: "ImageDescription",
    0x010F: "Make",
    0x0110: "Model",
    0x0112: "Orientation",
    0x0131: "Software",
    0x0132: "DateTime",
    0x013B: "Artist",
    0x8298: "Copyright",
    0x829A: "ExposureTime",
    0x829D: "FNumber",
    0x8827: "ISOSpeedRatings",
    0x9003: "DateTimeOriginal",
    0x9004: "DateTimeDigitized",
    0x9204: "ExposureBiasValue",
    0x9205: "MaxApertureValue",
    0x920A: "FocalLength",
    0x9286: "UserComment",
    0x9290: "SubSecTime",
    0x9291: "SubSecTimeOriginal",
    0xA002: "ExifImageWidth",
    0xA003: "ExifImageHeight",
    0xA404: "DigitalZoomRatio",
    0xA405: "FocalLengthIn35mmFilm",
    0xA430: "CameraOwnerName",
    0xA431: "BodySerialNumber",
    0xA432: "LensSpecification",
    0xA433: "LensMake",
    0xA434: "LensModel",
    0xA435: "LensSerialNumber",
}

GPS_TAG_NAMES = {
    0x0000: "GPSVersionID",
    0x0001: "GPSLatitudeRef",
    0x0002: "GPSLatitude",
    0x0003: "GPSLongitudeRef",
    0x0004: "GPSLongitude",
    0x0005: "GPSAltitudeRef",
    0x0006: "GPSAltitude",
    0x0007: "GPSTimeStamp",
    0x0008: "GPSSatellites",
    0x0009: "GPSStatus",
    0x000A: "GPSMeasureMode",
    0x000B: "GPSDOP",
    0x0010: "GPSImgDirectionRef",
    0x0011: "GPSImgDirection",
    0x0012: "GPSMapDatum",
    0x001D: "GPSDateStamp",
}

_BYTE = 1
_ASCII = 2
_SHORT = 3
_LONG = 4
_RATIONAL = 5
_UNDEFINED = 7
_SLONG = 9
_SRATIONAL = 10

_MAX_ENTRIES = 512
_MAX_STRING = 1024
_MAX_IFDS = 64
_MAX_PREVIEW_BYTES = 4 * 1024 * 1024
_HEIF_SCAN_BYTES = 4 * 1024 * 1024


class Exif(dict[int, object]):
    """Decoded tags and subordinate TIFF directories."""

    def __init__(self) -> None:
        super().__init__()
        self.gps: dict[int, object] = {}
        self.interop: dict[int, object] = {}
        self.thumbnail: dict[int, object] = {}
        self.sub_ifds: list[dict[int, object]] = []
        self.preview: EmbeddedPreview | None = None


def read_exif(path: Path) -> Exif | None:
    """Return the decoded EXIF of `path`, or None when it carries none."""
    suffix = path.suffix.lower()
    try:
        if suffix in JPEG_SUFFIXES:
            raw = _jpeg_exif(path)
        elif suffix in TIFF_SUFFIXES:
            return _tiff_exif(path)
        elif suffix in WEBP_SUFFIXES:
            raw = _webp_chunk(path, b"EXIF")
        elif suffix in HEIF_SUFFIXES:
            raw = _heif_exif(path)
        else:
            return None
    except (OSError, struct.error, ValueError):
        return None

    if not raw:
        return None
    try:
        return _parse_tiff(raw)
    except (struct.error, ValueError):
        return None


# --- containers --------------------------------------------------------------


def _tiff_exif(path: Path) -> Exif | None:
    """Parse a TIFF where it lies, instead of reading it in.

    Here the container *is* the header, so unlike every other reader in this
    module there is no small block to lift out - and the files are the largest
    the tool sees. A raw frame from a camera runs from twenty-five megabytes to
    past a hundred, the tags are a few hundred bytes of it, and a directory of
    them is the ordinary case rather than an attack.

    A window over the head would be wrong rather than merely smaller, because
    an IFD offset may point anywhere in the file. Mapping hands the parser the
    whole of it and leaves the pages to the operating system. An empty file
    cannot be mapped, which raises `ValueError` and is caught by the caller
    along with everything else that means "this is not one of these".
    """
    with path.open("rb") as handle:
        with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            return _parse_tiff(mapped)


def _jpeg_exif(path: Path) -> bytes:
    with path.open("rb") as handle:
        if handle.read(2) != b"\xff\xd8":
            return b""
        for marker, payload in jpeg.iter_segments(handle):
            if marker == 0xE1 and payload.startswith(b"Exif\x00\x00"):
                return payload[6:]
    return b""


def _webp_chunk(path: Path, wanted: bytes) -> bytes:
    """Return one chunk of a RIFF/WebP file."""
    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WEBP":
            return b""
        while True:
            entry = handle.read(8)
            if len(entry) < 8:
                return b""
            fourcc, size = struct.unpack("<4sI", entry)
            payload = handle.read(size)
            if fourcc == wanted:
                # Some writers prefix the TIFF header with the JPEG marker.
                return payload[6:] if payload.startswith(b"Exif\x00\x00") else payload
            if size % 2:
                handle.read(1)  # chunks are padded to an even length


def _heif_exif(path: Path) -> bytes:
    """Locate the Exif payload in an ISO base media file.

    Resolving it properly means walking `iinf` and `iloc` to find the item and
    its extent. The payload is self-identifying, so it is found by its marker
    instead, which is markedly simpler and works on the files people actually
    have.

    The marker is not unique: encoders write the literal `Exif` as the item type
    in the `infe` entry, which is followed by the version and flags word and so
    reads as the same six bytes. Only the occurrence followed by a TIFF header
    is the payload, so the scan continues until one is.
    """
    with path.open("rb") as handle:
        data = handle.read(_HEIF_SCAN_BYTES)

    start = 0
    while True:
        marker = data.find(b"Exif\x00\x00", start)
        if marker < 0:
            return b""
        payload = data[marker + 6 :]
        if payload[:2] in (b"II", b"MM"):
            return payload
        start = marker + 1


# --- TIFF --------------------------------------------------------------------


def _parse_tiff(data: Raw) -> Exif | None:
    if len(data) < 8:
        return None
    if data[:2] == b"II":
        endian = "<"
    elif data[:2] == b"MM":
        endian = ">"
    else:
        return None

    (first_ifd,) = struct.unpack_from(endian + "I", data, 4)
    exif = Exif()
    seen: set[int] = set()
    next_ifd = _read_ifd(data, first_ifd, endian, exif, exif, seen)

    for pointer, target in ((EXIF_IFD, exif), (GPS_IFD, exif.gps)):
        offset = exif.pop(pointer, None)
        if isinstance(offset, int):
            _read_ifd(data, offset, endian, target, exif, seen)

    interop = exif.pop(INTEROP_IFD, None)
    if isinstance(interop, int):
        _read_ifd(data, interop, endian, exif.interop, exif, seen)

    sub_ifds = exif.pop(SUB_IFDS, None)
    offsets = sub_ifds if isinstance(sub_ifds, list) else [sub_ifds]
    for offset in offsets[:_MAX_IFDS]:
        if not isinstance(offset, int):
            continue
        directory: dict[int, object] = {}
        _read_ifd(data, offset, endian, directory, exif, seen)
        if directory:
            exif.sub_ifds.append(directory)

    if isinstance(next_ifd, int) and next_ifd > 0:
        _read_ifd(data, next_ifd, endian, exif.thumbnail, exif, seen)
        exif.preview = _thumbnail_preview(data, exif.thumbnail)

    return exif if (exif or exif.gps or exif.thumbnail or exif.interop or exif.sub_ifds) else None


def _read_ifd(
    data: Raw,
    offset: int,
    endian: str,
    into: dict[int, object],
    exif: Exif,
    seen: set[int],
) -> int | None:
    if offset <= 0 or offset in seen or len(seen) >= _MAX_IFDS or offset + 2 > len(data):
        return None
    seen.add(offset)
    (count,) = struct.unpack_from(endian + "H", data, offset)
    if count > _MAX_ENTRIES:
        return None
    end = offset + 2 + count * 12
    if end + 4 > len(data):
        return None

    for index in range(count):
        entry = offset + 2 + index * 12
        tag, kind, length = struct.unpack_from(endian + "HHI", data, entry)

        value = _read_value(data, entry, endian, kind, length)
        if value is not None:
            into[tag] = value
            if tag in (EXIF_IFD, GPS_IFD, SUB_IFDS, INTEROP_IFD):
                exif[tag] = value
    (next_ifd,) = struct.unpack_from(endian + "I", data, end)
    return next_ifd or None


def _thumbnail_preview(data: Raw, thumbnail: dict[int, object]) -> EmbeddedPreview | None:
    if thumbnail.get(THUMBNAIL_COMPRESSION) != 6:
        return None
    offset = thumbnail.get(THUMBNAIL_OFFSET)
    length = thumbnail.get(THUMBNAIL_LENGTH)
    if (
        not isinstance(offset, int)
        or not isinstance(length, int)
        or isinstance(offset, bool)
        or isinstance(length, bool)
        or offset <= 0
        or length <= 0
        or length > _MAX_PREVIEW_BYTES
        or offset > len(data) - length
    ):
        return None
    payload = bytes(data[offset : offset + length])
    dimensions = jpeg_dimensions(payload)
    if dimensions is None:
        return None
    return EmbeddedPreview("EXIF IFD1", "image/jpeg", payload, *dimensions)


def _read_value(data: Raw, entry: int, endian: str, kind: int, length: int) -> object | None:
    if kind == _ASCII:
        if length == 0 or length > _MAX_STRING:
            return None
        raw = _payload(data, entry, endian, length)
        if raw is None:
            return None
        text = raw.split(b"\x00")[0].decode("utf-8", "replace").strip()
        return text or None

    if kind in (_SHORT, _LONG, _SLONG, _BYTE):
        width = {_BYTE: 1, _SHORT: 2, _LONG: 4, _SLONG: 4}[kind]
        if length == 0 or length > 8:
            return None
        raw = _payload(data, entry, endian, length * width)
        if raw is None or len(raw) < length * width:
            return None
        code = {_BYTE: "B", _SHORT: "H", _LONG: "I", _SLONG: "i"}[kind]
        values = [struct.unpack_from(endian + code, raw, i * width)[0] for i in range(length)]
        return values[0] if length == 1 else values

    if kind == _UNDEFINED:
        # UserComment and friends: an 8-byte character-set header, then text.
        if length == 0 or length > _MAX_STRING:
            return None
        raw = _payload(data, entry, endian, length)
        if raw is None:
            return None
        if raw[:8].rstrip(b"\x00") in (b"ASCII", b"UNICODE", b"JIS", b""):
            raw = raw[8:]
        text = raw.split(b"\x00")[0].decode("utf-8", "replace").strip()
        # Several UNDEFINED tags hold packed bytes rather than text -
        # ComponentsConfiguration is \x01\x02\x03\x00 - and decoding those as a
        # string yields control characters that print as an empty column. A row
        # with nothing in it is worse than no row: it reads as a field that was
        # read and found blank, which is not what happened.
        if not text or not text.isprintable():
            return None
        return text

    if kind in (_RATIONAL, _SRATIONAL):
        if length == 0 or length > 8:
            return None
        raw = _payload(data, entry, endian, length * 8)
        if raw is None or len(raw) < length * 8:
            return None
        fmt = endian + ("ii" if kind == _SRATIONAL else "II")
        values = []
        for index in range(length):
            numerator, denominator = struct.unpack_from(fmt, raw, index * 8)
            values.append(numerator / denominator if denominator else 0.0)
        return values[0] if length == 1 else values

    return None


def _payload(data: Raw, entry: int, endian: str, size: int) -> bytes | None:
    if size <= 4:
        return data[entry + 8 : entry + 8 + size]
    (offset,) = struct.unpack_from(endian + "I", data, entry + 8)
    if offset + size > len(data):
        return None
    return data[offset : offset + size]


# --- interpretation ----------------------------------------------------------


def camera(exif: Exif) -> str | None:
    """The device, as a human would name it, without repeating the maker."""
    make = _text(exif.get(MAKE))
    model = _text(exif.get(MODEL))
    if make and model:
        return model if model.lower().startswith(make.lower()) else f"{make} {model}"
    return make or model


def coordinates(exif: Exif) -> tuple[float, float] | None:
    """Return decimal (latitude, longitude) from the GPS IFD."""
    latitude = _degrees(exif.gps.get(GPS_LATITUDE), _text(exif.gps.get(GPS_LATITUDE_REF)), "S")
    longitude = _degrees(exif.gps.get(GPS_LONGITUDE), _text(exif.gps.get(GPS_LONGITUDE_REF)), "W")
    if latitude is None or longitude is None:
        return None
    if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
        return None
    return latitude, longitude


def _degrees(value: object, reference: str | None, negative: str) -> float | None:
    if not isinstance(value, list) or len(value) < 3:
        return None
    degrees, minutes, seconds = (float(part) for part in value[:3])
    decimal = degrees + minutes / 60 + seconds / 3600
    if reference and reference.upper().startswith(negative):
        decimal = -decimal
    return round(decimal, 6)


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
