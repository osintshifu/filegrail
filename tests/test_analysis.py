"""What a scan amounts to before anybody lays it out.

Numbers, findings, conflicts, coverage and pivots, each derived only from what
the records say - so the terminal and any other rendering of a case state the
same things, and a renderer never decides what is true.
"""

from __future__ import annotations

from pathlib import Path

from filegrail.analysis import analyse
from filegrail.doctor import AVAILABLE, FILESYSTEM, UNAVAILABLE, Check, Survey
from filegrail.identify import extract
from filegrail.models import EvidenceRecord, FileRecord

AI = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"


def _file(name: str, *evidence: EvidenceRecord, size: int = 1024) -> FileRecord:
    record = FileRecord(path=f"/case/{name}", size=size, mtime="2026-01-01T00:00:00Z")
    record.evidence.extend(evidence)
    return record


def _info(**fields: str) -> EvidenceRecord:
    return EvidenceRecord(source="document-metadata", block="pdf-info", fields=dict(fields))


def _xmp(**fields: str) -> EvidenceRecord:
    named = {name.replace("_", ":"): value for name, value in fields.items()}
    return EvidenceRecord(source="xmp", block="xmp", fields=named)


def _ooxml(at: str | None = None, **fields: str) -> EvidenceRecord:
    return EvidenceRecord(
        source="document-metadata", block="ooxml-properties", at=at, fields=dict(fields)
    )


def _exif(geo: str | None = None, **fields: str) -> EvidenceRecord:
    return EvidenceRecord(source="device-metadata", block="exif", geo=geo, fields=dict(fields))


def test_files_are_numbered_review_first_and_point_at_what_concerns_them():
    contested = _file(
        "report.pdf",
        _info(Creator="Adobe InDesign CC 13.1 (Macintosh)"),
        _xmp(xmp_CreatorTool="Adobe Illustrator CC 22.0 (Macintosh)"),
        size=10,
    )
    plain = _file("big.docx", _ooxml(creator="A. Person"), size=9000)
    bare = _file("notes.txt", size=50000)

    case = analyse([bare, plain, contested], Path("/case"))

    assert [(f.ref, Path(f.record.path).name, f.state) for f in case.files] == [
        ("#001", "report.pdf", "review"),
        ("#002", "big.docx", "evidence"),
        ("#003", "notes.txt", "nothing"),
    ]
    assert case.files[0].found["metadata"] == ["PDF Info", "XMP"]
    assert (case.files[0].conflicts, case.files[0].findings) == (["C01"], ["F01"])
    assert case.files[2].findings == ["F02"]


def test_findings_are_drawn_only_from_what_the_records_say():
    generated = _file(
        "gen.png",
        EvidenceRecord(
            source="c2pa",
            block="c2pa",
            fields={
                "claim_generator": "OpenAI Media Service API",
                "softwareAgent": "gpt-image 2.0",
                "digitalSourceType": AI,
            },
        ),
    )
    twins = [
        _file(name, _ooxml("2013-12-23T23:15:00Z", creator="OSINT360"), size=size)
        for name, size in (("a.docx", 100), ("b.docx", 200), ("c.docx", 300))
    ]
    two_only = [_file(name, _ooxml(creator="Two Only")) for name in ("x.docx", "y.docx")]
    photos = [
        _file("p.jpg", _exif(geo="43.46745,11.88513", BodySerialNumber="3001234")),
        _file("q.jpg", _exif(BodySerialNumber="3001234")),
    ]
    bare = _file("n.txt")

    case = analyse([generated, *twins, *two_only, *photos, bare], Path("/case"))

    assert [(f.ref, f.title) for f in case.findings] == [
        ("F01", "Declared AI-generated source"),
        ("F02", "Same-second creation cluster"),
        ("F03", "Shared author"),
        ("F04", "Shared camera body"),
        ("F05", "Geographic metadata exposure"),
        ("F06", "No supporting trace found"),
    ]
    assert dict(case.findings[0].items[0].facts)["software agent"] == "gpt-image 2.0"
    assert dict(case.findings[1].facts) == {
        "timestamp": "2013-12-23 23:15:00 UTC",
        "files": "3",
        "bytes": "different",
    }
    assert dict(case.findings[2].facts)["author"] == "OSINT360"


