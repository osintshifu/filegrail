"""Minimal CBOR decoder (RFC 8949).

C2PA manifests are CBOR, and reading them is the only reason this exists. A
third-party decoder would be the obvious choice, but `filegrail` takes no runtime
dependencies, and the subset needed here is small: the major types, indefinite
lengths, tag 0 for timestamps, and the simple values.

Decoding is bounded by a nesting depth and by the length of the input, because
the data comes from a file that arrived from somewhere else.
"""

from __future__ import annotations

import struct
from typing import Any

MAX_DEPTH = 32

_BREAK = object()

#: Tag 0 is an RFC 3339 timestamp; it carries the text string that follows it.
_TAG_DATETIME = 0


class CborError(ValueError):
    """The input is not decodable CBOR."""


def loads(data: bytes) -> Any:
    """Decode the first CBOR item in `data`."""
    value, _ = _decode(memoryview(data), 0, 0)
    if value is _BREAK:
        raise CborError("unexpected break")
    return value


def _read_head(data: memoryview, offset: int) -> tuple[int, int, int]:
    """Return (major type, argument, next offset)."""
    if offset >= len(data):
        raise CborError("truncated")
    initial = data[offset]
    major, minor = initial >> 5, initial & 0x1F
    offset += 1

    if minor < 24:
        return major, minor, offset
    if minor == 24:
        if offset + 1 > len(data):
            raise CborError("truncated")
        return major, data[offset], offset + 1
    for code, width in ((25, 2), (26, 4), (27, 8)):
        if minor == code:
            if offset + width > len(data):
                raise CborError("truncated")
            fmt = {2: ">H", 4: ">I", 8: ">Q"}[width]
            (value,) = struct.unpack(fmt, data[offset : offset + width])
            return major, value, offset + width
    if minor == 31:
        return major, -1, offset  # indefinite length
    raise CborError(f"reserved additional information {minor}")


def _decode(data: memoryview, offset: int, depth: int) -> tuple[Any, int]:
    if depth > MAX_DEPTH:
        raise CborError("nesting too deep")

    major, argument, offset = _read_head(data, offset)

    if major == 0:
        return argument, offset
    if major == 1:
        return -1 - argument, offset
    if major in (2, 3):
        return _decode_string(data, offset, argument, major, depth)
    if major == 4:
        return _decode_array(data, offset, argument, depth)
    if major == 5:
        return _decode_map(data, offset, argument, depth)
    if major == 6:
        value, offset = _decode(data, offset, depth + 1)
        return value, offset  # tag 0 and every other tag pass the value through
    if major == 7:
        return _decode_simple(data, offset, argument)
    raise CborError(f"unknown major type {major}")


def _decode_string(
    data: memoryview, offset: int, argument: int, major: int, depth: int
) -> tuple[Any, int]:
    if argument < 0:  # indefinite length: concatenate the chunks
        # RFC 8949 spells an indefinite-length string as definite-length chunks
        # of its own type and nothing else, and a chunk of any other type is a
        # malformed file that has to be refused as one. Appending it and letting
        # the join below fail raises `TypeError`, which is nobody's idea of a
        # refusal: every caller here catches `CborError` and only that, so it
        # would leave the reader, leave the scan, and end the run - a hundred
        # bytes in a file denying the whole tool.
        parts: list[bytes] = []
        while True:
            chunk, offset = _decode(data, offset, depth + 1)
            if chunk is _BREAK:
                break
            if major == 3 and isinstance(chunk, str):
                parts.append(chunk.encode("utf-8"))
            elif major == 2 and isinstance(chunk, bytes):
                parts.append(chunk)
            else:
                raise CborError("an indefinite-length string holding something else")
        joined = b"".join(parts)
        return (joined.decode("utf-8", "replace") if major == 3 else joined), offset

    end = offset + argument
    if end > len(data):
        raise CborError("truncated string")
    raw = bytes(data[offset:end])
    return (raw.decode("utf-8", "replace") if major == 3 else raw), end


def _decode_array(data: memoryview, offset: int, argument: int, depth: int) -> tuple[Any, int]:
    items: list[Any] = []
    if argument < 0:
        while True:
            item, offset = _decode(data, offset, depth + 1)
            if item is _BREAK:
                return items, offset
            items.append(item)
    for _ in range(argument):
        item, offset = _decode(data, offset, depth + 1)
        items.append(item)
    return items, offset


def _decode_map(data: memoryview, offset: int, argument: int, depth: int) -> tuple[Any, int]:
    result: dict[Any, Any] = {}
    if argument < 0:
        while True:
            key, offset = _decode(data, offset, depth + 1)
            if key is _BREAK:
                return result, offset
            value, offset = _decode(data, offset, depth + 1)
            result[_hashable(key)] = value
    for _ in range(argument):
        key, offset = _decode(data, offset, depth + 1)
        value, offset = _decode(data, offset, depth + 1)
        result[_hashable(key)] = value
    return result, offset


def _hashable(key: Any) -> Any:
    """Maps may be keyed by a container; keep those addressable rather than fail.

    All the way down, because containers nest: flattening only the outer one
    leaves a list sitting inside the tuple that is about to be hashed, and the
    dictionary raises `TypeError` for it - which is not `CborError` and so is
    not caught by anything that reads a file through here. The recursion is
    bounded by the same nesting depth the decode was.
    """
    if isinstance(key, list):
        return tuple(_hashable(item) for item in key)
    if isinstance(key, dict):
        return tuple(sorted(((_hashable(k), _hashable(v)) for k, v in key.items()), key=repr))
    return key


def _decode_simple(data: memoryview, offset: int, argument: int) -> tuple[Any, int]:
    simple = {20: False, 21: True, 22: None, 23: None}
    if argument in simple:
        return simple[argument], offset
    if argument == -1:
        return _BREAK, offset
    # Floats were consumed by _read_head as raw bits; filegrail never reads one.
    return None, offset
