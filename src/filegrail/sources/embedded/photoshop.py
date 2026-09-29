"""Photoshop Image Resource Blocks carried by JPEG, TIFF, PSD and PSB."""

from __future__ import annotations

import re
import struct
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

JPEG_SUFFIXES = {".jpg", ".jpeg", ".jpe"}
TIFF_SUFFIXES = {".tif", ".tiff"}
DOCUMENT_SUFFIXES = {".psd", ".psb"}
SUFFIXES = JPEG_SUFFIXES | TIFF_SUFFIXES | DOCUMENT_SUFFIXES

_MARKER = b"8BIM"
_WINDOW = 4 * 1024 * 1024
_MAX_RESOURCE = 4 * 1024 * 1024
_MAX_RESOURCES = 2048
_MAX_NAME = 255
_MAX_TEXT = 4096

_RESOLUTION = 0x03ED
_JPEG_QUALITY = 0x0406
_THUMBNAILS = {0x0409, 0x040C}
_COPYRIGHT_FLAG = 0x040A
_URL_RESOURCES = {0x040B, 0x041B, 0x041E}
_VERSION_INFO = 0x0421
_PATH_MIN = 0x07D0
_PATH_MAX = 0x0BB6

_URL = re.compile(r"https?://[^\x00\s<>\"']{1,2048}", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Resource:
    identifier: int
    name: str | None
    payload: bytes


@dataclass(slots=True)
class Metadata:
    fields: dict[str, str] = field(default_factory=dict)
    tool: str | None = None
    note: str | None = None

    def __bool__(self) -> bool:
        return bool(self.fields)


def read_photoshop_metadata(path: Path) -> Metadata | None:
    """Decode provenance-relevant, bounded Photoshop resources."""
    resources = _read_resources(path)
    if not resources:
        return None

    found = Metadata()
    thumbnails = 0
    paths = 0
    urls: list[str] = []
    for resource in resources:
        if resource.identifier == _RESOLUTION:
            found.fields.update(_resolution(resource.payload))
        elif resource.identifier == _JPEG_QUALITY:
            found.fields.update(_jpeg_quality(resource.payload))
        elif resource.identifier in _THUMBNAILS:
            if fields := _thumbnail(resource.payload):
                thumbnails += 1
                found.fields.update(
                    {
                        f"Photoshop:Thumbnail[{thumbnails}]:{name}": value
                        for name, value in fields.items()
                    }
                )
        elif resource.identifier == _COPYRIGHT_FLAG and resource.payload:
            found.fields["Photoshop:CopyrightFlag"] = (
                "set" if any(resource.payload[:1]) else "not set"
            )
        elif resource.identifier in _URL_RESOURCES:
            for value in _urls(resource.payload):
                if value not in urls:
                    urls.append(value)
        elif resource.identifier == _VERSION_INFO:
            fields, tool = _version_info(resource.payload)
            found.fields.update(fields)
            found.tool = found.tool or tool
        elif _PATH_MIN <= resource.identifier <= _PATH_MAX and resource.name:
            paths += 1
            found.fields[f"Photoshop:Path[{paths}]:Name"] = resource.name
            if len(resource.payload) % 26 == 0:
                found.fields[f"Photoshop:Path[{paths}]:Records"] = str(len(resource.payload) // 26)

    for index, value in enumerate(urls, 1):
        found.fields[f"Photoshop:URL[{index}]"] = value
    notes = []
    if thumbnails:
        notes.append(f"Photoshop thumbnails {thumbnails}")
    if paths:
        notes.append(f"Photoshop paths {paths}")
    if urls:
        notes.append(f"Photoshop URLs {len(urls)}")
    found.note = "; ".join(notes) or None
    return found if found else None


def find_resource(data: bytes, identifier: int) -> bytes:
    """Return the first complete resource payload with this identifier."""
    for resource in iter_resources(data):
        if resource.identifier == identifier:
            return resource.payload
    return b""


def iter_resources(data: bytes) -> Iterator[Resource]:
    """Walk complete 8BIM resources found in a bounded container window."""
    cursor = 0
    count = 0
    while count < _MAX_RESOURCES and (at := data.find(_MARKER, cursor)) >= 0:
        cursor = at + len(_MARKER)
        if at + 7 > len(data):
            return
        (identifier,) = struct.unpack_from(">H", data, at + 4)
        name_length = data[at + 6]
        if name_length > _MAX_NAME:
            continue
        name_start = at + 7
        name_end = name_start + name_length
        padded_name_end = name_end + ((1 + name_length) % 2)
        if padded_name_end + 4 > len(data):
            continue
        (length,) = struct.unpack_from(">I", data, padded_name_end)
        payload_start = padded_name_end + 4
        payload_end = payload_start + length
        if length > _MAX_RESOURCE or payload_end > len(data):
            continue
        raw_name = data[name_start:name_end]
        name = raw_name.decode("latin-1", "replace").strip() or None
        yield Resource(identifier, name, data[payload_start:payload_end])
        count += 1
        cursor = payload_end + (length % 2)


def _read_resources(path: Path) -> list[Resource]:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if path.suffix.lower() in TIFF_SUFFIXES | DOCUMENT_SUFFIXES:
                windows = [handle.read(_WINDOW)]
            elif size <= _WINDOW * 2:
                windows = [handle.read(_WINDOW * 2)]
            else:
                windows = [handle.read(_WINDOW)]
                handle.seek(size - _WINDOW)
                windows.append(handle.read(_WINDOW))
    except OSError:
        return []

    found: list[Resource] = []
    seen: set[tuple[int, str | None, bytes]] = set()
    for window in windows:
        for resource in iter_resources(window):
            key = (resource.identifier, resource.name, resource.payload)
            if key not in seen:
                seen.add(key)
                found.append(resource)
    return found


def _resolution(payload: bytes) -> dict[str, str]:
    if len(payload) < 16:
        return {}
    horizontal, horizontal_unit, width_unit, vertical, vertical_unit, height_unit = (
        struct.unpack_from(">IHHIHH", payload)
    )
    return {
        "Photoshop:XResolution": _fixed(horizontal),
        "Photoshop:XResolutionUnit": _resolution_unit(horizontal_unit),
        "Photoshop:WidthUnit": _dimension_unit(width_unit),
        "Photoshop:YResolution": _fixed(vertical),
        "Photoshop:YResolutionUnit": _resolution_unit(vertical_unit),
        "Photoshop:HeightUnit": _dimension_unit(height_unit),
    }


def _jpeg_quality(payload: bytes) -> dict[str, str]:
    if len(payload) < 6:
        return {}
    quality, format_code, scans = struct.unpack_from(">hHH", payload)
    return {
        "Photoshop:JPEGQuality": str(quality),
        "Photoshop:JPEGFormat": str(format_code),
        "Photoshop:JPEGScans": str(scans),
    }


def _thumbnail(payload: bytes) -> dict[str, str]:
    if len(payload) < 28:
        return {}
    format_code, width, height, row_bytes, total, compressed, bits, planes = struct.unpack_from(
        ">6I2H", payload
    )
    if not 0 < width <= 1_000_000 or not 0 < height <= 1_000_000:
        return {}
    if compressed > len(payload) - 28:
        return {}
    return {
        "Format": {0: "raw RGB", 1: "JPEG"}.get(format_code, str(format_code)),
        "Size": f"{width}x{height}",
        "RowBytes": str(row_bytes),
        "UncompressedSize": str(total),
        "CompressedSize": str(compressed),
        "BitsPerPixel": str(bits),
        "Planes": str(planes),
    }


def _version_info(payload: bytes) -> tuple[dict[str, str], str | None]:
    if len(payload) < 9:
        return {}, None
    version = struct.unpack_from(">I", payload)[0]
    merged = payload[4]
    writer, cursor = _unicode_string(payload, 5)
    if cursor < 0:
        return {}, None
    reader, cursor = _unicode_string(payload, cursor)
    if cursor < 0 or cursor + 4 > len(payload):
        return {}, None
    file_version = struct.unpack_from(">I", payload, cursor)[0]
    fields = {
        "Photoshop:VersionInfo": str(version),
        "Photoshop:HasRealMergedData": "yes" if merged else "no",
        "Photoshop:FileVersion": str(file_version),
    }
    if writer:
        fields["Photoshop:Writer"] = writer
    if reader:
        fields["Photoshop:Reader"] = reader
    return fields, writer or reader


def _unicode_string(payload: bytes, offset: int) -> tuple[str | None, int]:
    if offset + 4 > len(payload):
        return None, -1
    (count,) = struct.unpack_from(">I", payload, offset)
    if count > _MAX_TEXT or offset + 4 + count * 2 > len(payload):
        return None, -1
    end = offset + 4 + count * 2
    value = payload[offset + 4 : end].decode("utf-16-be", "replace").strip("\x00").strip()
    return value or None, end


def _urls(payload: bytes) -> list[str]:
    values: list[str] = []
    for encoding in ("utf-8", "utf-16-be", "utf-16-le"):
        text = payload[: _MAX_TEXT * 2].decode(encoding, "ignore")
        values.extend(match.group(0).rstrip(".,;)") for match in _URL.finditer(text))
    return list(dict.fromkeys(values))[:32]


def _fixed(value: int) -> str:
    return f"{value / 65536:.4f}".rstrip("0").rstrip(".")


def _resolution_unit(value: int) -> str:
    return {1: "pixels/inch", 2: "pixels/cm"}.get(value, str(value))


def _dimension_unit(value: int) -> str:
    return {1: "inches", 2: "cm", 3: "points", 4: "picas", 5: "columns"}.get(value, str(value))
