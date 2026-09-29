"""Compound File Binary documents: the pre-XML Word, Excel and PowerPoint files.

The fixtures here are assembled rather than committed, so every offset in them
is computed. A hand-counted length that happens to agree with a hand-counted
reader proves nothing; `test_corpus.py` checks the same reader against real
files, which is what proves the layout right.
"""

from __future__ import annotations

import struct
import uuid
from datetime import datetime, timezone
from pathlib import Path

from filegrail.sources.embedded import read_embedded_metadata
from filegrail.sources.embedded.ole import read_ole
from tests.compound import (
    DOCSUMMARY_FMTID,
    MINI_CUTOFF,
    SUMMARY_FMTID,
    VT_FILETIME,
    VT_LPSTR,
    directory_entry,
    ole,
)

# --- property set stream -----------------------------------------------------


EPOCH_1601 = datetime(1601, 1, 1, tzinfo=timezone.utc)


def _filetime(moment: datetime) -> bytes:
    """Encode an instant the way Windows does: 100ns ticks from 1601."""
    return struct.pack("<Q", _filetime_ticks(moment))


def _filetime_ticks(moment: datetime) -> int:
    return int((moment - EPOCH_1601).total_seconds()) * 10_000_000


def _property_set(fmtid: bytes, properties: dict[int, tuple[int, object]]) -> bytes:
    """Build a one-section property set stream.

    `properties` maps a property id to its (type, value). Offsets inside the
    section are computed from the encoded values, never assumed.
    """
    identifiers = sorted(properties)
    encoded: list[bytes] = []
    for identifier in identifiers:
        category, value = properties[identifier]
        if category == VT_LPSTR:
            raw = value.encode("utf-8") + b"\x00"
            blob = struct.pack("<II", VT_LPSTR, len(raw)) + raw
        elif category == VT_FILETIME:
            blob = struct.pack("<I", VT_FILETIME) + _filetime(value)
        else:  # pragma: no cover - the tests use no other type
            raise AssertionError(f"unsupported property type {category}")
        encoded.append(blob + b"\x00" * (-len(blob) % 4))

    table_size = 8 + len(identifiers) * 8
    offsets = []
    running = table_size
    for blob in encoded:
        offsets.append(running)
        running += len(blob)

    section = struct.pack("<II", running, len(identifiers))
    for identifier, offset in zip(identifiers, offsets, strict=True):
        section += struct.pack("<II", identifier, offset)
    section += b"".join(encoded)

    header = struct.pack("<HHI", 0xFFFE, 0, 0x00020006) + b"\x00" * 16
    header += struct.pack("<I", 1) + fmtid + struct.pack("<I", len(header) + 4 + 16 + 4)
    return header + section


WORD = {
    2: (VT_LPSTR, "Quarterly report"),
    4: (VT_LPSTR, "Ada Lovelace"),
    8: (VT_LPSTR, "Charles Babbage"),
    12: (VT_FILETIME, datetime(2001, 2, 3, 4, 0, 0, tzinfo=timezone.utc)),
    18: (VT_LPSTR, "Microsoft Word 9.0"),
}


# --- tests -------------------------------------------------------------------


def test_summary_information_from_the_mini_stream(tmp_path: Path):
    document = tmp_path / "report.doc"
    document.write_bytes(ole({"\x05SummaryInformation": _property_set(SUMMARY_FMTID, WORD)}))

    found = read_ole(document)

    assert found.tool == "Microsoft Word 9.0"
    assert found.author == "Ada Lovelace"
    assert found.title == "Quarterly report"
    assert found.created == "2001-02-03T04:00:00Z"


def test_summary_information_from_a_full_sector_stream(tmp_path: Path):
    """Real spreadsheets pad the stream to the cutoff, which moves it out of
    the mini stream and onto the regular FAT."""
    payload = _property_set(SUMMARY_FMTID, WORD)
    book = tmp_path / "book.xls"
    book.write_bytes(
        ole({"\x05SummaryInformation": payload.ljust(MINI_CUTOFF, b"\x00")}),
    )

    assert read_ole(book).tool == "Microsoft Word 9.0"