def test_a_conflict_keeps_both_values_and_says_how_far_apart_two_moments_are():
    export = _file(
        "export.pdf",
        _info(Creator="Adobe InDesign CC 13.1 (Macintosh)", CreationDate="D:20180511143720-04'00'"),
        _xmp(
            xmp_CreatorTool="Adobe Illustrator CC 22.0 (Macintosh)",
            xmp_CreateDate="2018-02-28T13:44:18-05:00",
        ),
    )
    template = _file(
        "template.pdf",
        _info(CreationDate="D:20260707080205Z"),
        _xmp(xmp_CreateDate="2013-12-23T23:15:00Z"),
    )

    first, second = analyse([export, template], Path("/case")).conflicts

    assert (first.ref, first.sources) == ("C01", ["PDF Info", "XMP"])
    differences = {difference.field: difference for difference in first.differences}
    assert differences["Creator"].values == [
        ("PDF Info", "Adobe InDesign CC 13.1 (Macintosh)"),
        ("XMP", "Adobe Illustrator CC 22.0 (Macintosh)"),
    ]
    assert differences["Creator"].delta is None
    assert differences["CreationDate"].values == [
        ("PDF Info", "2018-05-11 18:37:20 UTC"),
        ("XMP", "2018-02-28 18:44:18 UTC"),
    ]
    assert differences["CreationDate"].delta == "72 days earlier"
    assert second.differences[0].delta == "12 years 6 months earlier"


def test_a_block_contradicting_itself_names_the_fields_rather_than_itself_twice():
    """One block states both values, so it stands on both sides of its own
    disagreement. Naming the source there says `PDF Info is 2 hours earlier
    than PDF Info`, and which of its two fields is the earlier one - the whole
    content of the finding - is exactly what goes missing."""
    export = _file(
        "export.pdf",
        _info(CreationDate="D:20260211184002Z", ModDate="D:20260211163315Z"),
    )

    conflict = analyse([export], Path("/case")).conflicts[0]
    difference = {entry.field: entry for entry in conflict.differences}["CreationDate / ModDate"]

    assert [source for source, _ in difference.values] == ["CreationDate", "ModDate"]
    assert difference.delta is not None
    assert conflict.sources == ["PDF Info"], "the block still names the conflict"


def test_coverage_tells_a_store_that_was_found_from_an_attribute_that_can_be_read():
    found = Survey(
        checks=[
            Check("Chromium family downloads", AVAILABLE, "3 records across 3 of 3 profiles"),
            Check("Firefox downloads", AVAILABLE, "0 records across 1 of 1 profile"),
            Check("XDG origin attribute", AVAILABLE, "written by KDE tools and wget --xattr"),
            Check("Shell history", UNAVAILABLE, "no history file found"),
            Check("Creation timestamps", AVAILABLE, "statx", kind=FILESYSTEM),
        ],
        horizon=[Check("Chromium family oldest record", AVAILABLE, "2026-09-15")],
    )

    case = analyse([], Path("/case"), survey=found)

    assert [(s.name, s.state, s.since) for s in case.coverage] == [
        ("Chromium family downloads", "found", "2026-09-15"),
        ("Firefox downloads", "found", None),
        ("XDG origin attribute", "readable", None),
        ("Shell history", "not found", None),
    ]
    assert case.begins == "2026-09-15"


def test_pivots_are_counted_in_every_place_and_what_one_file_holds_is_folded():
    links = {f"Link{i}": f"https://example.org/p{i}" for i in range(60)}
    dense = _file("links.docx", _ooxml(**links))
    other = _file("note.docx", _ooxml(Link="https://example.org/p1"))
    records = [dense, other]

    pivots = analyse(records, Path("/case"), identifiers=extract(records)).pivots

    assert pivots is not None
    assert pivots.across == 2
    assert [(ref, e.type, e.normalized) for ref, e in pivots.shared] == [
        ("P01", "domain", "example.org"),
        ("P02", "url", "https://example.org/p1"),
    ]
    (folded,) = pivots.dense
    assert (folded.path, folded.places, folded.by_type) == (
        dense.path,
        120,
        [("domain", 60), ("url", 60)],
    )
