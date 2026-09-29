"""Metadata carried by JPEG application segments outside EXIF.

JFIF describes the interchange wrapper and optional thumbnail. ICC profiles
are split over APP2 segments and can identify a colour workflow, device class,
manufacturer, model, creator and profile creation time.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

SUFFIXES = {".jpg", ".jpeg", ".jpe"}

_ICC_MARKER = b"ICC_PROFILE\x00"
_MAX_ICC_SIZE = 16 * 1024 * 1024
_MAX_ICC_TAGS = 512
_MAX_TEXT = 4096
_MAX_SEGMENTS = 4096
_MAX_SEGMENT_BYTES = 32 * 1024 * 1024


@dataclass(slots=True)
class Metadata:
    fields: dict[str, str] = field(default_factory=dict)
    icc_description: str | None = None
    icc_evidence: bool = False
    jfxx_thumbnail: bool = False

    def __bool__(self) -> bool:
        return bool(self.fields)


def read_jpeg_metadata(path: Path) -> Metadata | None:
    """Read JFIF, JFXX and ICC metadata without decoding image pixels."""
    try:
        with path.open("rb") as handle:
            if handle.read(2) != b"\xff\xd8":
                return None
            segments = list(iter_segments(handle))
    except (OSError, struct.error, ValueError):
        return None

    found = Metadata()
    for marker, payload in segments:
        if marker == 0xE0 and payload.startswith(b"JFIF\x00"):
            found.fields.update(_jfif(payload))
        elif marker == 0xE0 and payload.startswith(b"JFXX\x00"):
            fields = _jfxx(payload)
            if fields:
                found.fields.update(fields)
                found.jfxx_thumbnail = True

    profile = _icc_profile(payload for marker, payload in segments if marker == 0xE2)
    if profile:
        icc_fields, found.icc_description = _read_icc(profile)
        found.fields.update(icc_fields)
        found.icc_evidence = _icc_evidence(icc_fields, found.icc_description)
    return found if found else None


def iter_segments(handle: BinaryIO) -> Iterator[tuple[int, bytes]]:
    """Yield bounded JPEG segments after the SOI and before image data."""
    count = 0
    total = 0
    while count < _MAX_SEGMENTS and total <= _MAX_SEGMENT_BYTES:
        prefix = handle.read(1)
        if prefix != b"\xff":
            return
        marker = handle.read(1)
        while marker == b"\xff":
            marker = handle.read(1)
        if not marker:
            return
        code = marker[0]
        if code in (0xDA, 0xD9):
            return
        if code in (0x00, 0x01) or 0xD0 <= code <= 0xD8:
            continue
        length_bytes = handle.read(2)
        if len(length_bytes) != 2:
            return
        (length,) = struct.unpack(">H", length_bytes)
        if length < 2:
            return
        payload = handle.read(length - 2)
        if len(payload) != length - 2:
            return
        count += 1
        total += len(payload)
        if total > _MAX_SEGMENT_BYTES:
            return
        yield code, payload


def _jfif(payload: bytes) -> dict[str, str]:
    if len(payload) < 14:
        return {}
    major, minor, units = payload[5:8]
    x_density, y_density = struct.unpack_from(">HH", payload, 8)
    x_thumbnail, y_thumbnail = payload[12:14]
    thumbnail_size = x_thumbnail * y_thumbnail * 3
    if len(payload) < 14 + thumbnail_size:
        return {}

    unit = {0: "aspect ratio", 1: "dpi", 2: "dpcm"}.get(units, f"unknown ({units})")
    fields = {
        "JFIF:Version": f"{major}.{minor:02d}",
        "JFIF:DensityUnits": unit,
        "JFIF:XDensity": str(x_density),
        "JFIF:YDensity": str(y_density),
    }
    if x_thumbnail and y_thumbnail:
        fields["JFIF:Thumbnail"] = f"{x_thumbnail}x{y_thumbnail} RGB"
    return fields


def _jfxx(payload: bytes) -> dict[str, str]:
    if len(payload) < 6:
        return {}
    category = payload[5]
    if category == 0x10:
        return {"JFXX:ThumbnailFormat": "JPEG"} if payload[6:8] == b"\xff\xd8" else {}
    if category not in (0x11, 0x13) or len(payload) < 8:
        return {}
    width, height = payload[6:8]
    needed = width * height + (768 if category == 0x11 else width * height * 2)
    if width == 0 or height == 0 or len(payload) < 8 + needed:
        return {}
    return {
        "JFXX:ThumbnailFormat": "indexed" if category == 0x11 else "RGB",
        "JFXX:ThumbnailSize": f"{width}x{height}",
    }


def _icc_profile(segments: Iterator[bytes]) -> bytes | None:
    chunks: dict[int, bytes] = {}
    total: int | None = None
    size = 0
    for payload in segments:
        if not payload.startswith(_ICC_MARKER) or len(payload) < len(_ICC_MARKER) + 2:
            continue
        sequence, count = payload[len(_ICC_MARKER) : len(_ICC_MARKER) + 2]
        chunk = payload[len(_ICC_MARKER) + 2 :]
        if (
            count == 0
            or sequence == 0
            or sequence > count
            or (total is not None and total != count)
        ):
            return None
        if sequence in chunks:
            return None
        total = count
        chunks[sequence] = chunk
        size += len(chunk)
        if size > _MAX_ICC_SIZE:
            return None
    if total is None or set(chunks) != set(range(1, total + 1)):
        return None
    return b"".join(chunks[index] for index in range(1, total + 1))


def _read_icc(profile: bytes) -> tuple[dict[str, str], str | None]:
    if len(profile) < 132 or profile[36:40] != b"acsp":
        return {}, None
    (declared,) = struct.unpack_from(">I", profile)
    if not 132 <= declared <= len(profile):
        return {}, None
    profile = profile[:declared]

    fields = {
        "ICC:ProfileSize": str(declared),
        "ICC:Version": _icc_version(profile[8:12]),
    }
    for name, offset in (
        ("DeviceClass", 12),
        ("ColorSpace", 16),
        ("PCS", 20),
        ("Platform", 40),
        ("Manufacturer", 48),
        ("Model", 52),
        ("Creator", 80),
    ):
        if value := _signature(profile[offset : offset + 4]):
            fields[f"ICC:{name}"] = value
    if created := _icc_date(profile[24:36]):
        fields["ICC:Created"] = created

    tags = _icc_tags(profile)
    description = _icc_text(tags.get(b"desc"))
    for name, signature in (
        ("Description", b"desc"),
        ("DeviceManufacturerDescription", b"dmnd"),
        ("DeviceModelDescription", b"dmdd"),
        ("Copyright", b"cprt"),
    ):
        if value := _icc_text(tags.get(signature)):
            fields[f"ICC:{name}"] = value
    return fields, description


def _icc_version(raw: bytes) -> str:
    if len(raw) < 2:
        return "unknown"
    return f"{raw[0]}.{raw[1] >> 4}.{raw[1] & 0x0F}"


def _icc_evidence(fields: dict[str, str], description: str | None) -> bool:
    """Whether the profile identifies a workflow beyond a standard colour space."""
    device_class = fields.get("ICC:DeviceClass")
    if device_class in {"scnr", "prtr", "link", "nmcl"}:
        return True
    manufacturer = fields.get("ICC:Manufacturer", "").casefold()
    model = fields.get("ICC:Model", "").casefold()
    if (manufacturer, model) not in {("", ""), ("iec", "srgb")}:
        return True
    generic = {
        "adobe rgb (1998)",
        "display p3",
        "generic rgb profile",
        "srgb iec61966-2.1",
    }
    return bool(description and description.casefold().strip() not in generic)


def _signature(raw: bytes) -> str | None:
    if len(raw) != 4 or not any(raw) or any(byte < 32 or byte > 126 for byte in raw):
        return None
    return raw.decode("ascii").rstrip() or None


def _icc_date(raw: bytes) -> str | None:
    if len(raw) != 12:
        return None
    values = struct.unpack(">6H", raw)
    try:
        moment = datetime(*values)
    except ValueError:
        return None
    if not 1980 <= moment.year <= 2100:
        return None
    return moment.isoformat(timespec="seconds")


def _icc_tags(profile: bytes) -> dict[bytes, bytes]:
    (count,) = struct.unpack_from(">I", profile, 128)
    found: dict[bytes, bytes] = {}
    for index in range(min(count, _MAX_ICC_TAGS)):
        entry = 132 + index * 12
        if entry + 12 > len(profile):
            break
        signature, offset, size = struct.unpack_from(">4sII", profile, entry)
        if size <= _MAX_TEXT * 4 and offset >= 128 and offset + size <= len(profile):
            found.setdefault(signature, profile[offset : offset + size])
    return found


def _icc_text(blob: bytes | None) -> str | None:
    if not blob or len(blob) < 8:
        return None
    category = blob[:4]
    if category == b"desc" and len(blob) >= 12:
        (length,) = struct.unpack_from(">I", blob, 8)
        if 0 < length <= _MAX_TEXT and 12 + length <= len(blob):
            return _clean_text(blob[12 : 12 + length].split(b"\x00", 1)[0], "ascii")
    if category == b"text":
        return _clean_text(blob[8:].split(b"\x00", 1)[0], "ascii")
    if category == b"mluc" and len(blob) >= 28:
        count, record_size = struct.unpack_from(">II", blob, 8)
        if count == 0 or record_size < 12 or 16 + record_size > len(blob):
            return None
        length, offset = struct.unpack_from(">II", blob, 20)
        if 0 < length <= _MAX_TEXT * 2 and offset >= 16 and offset + length <= len(blob):
            return _clean_text(blob[offset : offset + length], "utf-16-be")
    return None


def _clean_text(raw: bytes, encoding: str) -> str | None:
    value = raw.decode(encoding, "replace").strip().strip("\x00").strip()
    if not value or any(ord(character) < 32 and character not in "\t\r\n" for character in value):
        return None
    return value
