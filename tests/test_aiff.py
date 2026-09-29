"""AIFF: text chunks, the ID3 tag in a chunk, and what the sound is."""

import struct
from pathlib import Path

from filegrail.sources.embedded import read_embedded_metadata


def _chunk(chunk_id: bytes, payload: bytes) -> bytes:
    return chunk_id + struct.pack(">I", len(payload)) + payload + b"\x00" * (len(payload) % 2)


def _extended(value: float) -> bytes:
    """44100 as the 80-bit float AIFF writes: exponent 16383 + 15, mantissa
    with the leading bit set."""
    exponent = 0
    mantissa = value
    while mantissa >= 2:
        mantissa /= 2
        exponent += 1
    return struct.pack(">HQ", 16383 + exponent, int(mantissa * (1 << 63)))


def _id3(frames: list[tuple[bytes, str]]) -> bytes:
    body = b""
    for identifier, text in frames:
        payload = b"\x03" + text.encode("utf-8")
        body += identifier + struct.pack(">I", len(payload)) + b"\x00\x00" + payload
    size = bytes(((len(body) >> shift) & 0x7F) for shift in (21, 14, 7, 0))
    return b"ID3\x03\x00\x00" + size + body


def _aiff(kind: bytes, chunks: list[bytes]) -> bytes:
    body = kind + b"".join(chunks)
    return b"FORM" + struct.pack(">I", len(body)) + body


def test_reads_text_chunks_the_id3_chunk_and_the_sound_description(tmp_path: Path):
    comm = struct.pack(">hIh", 2, 44100 * 30, 16) + _extended(44100) + b"sowt" + b"\x0bLittle Endn"
    path = tmp_path / "take.aifc"
    path.write_bytes(
        _aiff(
            b"AIFC",
            [
                _chunk(b"COMM", comm),
                _chunk(b"NAME", b"Field interview 3"),
                _chunk(b"AUTH", b"Anna Nowak"),
                _chunk(b"(c) ", b"2026 Example Radio"),
                _chunk(b"ANNO", b"Recorded on a Zoom H5"),
                _chunk(b"ANNO", b"Second annotation"),
                _chunk(b"ID3 ", _id3([(b"TSSE", "Lavf61.1.100"), (b"TDRC", "2026-09-18")])),
                _chunk(b"SSND", b"\x00" * 64),
            ],
        )
    )

    found = read_embedded_metadata(path)

    assert found is not None
    assert found.block == "aiff"
    assert found.tool == "Lavf61.1.100"
    assert found.at == "2026-09-18T00:00:00Z"
    assert found.note == "author Anna Nowak; title Field interview 3"
    assert found.fields["Copyright"] == "2026 Example Radio"
    assert found.fields["Annotation"] == "Recorded on a Zoom H5"
    assert found.fields["Annotation[2]"] == "Second annotation"
    assert found.fields["id3:encoder"] == "Lavf61.1.100"
    assert found.fields["Channels"] == "2"
    assert found.fields["SampleRate"] == "44100 Hz"
    assert found.fields["Duration"] == "30.0 s"
    assert found.fields["Compression"] == "Little Endn (sowt)"


def test_sound_data_alone_is_not_provenance(tmp_path: Path):
    path = tmp_path / "plain.aiff"
    path.write_bytes(_aiff(b"AIFF", [_chunk(b"SSND", b"\x00" * 16)]))

    assert read_embedded_metadata(path) is None