def test_company_comes_from_the_document_summary(tmp_path: Path):
    deck = tmp_path / "deck.ppt"
    deck.write_bytes(
        ole(
            {
                "\x05SummaryInformation": _property_set(SUMMARY_FMTID, WORD),
                "\x05DocumentSummaryInformation": _property_set(
                    DOCSUMMARY_FMTID, {15: (VT_LPSTR, "Analytical Engine Co")}
                ),
            }
        )
    )

    assert "Analytical Engine Co" in read_ole(deck).company


def test_the_reader_reaches_the_origin(tmp_path: Path):
    document = tmp_path / "memo.doc"
    document.write_bytes(ole({"\x05SummaryInformation": _property_set(SUMMARY_FMTID, WORD)}))

    origin = read_embedded_metadata(document)

    assert origin.source == "document-metadata"
    assert origin.tool == "Microsoft Word 9.0"
    assert origin.at == "2001-02-03T04:00:00Z"
    assert "author Ada Lovelace" in origin.note


def test_a_document_without_a_summary_reports_nothing(tmp_path: Path):
    document = tmp_path / "bare.doc"
    document.write_bytes(ole({"WordDocument": b"\x00" * 128}))

    assert read_ole(document) is None


def test_storage_directory_timestamps_and_clsid_are_reported(tmp_path: Path):
    document = tmp_path / "storage.doc"
    clsid = uuid.UUID("0003000c-0000-0000-c000-000000000046")
    created = datetime(2018, 5, 6, 7, 8, 9, tzinfo=timezone.utc)
    modified = datetime(2019, 6, 7, 8, 9, 10, tzinfo=timezone.utc)
    document.write_bytes(
        ole(
            {"WordDocument": b"\x00" * 128},
            directory_entries=(
                directory_entry(
                    "ObjectPool",
                    1,
                    0,
                    0,
                    clsid=clsid.bytes_le,
                    created=_filetime_ticks(created),
                    modified=_filetime_ticks(modified),
                ),
            ),
        )
    )

    found = read_ole(document)
    origin = read_embedded_metadata(document)

    assert found.storages[0].clsid == str(clsid)
    assert found.storages[0].created == "2018-05-06T07:08:09Z"
    assert found.storages[0].modified == "2019-06-07T08:09:10Z"
    assert origin.fields["Storage[1]:Name"] == "ObjectPool"
    assert origin.fields["Storage[1]:CLSID"] == str(clsid)
    assert origin.fields["Storage[1]:Created"] == "2018-05-06T07:08:09Z"
    assert origin.fields["Storage[1]:Modified"] == "2019-06-07T08:09:10Z"


def test_stream_directory_timestamps_are_not_reported(tmp_path: Path):
    document = tmp_path / "stream-time.doc"
    moment = datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    document.write_bytes(
        ole(
            {},
            directory_entries=(directory_entry("Bogus", 2, 0, 0, created=_filetime_ticks(moment)),),
        )
    )

    assert read_ole(document) is None
    assert read_embedded_metadata(document) is None


def test_vba_storage_is_reported_as_a_structural_indicator(tmp_path: Path):
    document = tmp_path / "vba.doc"
    document.write_bytes(ole({}, directory_entries=(directory_entry("VBA", 1, 0, 0),)))

    origin = read_embedded_metadata(document)

    assert origin.fields["VBAStorage"] == "present"
    assert origin.note == "VBA storage present"
    assert "macro" not in origin.note.lower()


