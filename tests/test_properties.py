"""What the two hand-written decoders have to hold for inputs nobody chose.

`filegrail` takes no runtime dependencies, so `cbor.py` and `bencode.py` are its
own, and both of them read bytes that arrived from somewhere else. The example
tests beside them check what somebody thought to write down. These check the two
claims the modules actually make:

* an arbitrary string of bytes is either decoded or refused, and refused means
  the module's own error class - every caller catches that one and nothing else,
  so an exception of another type walks out of the reader, out of the scan, and
  takes the run down with it;
* a value encoded canonically decodes back to itself.

`hypothesis` is deliberately not in the `dev` extra. It is the one thing here
that makes a run depend on a seed rather than on the code, so it lives in its
own extra and its own CI job, and without it these skip.
"""

from __future__ import annotations

import contextlib
import os
import struct
from datetime import timedelta

import pytest

pytest.importorskip("hypothesis")

from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from filegrail.bencode import BencodeError, loads, value_span  # noqa: E402
from filegrail.cbor import CborError  # noqa: E402
from filegrail.cbor import loads as cbor_loads  # noqa: E402

#: How hard to look. The CI job that installs `hypothesis` sets the profile; a
#: run on a laptop gets the smaller one, because these sit in the same suite as
#: a thousand example tests and are not the reason anybody ran it. The deadline
#: is generous rather than absent: a decoder that takes a second over five
#: hundred bytes has found something, and a slow runner has not.
settings.register_profile("default", max_examples=400, deadline=timedelta(seconds=1))
settings.register_profile("ci", max_examples=3000, deadline=timedelta(seconds=1))
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))

#: Long enough to reach a nested container, short enough that a falsifying
#: example is still something a person can read in the failure output.
_FUZZ_BYTES = 512

#: The bytes a CBOR item can begin with, and the one that ends an indefinite
#: one. Uniform random bytes practically never spell a container - the head has
#: to be right before anything inside it is reached at all - so the generator is
#: handed the alphabet of the format as well, which is what a fuzzer's
#: dictionary is for. Both halves matter: the dictionary reaches the code that
#: parses structure, and the raw bytes reach the arithmetic.
_CBOR_HEADS = [
    bytes([initial])
    # Grouped by major type, one row each, because the grouping is what says
    # which part of the decoder a row reaches.
    for row in (
        (0x00, 0x01, 0x17, 0x18, 0x19, 0x1A, 0x1B),  # unsigned, and the wider heads
        (0x20, 0x37, 0x38, 0x3B),  # negative
        (0x40, 0x41, 0x57, 0x58, 0x5F),  # byte strings, definite and not
        (0x60, 0x61, 0x77, 0x78, 0x7F),  # text strings
        (0x80, 0x81, 0x98, 0x9F),  # arrays
        (0xA0, 0xA1, 0xB8, 0xBF),  # maps
        (0xC0, 0xC1, 0xD8),  # tags
        (0xE0, 0xF4, 0xF5, 0xF6, 0xF7, 0xF8),  # simple values
        (0xFF,),  # the break that ends an indefinite item
    )
    for initial in row
]

#: The heads that open an item of unstated length, each with the byte that ends
#: it. Generated as a unit rather than left to chance: the code that assembles
#: one of these runs only once the closing byte arrives, and waiting for three
#: loose tokens to land in that order is waiting for a coincidence. Indefinite
#: lengths are a third of what this decoder says it supports, and a generator
#: that never spells one is not testing them.
_CBOR_FRAMES = [(b"\x5f", b"\xff"), (b"\x7f", b"\xff"), (b"\x9f", b"\xff"), (b"\xbf", b"\xff")]

#: The whole bencode alphabet, plus the digit forms its canonicity rules turn
#: away: a leading zero, a negative zero, a length with nothing after it.
_BENCODE_TOKENS = [
    token
    for row in (
        (b"i", b"e", b"l", b"d", b":"),  # the whole alphabet
        (b"-", b"0", b"1", b"9", b"12", b"spam"),  # a sign, some digits, something to point at
        (b"01", b"-0"),  # the forms its canonicity rules turn away
    )
    for token in row
]

_BENCODE_FRAMES = [(b"l", b"e"), (b"d", b"e")]


def _salad(tokens: list[bytes], frames: list[tuple[bytes, bytes]]) -> st.SearchStrategy[bytes]:
    """Structurally plausible garbage: the format's own tokens, in any order.

    Nothing random is mixed in here. A decoder reads the first item and stops,
    so a random byte early in the string ends the parse before any of the code
    that walks structure is reached, and an example that spends half its bytes
    on noise is an example that tests the first `if`. Random bytes get their own
    arm below, where they are the whole input rather than an interruption.
    """
    pieces = st.sampled_from(tokens)
    return st.lists(
        pieces
        | st.builds(
            lambda frame, body: frame[0] + b"".join(body) + frame[1],
            st.sampled_from(frames),
            st.lists(pieces, max_size=6),
        ),
        min_size=1,
        max_size=16,
    ).map(b"".join)


_CBOR_FUZZ = st.binary(max_size=_FUZZ_BYTES) | _salad(_CBOR_HEADS, _CBOR_FRAMES)
_BENCODE_FUZZ = st.binary(max_size=_FUZZ_BYTES) | _salad(_BENCODE_TOKENS, _BENCODE_FRAMES)


