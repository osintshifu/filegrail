"""What a scan found, counted before any one file is described.

The report used to open on its first entry, which answers the last question an
analyst asks. These are the ones that come first: what is in this directory,
how much of it, how many files said anything, what they said, and which of them
wants a second look.

Every count here is read back off records the scan already produced. Nothing in
this module decides anything, so a number in the overview and the entry it
refers to cannot disagree.
"""

from __future__ import annotations

from filegrail.filters import FAMILIES
from filegrail.identify import Identifier
from filegrail.models import EvidenceRecord, FileRecord
from filegrail.overview import NAMED, OTHER, inventory, notable, summary


def _record(name: str, *origins: EvidenceRecord, size: int = 1024) -> FileRecord:
    record = FileRecord(path=f"/case/{name}", size=size, mtime="2026-08-24T19:00:00Z")
    record.evidence.extend(origins)
    return record


def _named(found, name: str) -> int:
    """How many files one row of the findings table counted."""
    for tally in found:
        if tally.name == name:
            return tally.files
    return 0


# --- inventory ---------------------------------------------------------------


def test_every_extension_is_counted_and_none_are_dropped():
    """No top ten, no ellipsis. An inventory that hides the tail is a inventory
    of the part somebody already guessed."""
    records = [_record(f"file{index}.ext{index}") for index in range(30)]

    found = inventory(records)

    assert len(found.types) == 30
    assert sum(entry.count for entry in found.types) == 30


def test_an_extension_is_named_the_way_an_analyst_says_it():
    found = inventory([_record("a.PDF"), _record("b.pdf")])

    assert [entry.name for entry in found.types] == ["PDF"]
    assert found.types[0].count == 2


def test_a_file_with_no_extension_is_still_in_the_inventory():
    """A file nobody named is exactly the sort a scan should account for."""
    found = inventory([_record("README"), _record("a.pdf")])

    named = {entry.name: entry.count for entry in found.types}
    assert named["(none)"] == 1
    assert named["PDF"] == 1


def test_a_dotfile_has_no_extension_rather_than_a_strange_one():
    found = inventory([_record(".bashrc")])

    assert [entry.name for entry in found.types] == ["(none)"]


def test_the_inventory_carries_how_much_of_the_scan_each_type_is():
    records = [_record("a.pdf", size=2000), _record("b.pdf", size=1000), _record("c.jpg", size=50)]

    found = inventory(records)

    sizes = {entry.name: entry.size for entry in found.types}
    assert sizes == {"PDF": 3000, "JPEG": 50}
    assert found.size == 3050
    assert found.files == 3


def test_the_biggest_group_is_first():
    records = [_record("a.jpg"), _record("b.pdf"), _record("c.pdf")]

    assert [entry.name for entry in inventory(records).types] == ["PDF", "JPEG"]


# --- families ----------------------------------------------------------------


def test_families_are_the_ones_the_type_filter_already_knows():
    """`--type image` has to select what the inventory called an image, so the
    inventory reads the filter's own table rather than a second one beside it."""
    records = [_record("a.jpg"), _record("b.pdf"), _record("c.mp4"), _record("d.bin")]

    named = {name for name, _ in inventory(records).families}

    assert named <= set(FAMILIES) | {OTHER}
    assert named == {"image", "document", "video", OTHER}


def test_a_file_belongs_to_one_family_so_the_counts_add_up():
    """`.msg` is in both `document` and `mail` because either filter should
    select it. An inventory has to put it somewhere, and a message is the more
    specific of the two answers."""
    records = [_record("a.msg"), _record("b.jpg"), _record("c.pdf")]

    found = inventory(records)

    assert sum(count for _, count in found.families) == len(records)
    assert dict(found.families)["mail"] == 1
    assert "document" in dict(found.families)


def test_an_extension_no_family_claims_is_counted_rather_than_lost():
    found = inventory([_record("core.dmp")])

    assert dict(found.families) == {OTHER: 1}


# --- findings ----------------------------------------------------------------


def test_findings_say_what_was_found_rather_than_which_reader_ran():
    records = [
        _record(
            "photo.jpg", EvidenceRecord(source="device-metadata", tool="NIKON", geo="43.4, 11.8")
        ),
        _record(
            "paper.pdf", EvidenceRecord(source="document-metadata", block="pdf-info", tool="Word")
        ),
        _record("nothing.bin"),
    ]

    found = summary(records)

    assert _named(found, "device information") == 1
    assert _named(found, "coordinates") == 1
    assert _named(found, "creating software") == 2


def test_a_category_nothing_matched_is_not_printed_as_a_zero():
    """A table of zeroes reads as a list of things the tool cannot do."""
    found = summary([_record("paper.pdf", EvidenceRecord(source="document-metadata", tool="Word"))])

    assert "coordinates" not in {tally.name for tally in found}
    assert "Content Credentials" not in {tally.name for tally in found}


