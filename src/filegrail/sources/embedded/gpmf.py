"""Camera telemetry: GoPro's GPMF and Google's CAMM, summarised.

An action camera writes a second track beside the video with what its sensors
saw: a GPS fix every second, the accelerometer and gyroscope hundreds of times
a second, the device's own name. For provenance the summary is what matters -
which device, where the recording started and ended, and when by the GPS
clock, which is set by satellites rather than by whoever owns the camera.

Samples are decoded into a running summary and never kept: a long recording
holds millions of sensor readings and none of them is evidence on its own.

GPMF is a key-length-value format: a four-character key, a type character, a
sample size, a repeat count and the data, nested where the type is zero. CAMM
is a fixed record per sample with a type number in front.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

_MAX_DEPTH = 8
_MAX_ITEMS = 4096
_MAX_STREAMS = 16
_MAX_DEVICES = 4
_MAX_TEXT = 128

#: GPMF type characters and the struct code that reads one element.
_FORMATS = {
    b"b": "b",
    b"B": "B",
    b"s": "h",
    b"S": "H",
    b"l": "i",
    b"L": "I",
    b"f": "f",
    b"d": "d",
    b"j": "q",
    b"J": "Q",
}

_NESTED = b"\x00"
_TEXT = b"c"
_UTC = b"U"
_COMPLEX = b"?"

_EPOCH_2000 = datetime(2000, 1, 1, tzinfo=timezone.utc)

_DESCRIPTION = {b"DVNM", b"STNM", b"TYPE", b"SCAL", b"GPSU", b"GPSF"}
_DATA = {b"GPS5", b"GPS9"}

#: CAMM record types that carry a position.
_CAMM_MIN_GPS = 5
_CAMM_GPS = 6


@dataclass(slots=True)
class Telemetry:
    """The summary of one metadata track."""

    kind: str
    devices: list[str] = field(default_factory=list)
    streams: list[str] = field(default_factory=list)
    gps_points: int = 0
    gps_first: tuple[float, float] | None = None
    gps_last: tuple[float, float] | None = None
    gps_start: str | None = None
    gps_end: str | None = None
    gps_fix: int | None = None

    def __bool__(self) -> bool:
        return bool(self.devices or self.streams or self.gps_points)

    def _point(self, latitude: float, longitude: float, when: str | None, fix: int | None) -> None:
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return
        point = (round(latitude, 6), round(longitude, 6))
        if self.gps_first is None:
            self.gps_first = point
        self.gps_last = point
        self.gps_points += 1
        if when:
            self.gps_start = self.gps_start or when
            self.gps_end = when
        if fix is not None:
            self.gps_fix = max(self.gps_fix or 0, fix)


# --- GPMF -------------------------------------------------------------------


def absorb_gpmf(sample: bytes, found: Telemetry) -> None:
    """Fold one GPMF sample into the summary."""
    try:
        _walk(sample, 0, len(sample), 0, found, {})
    except (struct.error, ValueError, OverflowError):
        return


def _walk(
    data: bytes, offset: int, end: int, depth: int, found: Telemetry, context: dict[str, object]
) -> None:
    if depth > _MAX_DEPTH:
        return
    # A stream describes its data before writing it - scale, type, clock - but
    # nothing forbids the other order, so the description is read first.
    items = _items(data, offset, end)
    for key, kind, size, repeat, body in items:
        if kind != _NESTED and key in _DESCRIPTION:
            _measure(key, kind, size, repeat, data[body : body + size * repeat], found, context)
    for key, kind, size, repeat, body in items:
        if kind == _NESTED:
            _walk(data, body, body + size * repeat, depth + 1, found, dict(context))
        elif key in _DATA:
            _measure(key, kind, size, repeat, data[body : body + size * repeat], found, context)


def _items(data: bytes, offset: int, end: int) -> list[tuple[bytes, bytes, int, int, int]]:
    items: list[tuple[bytes, bytes, int, int, int]] = []
    while offset + 8 <= end and len(items) < _MAX_ITEMS:
        key = data[offset : offset + 4]
        kind = data[offset + 4 : offset + 5]
        size = data[offset + 5]
        (repeat,) = struct.unpack_from(">H", data, offset + 6)
        body = offset + 8
        length = size * repeat
        if body + length > end:
            break
        items.append((key, kind, size, repeat, body))
        offset = body + ((length + 3) & ~3)
    return items


def _measure(
    key: bytes,
    kind: bytes,
    size: int,
    repeat: int,
    payload: bytes,
    found: Telemetry,
    context: dict[str, object],
) -> None:
    if kind == _TEXT:
        text = payload.decode("latin-1", "replace").strip("\x00 ")[:_MAX_TEXT]
        if (
            key == b"DVNM"
            and text
            and text not in found.devices
            and len(found.devices) < _MAX_DEVICES
        ):
            found.devices.append(text)
        elif key == b"STNM" and text and text not in found.streams:
            if len(found.streams) < _MAX_STREAMS:
                found.streams.append(text)
        elif key == b"TYPE":
            context["type_string"] = text
        return
    if key == b"SCAL" and kind in _FORMATS:
        context["scale_values"] = list(_numbers(kind, size, repeat, payload))
        return
    if key == b"GPSU" and kind == _UTC:
        context["utc"] = _utc(payload[:16])
        return
    if key == b"GPSF" and kind in _FORMATS:
        values = list(_numbers(kind, size, repeat, payload))
        if values:
            context["fix"] = int(values[0])
        return
    if key == b"GPS5" and kind in _FORMATS and size == 20:
        scale = _scale(context, 5)
        for point in _rows(kind, 5, repeat, payload):
            when = context.get("utc")
            fix = context.get("fix")
            found._point(
                point[0] / scale[0],
                point[1] / scale[1],
                when if isinstance(when, str) else None,
                fix if isinstance(fix, int) else None,
            )
        return
    if key == b"GPS9" and kind == _COMPLEX:
        layout = context.get("type_string")
        if not isinstance(layout, str) or len(layout) < 9:
            return
        codes = [_FORMATS.get(char.encode("ascii")) for char in layout]
        if any(code is None for code in codes):
            return
        fmt = ">" + "".join(code for code in codes if code)
        if struct.calcsize(fmt) != size:
            return
        scale = _scale(context, len(codes))
        for at in range(0, size * repeat, size):
            row = struct.unpack_from(fmt, payload, at)
            days, millis = row[5], row[6]
            when = None
            if isinstance(days, int) and isinstance(millis, int) and 0 <= days < 40000:
                moment = _EPOCH_2000 + timedelta(days=days, milliseconds=millis)
                when = moment.isoformat(timespec="seconds").replace("+00:00", "Z")
            fix = int(row[8]) if len(row) > 8 else None
            found._point(row[0] / scale[0], row[1] / scale[1], when, fix)


def _scale(context: dict[str, object], count: int) -> list[float]:
    values = context.get("scale_values")
    scale = [float(v) for v in values] if isinstance(values, list) else []
    scale = [v if v else 1.0 for v in scale]
    if len(scale) == 1:
        scale = scale * count
    while len(scale) < count:
        scale.append(1.0)
    return scale


def _numbers(kind: bytes, size: int, repeat: int, payload: bytes) -> list[float]:
    code = _FORMATS[kind]
    width = struct.calcsize(code)
    if width == 0 or size % width:
        return []
    per = size // width
    return [
        float(value)
        for value in struct.unpack_from(f">{per * repeat}{code}", payload, 0)
        if isinstance(value, (int, float))
    ][: per * repeat]


def _rows(kind: bytes, columns: int, repeat: int, payload: bytes) -> list[tuple[float, ...]]:
    code = _FORMATS[kind]
    width = struct.calcsize(code) * columns
    rows: list[tuple[float, ...]] = []
    for at in range(0, min(len(payload), width * repeat), width):
        rows.append(tuple(float(v) for v in struct.unpack_from(f">{columns}{code}", payload, at)))
    return rows


def _utc(raw: bytes) -> str | None:
    """GoPro writes the GPS clock as `yymmddhhmmss.sss`."""
    text = raw.decode("ascii", "replace")
    try:
        moment = datetime.strptime(text[:12], "%y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return moment.isoformat().replace("+00:00", "Z")


# --- CAMM -------------------------------------------------------------------


def absorb_camm(sample: bytes, found: Telemetry) -> None:
    """Fold one CAMM sample into the summary: only the position records."""
    if len(sample) < 4:
        return
    (kind,) = struct.unpack_from("<H", sample, 2)
    try:
        if kind == _CAMM_MIN_GPS and len(sample) >= 28:
            latitude, longitude, _ = struct.unpack_from("<ddd", sample, 4)
            found._point(latitude, longitude, None, None)
        elif kind == _CAMM_GPS and len(sample) >= 40:
            epoch, fix, latitude, longitude, _ = struct.unpack_from("<diddd", sample, 4)
            when = None
            if 0 < epoch < 4_102_444_800:  # before 2100
                moment = datetime.fromtimestamp(epoch, tz=timezone.utc)
                when = moment.isoformat(timespec="seconds").replace("+00:00", "Z")
            found._point(latitude, longitude, when, int(fix))
    except (struct.error, ValueError, OverflowError, OSError):
        return
    if "position" not in found.streams:
        found.streams.append("position")
