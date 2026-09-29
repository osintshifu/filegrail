import pytest

from filegrail.cbor import CborError, loads


def test_unsigned_and_negative_integers():
    assert loads(b"\x00") == 0
    assert loads(b"\x17") == 23
    assert loads(b"\x18\x18") == 24
    assert loads(b"\x19\x03\xe8") == 1000
    assert loads(b"\x1a\x00\x0f\x42\x40") == 1000000
    assert loads(b"\x20") == -1
    assert loads(b"\x38\x63") == -100


def test_text_and_byte_strings():
    assert loads(b"\x64\x49\x45\x54\x46") == "IETF"
    assert loads(b"\x44\x01\x02\x03\x04") == b"\x01\x02\x03\x04"
    assert loads(b"\x60") == ""


def test_arrays_and_maps():
    assert loads(b"\x83\x01\x02\x03") == [1, 2, 3]
    assert loads(b"\xa2\x61\x61\x01\x61\x62\x02") == {"a": 1, "b": 2}
    assert loads(b"\x80") == []
    assert loads(b"\xa0") == {}


def test_indefinite_length_array_and_map():
    assert loads(b"\x9f\x01\x02\xff") == [1, 2]
    assert loads(b"\xbf\x61\x61\x01\xff") == {"a": 1}


def test_indefinite_length_string_is_concatenated():
    assert loads(b"\x7f\x62\x68\x65\x63\x6c\x6c\x6f\xff") == "hello"


def test_tagged_value_passes_through():
    """C2PA wraps timestamps in tag 0; the string is what matters."""
    assert loads(b"\xc0\x74" + b"2026-07-15T00:00:00Z") == "2026-07-15T00:00:00Z"


def test_simple_values():
    assert loads(b"\xf4") is False
    assert loads(b"\xf5") is True
    assert loads(b"\xf6") is None


def test_nested_structure_like_a_c2pa_action():
    encoded = (
        b"\xa1\x67actions\x81"
        b"\xa2\x66action\x6cc2pa.created"
        b"\x6dsoftwareAgent\xa1\x64name\x69gpt-image"
    )
    assert loads(encoded) == {
        "actions": [{"action": "c2pa.created", "softwareAgent": {"name": "gpt-image"}}]
    }


def test_truncated_input_is_rejected():
    with pytest.raises(CborError):
        loads(b"\x64\x49\x45")


def test_empty_input_is_rejected():
    with pytest.raises(CborError):
        loads(b"")


def test_deep_nesting_is_rejected():
    with pytest.raises(CborError):
        loads(b"\x81" * 64 + b"\x00")


def test_an_indefinite_string_whose_chunk_is_not_a_string_is_rejected():
    """RFC 8949 spells an indefinite-length string as definite-length chunks.

    A chunk that decoded to something else used to be appended anyway and reach
    `b"".join`, which raises `TypeError` - and `TypeError` is not what any
    caller of this catches, so it left the reader, left the scan, and ended the
    run on one crafted file.
    """
    with pytest.raises(CborError):
        loads(b"\x5f\x00\xff")  # a byte string whose only chunk is the integer 0
    with pytest.raises(CborError):
        loads(b"\x7f\x80\xff")  # a text string whose only chunk is an empty array


def test_an_indefinite_string_does_not_take_chunks_of_the_other_kind():
    """The chunks of a text string are text strings, and a byte string's are bytes."""
    with pytest.raises(CborError):
        loads(b"\x7f\x41a\xff")
    with pytest.raises(CborError):
        loads(b"\x5f\x61a\xff")


def test_a_map_keyed_by_a_nested_container_is_still_decodable():
    """CBOR allows a container as a map key, and containers nest.

    Flattening only the outer one leaves a list inside the tuple that is about
    to be hashed, which raises `TypeError` from the dictionary rather than
    `CborError` from here - and that is the difference between one unreadable
    manifest and a scan that stops.
    """
    assert loads(b"\xa1\x81\x81\x00\x00") == {((0,),): 0}
    assert loads(b"\xa1\xa1\x00\x81\x00\x00") == {((0, (0,)),): 0}
