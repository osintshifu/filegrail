"""The investigation report as a page: dark, self-contained, and unable to say
anything to anybody by being opened.

A file's metadata is untrusted input. A name or a field that carries markup has
to arrive in the page as text, and nothing in the page may reach outside it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from filegrail.analysis import analyse
from filegrail.htmlreport import render_html
from filegrail.htmlscript import SCRIPT
from filegrail.identify import extract
from filegrail.models import EvidenceRecord, FileRecord

ROOT = Path("/case")
NOW = datetime(2026, 9, 16, 9, 0, tzinfo=timezone.utc)


def _file(name: str, *evidence: EvidenceRecord, size: int = 1024) -> FileRecord:
    record = FileRecord(path=f"/case/{name}", size=size, mtime="2026-01-01T00:00:00Z")
    record.evidence.extend(evidence)
    return record


def _corpus() -> list[FileRecord]:
    contested = _file(
        "report.pdf",
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
    )
    download = _file(
        "press/holiday.jpg",
        EvidenceRecord(source="browser-download", url="https://example.org/holiday.jpg"),
    )
    return [contested, download, _file("notes.md")]


def _page(records: list[FileRecord], **options: object) -> str:
    found = extract(records)
    case = analyse(records, ROOT, identifiers=found)
    return render_html(case, identifiers=found, now=NOW, **options)  # type: ignore[arg-type]


def test_the_page_is_dark_self_contained_and_reaches_nothing_outside_itself():
    page = _page(_corpus())

    assert page.startswith("<!doctype html>")
    assert "color-scheme:dark" in page
    assert "prefers-color-scheme" not in page and "data-theme" not in page
    assert '<h1 class="report-title">' in page
    assert "default-src 'none'" in page
    assert "@media print" in page
    outward = r"""\b(?:src|href|action)\s*=\s*["'](?!#|data:image/svg\+xml,)"""
    assert not re.search(outward, page)
    assert page.count("<link") == 1 and 'rel="icon" href="data:image/svg+xml,' in page
    assert "@import" not in page and "url(" not in page
    assert "https://example.org/holiday.jpg" in page


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_script_is_valid_javascript(tmp_path: Path):
    """A separator written as '\\n' in Python is a newline inside a JS string literal."""
    script = tmp_path / "report.js"
    script.write_text(SCRIPT, encoding="utf-8")

    checked = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True)

    assert checked.returncode == 0, checked.stderr


def test_author_styles_do_not_reveal_elements_marked_hidden():
    page = _page(_corpus())

    assert "[hidden]{display:none!important}" in page


def test_every_value_that_came_out_of_a_file_is_escaped():
    hostile = "<script>alert(1)</script>"
    record = _file(
        f"{hostile}.pdf",
        EvidenceRecord(
            source="document-metadata",
            block="pdf-info",
            fields={"Author": hostile, "Title": '"><img src=x onerror=alert(1)>'},
        ),
    )

    page = _page([record], verbose=True)

    assert "<script>alert" not in page
    assert "<img src=x" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_the_numbers_are_anchors_and_the_references_lead_to_them():
    page = _page(_corpus())

    for anchor in ('id="file-001"', 'id="F01"', 'id="C01"'):
        assert anchor in page
    assert 'href="#C01"' in page
    assert 'href="#file-001"' in page


def test_the_cards_open_what_they_count_and_the_index_sorts_by_raw_values():
    page = _page(_corpus())

    assert 'href="#files" data-filter="origin"' in page
    assert 'href="#conflicts"' in page
    assert 'class="tbl index" id="index"' in page
    assert 'data-value="1024"' in page


def test_every_rendered_table_has_one_copy_action():
    page = _page(_corpus())

    assert page.count("<table") > 1
    assert page.count('class="btn icon table-copy" type="button" title="Copy table"') == page.count(
        "<table"
    )


def test_a_copy_button_copies_the_value_shown_and_keeps_no_copy_of_its_own():
    page = _page(_corpus())

    assert '<span class="v">https://example.org/holiday.jpg</span><button class="copy"' in page
    assert "data-copy" not in page


def test_the_sections_come_in_the_order_they_are_worked_through():
    page = _page(_corpus())

    assert re.findall(r"<h2>([^<]+)</h2>", page) == [
        "Summary",
        "Key findings",
        "Files",
        "Relationships",
        "Investigative pivots",
        "Conflicts",
        "File detail",
        "Report notes",
    ]


def test_report_notes_are_brief_and_only_explain_match_bases_in_use():
    page = _page(_corpus())
    section = page.split('<section id="notes"')[1].split("</section>")[0]

    assert "how it arrived here" in section
    assert "what the file says about itself" in section
    assert "what happened to it here" in section
    assert "file bytes" in section
    assert "exact path in an external store" in section
    assert "same name and size" not in section
    assert "How a file reached the examined environment" not in section


