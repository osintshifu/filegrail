"""Bounded JPEG structure analysis without decoding image pixels."""

from __future__ import annotations

import struct
from dataclasses import dataclass, replace
from pathlib import Path
from typing import BinaryIO

from .preview import jpeg_dimensions
from .redact import redact_text

_MAX_SEGMENTS = 8192
_MAX_TABLES = 32
_MAX_COMMENT = 4096

_NAMES = {
    0xC0: "SOF0",
    0xC1: "SOF1",
    0xC2: "SOF2",
    0xC3: "SOF3",
    0xC4: "DHT",
    0xC5: "SOF5",
    0xC6: "SOF6",
    0xC7: "SOF7",
    0xC9: "SOF9",
    0xCA: "SOF10",
    0xCB: "SOF11",
    0xCD: "SOF13",
    0xCE: "SOF14",
    0xCF: "SOF15",
    0xD8: "SOI",
    0xD9: "EOI",
    0xDA: "SOS",
    0xDB: "DQT",
    0xDD: "DRI",
    0xFE: "COM",
}
_ENCODINGS = {
    0xC0: "baseline DCT",
    0xC1: "extended sequential DCT",
    0xC2: "progressive DCT",
    0xC3: "lossless sequential",
    0xC5: "differential sequential DCT",
    0xC6: "differential progressive DCT",
    0xC7: "differential lossless",
    0xC9: "arithmetic extended sequential DCT",
    0xCA: "arithmetic progressive DCT",
    0xCB: "arithmetic lossless sequential",
    0xCD: "arithmetic differential sequential DCT",
    0xCE: "arithmetic differential progressive DCT",
    0xCF: "arithmetic differential lossless",
}


#: How much of a segment is kept so a report can show the bytes it is talking
#: about. Enough for the marker, its declared length and the field that names it
#: - `Exif\x00\x00II*`, `JFIF\x00`, a quantization table's precision - and short
#: enough that a file with hundreds of segments costs nothing to carry.
HEAD_BYTES = 16


@dataclass(frozen=True, slots=True)
class JpegMarker:
    name: str
    code: int
    offset: int
    length: int
    #: The opening bytes of the segment as they lie in the file, so a byte map
    #: can print them rather than describe them.
    head: bytes = b""


@dataclass(frozen=True, slots=True)
class QuantizationTable:
    identifier: int
    precision: int
    values: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class HuffmanTable:
    table_class: str
    identifier: int
    symbols: int


@dataclass(frozen=True, slots=True)
class QualityEstimate:
    quality: int
    exact: bool
    distance: int


@dataclass(frozen=True, slots=True)
class JpegAnalysis:
    width: int | None
    height: int | None
    encoding: str | None
    precision: int | None
    components: tuple[tuple[int, int, int, int], ...]
    scans: int
    restart_interval: int | None
    markers: tuple[JpegMarker, ...]
    quantization: tuple[QuantizationTable, ...]
    huffman: tuple[HuffmanTable, ...]
    comments: tuple[str, ...]
    eoi_offset: int | None
    trailing_bytes: int
    quality: QualityEstimate | None

    def redacted(self) -> JpegAnalysis:
        """The same analysis with the text the file carried put through redaction.

        A comment is free text a camera or an editor wrote, so it can hold what
        any other free text can, and it reaches the report as written. Named the
        same as `EvidenceRecord.redacted` because it answers for the same promise.
        Everything else here is measured rather than quoted.
        """
        # A comment segment's opening bytes are the comment, so the head that
        # lets a byte map print what it names would put the text back into the
        # report a line below where redaction took it out.
        markers = tuple(
            replace(marker, head=b"") if marker.code == 0xFE else marker for marker in self.markers
        )
        return replace(
            self,
            comments=tuple(redact_text(value) for value in self.comments),
            markers=markers,
        )


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    return jpeg_dimensions(data)


def analyse_jpeg(path: Path) -> JpegAnalysis | None:
    """Read the marker structure of one JPEG, returning none for other bytes."""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if handle.read(2) != b"\xff\xd8":
                return None
            return _walk(handle, size)
    except (OSError, ValueError, struct.error):
        return None