def test_orphaned_storage_is_kept_separate_from_active_vba(tmp_path: Path):
    document = tmp_path / "deleted-vba.doc"
    clsid = uuid.UUID("0003000c-0000-0000-c000-000000000046")
    modified = datetime(2021, 2, 3, 4, 5, 6, tzinfo=timezone.utc)
    document.write_bytes(
        ole(
            {},
            orphan_entries=(
                directory_entry(
                    "VBA",
                    1,
                    0,
                    0,
                    clsid=clsid.bytes_le,
                    modified=_filetime_ticks(modified),
                ),
            ),
        )
    )

    found = read_ole(document)
    origin = read_embedded_metadata(document)

    assert found.vba_storage is False
    assert len(found.orphaned_entries) == 1
    assert "VBAStorage" not in origin.fields
    assert origin.note == "orphaned directory entries 1"
    assert origin.fields["OrphanedEntry[1]:Name"] == "VBA"
    assert origin.fields["OrphanedEntry[1]:Type"] == "storage"
    assert origin.fields["OrphanedEntry[1]:CLSID"] == str(clsid)
    assert origin.fields["OrphanedEntry[1]:Modified"] == "2021-02-03T04:05:06Z"


def test_orphaned_native_stream_is_not_reported_as_an_active_object(tmp_path: Path):
    document = tmp_path / "deleted-object.doc"
    document.write_bytes(ole({}, orphan_entries=(directory_entry("\x01Ole10Native", 2, 0, 64),)))

    origin = read_embedded_metadata(document)

    assert "Ole10NativeStreams" not in origin.fields
    assert origin.fields["OrphanedEntry[1]:Name"] == "\x01Ole10Native"
    assert origin.fields["OrphanedEntry[1]:Type"] == "stream"
    assert origin.fields["OrphanedEntry[1]:Size"] == "64"


def test_biff_macro_sheet_is_reported_without_guessing_from_stream_name(tmp_path: Path):
    bof = struct.pack("<HHHH", 0x0809, 4, 0x0600, 0x0005)
    macro_sheet = struct.pack("<HHIBB", 0x0085, 6, 0, 0, 1)
    eof = struct.pack("<HH", 0x000A, 0)
    document = tmp_path / "xlm.xls"
    document.write_bytes(ole({"Workbook": bof + macro_sheet + eof}))

    origin = read_embedded_metadata(document)

    assert origin.fields["XLMMacroSheets"] == "1"
    assert origin.note == "XLM macro sheets 1"
    assert "malicious" not in origin.note.lower()


def test_workbook_stream_name_alone_is_not_an_xlm_indicator(tmp_path: Path):
    bof = struct.pack("<HHHH", 0x0809, 4, 0x0600, 0x0005)
    worksheet = struct.pack("<HHIBB", 0x0085, 6, 0, 0, 0)
    eof = struct.pack("<HH", 0x000A, 0)
    document = tmp_path / "plain.xls"
    document.write_bytes(ole({"Workbook": bof + worksheet + eof}))

    assert read_embedded_metadata(document) is None


def test_ole_packager_paths_and_payload_size_are_reported(tmp_path: Path):
    payload = b"embedded payload"
    package = struct.pack("<H", 2)
    package += b"invoice.pdf\x00"
    package += b"C:\\Cases\\invoice.pdf\x00"
    package += struct.pack("<II", 0, 0)
    package += b"C:\\Temp\\invoice.pdf\x00"
    package += struct.pack("<I", len(payload)) + payload
    native = struct.pack("<I", len(package)) + package
    document = tmp_path / "embedded.doc"
    document.write_bytes(ole({"\x01Ole10Native": native}))

    origin = read_embedded_metadata(document)

    assert origin.fields["Ole10NativeStreams"] == "1"
    assert origin.fields["EmbeddedObject[1]:Filename"] == "invoice.pdf"
    assert origin.fields["EmbeddedObject[1]:SourcePath"] == "C:\\Cases\\invoice.pdf"
    assert origin.fields["EmbeddedObject[1]:TempPath"] == "C:\\Temp\\invoice.pdf"
    assert origin.fields["EmbeddedObject[1]:Size"] == str(len(payload))


def test_a_file_that_is_not_a_compound_document(tmp_path: Path):
    document = tmp_path / "fake.doc"
    document.write_bytes(b"not a compound file at all")

    assert read_ole(document) is None
    assert read_embedded_metadata(document) is None
