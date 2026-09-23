"""Which metadata block a claim was decoded from.

`source` names what the reader found - a camera, a bare document - which is the
axis the category and the colour turn on. Two files can hand the same parser different
answers there: a photograph from a camera and a rendering with nothing but a
`Software` tag are both EXIF, and only one of them is `device-metadata`.

`block` names what the reader read. It is the axis a mirrored self-description
turns on, because whether IIM, EXIF or a PDF Info dictionary applies is a
question about the standard, not about what happened to be in it.
"""

from __future__ import annotations

import json
import struct
import zipfile
from pathlib import Path

import pytest

from filegrail.sources.embedded import read_embedded_metadata

from .test_formats import _jpeg, _png, _tiff

CAMERA = [(0x010F, 2, "NIKON"), (0x0110, 2, "COOLPIX P6000"), (0x9003, 2, "2008:10:22 16:28:39")]
NO_CAMERA = [(0x0131, 2, "GIMP 2.10.38")]

ODF_META = """<?xml version="1.0"?>
<office:document-meta
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0">
  <office:meta><meta:generator>LibreOffice/24.2</meta:generator></office:meta>
</office:document-meta>"""

CORE_XML = """<?xml version="1.0"?>
<cp:coreProperties
  xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
  xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:creator>Jan Kowalski</dc:creator>
</cp:coreProperties>"""

EPUB_CONTAINER = """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
</container>"""

EPUB_OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:creator>Mary Shelley</dc:creator>
  </metadata>
</package>"""


def _zipped(path: Path, members: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return path


def _pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-1.7\n1 0 obj\n<< /Creator (Adobe InDesign CC 13.1) >>\nendobj\n")
    return path


#: What makes a zip an Office package rather than a zip with an Office name.
#: Every conforming reader identifies one by this part, and a package without
#: it is only read by something lenient enough to go looking: `exiftool` reads
#: a one-member zip as a zip on one version and as a document on another, which
#: is how a fixture missing this was caught.
CONTENT_TYPES = """<?xml version="1.0"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels"
    ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-\
officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml"
    ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

PACKAGE_RELS = """<?xml version="1.0"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Target="word/document.xml"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/\
officeDocument"/>
  <Relationship Id="rId2" Target="docProps/core.xml"
    Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/\
core-properties"/>
</Relationships>"""

DOCUMENT_XML = """<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>Field notes</w:t></w:r></w:p></w:body>
</w:document>"""


def _ooxml(path: Path) -> Path:
    """A package with the parts an Office document is recognised by.

    The content types part comes first because that is where it belongs in an
    OPC package, and because a reader that identifies the format by the first
    member finds it there.
    """
    return _zipped(
        path,
        {
            "[Content_Types].xml": CONTENT_TYPES,
            "_rels/.rels": PACKAGE_RELS,
            "word/document.xml": DOCUMENT_XML,
            "docProps/core.xml": CORE_XML,
        },
    )


def _odf(path: Path) -> Path:
    return _zipped(path, {"meta.xml": ODF_META})


def _epub(path: Path) -> Path:
    return _zipped(path, {"META-INF/container.xml": EPUB_CONTAINER, "OEBPS/content.opf": EPUB_OPF})


def _rtf(path: Path) -> Path:
    path.write_bytes(rb"{\rtf1\ansi{\*\generator Riched20 10.0.19041;}Hello}")
    return path


def _svg(path: Path) -> Path:
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        'inkscape:version="1.3.2"/>',
        encoding="utf-8",
    )
    return path


def _notebook(path: Path) -> Path:
    path.write_text(
        json.dumps({"cells": [], "metadata": {"kernelspec": {"display_name": "Python 3"}}}),
        encoding="utf-8",
    )
    return path


def _photograph(path: Path) -> Path:
    path.write_bytes(_jpeg(_tiff(CAMERA)))
    return path


def _rendering(path: Path) -> Path:
    path.write_bytes(_jpeg(_tiff(NO_CAMERA)))
    return path


def _image(path: Path) -> Path:
    path.write_bytes(_png([(b"tEXt", b"Software\x00matplotlib 3.9.0")]))
    return path


def _movie(path: Path) -> Path:
    def atom(category: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload) + 8) + category + payload

    def itunes(category: bytes, text: str) -> bytes:
        return atom(category, atom(b"data", struct.pack(">II", 1, 0) + text.encode("utf-8")))

    meta = atom(b"meta", b"\x00" * 4 + atom(b"ilst", itunes(b"\xa9too", "HandBrake 1.7.3")))
    path.write_bytes(atom(b"ftyp", b"isom") + atom(b"moov", atom(b"udta", meta)))
    return path


def _audio(path: Path) -> Path:
    payload = b"\x03" + b"Lavf58.44.100"
    body = b"TSSE" + struct.pack(">I", len(payload)) + b"\x00\x00" + payload
    size = bytes(((len(body) >> shift) & 0x7F) for shift in (21, 14, 7, 0))
    path.write_bytes(b"ID3\x03\x00\x00" + size + body)
    return path


