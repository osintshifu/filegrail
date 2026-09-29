"""One file, every source, and why the verdict says what it says.

The report answers "what do we know". This answers "why should I believe it",
which is a different question and the one that decides whether a finding can be
used. It adds no data: it lays out what was already found, says which records
support each other and which do not, and draws the conclusion out loud so that a
reader can disagree with it.
"""

from __future__ import annotations

from pathlib import Path

from filegrail.correlate import correlate
from filegrail.explain import assessment
from filegrail.models import EvidenceRecord, FileRecord
from filegrail.report import render_explain
from filegrail.theme import Theme

PLAIN = Theme(colour=False, unicode=False, width=88)

DOWNLOAD = EvidenceRecord(
    source="browser-download",
    url="https://example.org/holiday.jpg",
    tool="firefox",
    at="2026-08-24T19:02:11Z",
)
ZONE = EvidenceRecord(source="windows-zone-identifier", url="https://example.org/holiday.jpg")
MIRROR = EvidenceRecord(
    source="windows-zone-identifier", url="https://mirror.example.net/holiday.jpg"
)
CAMERA = EvidenceRecord(
    source="device-metadata",
    tool="NIKON COOLPIX P6000",
    at="2008-10-22T16:28:39Z",
    geo="43.467448, 11.885127",
)
OPENED = EvidenceRecord(source="recent-documents", tool="GIMP", note="opened by GIMP")


def _record(*origins: EvidenceRecord) -> FileRecord:
    record = FileRecord(path="/case/holiday.jpg", size=4096, mtime="2026-08-24T19:00:00Z")
    record.evidence.extend(origins)
    return record


def _said(record: FileRecord) -> str:
    return " ".join(assessment(record, correlate(record)))


# --- the conclusion ----------------------------------------------------------


def test_nothing_at_all_says_so_and_points_at_doctor():
    """The advice has to name something a reader can actually type. `doctor`
    stopped being a flag when the modes became commands."""
    said = _said(_record())

    assert "nothing" in said.lower()
    assert "filegrail doctor" in said
    assert "--doctor" not in said


def test_one_record_is_described_as_uncorroborated():
    said = _said(_record(DOWNLOAD))

    assert "one" in said.lower()
    assert "corroborat" in said


def test_two_agreeing_records_are_described_as_independent():
    said = _said(_record(DOWNLOAD, ZONE))

    assert "two" in said.lower() or "2" in said
    assert "agree" in said


def test_a_conflict_is_stated_as_a_conflict():
    said = _said(_record(DOWNLOAD, MIRROR))

    assert "not agree" in said or "disagree" in said


def test_metadata_is_described_as_not_contesting_the_origin_record():
    """The distinction the whole model exists to keep."""
    said = _said(_record(DOWNLOAD, CAMERA))

    assert "earlier" in said


def test_activity_is_never_described_as_explaining_arrival():
    said = _said(_record(OPENED))

    assert "handled" in said or "opened" in said
    assert "downloaded from" not in said


def test_a_timeline_conflict_is_called_out_in_the_conclusion():
    late = EvidenceRecord(source="document-metadata", tool="Word", at="2026-09-01T10:00:00Z")

    said = _said(_record(DOWNLOAD, late))

    assert "after" in said


# --- the rendering -----------------------------------------------------------


def test_it_groups_the_sources_by_kind():
    output = render_explain(_record(DOWNLOAD, CAMERA, OPENED), theme=PLAIN)

    assert "ORIGIN" in output
    assert "METADATA" in output
    assert "ACTIVITY" in output


def test_it_names_every_record_it_found():
    output = render_explain(_record(DOWNLOAD, ZONE, CAMERA), theme=PLAIN)

    assert "browser download" in output
    assert "Windows zone" in output
    assert "device metadata" in output


def test_it_stays_inside_the_width():
    record = _record(DOWNLOAD, MIRROR, CAMERA, OPENED)

    for width in (48, 64, 88, 110):
        output = render_explain(record, theme=Theme(colour=False, unicode=False, width=width))
        assert not [line for line in output.splitlines() if len(line) > width]


def test_every_heading_is_uppercase_in_explain_and_compare():
    """The same reasoning as the scan report: without colour a heading has only
    its letters and its position left to distinguish it from body text, and a
    report read from a file has no colour."""
    from filegrail.compare import compare
    from filegrail.report import render_compare

    record = _record(DOWNLOAD, CAMERA, OPENED)
    explained = render_explain(record, theme=PLAIN)
    for heading in ("SUMMARY", "ORIGIN"):
        assert heading in explained, heading

    other = _record(DOWNLOAD, CAMERA)
    compared = render_compare(record, other, compare(record, other), theme=PLAIN)
    for heading in ("FILES", "METADATA", "CORRELATION"):
        assert heading in compared, heading


# --- what explain answers first -----------------------------------------------

NARROW = Theme(colour=False, unicode=False, width=72)


def test_an_address_is_not_broken_in_the_middle_of_itself(tmp_path: Path):
    """A URL used to share a line with the source name and the strength, which
    left it a third of the terminal. Anything longer broke inside a token, and
    an address the report cut in half is one nothing can open or grep for."""
    long_url = "https://portal.example.org/press/2026/holiday-master.jpg"
    record = _record(EvidenceRecord(source="browser-download", url=long_url, tool="firefox"))

    output = render_explain(record, theme=NARROW)

    assert long_url in output


def test_a_record_carries_the_same_match_basis_the_scan_shows():
    """One report, one way of saying how a record was tied to the file."""
    record = _record(EvidenceRecord(source="browser-download", url="https://a.example/h.jpg"))

    printed = render_explain(record, theme=PLAIN)

    assert "recorded-path" in printed
