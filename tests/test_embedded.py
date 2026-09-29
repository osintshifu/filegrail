import tracemalloc
import zipfile
from pathlib import Path

from filegrail.sources.embedded import containers, documents, read_embedded_metadata
from tests.photo import jpeg_with_exif

CORE_XML = """<?xml version="1.0"?>
<cp:coreProperties
  xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
  xmlns:dc="http://purl.org/dc/elements/1.1/"
  xmlns:dcterms="http://purl.org/dc/terms/">
  <dc:creator>Jan Kowalski</dc:creator>
  <cp:lastModifiedBy>Anna Nowak</cp:lastModifiedBy>
  <dcterms:created>2026-03-12T09:14:00Z</dcterms:created>
</cp:coreProperties>"""

APP_XML = """<?xml version="1.0"?>
<Properties
  xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  <Application>Microsoft Office Word</Application>
  <AppVersion>16.0000</AppVersion>
  <Company>Acme Holdings</Company>
</Properties>"""


def test_reads_ooxml_authorship(tmp_path: Path):
    document = tmp_path / "report.docx"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("docProps/core.xml", CORE_XML)
        archive.writestr("docProps/app.xml", APP_XML)

    origin = read_embedded_metadata(document)

    assert origin is not None
    assert origin.source == "document-metadata"
    assert origin.tool == "Microsoft Office Word 16.0000"
    assert origin.at == "2026-03-12T09:14:00Z"
    assert "author Jan Kowalski" in origin.note
    assert "last edited by Anna Nowak" in origin.note
    assert "company Acme Holdings" in origin.note
    assert origin.priority == 50


def test_ooxml_without_properties_yields_nothing(tmp_path: Path):
    document = tmp_path / "empty.docx"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")

    assert read_embedded_metadata(document) is None


def test_reads_pdf_info_dictionary(tmp_path: Path):
    document = tmp_path / "paper.pdf"
    document.write_bytes(
        b"%PDF-1.7\n"
        b"1 0 obj\n<< /Producer (Adobe PDF Library 15.0) "
        b"/Creator (Adobe InDesign CC 13.1) "
        b"/Author (Maria Wolf) "
        b"/CreationDate (D:20180511143720+02'00') >>\nendobj\n"
    )

    origin = read_embedded_metadata(document)

    assert origin is not None
    assert origin.tool == "Adobe PDF Library 15.0 (created in Adobe InDesign CC 13.1)"
    assert origin.at == "2018-05-11T12:37:20Z"
    assert origin.note == "author Maria Wolf"

    # West of Greenwich the offset is added back, not taken away.
    behind = tmp_path / "behind.pdf"
    behind.write_bytes(
        b"%PDF-1.4\n<< /Producer (Visio) /CreationDate (D:20110224082252-07'00') >>\n"
    )
    assert (read_embedded_metadata(behind) or origin).at == "2011-02-24T15:22:52Z"


def test_pdf_with_only_a_producer(tmp_path: Path):
    document = tmp_path / "print.pdf"
    document.write_bytes(b"%PDF-1.4\n<< /Producer (Skia/PDF m142) >>\n")

    origin = read_embedded_metadata(document)

    assert origin is not None
    assert origin.tool == "Skia/PDF m142"
    assert origin.at is None


def test_pdf_without_metadata_yields_nothing(tmp_path: Path):
    document = tmp_path / "bare.pdf"
    document.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n")

    assert read_embedded_metadata(document) is None


def test_reads_jpeg_camera_and_capture_time(tmp_path: Path):
    photo = tmp_path / "photo.jpg"
    jpeg_with_exif(photo, "Canon", "Canon EOS 5D", "2026:04:19 21:43:48")

    origin = read_embedded_metadata(photo)

    assert origin is not None
    # The maker is not repeated when the model already carries it.
    assert origin.tool == "Canon EOS 5D"
    assert origin.at == "2026-04-19T21:43:48Z"
    assert origin.source == "device-metadata"


