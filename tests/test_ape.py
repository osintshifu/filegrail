"""APEv2 tags at the end of a file."""

import struct
from pathlib import Path

from filegrail.sources.embedded import read_embedded_metadata


def _ape(items: list[tuple[str, bytes, int]]) -> bytes:
    body = b"".join(
        struct.pack("<II", len(value), flags) + key.encode("ascii") + b"\x00" + value
        for key, value, flags in items
    )
    footer = b"APETAGEX" + struct.pack("<IIII", 2000, len(body) + 32, len(items), 0) + b"\x00" * 8
    return body + footer


def test_reads_text_items_behind_the_footer_and_an_id3v1_tag(tmp_path: Path):
    """The tag is found from the end of the file, past an ID3v1 block, and a
    binary item such as cover art is counted but never decoded as text."""
    path = tmp_path / "take.ape"
    tag = _ape(
        [
            ("Artist", b"Anna Nowak", 0),
            ("Title", b"Field interview", 0),
            ("Year", b"2026", 0),
            ("Tool Name", b"Monkey's Audio", 0),
            ("Tool Version", b"10.38", 0),
            ("Cover Art (Front)", b"front.jpg\x00\xff\xd8\xff", 2),
        ]
    )
    path.write_bytes(b"MAC \x00" * 40 + tag + b"TAG" + b"\x00" * 125)

    found = read_embedded_metadata(path)

    assert found is not None
    assert found.block == "ape-tag"
    assert found.tool == "Monkey's Audio 10.38"
    assert found.at == "2026-01-01T00:00:00Z"
    assert found.note == "artist Anna Nowak; title Field interview"
    assert "Cover Art (Front)" not in found.fields
    assert found.fields["Year"] == "2026"


def test_a_file_without_a_tag_yields_nothing(tmp_path: Path):
    path = tmp_path / "raw.wv"
    path.write_bytes(b"wvpk" + b"\x00" * 200)

    assert read_embedded_metadata(path) is None