def _walk(handle: BinaryIO, file_size: int) -> JpegAnalysis | None:
    markers = [JpegMarker("SOI", 0xD8, 0, 2, b"\xff\xd8")]
    quantization: list[QuantizationTable] = []
    huffman: list[HuffmanTable] = []
    comments: list[str] = []
    width = height = precision = None
    components: tuple[tuple[int, int, int, int], ...] = ()
    encoding = None
    scans = 0
    restart_interval = None
    eoi_offset = None
    pending: tuple[int, int] | None = None

    while len(markers) < _MAX_SEGMENTS:
        found = pending or _next_marker(handle)
        pending = None
        if found is None:
            break
        code, offset = found
        name = _marker_name(code)
        if code == 0xD9:
            markers.append(JpegMarker(name, code, offset, 2, bytes((0xFF, code))))
            eoi_offset = offset
            break
        if code == 0x01 or 0xD0 <= code <= 0xD8:
            markers.append(JpegMarker(name, code, offset, 2, bytes((0xFF, code))))
            continue
        length_raw = handle.read(2)
        if len(length_raw) != 2:
            return None
        length = struct.unpack(">H", length_raw)[0]
        if length < 2:
            return None
        payload = handle.read(length - 2)
        if len(payload) != length - 2:
            return None
        head = bytes((0xFF, code)) + length_raw + payload
        markers.append(JpegMarker(name, code, offset, length + 2, head[:HEAD_BYTES]))

        if code in _ENCODINGS:
            frame = _frame(payload)
            if frame is None:
                return None
            precision, height, width, components = frame
            encoding = _ENCODINGS[code]
        elif code == 0xDB:
            parsed = _dqt(payload)
            if parsed is None or len(quantization) + len(parsed) > _MAX_TABLES:
                return None
            quantization.extend(parsed)
        elif code == 0xC4:
            parsed_huffman = _dht(payload)
            if parsed_huffman is None or len(huffman) + len(parsed_huffman) > _MAX_TABLES:
                return None
            huffman.extend(parsed_huffman)
        elif code == 0xDD:
            if len(payload) != 2:
                return None
            restart_interval = struct.unpack(">H", payload)[0]
        elif code == 0xFE:
            comments.append(payload[:_MAX_COMMENT].decode("utf-8", "replace").strip())
        elif code == 0xDA:
            scans += 1
            pending, restarts = _entropy_marker(handle, markers)
            if restarts + len(markers) >= _MAX_SEGMENTS:
                return None

    trailing = file_size - eoi_offset - 2 if eoi_offset is not None else 0
    return JpegAnalysis(
        width,
        height,
        encoding,
        precision,
        components,
        scans,
        restart_interval,
        tuple(markers),
        tuple(quantization),
        tuple(huffman),
        tuple(value for value in comments if value),
        eoi_offset,
        max(0, trailing),
        _estimate_quality(quantization),
    )


def _next_marker(handle: BinaryIO) -> tuple[int, int] | None:
    while True:
        offset = handle.tell()
        prefix = handle.read(1)
        if not prefix:
            return None
        if prefix != b"\xff":
            return None
        marker = handle.read(1)
        while marker == b"\xff":
            marker = handle.read(1)
        if not marker:
            return None
        if marker != b"\x00":
            return marker[0], offset


#: How much of an entropy-coded scan to search at a time.
_ENTROPY_BLOCK = 1 << 16


def _entropy_marker(
    handle: BinaryIO, markers: list[JpegMarker]
) -> tuple[tuple[int, int] | None, int]:
    """The marker ending the entropy-coded scan, and the restarts found in it.

    The scan is most of the file and holds no marker until it ends, so this walk
    covers nearly every byte of the photograph. Searched a block at a time with
    `bytes.find` rather than a byte at a time: the same work read one byte per
    call costs a `tell` and a `read` for every byte of every file, which is what
    put a folder of two hundred photographs beyond use.

    A `0xFF` is a marker unless the byte after it is `0x00`, which is how the
    scan escapes one in its own data. A run of them is padding before the real
    marker, and the position reported is the first of the run.
    """
    restarts = 0
    base = handle.tell()
    block = handle.read(_ENTROPY_BLOCK)
    at = 0
    while True:
        first = block.find(0xFF, at)
        last = first
        while last >= 0 and last + 1 < len(block) and block[last + 1] == 0xFF:
            last += 1
        if first < 0 or last + 2 > len(block):
            # No marker in what is in hand, or one that straddles the end of it.
            # Whatever might still be part of a marker is kept and read on from.
            keep = len(block) if first < 0 else first
            base += keep
            block = block[keep:]
            more = handle.read(_ENTROPY_BLOCK)
            if not more:
                # The file ends inside what could have been a marker, so there is
                # no byte left to decide on and the scan has no end. Returning on
                # the read rather than on what is held is what ends the walk: a
                # file whose last bytes are 0xFF keeps two of them in hand for
                # ever, and testing the buffer alone never terminates.
                handle.seek(base + len(block))
                return None, restarts
            block += more
            at = 0
            continue
        code = block[last + 1]
        if code == 0x00:
            at = last + 2
            continue
        if 0xD0 <= code <= 0xD7:
            if len(markers) >= _MAX_SEGMENTS:
                # The file's whole marker budget is spent inside this one scan.
                # Counted here rather than on the way out, so a file declaring
                # millions of restarts cannot be read into memory first.
                handle.seek(base + last + 2)
                return None, restarts
            markers.append(
                JpegMarker(_marker_name(code), code, base + first, 2, bytes((0xFF, code)))
            )
            restarts += 1
            at = last + 2
            continue
        handle.seek(base + last + 2)
        return (code, base + first), restarts