def test_maker_is_kept_when_the_model_does_not_carry_it(tmp_path: Path):
    photo = tmp_path / "photo.jpg"
    jpeg_with_exif(photo, "NIKON", "COOLPIX P6000", "2026:04:19 21:43:48")

    assert read_embedded_metadata(photo).tool == "NIKON COOLPIX P6000"


def test_jpeg_without_exif_yields_nothing(tmp_path: Path):
    photo = tmp_path / "plain.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xdb\x00\x04\x00\x00\xff\xd9")

    assert read_embedded_metadata(photo) is None


def test_unsupported_and_corrupt_files_are_not_an_error(tmp_path: Path):
    plain = tmp_path / "notes.txt"
    plain.write_text("hello", encoding="utf-8")
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"not a zip at all")

    assert read_embedded_metadata(plain) is None
    assert read_embedded_metadata(broken) is None


def test_reads_hex_string_info_values(tmp_path: Path):
    """LibreOffice writes /Producer<FEFF...> rather than a literal string."""
    document = tmp_path / "hex.pdf"
    producer = "LibreOffice 24.2".encode("utf-16-be").hex().upper()
    author = "OSINT360".encode("utf-16-be").hex().upper()
    document.write_bytes(
        b"%PDF-1.6\n<< /Producer<FEFF"
        + producer.encode()
        + b"> /Author<FEFF"
        + author.encode()
        + b"> >>\n"
    )

    origin = read_embedded_metadata(document)

    assert origin is not None
    assert origin.tool == "LibreOffice 24.2"
    assert origin.note == "author OSINT360"
    assert "﻿" not in origin.tool  # the byte-order mark must not survive


def test_empty_info_values_do_not_mask_a_real_date(tmp_path: Path):
    document = tmp_path / "empty-producer.pdf"
    document.write_bytes(
        b"%PDF-1.4\n<< /Creator () /Producer () /CreationDate (D:20260720190521+00'00') >>\n"
    )

    origin = read_embedded_metadata(document)

    assert origin is not None
    assert origin.tool is None
    assert origin.at == "2026-07-20T19:05:21Z"


def test_reads_info_from_a_compressed_object_stream(tmp_path: Path):
    """PDF 1.5+ writers put the Info dictionary inside a Flate stream."""
    import zlib

    inner = b"<< /Producer (WeasyPrint 68.0) /Creator (pandoc) >>"
    compressed = zlib.compress(inner)
    document = tmp_path / "objstm.pdf"
    document.write_bytes(
        b"%PDF-1.7\n5 0 obj\n<< /Type /ObjStm /Filter /FlateDecode >>\nstream\n"
        + compressed
        + b"\nendstream\nendobj\n"
    )

    origin = read_embedded_metadata(document)

    assert origin is not None
    assert origin.tool == "WeasyPrint 68.0 (created in pandoc)"


def test_undecompressable_stream_is_not_an_error(tmp_path: Path):
    document = tmp_path / "broken-stream.pdf"
    document.write_bytes(
        b"%PDF-1.7\nstream\nnot actually deflate data at all\nendstream\n"
        b"<< /Producer (Fallback 1.0) >>\n"
    )

    origin = read_embedded_metadata(document)

    assert origin is not None
    assert origin.tool == "Fallback 1.0"


# --- how much of a member is read --------------------------------------------
#
# A zip member's uncompressed size is whatever its header declares, and
# `ZipFile.read` hands back as much as the archive asks for. XML compresses
# around fifteen hundred to one, so a document under a megabyte on disk can
# name a property part of six hundred, and reading it allocates that twice -
# once as bytes and once as a parse tree. Property parts are kilobytes in every
# real file, and the ones that are not are not property parts.