# --- anything at all goes in ---------------------------------------------------


@given(_CBOR_FUZZ)
def test_cbor_answers_arbitrary_bytes_with_a_value_or_its_own_error(raw: bytes):
    """`CborError` is the only refusal `read_c2pa_manifest` knows how to catch."""
    with contextlib.suppress(CborError):
        cbor_loads(raw)


@given(_BENCODE_FUZZ)
def test_bencode_answers_arbitrary_bytes_with_a_value_or_its_own_error(raw: bytes):
    with contextlib.suppress(BencodeError):
        loads(raw)


@given(_BENCODE_FUZZ)
def test_the_span_of_a_value_survives_arbitrary_bytes(raw: bytes):
    """`value_span` reads the same grammar and is reached by the same files."""
    with contextlib.suppress(BencodeError):
        value_span(raw, b"info")


@given(st.integers(min_value=1, max_value=400))
def test_neither_decoder_recurses_off_the_stack(depth: int):
    """Nesting is bounded by a depth, and the bound is what keeps it off the stack.

    A file is free to say `an array of an array of...` for as long as it likes,
    and a `RecursionError` is not a refusal - it is the interpreter's, it names
    nothing, and no caller catches it.
    """
    with contextlib.suppress(CborError):
        cbor_loads(b"\x9f" * depth + b"\xff" * depth)
    with contextlib.suppress(CborError):
        cbor_loads(b"\xc0" * depth + b"\x00")  # a chain of tags, each one deeper
    with contextlib.suppress(BencodeError):
        loads(b"l" * depth + b"e" * depth)


# --- what was encoded comes back ----------------------------------------------

#: The subset of CBOR this decoder claims: the major types, the simple values,
#: and containers of them. Floats are excluded because the decoder says outright
#: that it never reads one.
_CBOR_VALUES = st.recursive(
    st.one_of(
        st.integers(min_value=-(2**64), max_value=2**64 - 1),
        st.binary(max_size=24),
        st.text(max_size=24),
        st.booleans(),
        st.none(),
    ),
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(max_size=8), children, max_size=5),
    ),
    max_leaves=10,
)

#: Bencode is four productions, and a dictionary is keyed by a byte string.
_BENCODE_VALUES = st.recursive(
    st.one_of(st.integers(min_value=-(2**63), max_value=2**63), st.binary(max_size=24)),
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.binary(max_size=8), children, max_size=5),
    ),
    max_leaves=10,
)


def _cbor(value: object) -> bytes:
    """Encode the subset above. Written here rather than shared with the C2PA
    fixtures, which encode a manifest by hand and have a different job."""

    def head(major: int, argument: int) -> bytes:
        if argument < 24:
            return bytes([major << 5 | argument])
        for code, width, fmt in ((24, 1, "B"), (25, 2, "H"), (26, 4, "I"), (27, 8, "Q")):
            if argument < 1 << (width * 8):
                return bytes([major << 5 | code]) + struct.pack(f">{fmt}", argument)
        raise AssertionError(argument)

    # bool before int: `True` is an `int` in Python and would encode as 1.
    if value is None:
        return b"\xf6"
    if isinstance(value, bool):
        return b"\xf5" if value else b"\xf4"
    if isinstance(value, int):
        return head(0, value) if value >= 0 else head(1, -1 - value)
    if isinstance(value, bytes):
        return head(2, len(value)) + value
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return head(3, len(raw)) + raw
    if isinstance(value, list):
        return head(4, len(value)) + b"".join(_cbor(item) for item in value)
    if isinstance(value, dict):
        return head(5, len(value)) + b"".join(_cbor(k) + _cbor(v) for k, v in value.items())
    raise AssertionError(value)


def _bencode(value: object) -> bytes:
    if isinstance(value, int):
        return b"i%de" % value
    if isinstance(value, bytes):
        return b"%d:%s" % (len(value), value)
    if isinstance(value, list):
        return b"l" + b"".join(_bencode(item) for item in value) + b"e"
    if isinstance(value, dict):
        # Canonical bencode sorts its keys, and a torrent's info hash is taken
        # over the bytes as written, so the encoder here writes the canonical
        # form or it is not testing what a torrent contains.
        return b"d" + b"".join(_bencode(k) + _bencode(value[k]) for k in sorted(value)) + b"e"
    raise AssertionError(value)


@given(_CBOR_VALUES)
def test_a_canonically_encoded_cbor_value_decodes_back_to_itself(value: object):
    assert cbor_loads(_cbor(value)) == value


@given(_BENCODE_VALUES)
def test_a_canonically_encoded_bencode_value_decodes_back_to_itself(value: object):
    assert loads(_bencode(value)) == value


@given(st.dictionaries(st.binary(min_size=1, max_size=8), _BENCODE_VALUES, min_size=1, max_size=5))
def test_the_span_of_a_value_is_exactly_that_value_as_written(mapping: dict[bytes, object]):
    """The claim the info hash rests on.

    A torrent's info hash is the SHA-1 of the `info` value exactly as its author
    wrote it, so the span has to be the encoding of that value and nothing else -
    not a byte of the key before it, not a byte of the next pair after it.
    """
    raw = _bencode(mapping)
    for key, value in mapping.items():
        span = value_span(raw, key)
        assert span is not None
        start, end = span
        assert raw[start:end] == _bencode(value)
        assert loads(raw[start:end]) == value
