"""Files carried inside documents and messages, read as files of their own.

A PDF can carry an attachment, a message carries the files sent with it, and an
Office document can hold an object packaged from another file. Each is read
under its own name and reported as a file inside its carrier: with its own
record, its own evidence, and the carrier as its parent - the way a member of
an archive already is.
"""

from __future__ import annotations

import json
import struct
import zipfile
import zlib
from email.message import EmailMessage
from pathlib import Path

from filegrail.models import ORIGIN, category
from filegrail.report import render_json
from filegrail.scan import scan
from tests.compound import ole
from tests.photo import jpeg_with_exif

CORE_XML = """<?xml version="1.0"?>
<cp:coreProperties
  xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
  xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:creator>Jan Kowalski</dc:creator>
</cp:coreProperties>"""


def _photo(tmp_path: Path) -> bytes:
    source = tmp_path / "source.jpg"
    jpeg_with_exif(source, "NIKON", "COOLPIX P6000", "2008:10:22 16:28:39")
    return source.read_bytes()


def _case(tmp_path: Path) -> Path:
    case = tmp_path / "case"
    case.mkdir()
    return case


def _child(records, member: str):
    return next(record for record in records if record.member == member)


def _model(record) -> str:
    exif = next(found for found in record.evidence if found.block == "exif")
    return exif.fields["Model"]


def _packaged(filename: str, payload: bytes) -> bytes:
    """An Ole10Native stream in the OLE Packager layout, wrapping `payload`."""
    package = struct.pack("<H", 2)
    package += filename.encode() + b"\x00"
    package += b"C:\\Cases\\" + filename.encode() + b"\x00"
    package += struct.pack("<II", 0, 0)
    package += b"C:\\Temp\\" + filename.encode() + b"\x00"
    package += struct.pack("<I", len(payload)) + payload
    return struct.pack("<I", len(package)) + package


def _pdf_with_attachment(path: Path, name: str, payload: bytes) -> None:
    deflated = zlib.compress(payload)
    path.write_bytes(
        b"%PDF-1.7\n"
        b"1 0 obj\n<< /Type /Catalog /Names << /EmbeddedFiles << /Names [("
        + name.encode()
        + b") 2 0 R] >> >> >>\nendobj\n"
        b"2 0 obj\n<< /Type /Filespec /F (" + name.encode() + b") /UF (" + name.encode() + b")"
        b" /EF << /F 3 0 R >> >>\nendobj\n"
        b"3 0 obj\n<< /Type /EmbeddedFile /Filter /FlateDecode /Length "
        + str(len(deflated)).encode()
        + b" /Params << /Size "
        + str(len(payload)).encode()
        + b" /ModDate (D:20080102030405Z) >> >>\nstream\n"
        + deflated
        + b"\nendstream\nendobj\n"
        b"4 0 obj\n<< /Producer (Test writer) >>\nendobj\n"
        b"trailer\n<< /Info 4 0 R /Root 1 0 R >>\n%%EOF\n"
    )


def test_a_file_attached_to_a_pdf_is_a_file_of_its_own(tmp_path: Path):
    case = _case(tmp_path)
    photo = _photo(tmp_path)
    _pdf_with_attachment(case / "report.pdf", "holiday.jpg", photo)

    records = scan(case, use_shell_history=False)
    child = _child(records, "holiday.jpg")

    assert child.parent == str(case / "report.pdf")
    assert child.path == str(case / "report.pdf") + "/holiday.jpg"
    assert child.size == len(photo)
    assert child.mtime == "2008-01-02T03:04:05Z"
    assert _model(child) == "COOLPIX P6000"

    inside = next(found for found in child.evidence if category(found) == ORIGIN)
    assert inside.source == "embedded-file"
    assert inside.container == str(case / "report.pdf")
    assert inside.matched_by == "container-member"
    assert inside.where == {"member": "holiday.jpg"}

    graph = json.loads(render_json(records, case))["graph"]
    kinds = {(edge["source"], edge["target"]): edge["kind"] for edge in graph["relationships"]}
    assert kinds[(f"file:{child.path}", f"file:{case / 'report.pdf'}")] == "embedded in"


def test_a_message_attachment_is_a_file_of_its_own(tmp_path: Path):
    case = _case(tmp_path)
    photo = _photo(tmp_path)
    message = EmailMessage()
    message["From"] = "bob@example.net"
    message["To"] = "alice@example.org"
    message["Subject"] = "Holiday"
    message.set_content("See attached.")
    message.add_attachment(photo, maintype="image", subtype="jpeg", filename="holiday.jpg")
    (case / "holiday.eml").write_bytes(bytes(message))

    child = _child(scan(case, use_shell_history=False), "holiday.jpg")

    assert child.parent == str(case / "holiday.eml")
    assert child.size == len(photo)
    assert _model(child) == "COOLPIX P6000"


def test_an_outlook_attachment_is_a_file_of_its_own(tmp_path: Path):
    case = _case(tmp_path)
    photo = _photo(tmp_path)
    (case / "holiday.msg").write_bytes(
        ole(
            {"__substg1.0_0037001F": "Holiday".encode("utf-16-le")},
            storages={
                "__attach_version1.0_#00000000": {
                    "__substg1.0_3707001F": "holiday.jpg".encode("utf-16-le"),
                    "__substg1.0_37010102": photo,
                }
            },
        )
    )

    child = _child(scan(case, use_shell_history=False), "holiday.jpg")

    assert child.parent == str(case / "holiday.msg")
    assert child.size == len(photo)
    assert _model(child) == "COOLPIX P6000"


def test_an_object_packaged_in_an_office_document_is_a_file_of_its_own(tmp_path: Path):
    case = _case(tmp_path)
    photo = _photo(tmp_path)
    with zipfile.ZipFile(case / "memo.docx", "w") as package:
        package.writestr("docProps/core.xml", CORE_XML)
        package.writestr(
            "word/embeddings/oleObject1.bin",
            ole({"\x01Ole10Native": _packaged("holiday.jpg", photo)}),
        )

    child = _child(
        scan(case, use_shell_history=False), "word/embeddings/oleObject1.bin/holiday.jpg"
    )

    assert child.parent == str(case / "memo.docx")
    assert child.size == len(photo)
    assert _model(child) == "COOLPIX P6000"


def test_an_object_packaged_in_a_legacy_office_document_is_a_file_of_its_own(tmp_path: Path):
    case = _case(tmp_path)
    photo = _photo(tmp_path)
    (case / "memo.doc").write_bytes(
        ole({}, storages={"ObjectPool": {"\x01Ole10Native": _packaged("holiday.jpg", photo)}})
    )

    child = _child(scan(case, use_shell_history=False), "ObjectPool/holiday.jpg")

    assert child.parent == str(case / "memo.doc")
    assert _model(child) == "COOLPIX P6000"


def test_a_carrier_is_not_described_by_what_it_carries(tmp_path: Path):
    """The photograph's camera belongs to the attachment, not to the PDF."""
    case = _case(tmp_path)
    _pdf_with_attachment(case / "report.pdf", "holiday.jpg", _photo(tmp_path))

    records = scan(case, use_shell_history=False)
    carrier = next(record for record in records if record.parent is None)

    assert not any(found.block == "exif" for found in carrier.evidence)
    pdf = next(found for found in carrier.evidence if found.block == "pdf-info")
    assert pdf.fields["EmbeddedFile[1]"] == "holiday.jpg"