def _marker_name(code: int) -> str:
    if 0xD0 <= code <= 0xD7:
        return f"RST{code - 0xD0}"
    if 0xE0 <= code <= 0xEF:
        return f"APP{code - 0xE0}"
    return _NAMES.get(code, f"0x{code:02X}")


def _frame(payload: bytes) -> tuple[int, int, int, tuple[tuple[int, int, int, int], ...]] | None:
    if len(payload) < 6:
        return None
    precision, height, width, count = struct.unpack_from(">BHHB", payload)
    if width == 0 or height == 0 or count == 0 or len(payload) != 6 + count * 3:
        return None
    components = []
    for cursor in range(6, len(payload), 3):
        identifier, sampling, table = payload[cursor : cursor + 3]
        horizontal, vertical = sampling >> 4, sampling & 0x0F
        if horizontal == 0 or vertical == 0:
            return None
        components.append((identifier, horizontal, vertical, table))
    return precision, height, width, tuple(components)


def _dqt(payload: bytes) -> list[QuantizationTable] | None:
    tables = []
    cursor = 0
    while cursor < len(payload):
        info = payload[cursor]
        cursor += 1
        precision, identifier = info >> 4, info & 0x0F
        if precision not in (0, 1):
            return None
        width = 1 if precision == 0 else 2
        end = cursor + 64 * width
        if end > len(payload):
            return None
        if width == 1:
            values = tuple(payload[cursor:end])
        else:
            values = tuple(
                struct.unpack_from(">H", payload, cursor + index * 2)[0] for index in range(64)
            )
        if any(value == 0 for value in values):
            return None
        tables.append(QuantizationTable(identifier, width * 8, values))
        cursor = end
    return tables


def _dht(payload: bytes) -> list[HuffmanTable] | None:
    tables = []
    cursor = 0
    while cursor < len(payload):
        if cursor + 17 > len(payload):
            return None
        info = payload[cursor]
        cursor += 1
        table_class, identifier = info >> 4, info & 0x0F
        if table_class not in (0, 1):
            return None
        symbols = sum(payload[cursor : cursor + 16])
        cursor += 16
        if symbols > 256 or cursor + symbols > len(payload):
            return None
        cursor += symbols
        tables.append(HuffmanTable("DC" if table_class == 0 else "AC", identifier, symbols))
    return tables


# Annex K tables in JPEG zig-zag storage order.
_LUMA = (
    16,
    11,
    12,
    14,
    12,
    10,
    16,
    14,
    13,
    14,
    18,
    17,
    16,
    19,
    24,
    40,
    26,
    24,
    22,
    22,
    24,
    49,
    35,
    37,
    29,
    40,
    58,
    51,
    61,
    60,
    57,
    51,
    56,
    55,
    64,
    72,
    92,
    78,
    64,
    68,
    87,
    69,
    55,
    56,
    80,
    109,
    81,
    87,
    95,
    98,
    103,
    104,
    103,
    62,
    77,
    113,
    121,
    112,
    100,
    120,
    92,
    101,
    103,
    99,
)
_CHROMA = (
    17,
    18,
    18,
    24,
    21,
    24,
    47,
    26,
    26,
    47,
    99,
    66,
    56,
    66,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
    99,
)


def _scaled(base: tuple[int, ...], quality: int) -> tuple[int, ...]:
    scale = 5000 // quality if quality < 50 else 200 - quality * 2
    return tuple(max(1, min(255, (value * scale + 50) // 100)) for value in base)


def _estimate_quality(tables: list[QuantizationTable]) -> QualityEstimate | None:
    observed = {table.identifier: table.values for table in tables if table.precision == 8}
    if not observed or not set(observed).issubset({0, 1}):
        return None
    best: tuple[int, int] | None = None
    for quality in range(1, 101):
        expected = {0: _scaled(_LUMA, quality), 1: _scaled(_CHROMA, quality)}
        distance = sum(
            abs(value - expected[identifier][index])
            for identifier, values in observed.items()
            for index, value in enumerate(values)
        )
        if distance == 0:
            return QualityEstimate(quality, True, 0)
        if best is None or distance < best[0]:
            best = (distance, quality)
    return QualityEstimate(best[1], False, best[0]) if best is not None else None
