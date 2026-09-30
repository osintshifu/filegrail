"""The investigation report, read the way an analyst reads it.

Every object starts on its own line with its number, no name is broken inside a
column, the sections follow the questions a case is opened with, and a file with
nothing to say takes one line until `-v` asks for all of it.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from filegrail.analysis import analyse
from filegrail.casereport import render_case
from filegrail.doctor import AVAILABLE, UNAVAILABLE, Check, Survey
from filegrail.identify import extract
from filegrail.models import EvidenceRecord, FileRecord
from filegrail.theme import Theme

ROOT = Path("/case")
NOW = datetime(2026, 9, 15, 21, 18, tzinfo=timezone.utc)
LONG = "investigative-case-file-review-final-version-for-the-board.pdf"

HEADINGS = (
    "SUMMARY",
    "KEY FINDINGS",
    "FILES",
    "XMP LINEAGE",
    "INVESTIGATIVE PIVOTS",
    "FILE DETAIL",
    "EVIDENCE COVERAGE",
    "REPORT NOTES",
    "END OF REPORT",
)


def _theme(width: int = 94) -> Theme:
    return Theme(colour=False, unicode=True, width=width)


def _heading(line: str) -> str:
    """`01  SUMMARY  ────` reads as `SUMMARY`; the footer reads as itself."""
    if line.startswith("END OF REPORT"):
        return "END OF REPORT"
    found = re.match(r"^\d\d  (.+?)  ─", line)
    return found.group(1) if found else ""


def _between(report: str, start: str, end: str | None = None) -> str:
    """The text of one section, found by its numbered heading."""
    lines = report.splitlines()
    first = next(number for number, line in enumerate(lines) if _heading(line) == start)
    last = len(lines)
    if end is not None:
        last = next(number for number, line in enumerate(lines) if _heading(line) == end)
    return "\n".join(lines[first + 1 : last])


def _file(name: str, *evidence: EvidenceRecord, size: int = 1024) -> FileRecord:
    record = FileRecord(path=f"/case/{name}", size=size, mtime="2026-01-01T00:00:00Z")
    record.evidence.extend(evidence)
    return record


def _corpus() -> list[FileRecord]:
    contested = _file(
        LONG,
        EvidenceRecord(
            source="document-metadata",
            block="pdf-info",
            fields={"Creator": "Adobe InDesign", "CreationDate": "D:20180511143720-04'00'"},
        ),
        EvidenceRecord(
            source="xmp",
            block="xmp",
            fields={
                "xmp:CreatorTool": "Adobe Illustrator",
                "xmp:CreateDate": "2018-02-28T13:44:18-05:00",
            },
        ),
        size=10,
    )
    photo = _file(
        "press/holiday.jpg",
        EvidenceRecord(source="device-metadata", block="exif", geo="43.46745,11.88513"),
        size=5000,
    )
    sheet = _file(
        "isamples/sheet.xlsx",
        EvidenceRecord(
            source="document-metadata", block="ooxml-properties", fields={"creator": "A. Person"}
        ),
        size=3000,
    )
    return [contested, photo, sheet, _file("notes.md", size=100)]


def _report(records: list[FileRecord], **options: object) -> str:
    found = extract(records)
    survey = Survey(
        checks=[
            Check("Chromium family downloads", AVAILABLE, "3 records across 3 of 3 profiles"),
            Check("Shell history", UNAVAILABLE, "no history file found"),
        ],
        horizon=[Check("Chromium family oldest record", AVAILABLE, "2026-09-15")],
    )
    case = analyse(records, ROOT, survey=survey, identifiers=found)
    return render_case(case, identifiers=found, now=NOW, **options)  # type: ignore[arg-type]


def test_the_sections_follow_the_questions_a_case_is_opened_with():
    lines = _report(_corpus(), theme=_theme()).splitlines()

    assert [_heading(line) for line in lines if _heading(line) in HEADINGS] == [
        "SUMMARY",
        "KEY FINDINGS",
        "FILES",
        "INVESTIGATIVE PIVOTS",
        "FILE DETAIL",
        "EVIDENCE COVERAGE",
        "REPORT NOTES",
        "END OF REPORT",
    ]


def test_every_object_starts_on_its_own_line_with_its_whole_name():
    lines = _report(_corpus(), theme=_theme()).splitlines()

    assert f"#001  {LONG}" in lines
    assert any(line.endswith(f"── #001  {LONG}") for line in lines)


def test_a_file_with_nothing_to_say_takes_one_line_until_verbose_opens_it():
    sheet = f"#003  {Path('isamples/sheet.xlsx')}"
    quiet = _report(_corpus(), theme=_theme()).splitlines()
    assert any(line.startswith("#004  notes.md") for line in quiet)
    assert not any(line == sheet for line in quiet)

    assert sheet in _report(_corpus(), theme=_theme(), verbose=True).splitlines()


def test_brief_stops_at_a_one_line_index():
    brief = _report(_corpus(), theme=_theme(), brief=True)

    assert "ID    FILE" in brief
    assert "MARK" not in _between(brief, "FILES")
    for later in ("EVIDENCE COVERAGE", "FILE DETAIL", "REPORT NOTES"):
        assert later not in [_heading(line) for line in brief.splitlines()], later


def test_a_file_points_at_its_conflict_and_the_conflict_shows_both_statements():
    report = _report(_corpus(), theme=_theme())
    files = _between(report, "FILES", "INVESTIGATIVE PIVOTS")

    assert "conflict: Creator" in files
    assert "  └── #001 " in _between(report, "KEY FINDINGS", "FILES")
    assert "Conflict (C01)" in _between(report, "FILE DETAIL", "EVIDENCE COVERAGE")
    assert re.search(r"PDF Info\s+2018-05-11 18:37:20 UTC", report)
    assert re.search(r"Difference\s+XMP is 72 days earlier than PDF Info", report)
    assert "43.46745,11.88513" in _between(report, "KEY FINDINGS", "FILES")


def test_a_declared_source_is_visible_without_becoming_a_metadata_conflict():
    record = _file(
        "generated.png",
        EvidenceRecord(
            source="c2pa",
            fields={
                "digitalSourceType": "trainedAlgorithmicMedia",
                "claim_generator": "Example generator",
            },
        ),
    )

    report = _report([record], theme=_theme())
    summary = _between(report, "SUMMARY", "KEY FINDINGS")

    assert "Declared AI source" in summary
    assert "Need review" not in summary
    assert "declared AI source" in _between(report, "FILES", "FILE DETAIL")
    assert "#001  generated.png" in _between(report, "FILE DETAIL", "EVIDENCE COVERAGE")


def test_a_shared_pivot_lists_every_file_that_holds_it():
    records = [
        _file(
            "alpha.pdf",
            EvidenceRecord(
                source="document-metadata",
                block="pdf-info",
                fields={"Author": "Stephen Richard"},
            ),
        ),
        _file(
            "nested/beta.docx",
            EvidenceRecord(
                source="document-metadata",
                block="ooxml-properties",
                fields={"Author": "Stephen Richard"},
            ),
        ),
    ]

    pivots = _between(_report(records, theme=_theme()), "INVESTIGATIVE PIVOTS", "EVIDENCE COVERAGE")

    assert "P01  PERSON" in pivots
    assert "Files       2" in pivots
    assert "├── #001  alpha.pdf" in pivots
    assert f"└── #002  {Path('nested/beta.docx')}" in pivots


def test_pivot_dense_files_use_the_same_tree_shape_as_shared_pivots():
    links = {f"Link{i}": f"https://example.org/p{i}" for i in range(60)}
    records = [
        _file(
            "links.docx",
            EvidenceRecord(source="document-metadata", block="ooxml-properties", fields=links),
        ),
        _file(
            "note.docx",
            EvidenceRecord(
                source="document-metadata",
                block="ooxml-properties",
                fields={"Link": "https://example.org/p1"},
            ),
        ),
    ]

    report = _report(records, theme=_theme())
    dense = report[report.index("FILES WITH MOST PIVOT OCCURRENCES") :]

    assert "└── #001  links.docx" in dense
    assert "    ├── Pivot occurrences  120" in dense
    assert "    └── URLs  60" in dense


def test_the_notes_explain_only_the_match_bases_the_report_uses():
    notes = _between(_report(_corpus(), theme=_theme()), "REPORT NOTES")

    assert "embedded" in notes
    assert "recorded-path" not in notes
