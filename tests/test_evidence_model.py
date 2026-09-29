"""What the vocabulary is for: each record says what it is and how it got here.

The model this replaced had one class called `Origin` holding a camera's own
tags, a browser's download row and a trash record alike, one number called
`confidence` standing for six unrelated properties, and the basis of a match
written into an English sentence. These tests hold the replacement to the
distinctions it was made for - the ones a report is wrong without.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from filegrail.correlate import CONFLICTS, WEAK_MATCH, correlate
from filegrail.models import (
    ACTIVITY,
    CATEGORIES,
    EMBEDDED,
    FILENAME,
    METADATA,
    NAME_AND_SIZE,
    ORIGIN,
    SOURCE_CATEGORIES,
    SOURCE_LABELS,
    SOURCE_MATCH,
    SOURCE_PRIORITY,
    EvidenceRecord,
    FileRecord,
    category,
)
from filegrail.report import render_json, render_text
from filegrail.theme import Theme

PLAIN = Theme(colour=False, unicode=False, width=88)


def _file(*evidence: EvidenceRecord) -> FileRecord:
    record = FileRecord(path="/case/holiday.jpg", size=4096, mtime="2026-08-24T19:00:00Z")
    record.evidence.extend(evidence)
    return record


# --- every source is classified, and classified correctly ----------------------


def test_every_source_that_can_be_reported_has_a_category_and_a_match_basis():
    """A source missing from either table is one nobody thought about. The
    default used to be `interaction`, which classified by forgetting."""
    assert set(SOURCE_CATEGORIES) == set(SOURCE_LABELS)
    assert set(SOURCE_MATCH) == set(SOURCE_LABELS)
    assert set(SOURCE_PRIORITY) == set(SOURCE_LABELS)
    assert set(SOURCE_CATEGORIES.values()) <= set(CATEGORIES)


def test_an_unclassified_source_raises_rather_than_being_guessed_at():
    with pytest.raises(KeyError, match="evidence category"):
        category(EvidenceRecord(source="something-nobody-registered"))


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("browser-download", ORIGIN),
        ("windows-zone-identifier", ORIGIN),
        ("macos-wherefroms", ORIGIN),
        ("xdg-xattr", ORIGIN),
        ("device-metadata", METADATA),
        ("xmp", METADATA),
        ("iptc", METADATA),
        ("document-metadata", METADATA),
        ("email-header", METADATA),
        ("recent-documents", ACTIVITY),
        ("windows-recent", ACTIVITY),
        ("freedesktop-trash", ACTIVITY),
        ("sync-folder", ACTIVITY),
    ],
)
def test_each_source_answers_the_question_it_actually_answers(source: str, expected: str):
    assert category(EvidenceRecord(source=source)) == expected


def test_exif_is_never_an_origin_record():
    """It is the file describing its own earlier life. Where the bytes came
    from is a question a camera has never been able to answer."""
    exif = EvidenceRecord(source="device-metadata", block="exif", tool="NIKON COOLPIX P6000")

    assert category(exif) == METADATA
    assert _file(exif).origin is None


def test_recent_documents_is_not_metadata():
    """It is a desktop's list of what was opened - a fact about this machine,
    not about the file."""
    assert category(EvidenceRecord(source="recent-documents")) == ACTIVITY


def test_a_filesystem_timestamp_is_not_an_origin_record():
    """`btime` says when this filesystem first saw the file. It was classified
    as acquisition, so every unexplained file looked as though something had
    explained it."""
    stamped = EvidenceRecord(source="filesystem", at="2026-08-24T19:00:00Z")

    assert category(stamped) == ACTIVITY
    assert _file(stamped).origin is None


def test_a_shell_command_is_read_per_record_rather_than_per_source():
    """`curl -o` fetched the bytes; `cat` merely read them."""
    fetched = EvidenceRecord(source="shell-history", tool="curl", command="curl -o a.pdf http://x")
    opened = EvidenceRecord(source="shell-history", tool="cat", command="cat a.pdf")

    assert category(fetched) == ORIGIN
    assert category(opened) == ACTIVITY


# --- how a record got attached to this file ------------------------------------


def test_a_torrent_records_what_it_matched_on():
    """Name and exact size, which is not a hash and must not read like one."""

    assert SOURCE_MATCH["torrent"] == NAME_AND_SIZE


def test_a_messenger_file_name_is_matched_by_the_name_and_says_so():
    """The pattern is an association with a client's naming convention. It is
    reported as what it is, and correlation calls the match weak."""
    named = EvidenceRecord(source="messenger-name", note="WhatsApp naming pattern")
    record = _file(named)

    assert named.matched_by == FILENAME
    assert WEAK_MATCH in {finding.kind for finding in correlate(record).findings}


def test_metadata_read_out_of_the_file_says_so():
    assert EvidenceRecord(source="device-metadata").matched_by == EMBEDDED


# --- what leaves the tool ------------------------------------------------------


def test_no_document_exports_a_number_that_could_be_read_as_a_probability():
    record = _file(
        EvidenceRecord(source="browser-download", url="https://example.org/a.jpg"),
        EvidenceRecord(source="device-metadata", block="exif", tool="NIKON"),
    )

    written = json.loads(render_json([record], Path("/case")))
    for found in written["files"][0]["evidence"]:
        assert "confidence" not in found
        assert "priority" not in found
        assert {"category", "source", "match"} <= set(found)


def test_the_scan_document_uses_the_new_vocabulary():
    record = _file(EvidenceRecord(source="browser-download", url="https://example.org/a.jpg"))

    written = json.loads(render_json([record], Path("/case")))
    document = json.dumps(written)

    assert written["schema"] == "filegrail.scan/2"
    assert "evidence" in written["files"][0]
    assert "origins" not in written["files"][0]
    for gone in ('"confidence"', '"acquisition"', '"intrinsic"', '"interaction"'):
        assert gone not in document, gone


def test_the_terminal_report_does_not_print_the_old_model():
    record = _file(
        EvidenceRecord(source="browser-download", url="https://example.org/a.jpg"),
        EvidenceRecord(source="device-metadata", block="exif", tool="NIKON"),
        EvidenceRecord(source="recent-documents", at="2026-08-25T08:00:00Z"),
    )

    printed = render_text([record], Path("/case"), theme=PLAIN)

    for gone in ("ACQUISITION", "INTRINSIC", "INTERACTION", "self-reported", "circumstantial"):
        assert gone not in printed, gone
    for wanted in ("ORIGIN", "METADATA", "ACTIVITY"):
        assert wanted in printed, wanted


# --- correlation decides nothing it cannot decide -------------------------------


def test_two_records_that_disagree_are_both_kept_and_neither_is_chosen():
    record = _file(
        EvidenceRecord(source="browser-download", url="https://one.example/a.pdf"),
        EvidenceRecord(source="windows-zone-identifier", url="https://other.example/a.pdf"),
    )

    result = correlate(record)
    printed = render_text([record], Path("/case"), theme=PLAIN)

    assert result.state == "conflict"
    assert any(finding.kind in CONFLICTS for finding in result.findings)
    assert "one.example" in printed and "other.example" in printed


def test_a_single_record_is_not_reported_as_corroborated():
    record = _file(EvidenceRecord(source="browser-download", url="https://one.example/a.pdf"))

    result = correlate(record)

    assert result.state == "single source"
    assert not result.findings
