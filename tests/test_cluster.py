"""Which files in one scan came from the same place.

A directory is a list of files. A case is a smaller number of sources that
produced them, and the difference between those two readings is the whole
point of this: twelve files by three authors is a picture, twelve rows is not.

Nothing here claims two files came from one person or one camera. It says the
files name the same thing, and how strongly that name identifies anything.
"""

from __future__ import annotations

from pathlib import Path

from filegrail.cluster import AUTHOR, DEVICE, MODEL, cluster
from filegrail.models import EvidenceRecord, FileRecord
from filegrail.report import render_text
from filegrail.theme import Theme

PLAIN = Theme(colour=False, unicode=True, width=88)


def _record(path: str, block: str, **fields: str) -> FileRecord:
    record = FileRecord(path=path, size=1024, mtime="2026-01-01T00:00:00Z")
    record.evidence.append(
        EvidenceRecord(source="document-metadata", block=block, fields=dict(fields))
    )
    return record


def _photo(path: str, **fields: str) -> FileRecord:
    record = FileRecord(path=path, size=1024, mtime="2026-01-01T00:00:00Z")
    record.evidence.append(
        EvidenceRecord(source="device-metadata", block="exif", fields=dict(fields))
    )
    return record


def test_files_naming_the_same_author_are_grouped():
    records = [
        _record("/case/a.docx", "ooxml-properties", creator="A. Person"),
        _record("/case/b.docx", "ooxml-properties", creator="A. Person"),
        _record("/case/c.docx", "ooxml-properties", creator="Someone Else"),
    ]

    groups = {group.name: group.paths for group in cluster(records) if group.axis == AUTHOR}

    assert groups["A. Person"] == ["/case/a.docx", "/case/b.docx"]
    assert groups["Someone Else"] == ["/case/c.docx"]


def test_one_author_spelled_in_two_cases_is_one_group():
    records = [
        _record("/case/a.pdf", "pdf-info", Author="iSamples Team"),
        _record("/case/b.pdf", "pdf-info", Author="iSamples team"),
    ]

    groups = [group for group in cluster(records) if group.axis == AUTHOR]

    assert [(g.name, g.paths) for g in groups] == [
        ("iSamples Team", ["/case/a.pdf", "/case/b.pdf"])
    ]


def test_files_from_one_camera_body_are_grouped_by_its_serial():
    records = [
        _photo("/case/1.jpg", Make="NIKON", Model="COOLPIX P6000", BodySerialNumber="3001234"),
        _photo("/case/2.jpg", Make="NIKON", Model="COOLPIX P6000", BodySerialNumber="3001234"),
    ]

    groups = {group.name: group.paths for group in cluster(records) if group.axis == DEVICE}

    assert groups["3001234"] == ["/case/1.jpg", "/case/2.jpg"]


def test_a_shared_model_is_not_reported_as_a_shared_camera():
    """Thousands of people own one model, so it cannot say the bodies are the
    same. It still groups - on an axis that says what it actually knows."""
    records = [
        _photo("/case/1.jpg", Make="NIKON", Model="COOLPIX P6000"),
        _photo("/case/2.jpg", Make="NIKON", Model="COOLPIX P6000"),
    ]

    groups = cluster(records)

    assert not [group for group in groups if group.axis == DEVICE]
    assert [group.paths for group in groups if group.axis == MODEL] == [
        ["/case/1.jpg", "/case/2.jpg"]
    ]


def test_the_biggest_group_on_each_axis_comes_first():
    """The report reads top down and the section is capped, so what is cut has
    to be the least of it rather than whatever hashed last."""
    records = [
        _record("/case/a.docx", "ooxml-properties", creator="Rare"),
        _record("/case/b.docx", "ooxml-properties", creator="Common"),
        _record("/case/c.docx", "ooxml-properties", creator="Common"),
        _photo("/case/1.jpg", Make="NIKON", Model="COOLPIX P6000"),
    ]

    groups = cluster(records)

    assert [(g.axis, g.name, len(g.paths)) for g in groups] == [
        (MODEL, "NIKON COOLPIX P6000", 1),
        (AUTHOR, "Common", 2),
        (AUTHOR, "Rare", 1),
    ]


def test_a_field_naming_two_people_groups_the_file_under_each():
    """A semicolon is how these formats write a list of authors. Read as one
    name it invents a person nobody is, and hides both of the real ones."""
    records = [
        _record("/case/a.docx", "ooxml-properties", creator="A. Person;B. Other"),
        _record("/case/b.docx", "ooxml-properties", creator="A. Person"),
    ]

    groups = {group.name: group.paths for group in cluster(records) if group.axis == AUTHOR}

    assert groups["A. Person"] == ["/case/a.docx", "/case/b.docx"]
    assert groups["B. Other"] == ["/case/a.docx"]


def test_a_comma_does_not_separate_two_authors():
    """`Smith, John` is one person written surname first, and splitting there
    would turn every such document into two people who do not exist."""
    records = [_record("/case/a.docx", "ooxml-properties", creator="Smith, John")]

    assert [group.name for group in cluster(records) if group.axis == AUTHOR] == ["Smith, John"]


# --- how it reads ------------------------------------------------------------


def test_the_section_names_each_shared_attribute_and_how_many_files_it_covers():
    records = [
        _record("/case/a.docx", "ooxml-properties", creator="A. Person"),
        _record("/case/b.docx", "ooxml-properties", creator="A. Person"),
        _photo("/case/1.jpg", Make="NIKON", Model="COOLPIX P6000"),
    ]

    out = render_text(records, Path("/case"), theme=PLAIN, cluster=True)

    assert "A. Person" in out
    assert "2 files" in out


def test_nothing_shared_is_said_rather_than_left_blank():
    """A section that vanishes when it found nothing reads as an omission
    rather than as an answer."""
    records = [_record("/case/a.docx", "ooxml-properties", creator="Only One")]

    out = render_text(records, Path("/case"), theme=PLAIN, cluster=True)

    assert "CLUSTERS" not in out


def test_the_section_is_absent_unless_it_was_asked_for():
    """The name itself still appears - it is a decoded field like any other.
    What the flag governs is the section that groups by it."""
    records = [
        _record("/case/a.docx", "ooxml-properties", creator="A. Person"),
        _record("/case/b.docx", "ooxml-properties", creator="A. Person"),
    ]

    assert "SHARED ATTRIBUTES" not in render_text(records, Path("/case"), theme=PLAIN)
