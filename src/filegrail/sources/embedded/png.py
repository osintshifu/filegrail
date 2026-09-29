"""PNG textual chunks.

PNG carries free-form key/value text in `tEXt`, `zTXt` and `iTXt` chunks. The
conventional keys name the producing software, and generative image tools have
adopted the same chunks to record the prompt and model that made the picture -
which is provenance of the most direct kind.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from pathlib import Path

from ..compression import decompress_zlib

SUFFIXES = {".png", ".apng"}

_MAGIC = b"\x89PNG\r\n\x1a\n"
_TEXT_CHUNKS = (b"tEXt", b"zTXt", b"iTXt")
_EXIF_CHUNK = b"eXIf"
_STOP_CHUNKS = (b"IDAT", b"IEND")
_MAX_CHUNK = 1024 * 1024
_MAX_VALUE = 4096

#: Keys that name the producing tool, most specific first.
SOFTWARE_KEYS = ("Software", "Source", "Creator", "generator")
#: Keys used by generative image tools to record how the picture was made.
GENERATOR_KEYS = ("parameters", "prompt", "Comment", "workflow", "sd-metadata", "Dream")
DATE_KEYS = ("Creation Time", "create-date", "date:create")
AUTHOR_KEYS = ("Author", "Artist", "Copyright")

#: The keyword PNG reserves for an XMP packet.
XMP_KEYWORD = "XML:com.adobe.xmp"


def read_png_text(path: Path) -> dict[str, str]:
    """Return the decoded text chunks of a PNG, keyed by their keyword."""
    found: dict[str, str] = {}
    for chunk_type, payload in _text_chunks(path):
        _absorb(chunk_type, payload, found)
    return found


def read_exif_chunk(path: Path) -> bytes:
    """The TIFF-shaped payload of the `eXIf` chunk, or nothing."""
    for _chunk_type, payload in _chunks(path, (_EXIF_CHUNK,)):
        return payload
    return b""


def read_xmp_packet(path: Path) -> str | None:
    """The XMP packet an iTXt chunk carries, inflated and unclipped.

    `read_png_text` clips every value, which is right for a report and wrong for
    a packet that still has to parse as XML afterwards. PNG is also the one
    container that may deflate the packet, putting it beyond any search over the
    file's raw bytes.
    """
    for chunk_type, payload in _text_chunks(path):
        keyword, separator, rest = payload.partition(b"\x00")
        if not separator or chunk_type != b"iTXt":
            continue
        if keyword.decode("latin-1", "replace").strip() != XMP_KEYWORD:
            continue
        try:
            return _decode_itxt(rest, limit=_MAX_CHUNK)
        except (ValueError, IndexError):
            return None
    return None


def _text_chunks(path: Path) -> Iterator[tuple[bytes, bytes]]:
    """Every text chunk of a PNG, as (type, payload), until the image data."""
    yield from _chunks(path, _TEXT_CHUNKS)


def _chunks(path: Path, wanted: tuple[bytes, ...]) -> Iterator[tuple[bytes, bytes]]:
    """The chunks of `wanted` types, as (type, payload), until the image data."""
    try:
        with path.open("rb") as handle:
            if handle.read(8) != _MAGIC:
                return
            while True:
                header = handle.read(8)
                if len(header) < 8:
                    return
                length, chunk_type = struct.unpack(">I4s", header)
                if chunk_type in _STOP_CHUNKS:
                    return
                if chunk_type in wanted and length <= _MAX_CHUNK:
                    yield chunk_type, handle.read(length)
                    handle.read(4)  # CRC
                    continue
                handle.seek(length + 4, 1)
    except (OSError, struct.error, ValueError):
        return


def _absorb(chunk_type: bytes, payload: bytes, found: dict[str, str]) -> None:
    keyword, separator, rest = payload.partition(b"\x00")
    if not separator:
        return
    key = keyword.decode("latin-1", "replace").strip()
    if not key or key in found:
        return

    try:
        if chunk_type == b"tEXt":
            value = rest.decode("latin-1", "replace")
        elif chunk_type == b"zTXt":
            inflated = decompress_zlib(rest[1:], _MAX_VALUE)
            if inflated is None:
                return
            value = inflated.decode("latin-1", "replace")
        else:
            value = _decode_itxt(rest)
    except (ValueError, IndexError):
        return

    value = value.strip()
    if value:
        found[key] = value[:_MAX_VALUE]


def _decode_itxt(rest: bytes, limit: int = _MAX_VALUE) -> str:
    """iTXt: compression flag, method, language tag, translated keyword, text."""
    if len(rest) < 2:
        return ""
    compressed, _method = rest[0], rest[1]
    body = rest[2:]
    for _ in range(2):  # skip the language tag and the translated keyword
        _, _, body = body.partition(b"\x00")
    if compressed:
        inflated = decompress_zlib(body, limit)
        if inflated is None:
            raise ValueError("iTXt value exceeds its decompression budget")
        body = inflated
    return body.decode("utf-8", "replace")
