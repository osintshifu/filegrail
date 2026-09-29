"""Minimal bencode decoder.

A `.torrent` file is written in it, and reading one is the only reason this
exists. `filegrail` takes no runtime dependencies, and the whole grammar is four
productions: integers, byte strings, lists and dictionaries.

Bencode is meant to be canonical - one value has exactly one encoding - and
that matters here rather than being pedantry. A torrent's info hash is the
SHA-1 of its `info` value *as written*, so a decoder that quietly accepted
`i-0e` or a zero-padded length would be accepting bytes that no honest encoder
produced, and the hash computed from them would identify nothing.

Decoding is bounded by nesting depth and by the length of the input, because
the data comes from a file that arrived from somewhere else.
"""

from __future__ import annotations

from typing import Any

MAX_DEPTH = 32

#: The longest byte string worth decoding. A `pieces` field is a hash per piece
#: and runs to megabytes on a large torrent, which is legitimate; far beyond
#: that is not a torrent.
MAX_STRING = 64 * 1024 * 1024


class BencodeError(ValueError):
    """The input is not decodable bencode."""


def loads(data: bytes) -> Any:
    """Decode the single bencode value in `data`."""
    value, offset = _decode(data, 0, 0)
    if offset != len(data):
        raise BencodeError("trailing bytes after the value")
    return value


def value_span(data: bytes, key: bytes) -> tuple[int, int] | None:
    """Where `key`'s value sits in a top-level dictionary, or None.

    The caller wants the bytes rather than the decoded value: an info hash is
    taken over the encoding an author wrote, and re-encoding what was decoded
    would be a different string of bytes whenever the two disagree - which is
    exactly when it matters.
    """
    if not data.startswith(b"d"):
        return None
    offset = 1
    while offset < len(data) and data[offset : offset + 1] != b"e":
        name, offset = _decode(data, offset, 0)
        start = offset
        _, offset = _decode(data, offset, 0)
        if name == key:
            return start, offset
    return None


def _decode(data: bytes, offset: int, depth: int) -> tuple[Any, int]:
    if depth > MAX_DEPTH:
        raise BencodeError("too deeply nested")
    if offset >= len(data):
        raise BencodeError("ended in the middle of a value")

    marker = data[offset : offset + 1]
    if marker == b"i":
        return _integer(data, offset)
    if marker == b"l":
        return _list(data, offset, depth)
    if marker == b"d":
        return _dictionary(data, offset, depth)
    if marker.isdigit():
        return _string(data, offset)
    raise BencodeError(f"no value begins with {marker!r}")


def _integer(data: bytes, offset: int) -> tuple[int, int]:
    end = data.find(b"e", offset)
    if end < 0:
        raise BencodeError("unterminated integer")
    digits = data[offset + 1 : end]
    if not _canonical_integer(digits):
        raise BencodeError(f"not a canonically encoded integer: {digits!r}")
    return int(digits), end + 1


def _canonical_integer(digits: bytes) -> bool:
    """`i-0e` and a leading zero are forbidden, and there is one spelling of 0."""
    body = digits[1:] if digits.startswith(b"-") else digits
    if not body.isdigit():
        return False
    if digits.startswith(b"-0"):
        return False
    return not (len(body) > 1 and body.startswith(b"0"))


def _string(data: bytes, offset: int) -> tuple[bytes, int]:
    colon = data.find(b":", offset)
    if colon < 0:
        raise BencodeError("a length with no string after it")
    digits = data[offset:colon]
    if not digits.isdigit() or (len(digits) > 1 and digits.startswith(b"0")):
        raise BencodeError(f"not a canonically encoded length: {digits!r}")
    length = int(digits)
    if length > MAX_STRING:
        raise BencodeError("string longer than anything this reads")
    end = colon + 1 + length
    if end > len(data):
        raise BencodeError("string shorter than its own length")
    return data[colon + 1 : end], end


def _list(data: bytes, offset: int, depth: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    offset += 1
    while True:
        if offset >= len(data):
            raise BencodeError("unterminated list")
        if data[offset : offset + 1] == b"e":
            return items, offset + 1
        value, offset = _decode(data, offset, depth + 1)
        items.append(value)


def _dictionary(data: bytes, offset: int, depth: int) -> tuple[dict[bytes, Any], int]:
    found: dict[bytes, Any] = {}
    offset += 1
    while True:
        if offset >= len(data):
            raise BencodeError("unterminated dictionary")
        if data[offset : offset + 1] == b"e":
            return found, offset + 1
        key, offset = _decode(data, offset, depth + 1)
        if not isinstance(key, bytes):
            raise BencodeError("a dictionary key that is not a byte string")
        value, offset = _decode(data, offset, depth + 1)
        found[key] = value
