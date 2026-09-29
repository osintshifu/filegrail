"""Where in the file a record was read from: the member, the object."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from filegrail.models import EvidenceRecord, FileRecord
from filegrail.report import render_json
from filegrail.sources.embedded import read_embedded_metadata
from tests.pdf import document


def test_a_pdf_info_record_names_the_object_it_was_read_from(tmp_path: Path):
    body = document([b"BT (page) Tj ET"], extra=b"<< /Producer (Writer 7) /Author (A. Person) >>")
    body = body.replace(b"trailer\n<<", b"trailer\n<< /Info 6 0 R", 1)
    path = tmp_path / "brief.pdf"
    path.write_bytes(body)

    origin = read_embedded_metadata(path)

    assert origin is not None
    assert origin.where == {"object": "6 0 R"}


def test_an_ooxml_record_names_the_parts_it_was_read_from(tmp_path: Path):
    path = tmp_path / "report.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "docProps/core.xml",
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
            'metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">'
            "<dc:creator>Jan Kowalski</dc:creator></cp:coreProperties>",
        )

    origin = read_embedded_metadata(path)

    assert origin is not None
    assert origin.where == {"member": "docProps/core.xml"}


def test_the_json_carries_where_only_when_there_is_one(tmp_path: Path):
    placed = FileRecord(path="/case/a.docx", size=1, mtime="2026-01-01T00:00:00Z")
    placed.evidence.append(
        EvidenceRecord(
            source="document-metadata", tool="Word", where={"member": "docProps/core.xml"}
        )
    )
    bare = FileRecord(path="/case/b.jpg", size=1, mtime="2026-01-01T00:00:00Z")
    bare.evidence.append(EvidenceRecord(source="device-metadata", tool="Camera"))

    files = json.loads(render_json([placed, bare], tmp_path))["files"]

    assert files[0]["evidence"][0]["where"] == {"member": "docProps/core.xml"}
    assert "where" not in files[1]["evidence"][0]