def _bomb(path: Path, member: str, size: int, alongside: dict[str, str] | None = None) -> None:
    """A zip whose named member inflates to `size` bytes of well-formed XML."""
    filler = b"<!-- " + b"A" * 4000 + b" -->"
    body = b"<r>" + filler * (size // len(filler)) + b"</r>"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in (alongside or {}).items():
            archive.writestr(name, text)
        archive.writestr(member, body)


def _peak_reading(path: Path) -> int:
    """Bytes the readers allocate while looking at one file."""
    tracemalloc.start()
    try:
        read_embedded_metadata(path)
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


BOMB_BYTES = 32 * 1024 * 1024


def test_an_odf_does_not_allocate_the_part_it_declares(tmp_path: Path):
    document = tmp_path / "report.odt"
    _bomb(document, "meta.xml", BOMB_BYTES)

    assert document.stat().st_size < 1024 * 1024  # small on disk
    assert _peak_reading(document) < BOMB_BYTES // 2
    assert read_embedded_metadata(document) is None


def test_an_ooxml_does_not_allocate_the_part_it_declares(tmp_path: Path):
    document = tmp_path / "report.docx"
    _bomb(document, "docProps/core.xml", BOMB_BYTES, {"docProps/app.xml": APP_XML})

    assert _peak_reading(document) < BOMB_BYTES // 2


def test_an_epub_does_not_allocate_the_package_it_declares(tmp_path: Path):
    container = (
        '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="content.opf"/></rootfiles></container>'
    )
    book = tmp_path / "book.epub"
    _bomb(book, "content.opf", BOMB_BYTES, {"META-INF/container.xml": container})

    assert _peak_reading(book) < BOMB_BYTES // 2


def test_a_property_part_of_an_ordinary_size_is_still_read_whole(tmp_path: Path):
    """The bound has to be a bound and not a refusal to read anything."""
    document = tmp_path / "report.docx"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("docProps/core.xml", CORE_XML)
        archive.writestr("docProps/app.xml", APP_XML)

    origin = read_embedded_metadata(document)

    assert origin is not None and origin.tool == "Microsoft Office Word 16.0000"


def test_no_reader_takes_a_zip_member_without_a_bound():
    """Every member goes through `read_part`, and a new one has to as well.

    Written against the source rather than against behaviour because the point
    is the absence of a call, and a site added tomorrow would be missed by any
    test that enumerates the ones present today.
    """
    for module in (containers, documents):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "archive.read(" not in source, module.__name__


def test_an_encrypted_property_part_is_declined(tmp_path: Path):
    document = tmp_path / "locked.docx"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("docProps/core.xml", CORE_XML)
    body = bytearray(document.read_bytes())
    for magic, field in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        at = 0
        while (at := body.find(magic, at)) >= 0:
            flags = int.from_bytes(body[at + field : at + field + 2], "little")
            body[at + field : at + field + 2] = (flags | 1).to_bytes(2, "little")
            at += 4
    document.write_bytes(body)

    assert read_embedded_metadata(document) is None


def test_pdf_structure_reports_updates_attachments_actions_and_signatures(tmp_path: Path):
    """None of this is in the Info dictionary: an incrementally updated file
    keeps its earlier version, and an attachment, a script and a signature are
    each a fact the producer string does not mention."""
    from tests.pdf import document

    first = document(
        [b"BT (page) Tj ET"],
        extra=[
            b"<< /Type /Filespec /F (notes.txt) /UF (notes.txt) /EF << /F 8 0 R >> >>",
            b"<< /Type /EmbeddedFile /Length 5 >>\nstream\nhello\nendstream",
            b"<< /Type /Sig /Filter /Adobe.PPKLite /SubFilter /adbe.pkcs7.detached "
            b"/Name (Maria Wolf) /M (D:20260918090000Z) /Reason (Approved) "
            b"/ByteRange [0 0 0 0] /Contents <00> >>",
            b"<< /S /JavaScript /JS (app.alert\\(1\\)) >>",
            b"<< /Type /Annot /Subtype /Link /A << /S /URI /URI (https://example.org/x) >> >>",
        ],
        catalogue=(
            b"/OpenAction << /S /JavaScript /JS (this.print\\(\\)) >> /AcroForm << /Fields [] >> "
        ),
    )
    first = first.replace(b"trailer\n<<", b"trailer\n<< /ID [<AB01> <CD02>]", 1)
    prev = first.rfind(b"xref")
    update = (
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"xref\n0 1\n0000000000 65535 f \n"
        b"trailer\n<< /Size 12 /Root 1 0 R /Prev %d /ID [<AB01> <EF03>] >>\n"
        % prev
        + b"startxref\n%d\n%%%%EOF\n" % len(first)
    )
    path = tmp_path / "history.pdf"
    path.write_bytes(first + update)

    origin = read_embedded_metadata(path)

    assert origin is not None
    assert origin.note == (
        "1 incremental update; 1 embedded file; signed by Maria Wolf; JavaScript"
    )
    assert origin.fields["IncrementalUpdates"] == "1"
    assert origin.fields["PermanentID"] == "ab01"
    assert origin.fields["ChangingID"] == "ef03"
    assert origin.fields["EmbeddedFile[1]"] == "notes.txt"
    assert origin.fields["Signature[1]:M"] == "2026-09-18T09:00:00Z"
    assert origin.fields["Signature[1]:Reason"] == "Approved"
    assert origin.fields["OpenAction"] == "present"
    assert origin.fields["AcroForm"] == "present"
    assert origin.fields["URI[1]"] == "https://example.org/x"
    assert "Launch" not in origin.fields


def test_pdf_incremental_update_uses_the_latest_info_dictionary(tmp_path: Path):
    """A superseded Info object remains in the bytes but is no longer current."""
    from tests.pdf import document

    first = document(
        [b"BT (page) Tj ET"],
        extra=b"<< /Producer (Old Writer) /Author (Old Author) >>",
    )
    first = first.replace(b"trailer\n<<", b"trailer\n<< /Info 6 0 R", 1)
    previous = first.rfind(b"xref")
    new_info = b"7 0 obj\n<< /Producer (New Writer) /Author (New Author) >>\nendobj\n"
    new_xref = len(first) + len(new_info)
    update = (
        new_info
        + b"xref\n7 1\n%010d 00000 n \n" % len(first)
        + b"trailer\n<< /Size 8 /Root 1 0 R /Info 7 0 R /Prev %d >>\n" % previous
        + b"startxref\n%d\n%%%%EOF\n" % new_xref
    )
    path = tmp_path / "updated.pdf"
    path.write_bytes(first + update)

    origin = read_embedded_metadata(path)

    assert origin is not None
    assert origin.tool == "New Writer"
    assert origin.fields["Author"] == "New Author"


def _png_chunk(category: bytes, payload: bytes) -> bytes:
    import struct
    import zlib

    return (
        struct.pack(">I", len(payload))
        + category
        + payload
        + struct.pack(">I", zlib.crc32(category + payload))
    )


def _png(path: Path, *extra: bytes) -> None:
    import struct

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + b"".join(extra)
        + _png_chunk(b"IDAT", b"\x00")
        + _png_chunk(b"IEND", b"")
    )


