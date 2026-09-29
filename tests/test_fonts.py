"""Fonts: what the SFNT tables say about who made a typeface."""

import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path

from filegrail.sources.embedded import read_embedded_metadata

_EPOCH = datetime(1904, 1, 1, tzinfo=timezone.utc)


def _since_1904(moment: datetime) -> int:
    return int((moment - _EPOCH).total_seconds())


def _name_table(names: dict[int, str], mac_family: str | None = None) -> bytes:
    records = b""
    strings = b""
    if mac_family is not None:  # a Macintosh record that must lose to Windows
        raw = mac_family.encode("mac_roman")
        records += struct.pack(">HHHHHH", 1, 0, 0, 1, len(raw), len(strings))
        strings += raw
    for name_id, text in names.items():
        raw = text.encode("utf-16-be")
        records += struct.pack(">HHHHHH", 3, 1, 0x409, name_id, len(raw), len(strings))
        strings += raw
    count = len(names) + (1 if mac_family is not None else 0)
    return struct.pack(">HHH", 0, count, 6 + 12 * count) + records + strings


def _head(created: datetime, modified: datetime, revision: float = 2.001) -> bytes:
    return struct.pack(
        ">IIIIHHqqhhhhHHhhh",
        0x10000,
        int(revision * 65536),
        0,
        0x5F0F3CF5,
        0,
        1000,
        _since_1904(created),
        _since_1904(modified),
        0,
        0,
        0,
        0,
        0,
        3,
        2,
        0,
        0,
    )


def _os2(vendor: bytes, rights: int) -> bytes:
    table = bytearray(96)
    struct.pack_into(">H", table, 0, 4)
    struct.pack_into(">H", table, 8, rights)
    table[58:62] = vendor
    return bytes(table)


def _fvar(axes: list[tuple[bytes, float, float, float]]) -> bytes:
    header = struct.pack(">HHHHHHHH", 1, 0, 16, 2, len(axes), 20, 0, 0)
    body = b"".join(
        struct.pack(
            ">4sIIIHH", tag, int(low * 65536), int(default * 65536), int(high * 65536), 0, 256
        )
        for tag, low, default, high in axes
    )
    return header + body


def _sfnt(tables: dict[bytes, bytes], base: int = 0) -> bytes:
    """One font. `base` is where it starts in the file: a collection's table
    offsets count from the file, not from the font."""
    version = b"\x00\x01\x00\x00"
    directory = b""
    body = b""
    start = base + 12 + 16 * len(tables)
    for tag, data in tables.items():
        directory += tag + struct.pack(">III", 0, start + len(body), len(data))
        body += data + b"\x00" * (-len(data) % 4)
    return version + struct.pack(">HHHH", len(tables), 0, 0, 0) + directory + body


def _woff(tables: dict[bytes, bytes], metadata: bytes) -> bytes:
    entries = b""
    body = b""
    start = 44 + 20 * len(tables)
    for tag, data in tables.items():
        packed = zlib.compress(data, 9)
        if len(packed) >= len(data):
            packed = data
        entries += tag + struct.pack(">IIII", start + len(body), len(packed), len(data), 0)
        body += packed + b"\x00" * (-len(packed) % 4)
    packed_meta = zlib.compress(metadata, 9)
    meta_at = start + len(body)
    header = (
        b"wOFF"
        + b"\x00\x01\x00\x00"
        + struct.pack(
            ">IHHIHHIIIII",
            meta_at + len(packed_meta),
            len(tables),
            0,
            0,
            1,
            0,
            meta_at,
            len(packed_meta),
            len(metadata),
            0,
            0,
        )
    )
    return header + entries + body + packed_meta