def test_relationship_explorer_uses_the_evidence_backed_graph():
    page = _page(_corpus())
    section = page.split('<section id="relationships"')[1].split("</section>")[0]

    assert '<select id="relationship-node">' in section
    assert '<input id="relationship-find" type="search"' in section
    assert '<optgroup label="files">' in section
    assert '<optgroup label="domains">' in section
    assert 'data-kind="has identifier"' in section
    assert 'data-kind="origin URL"' in section
    assert 'data-kind="URL host"' in section
    assert 'data-rel-focus="domain:example.org"' in section
    assert "browser-download" in section
    assert "recorded-path" in section
    assert "URL host" in section and "derived" in section
    assert section.count('id="relationship-shown"') == 1
    assert "relationships drawn" not in section
    assert 'class="rel-count"' not in section
    assert 'class="graph-legend"' not in section
    assert 'id="graph-export"' in section
    assert 'id="relationship-table-find"' in section
    assert 'id="relationship-sort"' in section
    assert 'id="relationship-table-clear"' in section


def test_relationship_explorer_includes_authors_and_cameras_without_clustering():
    record = _file(
        "photo.jpg",
        EvidenceRecord(
            source="device-metadata",
            block="exif",
            fields={
                "Make": "NIKON",
                "Model": "Z 8",
                "BodySerialNumber": "BODY-1042",
                "Artist": "Anna Nowak",
            },
        ),
    )

    page = _page([record])

    assert 'data-kind="author"' in page
    assert 'data-kind="camera body"' in page
    assert 'data-kind="camera model"' in page
    assert '<optgroup label="people">' in page
    assert '<optgroup label="camera bodies">' in page
    assert '<optgroup label="camera models">' in page
    assert 'data-rel-kind="author"><i class="t-person f-person"></i>author' in page
    assert 'data-rel-kind="camera body"><i class="t-device f-device"></i>camera body' in page
    assert (
        'data-rel-kind="camera model"><i class="t-camera_model f-device"></i>camera model' in page
    )


def test_every_pivot_is_listed_with_the_files_it_was_found_in():
    page = _page(_corpus())
    panel = page.split('id="pivots-type-url"')[1].split('class="panel')[0]

    assert '<span class="v">https://example.org/holiday.jpg</span>' in panel
    assert 'href="#file-002"' in panel


def test_a_conflict_says_which_statement_is_how_much_earlier():
    assert "XMP is 72 days earlier than PDF Info" in _page(_corpus())


def _metadata_only() -> FileRecord:
    return _file(
        "tool.exe",
        EvidenceRecord(
            source="document-metadata",
            block="pe-header",
            tool="Example Tool 1.2",
            note="company Example Corp",
            fields={"Machine": "x64", "PDBPath": "C:\\build\\tool.pdb"},
        ),
    )


def test_a_file_with_only_metadata_gets_a_detail_block_with_every_field():
    """Metadata is something to read. Without a download record beside it the
    block used to be left out, and with it the fields were left out unless the
    report was asked for in full."""
    page = _page([_metadata_only()])
    section = page.split('<section id="detail"')[1].split("</section>")[0]

    assert '<details class="file" id="detail-001">' in section
    assert "<dt>PDBPath</dt>" in section
    assert "C:\\build\\tool.pdb" in section
    assert "<dt>Machine</dt>" in section