def test_a_png_creation_time_written_as_rfc_1123_is_read_as_a_moment(tmp_path: Path):
    """libpng's own example writes `Creation Time` in the RFC 1123 form."""
    image = tmp_path / "chart.png"
    _png(image, _png_chunk(b"tEXt", b"Creation Time\x00Mon, 24 Aug 2026 19:02:11 GMT"))

    origin = read_embedded_metadata(image)

    assert origin is not None
    assert origin.at == "2026-08-24T19:02:11Z"


def test_a_png_exif_chunk_names_the_camera_and_the_capture_time(tmp_path: Path):
    """PNG 1.5 gave the format an `eXIf` chunk, and phones and screenshot
    tools write one. It carries a plain TIFF header, like APP1 in a JPEG."""
    import struct

    entries = [
        (0x010F, b"Pentax\x00"),
        (0x0110, b"K-3 III\x00"),
        (0x9003, b"2026:08:24 19:02:11\x00"),
    ]
    base = 8 + 2 + len(entries) * 12 + 4
    directory = struct.pack(">H", len(entries))
    values = b""
    for tag, raw in entries:
        directory += struct.pack(">HHII", tag, 2, len(raw), base + len(values))
        values += raw
    tiff = b"MM\x00\x2a" + struct.pack(">I", 8) + directory + struct.pack(">I", 0) + values
    image = tmp_path / "shot.png"
    _png(image, _png_chunk(b"eXIf", tiff), _png_chunk(b"tEXt", b"Software\x00Snapper 2"))

    origin = read_embedded_metadata(image)

    assert origin is not None
    assert origin.fields["Software"] == "Snapper 2"
    assert origin.fields["Make"] == "Pentax"
    assert origin.fields["Model"] == "K-3 III"
    assert origin.at == "2026-08-24T19:02:11Z"
    assert "Pentax" in (origin.tool or "")