def _wav(path: Path) -> Path:
    def chunk(fourcc: bytes, payload: bytes) -> bytes:
        return fourcc + struct.pack("<I", len(payload)) + payload + b"\x00" * (len(payload) % 2)

    info = chunk(b"LIST", b"INFO" + chunk(b"ISFT", b"Audacity 3.4.2\x00"))
    path.write_bytes(b"RIFF" + struct.pack("<I", len(info) + 4) + b"WAVE" + info)
    return path


#: One minimal file per reader, and the block each of them reads.
BLOCKS = [
    ("paper.pdf", _pdf, "pdf-info"),
    ("report.docx", _ooxml, "ooxml-properties"),
    ("notes.odt", _odf, "odf-meta"),
    ("book.epub", _epub, "epub-package"),
    ("letter.rtf", _rtf, "rtf-generator"),
    ("logo.svg", _svg, "svg-metadata"),
    ("analysis.ipynb", _notebook, "notebook-kernel"),
    ("holiday.jpg", _photograph, "exif"),
    ("plot.jpg", _rendering, "exif"),
    ("chart.png", _image, "png-text"),
    ("clip.mp4", _movie, "isobmff"),
    ("track.mp3", _audio, "id3"),
    ("take.wav", _wav, "riff"),
]


@pytest.mark.parametrize("name,build,block", BLOCKS, ids=[block for _, _, block in BLOCKS])
def test_a_reader_names_the_block_it_read(tmp_path: Path, name: str, build, block: str):
    origin = read_embedded_metadata(build(tmp_path / name))

    assert origin is not None, f"{name} produced no claim to name a block on"
    assert origin.block == block


def test_one_block_can_arrive_under_two_source_names(tmp_path: Path):
    """A camera naming its own model is a stronger claim than a bare `Software`
    tag, so the EXIF reader names its claim after what it found. The block is
    the same either way, and a mirror keyed on the source would have to list
    both names to catch what is one standard."""
    photograph = read_embedded_metadata(_photograph(tmp_path / "holiday.jpg"))
    rendering = read_embedded_metadata(_rendering(tmp_path / "plot.jpg"))

    assert photograph.source == "device-metadata"
    assert rendering.source == "document-metadata"
    assert photograph.block == rendering.block == "exif"


def test_an_xmp_packet_names_its_own_block(tmp_path: Path):
    """`xmp` and `iptc` already name the standard they read, so their block and
    their source read alike. Setting it anyway keeps `block` meaning one thing
    everywhere, so a mirror can key on it without a fallback that would also
    match a source name by coincidence."""
    from filegrail.sources.xmp import read_xmp

    from .test_xmp import _app1_xmp, _packet
    from .test_xmp import _jpeg as _xmp_jpeg

    photo = tmp_path / "export.jpg"
    photo.write_bytes(
        _xmp_jpeg(
            _app1_xmp(
                _packet(
                    "<xmp:CreatorTool>Adobe Photoshop 22.0</xmp:CreatorTool>"
                    "<xmpMM:History><rdf:Seq><rdf:li"
                    ' stEvt:action="saved" stEvt:softwareAgent="darktable 4.6.1"'
                    ' stEvt:when="2024-01-02T03:04:05Z"/></rdf:Seq></xmpMM:History>'
                )
            )
        )
    )

    blocks = {claim.source: claim.block for claim in read_xmp(photo)}

    assert blocks == {"xmp": "xmp", "xmp-history": "xmp-history"}


def test_an_iim_block_names_its_own_block(tmp_path: Path):
    from filegrail.sources.iptc import read_iptc

    from .test_iptc import _app13, _dataset, _irb
    from .test_iptc import _jpeg as _iptc_jpeg

    photo = tmp_path / "wire.jpg"
    photo.write_bytes(_iptc_jpeg(_app13(_irb(0x0404, _dataset(80, b"Francisco Gonzalez")))))

    assert read_iptc(photo).block == "iptc"


def test_a_content_credential_names_its_own_block(tmp_path: Path):
    from filegrail.sources.c2pa import read_c2pa_manifest

    from .test_c2pa import GENERATED_CLAIM, _manifest, _png_with

    image = tmp_path / "generated.png"
    _png_with(image, _manifest(GENERATED_CLAIM))

    assert read_c2pa_manifest(image).block == "c2pa"


def test_a_claim_that_read_no_block_does_not_invent_one():
    """`block` records what a reader decoded. A download record read no metadata
    block at all, and naming one for it would be a claim nobody made."""
    from filegrail.models import EvidenceRecord

    assert EvidenceRecord(source="browser-download", url="https://example.org/a.pdf").block is None


# --- what the report calls it ------------------------------------------------