def _ids_and_targets(page: str) -> tuple[list[str], set[str]]:
    from html.parser import HTMLParser

    class Walk(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.ids: list[str] = []
            self.targets: set[str] = set()

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            held = dict(attrs)
            if held.get("id"):
                self.ids.append(held["id"])
            href = held.get("href") or ""
            if href.startswith("#") and len(href) > 1:
                self.targets.add(href[1:])

    walk = Walk()
    walk.feed(page)
    return walk.ids, walk.targets


def test_every_id_is_unique_and_every_internal_link_has_a_target():
    """A pivot shared by two files is listed twice - across files and under its
    type - and used to carry its anchor both times."""
    shared = "https://example.org/holiday.jpg"
    records = _corpus() + [
        _metadata_only(),
        _file("copy.jpg", EvidenceRecord(source="browser-download", url=shared)),
    ]

    page = _page(records)
    ids, targets = _ids_and_targets(page)

    assert "P01" in ids
    assert len(ids) == len(set(ids)), sorted(i for i in ids if ids.count(i) > 1)
    assert targets <= set(ids), sorted(targets - set(ids))


def test_the_print_layout_opens_every_block_and_lets_the_tables_fit_the_page():
    """A printed report used to lose the last column of the file index and the
    evidence of every relationship, and printed the controls instead."""
    page = _page(_corpus())
    printed = page.split("@media print{")[1].split("\n}\n")[0]

    assert "details:not([open])>:not(summary){display:block}" in printed
    assert ".wrap>table.index,.wrap>table.pivots,.wrap>table.relationships{min-width:0}" in printed
    assert ".rel-controls,.rel-kinds,.rel-focus,.graph-arrange{display:none!important}" in printed
    assert ".tbl.relationships td:last-child{grid-column:1/-1}" in printed
    assert "addEventListener('beforeprint'" in page


def test_numbered_fields_are_gathered_under_their_group():
    """A signature's name and reason belong together; fourteen Rich header
    entries are one list, not fourteen labels that differ by a digit."""
    record = _file(
        "signed.pdf",
        EvidenceRecord(
            source="document-metadata",
            block="pdf-info",
            tool="Acrobat",
            fields={
                "Signature[1]:Name": "Maria Wolf",
                "Signature[1]:Reason": "Approved",
                "RichEntry[1]": "id 253, build 31424, count 3",
                "RichEntry[2]": "id 260, build 31424, count 1",
            },
        ),
    )

    page = _page([record])
    section = page.split('<section id="detail"')[1].split("</section>")[0]

    assert '<dt>Signature 1</dt><dd><dl class="sub"><dt>Name</dt>' in section
    assert "<dt>Reason</dt>" in section
    assert '<dt>RichEntry</dt><dd><ol class="numbered"><li>' in section
    assert section.count('class="copy"') >= 5


def test_the_timeline_lists_dated_records_in_order_with_what_happened():
    records = [
        _file(
            "later.jpg",
            EvidenceRecord(
                source="device-metadata", block="exif", tool="Canon", at="2026-03-02T09:00:00Z"
            ),
        ),
        _file(
            "first.pdf",
            EvidenceRecord(
                source="browser-download",
                url="https://example.org/first.pdf",
                at="2026-03-01T10:00:00Z",
            ),
        ),
    ]

    page = _page(records)
    section = page.split('<section id="timeline"')[1].split("</section>")[0]

    assert section.index("downloaded") < section.index("captured")
    assert '<li class="tl-day"><time datetime="2026-03-01">2026-03-01</time>' in section
    assert '<span class="wd">Sunday</span>' in section
    assert "https://example.org/first.pdf" in section
    assert '<span class="verb" title="origin">downloaded</span>' in section
    headings = re.findall(r"<h2>([^<]+)</h2>", page)
    assert headings.index("Summary") < headings.index("Timeline") < headings.index("Files")


def test_the_timeline_orders_offsets_by_the_instant_they_represent():
    records = [
        _file(
            "later.jpg",
            EvidenceRecord(source="c2pa", tool="later actual", at="2026-01-01T00:00:00Z"),
        ),
        _file(
            "earlier.jpg",
            EvidenceRecord(source="c2pa", tool="earlier actual", at="2026-01-01T00:30:00+02:00"),
        ),
    ]

    page = _page(records)
    section = page.split('<section id="timeline"')[1].split("</section>")[0]

    assert section.index("earlier actual") < section.index("later actual")
    assert section.index("2025-12-31") < section.index("2026-01-01")
    assert "22:30:00" in section


def test_the_timeline_keeps_the_count_when_events_share_the_same_instant():
    records = [
        _file(
            f"same-{number}.docx",
            EvidenceRecord(
                source="document-metadata",
                block="ooxml-properties",
                at="2026-03-30T14:05:00Z",
            ),
        )
        for number in range(3)
    ]
    records.append(
        _file(
            "later.jpg",
            EvidenceRecord(
                source="device-metadata",
                block="exif",
                at="2026-04-05T08:12:44Z",
            ),
        )
    )

    page = _page(records)
    section = page.split('<section id="timeline"')[1].split("</section>")[0]

    assert section.count('<li class="ev event" data-f="metadata"') == 4
    assert section.count('<li class="tl-day">') == 2
    assert (
        'data-tl="metadata" aria-pressed="false"><i class="f-metadata"></i>metadata <b>4</b>'
        in section
    )


def test_the_graph_is_drawn_and_its_nodes_focus_the_explorer():
    page = _page(_corpus())
    section = page.split('<section id="relationships"')[1].split("</section>")[0]

    assert section.index('class="graph-toolbar"') < section.index('<figure class="graph"')
    assert '<svg id="evidence-graph" viewBox="0 0 960 560"' in section
    assert '<g class="graph-viewport">' in section
    assert 'id="graph-zoom-out"' in section
    assert 'id="graph-zoom-in"' in section
    assert 'id="graph-fit"' in section
    assert 'id="graph-reset"' in section
    assert 'id="graph-zoom-value"' in section
    assert 'id="graph-detail"' in section
    node = "file:/case/press/holiday.jpg"
    assert f'data-graph-node="{node}" data-rel-focus="{node}"' in section
    assert 'data-file-ref="#002"' in section
    assert 'data-file-format="JPEG"' in section
    assert 'id="graph-detail-connected"' in section
    assert 'id="graph-detail-pivot"' in section
    assert 'id="to-top"' in page and 'id="i-up"' in page
    assert 'data-source="file:/case/press/holiday.jpg"' in section
    assert "nodes drawn" not in section and "<figcaption" not in section


def test_a_graph_node_that_is_a_shared_pivot_links_to_its_pivot_row():
    shared = "https://example.org/holiday.jpg"
    records = _corpus() + [
        _file("copy.jpg", EvidenceRecord(source="browser-download", url=shared)),
    ]

    page = _page(records)
    ids, targets = _ids_and_targets(page)

    assert re.search(r'data-graph-node="[^"]+" [^>]*data-pivot-link="#P\d\d"', page)
    assert "P01" in ids and targets <= set(ids)
