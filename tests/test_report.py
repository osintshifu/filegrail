import re
from pathlib import Path

import pytest

from filegrail import __version__
from filegrail.models import EvidenceRecord, FileRecord
from filegrail.report import render_text
from filegrail.scan import Unsearched
from filegrail.theme import Theme

#: Deterministic rendering for assertions: no colour, no box drawing.
PLAIN = Theme(colour=False, unicode=False, width=88)


def _record(name: str, origin: EvidenceRecord | None = None) -> FileRecord:
    record = FileRecord(path=f"/case/{name}", size=1, mtime="2026-08-24T19:00:00Z")
    if origin is not None:
        record.evidence.append(origin)
    return record


def _listed(output: str) -> int:
    """How many unexplained files the index actually named."""
    return sum(
        1 for line in output.splitlines() if any(token.endswith(".txt") for token in line.split())
    )


def test_no_cap_message_when_everything_fits():
    output = render_text([_record("a.txt"), _record("b.txt")], Path("/case"), limit=25)
    assert "more (--json" not in output


def test_the_explanation_for_zero_matches_fits_the_window():
    """Its sentences were broken by hand, so the one carrying two counts grew
    past the edge as soon as a real machine had more than a few records."""
    stats = {"browser_profiles": 12, "browser_records": 148_392}

    for width in (48, 72, 88):
        theme = Theme(colour=False, unicode=False, width=width)
        output = render_text([_record("a.txt")], Path("/case"), stats=stats, theme=theme)
        over = [line for line in output.splitlines() if len(line) > width]
        assert not over, (width, over)


# --- what the report says before it says anything about a file ---------------


def _corpus() -> list[FileRecord]:
    """A directory of the ordinary shape: several types, most of them readable,
    a few that said nothing, and one pair of records that disagree."""
    records = [
        _record(
            "photo.jpg", EvidenceRecord(source="device-metadata", tool="NIKON", geo="43.4, 11.8")
        ),
        _record("holiday.jpg", EvidenceRecord(source="device-metadata", tool="NIKON")),
        _record(
            "paper.pdf", EvidenceRecord(source="document-metadata", block="pdf-info", tool="Word")
        ),
        _record(
            "report.pdf", EvidenceRecord(source="document-metadata", block="pdf-info", tool="Word")
        ),
        _record("figure.png", EvidenceRecord(source="c2pa", tool="OpenAI Media Service API")),
        _record("notes.txt"),
        _record("scratch.bin"),
    ]
    records.append(
        FileRecord(
            path="/case/invoice.pdf",
            size=2048,
            mtime="2026-08-24T19:00:00Z",
            evidence=[
                EvidenceRecord(
                    source="browser-download", url="https://one.example.org/invoice.pdf"
                ),
                EvidenceRecord(
                    source="windows-zone-identifier", url="https://other.example.net/i.pdf"
                ),
            ],
        )
    )
    return records


def _rule(line: str) -> bool:
    return bool(line.strip()) and set(line.strip()) <= {"-", "\u2500"}


def _at(output: str, heading: str) -> int:
    """Which line carries a section heading.

    A heading is a line at column two with a rule directly under it. Both halves
    matter: `findings` is a word the banner uses as a row label too, and a plain
    substring search compared the wrong two positions and passed.

    The name is upper-cased here rather than at every call site. What a section
    is called and how a heading is cased are two different claims, and only one
    test needs to make the second one.
    """
    heading = heading.upper()
    lines = output.splitlines()
    for index, line in enumerate(lines[:-1]):
        if line.startswith(heading) and _rule(lines[index + 1]):
            return index
    raise AssertionError(f"no {heading!r} section in the report")


def _line(output: str, text: str) -> int:
    for index, line in enumerate(output.splitlines()):
        if text in line:
            return index
    raise AssertionError(f"{text!r} is not in the report")


def _section(output: str, heading: str) -> list[str]:
    """The lines of one section, from its heading down to the next one.

    Asserting that a name appears somewhere in a long report proves nothing:
    every name in the attention block also appears in the entry it points at.
    """
    heading = heading.upper()
    lines = output.splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip().startswith(heading))
    rules = [index for index, line in enumerate(lines) if _rule(line) and index > start + 1]
    return lines[start : (rules[0] - 1) if rules else len(lines)]


def test_the_masthead_does_not_call_a_metadata_block_a_traced_origin():
    """A file with EXIF has not been traced anywhere. Counting it as though it
    had is the report telling the reader something it does not know."""
    output = render_text(_corpus(), Path("/case"), theme=PLAIN)

    assert "traced" not in output


def test_the_summary_section_says_what_was_read():
    output = render_text(_corpus(), Path("/case"), theme=PLAIN)

    assert "SUMMARY" in output
    # The rows are what was found, in the words the tally uses. Only the
    # heading above them is upper case; a row is not a heading.
    assert "with evidence" in output
    assert "origin records" in output
    assert "findings" in output


def test_a_quiet_directory_raises_nothing():
    records = [
        _record("a.pdf", EvidenceRecord(source="document-metadata", tool="Word")) for _ in range(3)
    ]

    output = render_text(records, Path("/case"), theme=PLAIN)

    assert "attention" not in output


def test_the_report_reads_from_the_directory_down_to_the_file():
    output = render_text(_corpus(), Path("/case"), theme=PLAIN)

    assert _at(output, "summary") < _at(output, "files")
    assert _at(output, "files") < _at(output, "origin")
    assert _at(output, "origin") < _at(output, "metadata")
    assert _at(output, "metadata") < _at(output, "unresolved")