def test_an_origin_record_is_counted_apart_from_the_metadata():
    """The two answer different questions and the report never ranks them."""
    records = [
        _record(
            "a.pdf", EvidenceRecord(source="browser-download", url="https://example.org/a.pdf")
        ),
        _record("b.pdf", EvidenceRecord(source="document-metadata", tool="Word")),
    ]

    found = summary(records)

    assert _named(found, "origin evidence") == 1
    assert _named(found, "activity records") == 0


def test_contradicting_records_are_counted_as_conflicting_evidence():
    record = _record(
        "a.pdf",
        EvidenceRecord(source="browser-download", url="https://one.example.org/a.pdf"),
        EvidenceRecord(source="windows-zone-identifier", url="https://other.example.net/a.pdf"),
    )

    assert _named(summary([record]), "conflicting evidence") == 1


def test_content_credentials_are_counted_on_their_own():
    record = _record("figure.png", EvidenceRecord(source="c2pa", tool="OpenAI Media Service API"))

    assert _named(summary([record]), "Content Credentials") == 1


# --- attention ---------------------------------------------------------------


def test_nothing_worth_a_second_look_prints_no_section():
    records = [_record("a.pdf", EvidenceRecord(source="document-metadata", tool="Word"))]

    assert notable(records, []) == []


def test_a_conflict_is_raised_and_the_files_are_named():
    """A count with no names sends the reader back through the whole report."""
    record = _record(
        "a.pdf",
        EvidenceRecord(source="browser-download", url="https://one.example.org/a.pdf"),
        EvidenceRecord(source="windows-zone-identifier", url="https://other.example.net/a.pdf"),
    )

    raised = notable([record], [])

    assert len(raised) == 1
    assert raised[0].contested
    assert raised[0].files == ("/case/a.pdf",)
    assert "1 file" in raised[0].text


def test_a_long_list_of_conflicts_says_how_many_it_did_not_name():
    """Capping in silence would read as "these are the conflicts" when it is
    not, so the line that caps says so and names where the rest are."""

    def conflicted(name: str) -> FileRecord:
        return _record(
            name,
            EvidenceRecord(source="browser-download", url="https://one.example.org/x"),
            EvidenceRecord(source="windows-zone-identifier", url="https://other.example.net/x"),
        )

    raised = notable([conflicted(f"f{index}.pdf") for index in range(NAMED + 3)], [])

    assert len(raised[0].files) == NAMED
    assert raised[0].hidden == 3


def test_coordinates_and_credentials_are_raised_because_they_are_easy_to_miss():
    records = [
        _record(
            "photo.jpg", EvidenceRecord(source="device-metadata", tool="NIKON", geo="43.4, 11.8")
        ),
        _record("figure.png", EvidenceRecord(source="c2pa", tool="OpenAI")),
    ]

    said = [alert.text for alert in notable(records, [])]

    assert any("coordinates" in text for text in said)
    assert any("Content Credentials" in text for text in said)


def test_identifiers_are_raised_with_a_way_to_see_them():
    found = [Identifier(type="email", value="a@example.org", normalized="a@example.org")]
    records = [_record("a.pdf", EvidenceRecord(source="document-metadata", tool="Word"))]

    raised = notable(records, found)

    assert any("--pivots" in alert.text for alert in raised)


def test_identifiers_already_listed_are_not_advertised_again():
    found = [Identifier(type="email", value="a@example.org", normalized="a@example.org")]
    records = [_record("a.pdf", EvidenceRecord(source="document-metadata", tool="Word"))]

    raised = notable(records, found, listed=True)

    assert any("identifier" in alert.text for alert in raised)
    assert not any("--pivots" in alert.text for alert in raised)


# --- what an analyst calls a format ------------------------------------------


def test_the_same_format_under_two_spellings_is_one_row():
    """`JPG 20` beside `JPEG 1` is one format counted twice. The extension is
    what the filesystem happened to record; the format is what was asked."""
    found = inventory([_record("a.jpg"), _record("b.jpeg"), _record("c.JPG")])

    assert [entry.name for entry in found.types] == ["JPEG"]
    assert found.types[0].count == 3


def test_the_other_obvious_aliases_are_folded_too():
    records = [_record("a.tif"), _record("b.tiff"), _record("c.yml"), _record("d.yaml")]

    named = {entry.name: entry.count for entry in inventory(records).types}

    assert named == {"TIFF": 2, "YAML": 2}


def test_an_html_page_is_one_format_whichever_way_it_was_named():
    found = inventory([_record("a.htm"), _record("b.html")])

    assert [entry.name for entry in found.types] == ["HTML"]


