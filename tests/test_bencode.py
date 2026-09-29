"""Bencode, the encoding a `.torrent` file is written in."""

from __future__ import annotations

import pytest

from filegrail.bencode import BencodeError, loads, value_span


def test_an_integer():
    assert loads(b"i42e") == 42


def test_a_negative_integer():
    assert loads(b"i-7e") == -7


def test_a_byte_string():
    assert loads(b"4:spam") == b"spam"


def test_a_list():
    assert loads(b"li1ei2ee") == [1, 2]


def test_a_dictionary():
    assert loads(b"d3:cow3:moo4:spam4:eggse") == {b"cow": b"moo", b"spam": b"eggs"}


def test_nesting():
    assert loads(b"d5:filesld6:lengthi12eeee") == {b"files": [{b"length": 12}]}


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"i42",  # unterminated
        b"4:ab",  # string shorter than its length
        b"iae",  # not a number
        b"d3:keye",  # key with no value
        b"x",  # no such type
        b"i-0e",  # bencode forbids negative zero
        b"01:a",  # a length may not be zero-padded
    ],
)
def test_malformed_input_is_refused(raw: bytes):
    with pytest.raises(BencodeError):
        loads(raw)


def test_nesting_is_bounded():
    """The input arrived from somewhere else, so depth is not open-ended."""
    with pytest.raises(BencodeError):
        loads(b"l" * 200 + b"e" * 200)


def test_the_span_of_a_value_is_reported():
    """A torrent's info hash is the SHA-1 of the `info` value exactly as it was
    written, so the reader needs its bytes rather than a re-encoding of them."""
    raw = b"d4:infod4:name3:abcee"

    start, end = value_span(raw, b"info")

    assert raw[start:end] == b"d4:name3:abce"


def test_a_missing_key_has_no_span():
    assert value_span(b"d3:cow3:mooe", b"info") is None
