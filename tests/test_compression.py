import zlib

import pytest

from filegrail.sources.compression import decompress_zlib


def test_zlib_output_is_limited_before_it_is_allocated():
    compressed = zlib.compress(b"A" * 8192)

    assert decompress_zlib(compressed, 4096) is None
    assert decompress_zlib(compressed, 8192) == b"A" * 8192


def test_complete_stream_is_required_by_default():
    compressed = zlib.compress(b"metadata")

    assert decompress_zlib(compressed[:-2], 4096) is None
    assert decompress_zlib(compressed[:-2], 4096, require_eof=False) == b"metadata"


def test_negative_limit_is_rejected():
    with pytest.raises(ValueError):
        decompress_zlib(b"", -1)