def test_folding_an_alias_does_not_move_a_file_between_families():
    """The family comes from the extension the file actually has, which is what
    `--type` will match on."""
    found = inventory([_record("a.jpeg")])

    assert dict(found.families) == {"image": 1}


# --- a compressed tarball is a tarball ---------------------------------------


def test_a_compressed_tarball_is_named_as_one():
    """`GZ 1` for `audit.tar.gz` tells a reader nothing they did not know from
    the file name, and hides that it is an archive of many files."""
    found = inventory([_record("audit.tar.gz"), _record("dump.tar.bz2")])

    assert {entry.name for entry in found.types} == {"TAR.GZ", "TAR.BZ2"}


def test_a_bare_compression_suffix_is_still_itself():
    found = inventory([_record("notes.txt.gz")])

    assert [entry.name for entry in found.types] == ["GZ"]


# --- the two pillars are always visible --------------------------------------


def test_metadata_and_origin_are_both_counted():
    records = [
        _record("a.pdf", EvidenceRecord(source="document-metadata", tool="Word")),
        _record(
            "b.pdf", EvidenceRecord(source="browser-download", url="https://example.org/b.pdf")
        ),
    ]

    found = summary(records)

    assert _named(found, "metadata") == 1
    assert _named(found, "origin evidence") == 1


def test_no_origin_evidence_is_a_result_and_stays_on_screen():
    """Zero is the finding: this scan read a lot of metadata and found nothing
    that says how any of it arrived. Dropping the row hides that."""
    records = [_record("a.pdf", EvidenceRecord(source="document-metadata", tool="Word"))]

    named = {tally.name: tally.files for tally in summary(records)}

    assert named["origin evidence"] == 0


def test_a_timestamp_is_called_a_timestamp():
    record = _record("a.pdf", EvidenceRecord(source="document-metadata", at="2026-07-20T19:05:21Z"))

    named = {tally.name for tally in summary([record])}

    assert "timestamps" in named
    assert "dated claims" not in named


def test_an_author_is_counted_where_the_block_names_one():
    """`Creator` is the application in a PDF Info dictionary and the person in
    OOXML core properties, which is why this is keyed on the block."""
    records = [
        _record(
            "a.docx",
            EvidenceRecord(
                source="document-metadata",
                block="ooxml-properties",
                fields={"creator": "Stephen Richard"},
            ),
        ),
        _record(
            "b.pdf",
            EvidenceRecord(
                source="document-metadata", block="pdf-info", fields={"Creator": "Adobe InDesign"}
            ),
        ),
    ]

    assert _named(summary(records), "authors / creators") == 1


def test_an_author_in_an_xmp_packet_counts_too():
    record = _record(
        "a.pdf", EvidenceRecord(source="xmp", block="xmp", fields={"dc:creator": "OSINT360"})
    )

    assert _named(summary([record]), "authors / creators") == 1


# --- notable findings --------------------------------------------------------


def test_a_notable_finding_says_a_file_contains_something():
    record = _record("photo.jpg", EvidenceRecord(source="device-metadata", geo="43.4, 11.8"))

    said = [alert.text for alert in notable([record], [])]

    assert "1 file contains coordinates" in said


def test_content_credentials_keep_the_name_the_standard_gave_them():
    record = _record("figure.png", EvidenceRecord(source="c2pa", tool="OpenAI"))

    said = [alert.text for alert in notable([record], [])]

    assert "1 file contains Content Credentials" in said


def test_identifiers_are_counted_in_identifiers_rather_than_in_files():
    found = [
        Identifier(type="email", value="a@example.org", normalized="a@example.org"),
        Identifier(type="domain", value="example.org", normalized="example.org"),
    ]

    said = [alert.text for alert in notable([_record("a.pdf")], found, listed=True)]

    assert "2 unique identifiers extracted" in said


def test_every_block_is_either_given_an_author_field_or_declared_to_have_none():
    """A reader added without a decision here would make the author count
    quietly understate itself, which is worse than not counting at all."""
    import ast
    from pathlib import Path as _Path

    from filegrail.overview import AUTHOR_FIELDS, WITHOUT_AUTHOR

    declared = set()
    for path in (_Path(__file__).resolve().parent.parent / "src" / "filegrail").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg == "block" and isinstance(keyword.value, ast.Constant):
                        if isinstance(keyword.value.value, str):
                            declared.add(keyword.value.value)

    assert declared, "no reader declares a block; the walk found nothing to check"
    assert declared <= set(AUTHOR_FIELDS) | WITHOUT_AUTHOR, sorted(
        declared - set(AUTHOR_FIELDS) - WITHOUT_AUTHOR
    )
