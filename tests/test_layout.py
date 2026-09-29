"""The grammar every view is written in, held to at every width.

A terminal layout breaks quietly: one long file name, one narrow window, and a
line wraps into the next row's gutter. Nothing raises, the tests stay green,
and the report is unreadable. These fail instead.

Three rules carry most of it. Nothing is wider than the window. Nothing is
truncated - a value cut off at an ellipsis is one the reader now has to fetch
another way, which defeats having read the file at all. And every count in a
section heading is of something a reader can go and count underneath it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from filegrail.analysis import analyse
from filegrail.casereport import render_case
from filegrail.clean import Cleaned
from filegrail.compare import compare
from filegrail.doctor import survey
from filegrail.identify import extract
from filegrail.models import EvidenceRecord, FileRecord
from filegrail.report import (
    render_clean,
    render_compare,
    render_doctor,
    render_explain,
    render_text,
    render_timeline,
)
from filegrail.theme import Theme

ROOT = Path("/case")

#: The narrowest window the theme allows, the width a redirected report is laid
#: out to, and two ordinary terminals.
WIDTHS = (48, 56, 64, 72, 80, 88, 110)

LONG_URL = "https://example.org/" + "path-segment/" * 12 + "report.pdf"


def _theme(width: int = 88, *, unicode: bool = True) -> Theme:
    return Theme(colour=False, unicode=unicode, width=width)


def _record(name: str, *evidence: EvidenceRecord, size: int = 4096) -> FileRecord:
    record = FileRecord(path=f"/case/{name}", size=size, mtime="2026-08-24T19:00:00Z")
    record.evidence.extend(evidence)
    return record


def _corpus() -> list[FileRecord]:
    """One file per category, plus the awkward cases: a very long name, a very
    long URL, records that disagree, and a file nothing explains."""
    return [
        _record(
            "downloads/" + "extremely-long-file-name-" * 6 + ".pdf",
            EvidenceRecord(
                source="browser-download",
                url=LONG_URL,
                referrer="https://example.org/" + "referring-page/" * 8,
                tool="firefox",
                at="2026-08-24T19:02:11Z",
            ),
            size=1 << 30,
        ),
        _record(
            "holiday.jpg",
            EvidenceRecord(
                source="device-metadata",
                block="exif",
                tool="NIKON COOLPIX P6000",
                geo="43.467448, 11.885127",
                at="2026-08-22T16:28:39Z",
                fields={"Make": "NIKON", "Model": "COOLPIX P6000", "BodySerialNumber": "3001234"},
            ),
        ),
        _record(
            "opened.pdf",
            EvidenceRecord(source="recent-documents", at="2026-08-25T08:00:00Z", tool="evince"),
        ),
        _record(
            "contested.pdf",
            EvidenceRecord(source="browser-download", url="https://one.example/a.pdf"),
            EvidenceRecord(source="windows-zone-identifier", url="https://other.example/a.pdf"),
        ),
        _record("notes.md", size=102),
    ]


def _every_view(theme: Theme) -> dict[str, str]:
    """Every text view there is, rendered from one corpus."""
    records = _corpus()
    one = records[1]
    found = extract(records)
    case = analyse(records, ROOT, survey=survey(Path("/nonexistent")), identifiers=found)
    return {
        "case": render_case(case, theme=theme, identifiers=found),
        "case-verbose": render_case(case, theme=theme, identifiers=found, verbose=True),
        "case-brief": render_case(case, theme=theme, brief=True),
        "scan": render_text(records, ROOT, theme=theme),
        "brief": render_text(records, ROOT, theme=theme, brief=True),
        "file": render_text([one], ROOT, theme=theme),
        "identify": render_text(records, ROOT, theme=theme, identify=True),
        "cluster": render_text(records, ROOT, theme=theme, cluster=True),
        "timeline": render_timeline(records, ROOT, theme=theme),
        "explain": render_explain(one, theme=theme),
        "compare": render_compare(one, records[3], compare(one, records[3]), theme=theme),
        "doctor": render_doctor(survey(Path("/nonexistent")), theme=theme),
        "clean": render_clean(
            [Cleaned(path=Path("/case/holiday.jpg"), removed=["exif"], remaining=["xmp"])],
            ROOT,
            None,
            theme=theme,
            check=True,
        ),
    }


def test_terminal_timeline_orders_offsets_by_the_instant_they_represent():
    records = [
        _record(
            "later.jpg",
            EvidenceRecord(source="c2pa", tool="later actual", at="2026-01-01T00:00:00Z"),
        ),
        _record(
            "earlier.jpg",
            EvidenceRecord(source="c2pa", tool="earlier actual", at="2026-01-01T00:30:00+02:00"),
        ),
    ]

    report = render_timeline(records, ROOT, theme=_theme())

    assert report.index("earlier.jpg") < report.index("later.jpg")
    assert report.index("2025-12-31 22:30:00") < report.index("2026-01-01 00:00:00")


# --- the window ---------------------------------------------------------------


@pytest.mark.parametrize("unicode_ok", [True, False])
@pytest.mark.parametrize("width", WIDTHS)
def test_no_line_in_any_view_exceeds_the_window(width: int, unicode_ok: bool):
    for name, output in _every_view(_theme(width, unicode=unicode_ok)).items():
        over = [line for line in output.splitlines() if len(line) > width]
        assert not over, f"{name} at {width}: {over[:1]}"


@pytest.mark.parametrize("width", WIDTHS)
def test_nothing_anywhere_is_truncated(width: int):
    """The one thing this report never does. A URL with an ellipsis in it
    cannot be copied, opened or grepped for."""
    for name, output in _every_view(_theme(width)).items():
        assert "…" not in output, name
        assert "..." not in output.replace("...and", ""), name


@pytest.mark.parametrize("width", WIDTHS)
def test_a_long_url_survives_intact(width: int):
    """Broken across lines by the window is unavoidable; broken and lost is not."""
    output = render_text(_corpus(), ROOT, theme=_theme(width))
    case = render_case(analyse(_corpus(), ROOT), theme=_theme(width), verbose=True)

    assert LONG_URL in _flat(output)
    assert LONG_URL in _flat(case)


def _flat(output: str) -> str:
    """The report with wrapping undone, for asking whether a value survived."""
    return re.sub(r"\s+", "", output)


# --- the grammar ---------------------------------------------------------------


def test_every_section_heading_is_upper_case_with_its_counts_beside_it():
    output = render_text(_corpus(), ROOT, theme=_theme())

    headings = [line for line in output.splitlines() if _is_heading(line)]
    assert headings
    for heading in headings:
        name = heading.split("·")[0].strip()
        assert name == name.upper(), heading


def _is_heading(line: str) -> bool:
    head = line.split("·")[0].strip()
    return bool(head) and head == head.upper() and head[:1].isalpha() and not line.startswith(" ")


def test_a_section_is_not_printed_when_it_holds_nothing():
    """An empty heading is a promise the scan did not keep."""
    output = render_text([_record("notes.md")], ROOT, theme=_theme())

    for absent in ("ORIGIN", "METADATA", "ACTIVITY", "FINDINGS", "CLUSTERS"):
        assert absent not in output, absent


def test_a_table_rules_the_width_of_each_column_not_of_its_name():
    """The rule is what says how far a column reaches, which is the question a
    reader has when the values in it are short."""
    output = render_text(_corpus(), ROOT, theme=_theme())

    head = next(i for i, line in enumerate(output.splitlines()) if line.strip().startswith("file "))
    rule = output.splitlines()[head + 1]
    assert set(rule.strip()) == {"─", " "}
    assert len(rule) > len(output.splitlines()[head].rstrip())


def test_the_marks_are_explained_where_they_are_used():
    output = render_text(_corpus(), ROOT, theme=_theme())

    assert "no evidence found" in output
    assert "needs review" in output


def test_an_ordinary_row_carries_no_mark():
    """A mark on every row is a mark that says nothing."""
    output = render_text(_corpus(), ROOT, theme=_theme())

    row = next(line for line in output.splitlines() if "holiday.jpg" in line and "JPEG" in line)
    assert row.startswith("  ")


# --- what the counts count ------------------------------------------------------


def test_the_origin_count_is_the_number_of_rows_under_it():
    records = _corpus()
    output = render_text(records, ROOT, theme=_theme(110))

    said = _counted(output, "ORIGIN", "record")
    assert said == sum(
        1 for record in records for one in record.evidence if one.category == "origin"
    )


def test_the_files_count_is_the_number_of_files():
    records = _corpus()
    output = render_text(records, ROOT, theme=_theme(110))

    assert _counted(output, "FILES", "file") == len(records)


def _counted(output: str, heading: str, noun: str) -> int:
    line = next(line for line in output.splitlines() if line.startswith(heading + " "))
    found = re.search(rf"(\d+) {noun}", line)
    assert found, line
    return int(found.group(1))


# --- the chrome -----------------------------------------------------------------


def test_the_run_says_what_it_looked_at_on_one_line():
    output = render_text(_corpus(), ROOT, theme=_theme(), home=Path("/mnt/image/home/ann"))

    row = next(line for line in output.splitlines() if line.startswith("target"))
    assert str(Path("/mnt/image/home/ann")) in row
    assert "external" in row


def test_a_scan_of_this_machine_says_nothing_about_a_profile():
    """A row saying the profile is the usual one is a row that says nothing."""
    output = render_text(_corpus(), ROOT, theme=_theme())

    assert "profile" not in output
    assert "external" not in output