def test_ooxml_external_relationships_are_listed(tmp_path: Path):
    """A template on a share and a hyperlink are what the document reaches for
    outside itself; an image inside the package is not."""
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/attachedTemplate" Target="file:///\\\\srv\\templates\\brief.dotm" '
        'TargetMode="External"/></Relationships>'
    )
    body = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/hyperlink" Target="https://example.org/x" TargetMode="External"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/image" Target="media/image1.png"/></Relationships>'
    )
    document = tmp_path / "brief.docx"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("docProps/core.xml", CORE_XML)
        archive.writestr("word/_rels/document.xml.rels", body)
        archive.writestr("word/_rels/settings.xml.rels", rels)

    origin = read_embedded_metadata(document)

    assert origin is not None
    assert origin.fields["ExternalLink[1]"] == "hyperlink: https://example.org/x"
    assert (
        origin.fields["ExternalLink[2]"]
        == "attachedTemplate: file:///\\\\srv\\templates\\brief.dotm"
    )
    assert "ExternalLink[3]" not in origin.fields
    assert "2 external links" in origin.note


def test_ooxml_dde_fields_are_reported_as_an_observation(tmp_path: Path):
    document = tmp_path / "invoice.docx"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:instrText> DDEAUTO c:\\\\windows\\\\system32\\\\cmd.exe "
            '"/k calc.exe" </w:instrText></w:r></w:p></w:body></w:document>',
        )

    origin = read_embedded_metadata(document)

    assert origin is not None
    assert origin.fields["DDE[1]"] == 'DDEAUTO c:\\\\windows\\\\system32\\\\cmd.exe "/k calc.exe"'
    assert "DDE field" in origin.note


def test_pdf_updates_say_which_objects_they_replaced_or_added(tmp_path: Path):
    from tests.pdf import document

    first = document(
        [b"BT (page) Tj ET"],
        extra=b"<< /Producer (Old Writer) /Author (Old Author) >>",
    )
    first = first.replace(b"trailer\n<<", b"trailer\n<< /Info 6 0 R", 1)
    previous = first.rfind(b"xref")
    update = (
        b"6 0 obj\n<< /Producer (New Writer) >>\nendobj\n"
        b"7 0 obj\n<< /S /JavaScript /JS (app.alert(1)) >>\nendobj\n"
    )
    new_xref = len(first) + len(update)
    update += (
        b"xref\n6 2\n%010d 00000 n \n%010d 00000 n \n" % (len(first), len(first) + 44)
        + b"trailer\n<< /Size 8 /Root 1 0 R /Info 6 0 R /Prev %d >>\n" % previous
        + b"startxref\n%d\n%%%%EOF\n" % new_xref
    )
    path = tmp_path / "updated.pdf"
    path.write_bytes(first + update)

    origin = read_embedded_metadata(path)

    assert origin is not None
    assert origin.fields["IncrementalUpdates"] == "1"
    assert origin.fields["Update[1]:Replaced"] == "6"
    assert origin.fields["Update[1]:Added"] == "7"