def test_one_file_is_not_given_an_inventory_of_itself():
    """`filegrail suspicious.pdf` is a common way in. A one-row inventory and a
    findings table over a single file is ceremony in front of the answer."""
    output = render_text(
        [_record("suspicious.pdf", EvidenceRecord(source="document-metadata", tool="Word"))],
        Path("/case"),
        theme=PLAIN,
    )

    assert "INVENTORY" not in output
    assert "suspicious.pdf" in output


def test_the_section_headings_say_what_the_section_holds():
    """`claimed by the file itself` is true and says nothing about what is in
    there, and `no recorded origin` describes a narrower case than the files it
    used to head - a file with nothing at all found for it."""
    output = render_text(_corpus(), Path("/case"), theme=PLAIN)

    assert "claimed by the file itself" not in output
    assert "no recorded origin" not in output


# --- the report names itself -------------------------------------------------


def test_the_banner_is_not_the_landing_screen():
    """The front door introduces the tool; a report identifies itself. Usage,
    commands and where to file a bug belong on one and not the other."""
    output = render_text(_corpus(), Path("/case"), theme=PLAIN)

    for elsewhere in ("github.com", "Apache-2.0", "usage", "commands", "help <command>"):
        assert elsewhere not in output, elsewhere


@pytest.mark.parametrize("width", [48, 64, 80, 110])
def test_the_banner_fits_every_terminal(width: int):
    theme = Theme(colour=False, unicode=True, width=width)

    output = render_text(_corpus(), Path("/case"), theme=theme)

    assert f"filegrail {__version__}" in output
    assert not [line for line in output.splitlines() if len(line) > width]


# --- notable findings --------------------------------------------------------


# --- the whole list, unless asked otherwise ----------------------------------


def _unexplained(count: int) -> list[FileRecord]:
    return [_record(f"f{index}.txt") for index in range(count)]


# --- what was not searched ---------------------------------------------------


def test_the_report_says_which_directories_were_not_read():
    """A directory the walk could not enter is a hole, and holes are findings.

    The report's own premise is that "searched and not found" and "never
    searched" are different sentences. A directory that could not be opened
    produces no files, so without this line nothing in the report is about it
    and nothing in the report says so.
    """
    missed = Unsearched(unreadable=["/case/locked", "/case/sealed"])

    output = render_text([_record("a.jpg")], Path("/case"), theme=PLAIN, unsearched=missed)

    assert "could not be read" in output
    assert "locked" in output and "sealed" in output


def test_the_report_says_which_directories_it_skipped_by_name():
    missed = Unsearched(by_name=["/case/node_modules"])

    output = render_text([_record("a.jpg")], Path("/case"), theme=PLAIN, unsearched=missed)

    assert "skipped by name" in output
    assert "node_modules" in output


def test_the_two_reasons_are_not_merged():
    """One is a choice this tool made; the other is evidence that was not there."""
    missed = Unsearched(unreadable=["/case/locked"], by_name=["/case/build"])

    output = render_text([_record("a.jpg")], Path("/case"), theme=PLAIN, unsearched=missed)

    assert "could not be read" in output
    assert "skipped by name" in output
    assert output.index("could not be read") < output.index("skipped by name")


def test_a_report_with_nothing_missed_says_nothing_about_it():
    output = render_text([_record("a.jpg")], Path("/case"), theme=PLAIN, unsearched=Unsearched())

    assert "could not be read" not in output
    assert "skipped by name" not in output


def test_the_profile_that_was_read_is_named_beside_the_target():
    """The one line saying the evidence did not come from this machine. It sits
    beside what was scanned, because both are facts about the same run."""
    # The path is compared as this platform writes it: `Path` renders a POSIX
    # literal with backslashes on Windows, and the claim here is about the row,
    # not about separators.
    profile = Path("/mnt/image/home/ann")
    output = render_text(_corpus(), Path("/case"), theme=PLAIN, home=profile)

    row = next(line for line in output.splitlines() if line.startswith("target"))
    assert str(profile) in row
    assert "external" in row
    assert "evidence read from the profile at" not in output


def test_a_file_that_needs_a_second_look_is_marked_once():
    """One mark, in the table of files, and the legend under it says what the
    mark means. The file then appears again in ORIGIN and in FINDINGS, where
    what is being listed is a record rather than a file - and a second mark
    beside it there would be the report flagging the same fact twice."""
    output = render_text(_corpus(), Path("/case"), theme=PLAIN)

    marks = re.findall(r"^([!.]) +invoice\.pdf", output, flags=re.MULTILINE)
    assert marks == ["!"], marks
    assert "needs review" in output


def test_the_profile_is_written_the_same_way_as_the_target(monkeypatch, tmp_path: Path):
    """Two paths on one line, one abbreviated and one not, read as two
    different kinds of thing. They are both just paths."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    output = render_text(_corpus(), tmp_path / "case", theme=PLAIN, home=tmp_path / "image" / "ann")

    # Built from a `Path` rather than written out: `_display` keeps the `~/`
    # prefix and then whatever separator the platform uses, so a POSIX literal
    # here fails on Windows for a row that is perfectly correct there.
    row = next(line for line in output.splitlines() if line.startswith("target"))

    assert "~/case" in row
    assert f"~/{Path('image') / 'ann'}" in row
