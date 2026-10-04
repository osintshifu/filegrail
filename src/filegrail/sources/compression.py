"""Bounded decompression helpers shared by binary format readers."""

from __future__ import annotations

import lzma
import zlib

#: What reading a member out of a package raises when its compressed data is
#: damaged. None of the three is an `OSError` or a `ValueError`, so a list of
#: "unreadable" that names only those lets one bad member end the whole scan.
DAMAGED_STREAM = (zlib.error, lzma.LZMAError, EOFError)


def decompress_zlib(payload: bytes, limit: int, *, require_eof: bool = True) -> bytes | None:
    """Inflate ``payload`` without producing more than ``limit`` bytes.

    ``zlib.decompress(..., bufsize=...)`` only chooses an initial allocation;
    it does not cap the output.  ``decompressobj`` does, and reading one byte
    past the budget distinguishes an exact-size result from a larger stream.

    A PDF whose declared stream length is short may legitimately give us a
    truncated input slice, so its caller can accept the partial result.  PNG
    text chunks require a complete zlib stream.
    """
    if limit < 0:
        raise ValueError("decompression limit must not be negative")

    inflater = zlib.decompressobj()
    try:
        inflated = inflater.decompress(payload, limit + 1)
    except zlib.error:
        return None

    if len(inflated) > limit or inflater.unconsumed_tail:
        return None
    if require_eof and not inflater.eof:
        return None
    return inflated