def test_a_block_is_named_where_the_source_would_only_say_document():
    """`document metadata` names a category rather than a thing: nine readers
    answer to it, and a reader told only that has been told the claim is
    a self-description and nothing else."""
    from filegrail.models import EvidenceRecord, label

    pdf = EvidenceRecord(source="document-metadata", block="pdf-info", tool="LibreOffice 25.2")

    assert label(pdf) == "PDF Info"


def test_a_camera_keeps_the_name_that_says_a_camera_made_the_claim():
    """`device metadata` says more than `EXIF`: it says the block held a make
    and a model, which is why it outranks a bare document property. Replacing
    it with the name of the standard would throw that away."""
    from filegrail.models import EvidenceRecord, label

    camera = EvidenceRecord(source="device-metadata", block="exif", tool="NIKON COOLPIX P6000")

    assert label(camera) == "device metadata"


def test_a_record_that_read_no_block_is_named_by_its_source():
    from filegrail.models import EvidenceRecord, label

    assert label(EvidenceRecord(source="browser-download", url="https://example.org/a.pdf")) == (
        "browser download"
    )


def test_the_report_calls_a_pdf_claim_by_the_block_it_read(tmp_path: Path):
    from filegrail.models import EvidenceRecord, FileRecord
    from filegrail.report import render_text
    from filegrail.theme import Theme

    record = FileRecord(path="/case/paper.pdf", size=4096, mtime="2026-08-24T19:00:00Z")
    record.evidence.append(
        EvidenceRecord(source="document-metadata", block="pdf-info", tool="Adobe PDF Library 15.0")
    )

    output = render_text([record], Path("/case"), theme=Theme(colour=False, unicode=True, width=88))

    assert "PDF Info" in output
    assert "document metadata" not in output


# --- what a phone writes into a MOV ------------------------------------------


def _atom(category: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + category + payload


def _mdta_movie(path: Path, values: dict[str, str]) -> Path:
    """A QuickTime `moov/meta` with `mdta` keys, the way iOS writes one: the
    meta atom carries no version and flags, and the items are numbered."""
    keys = b"".join(_atom(b"mdta", key.encode()) for key in values)
    keys_atom = _atom(b"keys", struct.pack(">II", 0, len(values)) + keys)
    items = b"".join(
        _atom(
            struct.pack(">I", index),
            _atom(b"data", struct.pack(">II", 1, 0) + value.encode("utf-8")),
        )
        for index, value in enumerate(values.values(), 1)
    )
    handler = _atom(b"hdlr", b"\x00" * 8 + b"mdta" + b"\x00" * 13)
    meta = _atom(b"meta", handler + keys_atom + _atom(b"ilst", items))
    path.write_bytes(_atom(b"ftyp", b"qt  ") + _atom(b"moov", meta))
    return path


def test_a_phones_mdta_keys_name_the_device_the_time_and_the_place(tmp_path: Path):
    clip = _mdta_movie(
        tmp_path / "IMG_0412.MOV",
        {
            "com.apple.quicktime.make": "Apple",
            "com.apple.quicktime.model": "iPhone 15 Pro",
            "com.apple.quicktime.software": "17.4",
            "com.apple.quicktime.creationdate": "2026-05-01T10:00:00+0200",
            "com.apple.quicktime.location.ISO6709": "+52.2297+021.0122+112.000/",
            "com.apple.quicktime.author": "Jan",
        },
    )

    origin = read_embedded_metadata(clip)

    assert origin is not None
    assert origin.tool == "Apple iPhone 15 Pro (encoded with 17.4)"
    assert origin.at == "2026-05-01T08:00:00Z"
    assert origin.geo == "52.2297, 21.0122"
    assert origin.fields["QuickTime:com.apple.quicktime.author"] == "Jan"


def test_track_languages_and_a_timecode_track_are_listed(tmp_path: Path):
    def track(handler: bytes, language: str) -> bytes:
        packed = 0
        for letter in language:
            packed = (packed << 5) | (ord(letter) - 0x60)
        mdhd = _atom(b"mdhd", b"\x00" * 4 + struct.pack(">IIIIHH", 0, 0, 600, 600, packed, 0))
        hdlr = _atom(b"hdlr", b"\x00" * 8 + handler + b"\x00" * 13)
        return _atom(b"trak", _atom(b"mdia", mdhd + hdlr))

    udta = _atom(b"udta", _atom(b"\xa9too", struct.pack(">HH", 9, 0) + b"HandBrake"))
    clip = tmp_path / "clip.mov"
    clip.write_bytes(
        _atom(b"ftyp", b"qt  ")
        + _atom(
            b"moov", udta + track(b"vide", "und") + track(b"soun", "pol") + track(b"tmcd", "und")
        )
    )

    origin = read_embedded_metadata(clip)

    assert origin is not None
    assert origin.fields["Track[1]"] == "vide und"
    assert origin.fields["Track[2]"] == "soun pol"
    assert origin.fields["Track[3]"] == "tmcd und"
    assert origin.fields["Timecode"] == "track present"