CREATED = datetime(2023, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
MODIFIED = datetime(2024, 2, 9, 8, 30, 0, tzinfo=timezone.utc)

TABLES = {
    b"name": _name_table(
        {
            1: "Example Sans",
            2: "Regular",
            5: "Version 2.001; ttfautohint (v1.8.4)",
            8: "Example Type Foundry",
            9: "Anna Nowak",
            11: "https://example.org/foundry",
            13: "Licensed under the SIL Open Font License 1.1",
        },
        mac_family="Example Sans Mac",
    ),
    b"head": _head(CREATED, MODIFIED),
    b"OS/2": _os2(b"EXMP", 8),
    b"fvar": _fvar([(b"wght", 100, 400, 900), (b"wdth", 75, 100, 125)]),
}


def test_reads_names_dates_vendor_and_axes_from_a_truetype_font(tmp_path: Path):
    path = tmp_path / "ExampleSans.ttf"
    path.write_bytes(_sfnt(TABLES))

    found = read_embedded_metadata(path)

    assert found is not None
    assert found.block == "font-tables"
    assert found.tool == "Example Type Foundry"
    assert found.at == "2023-05-01T12:00:00Z"
    assert found.note == "family Example Sans; designer Anna Nowak; version 2.001"
    assert found.fields["Family"] == "Example Sans"  # Windows beats Macintosh
    assert found.fields["Modified"] == "2024-02-09T08:30:00Z"
    assert found.fields["FontRevision"] == "2.001"
    assert found.fields["VendorID"] == "EXMP"
    assert found.fields["EmbeddingRights"] == "editable"
    assert found.fields["Container"] == "TrueType"
    assert found.fields["Axes"] == "wght, wdth"
    assert found.fields["Axis[wght]"] == "100 to 900, default 400"
    assert found.fields["VendorURL"] == "https://example.org/foundry"


def test_a_collection_is_read_through_its_first_font(tmp_path: Path):
    font = _sfnt(TABLES, base=24)
    path = tmp_path / "ExampleSans.ttc"
    # Three offsets after a 12-byte header: every one points at the same font.
    path.write_bytes(
        b"ttcf" + struct.pack(">II", 0x10000, 3) + struct.pack(">III", 24, 24, 24) + font
    )

    found = read_embedded_metadata(path)

    assert found is not None
    assert found.fields["Family"] == "Example Sans"
    assert found.fields["Container"] == "TrueType collection of 3 fonts"


def test_woff_tables_are_inflated_and_its_metadata_block_is_read(tmp_path: Path):
    metadata = b"""<?xml version="1.0" encoding="UTF-8"?>
<metadata version="1.0">
  <uniqueid id="org.example.examplesans.2.001"/>
  <vendor name="Example Type Foundry" url="https://example.org/foundry"/>
  <credits>
    <credit name="Anna Nowak" url="https://example.org/anna" role="Designer"/>
    <credit name="Jan Kowalski" role="Hinting"/>
  </credits>
  <license url="https://scripts.sil.org/OFL" id="OFL-1.1">
    <text xml:lang="en">Open Font License</text>
  </license>
  <copyright><text xml:lang="en">Copyright 2023 Example Type Foundry</text></copyright>
</metadata>"""
    path = tmp_path / "ExampleSans.woff"
    path.write_bytes(_woff(TABLES, metadata))

    found = read_embedded_metadata(path)

    assert found is not None
    assert found.fields["Container"] == "WOFF (TrueType)"
    assert found.fields["Designer"] == "Anna Nowak"
    assert found.at == "2023-05-01T12:00:00Z"
    assert found.fields["meta:vendor"] == "Example Type Foundry"
    assert found.fields["meta:credit[2]:name"] == "Jan Kowalski"
    assert found.fields["meta:credit[2]:role"] == "Hinting"
    assert found.fields["meta:licenseURL"] == "https://scripts.sil.org/OFL"
    assert found.fields["meta:copyright"] == "Copyright 2023 Example Type Foundry"


def test_woff_rejects_a_table_whose_stored_length_exceeds_the_read_budget(tmp_path: Path):
    table = _name_table({1: "Hidden beyond the budget"})
    offset = 64
    declared = 4 * 1024 * 1024 + 1
    entry = b"name" + struct.pack(">IIII", offset, declared, len(table), 0)
    header = (
        b"wOFF"
        + b"\x00\x01\x00\x00"
        + struct.pack(
            ">IHHIHHIIIII",
            offset + len(table),
            1,
            0,
            0,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
        )
    )
    path = tmp_path / "oversized-table.woff"
    path.write_bytes(header + entry + b"\x00" * (offset - len(header) - len(entry)) + table)

    assert read_embedded_metadata(path) is None


def test_woff_rejects_metadata_whose_stored_length_exceeds_the_read_budget(tmp_path: Path):
    metadata = b'<metadata><vendor name="Hidden beyond the budget"/></metadata>'
    offset = 44
    declared = 1024 * 1024 + 1
    header = (
        b"wOFF"
        + b"\x00\x01\x00\x00"
        + struct.pack(
            ">IHHIHHIIIII",
            offset + len(metadata),
            0,
            0,
            0,
            1,
            0,
            offset,
            declared,
            len(metadata),
            0,
            0,
        )
    )
    path = tmp_path / "oversized-metadata.woff"
    path.write_bytes(header + metadata)

    assert read_embedded_metadata(path) is None
