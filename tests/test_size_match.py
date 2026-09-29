"""What the record says about how it was tied to this file."""

from __future__ import annotations

from filegrail.correlate import correlate
from filegrail.models import FILENAME, NAME_AND_SIZE, EvidenceRecord, FileRecord
from filegrail.scan import matched_by_name


def _download(size: int | None) -> EvidenceRecord:
    return EvidenceRecord(source="browser-download", url="https://example.org/a.pdf", bytes=size)


def test_a_matching_size_is_part_of_the_match_basis():
    found = matched_by_name(_download(4096), 4096)

    assert found.matched_by == NAME_AND_SIZE
    assert "differs" not in (found.match_note or "")


def test_a_differing_size_leaves_the_basis_at_the_name_and_says_so():
    """Same name, different bytes: very likely a different file."""
    found = matched_by_name(_download(9999), 4096)

    assert found.matched_by == FILENAME
    assert "differs" in found.match_note


def test_no_recorded_size_leaves_the_name_alone_as_the_basis():
    found = matched_by_name(_download(None), 4096)

    assert found.matched_by == FILENAME
    assert "size" not in (found.match_note or "")


def test_a_size_mismatch_reaches_the_correlation():
    record = FileRecord(path="/case/a.pdf", size=4096, mtime="2026-08-24T19:00:00Z")
    record.evidence.append(matched_by_name(_download(9999), 4096))

    result = correlate(record)

    assert any("differs" in reason for reason in result.reasons)


def test_a_size_match_is_not_reported_as_a_problem():
    record = FileRecord(path="/case/a.pdf", size=4096, mtime="2026-08-24T19:00:00Z")
    record.evidence.append(matched_by_name(_download(4096), 4096))

    result = correlate(record)

    assert not any("differs" in reason for reason in result.reasons)


def test_a_source_that_has_already_explained_itself_adds_no_note():
    """The reason is optional, because not every source needs to give one.

    A shortcut's note already says where the file was opened from, so
    restating that the recorded path is not this one makes a third clause out
    of something the first clause said.
    """
    found = matched_by_name(_download(4096), 4096, "")

    assert found.matched_by == NAME_AND_SIZE
    assert found.match_note is None


def test_the_basis_reaches_json_rather_than_a_sentence():
    """`match` is a field a consumer can branch on, which a note never was."""
    record = FileRecord(path="/case/a.pdf", size=4096, mtime="2026-08-24T19:00:00Z")
    record.evidence.append(matched_by_name(_download(4096), 4096))

    written = record.to_dict()["evidence"][0]

    assert written["match"] == {
        "method": NAME_AND_SIZE,
        "note": "the file was moved or renamed since download",
    }
