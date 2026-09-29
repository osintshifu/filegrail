"""What the leading bytes say a file is, held against the name it was given.

An extension is a claim anybody can make, and a rename is one command. The
bytes are harder to argue with, so where the two disagree the disagreement is
worth a line. Where they agree there is nothing to say: a `.jpg` that really is
a JPEG has confirmed only what everybody already assumed.

The three silences below matter as much as the report itself. A format written
under many names, bytes that match nothing here, and an extension nothing here
has an expectation of are all reasons to say nothing, and none of them is a
misnamed file.
"""

from __future__ import annotations

from pathlib import Path

from filegrail.analysis import analyse
from filegrail.models import EMBEDDED, METADATA, category
from filegrail.scan import scan
from filegrail.sources.signature import read_signature

PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"


def test_a_pdf_named_as_a_photograph_is_reported(tmp_path: Path):
    path = tmp_path / "invoice.jpg"
    path.write_bytes(PDF)

    found = read_signature(path)

    assert found is not None
    assert found.fields == {"extension": ".jpg", "content": "PDF"}
    assert category(found) == METADATA
    assert found.matched_by == EMBEDDED


def test_a_format_written_under_several_names_is_not_a_mismatch(tmp_path: Path):
    """A `.docx` is a zip, and so is an `.epub` and a `.jar`. Reporting the
    format's own file types as an anomaly would report every office document."""
    path = tmp_path / "report.docx"
    path.write_bytes(b"PK\x03\x04" + bytes(26))

    assert read_signature(path) is None


def test_bytes_that_match_no_format_are_not_a_mismatch(tmp_path: Path):
    """Not knowing what a file is and knowing it is misnamed are different."""
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"this is not a photograph")

    assert read_signature(path) is None


def test_an_extension_nothing_expects_is_not_judged(tmp_path: Path):
    """A `.dat` holding a PDF is not a misnamed PDF. Nothing here knows what a
    `.dat` was supposed to hold, so nothing here can say it holds the wrong thing."""
    path = tmp_path / "blob.dat"
    path.write_bytes(PDF)

    assert read_signature(path) is None


def test_a_scan_attaches_it(tmp_path: Path):
    (tmp_path / "invoice.jpg").write_bytes(PDF)

    record = next(iter(scan(tmp_path, use_shell_history=False)))

    assert [found.note for found in record.evidence if found.source == "file-signature"] == [
        "the name says .jpg, the bytes say PDF"
    ]


def test_the_case_names_it_among_the_findings(tmp_path: Path):
    (tmp_path / "invoice.jpg").write_bytes(PDF)
    records = scan(tmp_path, use_shell_history=False)

    case = analyse(records, tmp_path)

    finding = next(found for found in case.findings if found.kind == "signature")
    assert finding.notable
    assert [(item.path, item.facts) for item in finding.items] == [
        (records[0].path, [("extension", ".jpg"), ("content", "PDF")])
    ]
