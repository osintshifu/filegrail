import struct
import zlib
from pathlib import Path

from filegrail.models import METADATA, SOURCE_LABELS, SOURCE_PRIORITY, category
from filegrail.scan import scan
from filegrail.sources.xmp import read_xmp


def _jpeg(*segments: tuple[bytes, bytes]) -> bytes:
    """A JPEG whose segment lengths are computed rather than typed."""
    out = b"\xff\xd8"
    for marker, payload in segments:
        out += marker + struct.pack(">H", len(payload) + 2) + payload
    return out + b"\xff\xd9"


def _app1_xmp(xml: str) -> tuple[bytes, bytes]:
    return b"\xff\xe1", b"http://ns.adobe.com/xap/1.0/\x00" + xml.encode("utf-8")


def _packet(body: str) -> str:
    """The wrapping a real encoder writes around an XMP payload."""
    return (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about=""'
        ' xmlns:xmp="http://ns.adobe.com/xap/1.0/"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
        ' xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"'
        ' xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/"'
        ' xmlns:stEvt="http://ns.adobe.com/xap/1.0/sType/ResourceEvent#"'
        ' xmlns:stRef="http://ns.adobe.com/xap/1.0/sType/ResourceRef#">'
        f"{body}"
        "</rdf:Description></rdf:RDF></x:xmpmeta>"
        '<?xpacket end="w"?>'
    )


def test_reads_creator_tool_and_date_from_a_jpeg(tmp_path: Path):
    photo = tmp_path / "export.jpg"
    photo.write_bytes(
        _jpeg(
            _app1_xmp(
                _packet(
                    "<xmp:CreatorTool>Adobe Photoshop 22.0 (Windows)</xmp:CreatorTool>"
                    "<xmp:CreateDate>2019-03-04T12:00:01+01:00</xmp:CreateDate>"
                )
            )
        )
    )

    origins = read_xmp(photo)

    assert len(origins) == 1
    assert origins[0].source == "xmp"
    assert origins[0].tool == "Adobe Photoshop 22.0 (Windows)"
    assert origins[0].at == "2019-03-04T11:00:01Z"


HISTORY = (
    "<xmpMM:History><rdf:Seq>"
    '<rdf:li rdf:parseType="Resource">'
    "<stEvt:action>created</stEvt:action>"
    "<stEvt:softwareAgent>Adobe Photoshop 22.0 (Windows)</stEvt:softwareAgent>"
    "<stEvt:when>2019-03-04T12:00:01+01:00</stEvt:when>"
    "</rdf:li>"
    '<rdf:li rdf:parseType="Resource">'
    "<stEvt:action>converted</stEvt:action>"
    "<stEvt:softwareAgent>Adobe Photoshop 22.0 (Windows)</stEvt:softwareAgent>"
    "<stEvt:when>2019-03-04T12:41:55+01:00</stEvt:when>"
    "<stEvt:parameters>from image/vnd.adobe.photoshop to image/jpeg</stEvt:parameters>"
    "</rdf:li>"
    "</rdf:Seq></xmpMM:History>"
)


def test_each_recorded_edit_becomes_its_own_claim(tmp_path: Path):
    photo = tmp_path / "edited.jpg"
    photo.write_bytes(_jpeg(_app1_xmp(_packet(HISTORY))))

    steps = [origin for origin in read_xmp(photo) if origin.source == "xmp-history"]

    assert [step.at for step in steps] == ["2019-03-04T11:00:01Z", "2019-03-04T11:41:55Z"]
    assert [step.tool for step in steps] == ["Adobe Photoshop 22.0 (Windows)"] * 2
    assert steps[0].note == "created"
    assert steps[1].note == "converted from image/vnd.adobe.photoshop to image/jpeg"
    assert steps[1].fields["stEvt:action"] == "converted"


def test_reads_the_compact_attribute_form(tmp_path: Path):
    """Adobe and darktable both write properties as attributes, not elements."""
    photo = tmp_path / "compact.jpg"
    photo.write_bytes(
        _jpeg(
            _app1_xmp(
                '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
                '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
                '<rdf:Description rdf:about=""'
                ' xmlns:xmp="http://ns.adobe.com/xap/1.0/"'
                ' xmp:CreatorTool="darktable 4.6.1"'
                ' xmp:CreateDate="2024-02-11T08:30:00Z"/>'
                "</rdf:RDF></x:xmpmeta>"
            )
        )
    )

    packet = read_xmp(photo)[0]

    assert packet.tool == "darktable 4.6.1"
    assert packet.at == "2024-02-11T08:30:00Z"


def test_reads_array_valued_properties(tmp_path: Path):
    """dc:creator is an rdf:Seq, not a string; dropping it loses the byline."""
    photo = tmp_path / "credited.jpg"
    photo.write_bytes(
        _jpeg(
            _app1_xmp(
                _packet(
                    "<dc:creator><rdf:Seq>"
                    "<rdf:li>Maria Wolf</rdf:li><rdf:li>Jan Kowalski</rdf:li>"
                    "</rdf:Seq></dc:creator>"
                    "<dc:title><rdf:Alt>"
                    '<rdf:li xml:lang="x-default">Harbour at dusk</rdf:li>'
                    "</rdf:Alt></dc:title>"
                )
            )
        )
    )

    packet = read_xmp(photo)[0]

    assert packet.fields["dc:creator"] == "Maria Wolf, Jan Kowalski"
    assert packet.fields["dc:title"] == "Harbour at dusk"


def test_xmp_is_metadata_ranked_between_document_and_device(tmp_path: Path):
    """An editor writing its own name is a weaker claim than a camera's model,
    and a stronger one than a bare document property."""
    photo = tmp_path / "ranked.jpg"
    photo.write_bytes(
        _jpeg(
            _app1_xmp(
                _packet(
                    "<xmp:CreatorTool>Adobe Photoshop 22.0 (Windows)</xmp:CreatorTool>" + HISTORY
                )
            )
        )
    )

    packet, step = read_xmp(photo)[:2]

    assert category(packet) == METADATA
    assert category(step) == METADATA
    assert packet.priority == step.priority == 52
    assert (
        SOURCE_PRIORITY["document-metadata"] < packet.priority < SOURCE_PRIORITY["device-metadata"]
    )
    assert SOURCE_LABELS["xmp"] == "XMP"
    assert SOURCE_LABELS["xmp-history"] == "XMP history"


def test_a_long_edit_history_is_capped_and_says_how_much_was_dropped(tmp_path: Path):
    """A heavily reworked file can record hundreds of edits. Bounding them keeps
    one file from burying a scan - reporting the bound keeps that honest."""
    steps = "".join(
        '<rdf:li rdf:parseType="Resource">'
        "<stEvt:action>saved</stEvt:action>"
        f"<stEvt:when>2019-03-04T12:{minute:02d}:00Z</stEvt:when>"
        "</rdf:li>"
        for minute in range(40)
    )
    photo = tmp_path / "reworked.jpg"
    photo.write_bytes(
        _jpeg(_app1_xmp(_packet("<xmpMM:History><rdf:Seq>" + steps + "</rdf:Seq></xmpMM:History>")))
    )

    origins = read_xmp(photo)

    assert len([origin for origin in origins if origin.source == "xmp-history"]) == 25
    assert origins[0].source == "xmp"
    assert "15 of 40 recorded edits not shown separately" in origins[0].note


def test_flattens_struct_valued_properties(tmp_path: Path):
    """DerivedFrom is a struct. Its inner ids are what link an export back to
    the document it came from, so the struct cannot be skipped for having no
    text of its own."""
    photo = tmp_path / "derived.jpg"
    photo.write_bytes(
        _jpeg(
            _app1_xmp(
                _packet(
                    '<xmpMM:DerivedFrom rdf:parseType="Resource">'
                    "<stRef:instanceID>xmp.iid:9d1c</stRef:instanceID>"
                    "<stRef:documentID>xmp.did:4b77</stRef:documentID>"
                    "</xmpMM:DerivedFrom>"
                )
            )
        )
    )

    packet = read_xmp(photo)[0]

    assert packet.fields["xmpMM:DerivedFrom/stRef:documentID"] == "xmp.did:4b77"
    assert packet.fields["xmpMM:DerivedFrom/stRef:instanceID"] == "xmp.iid:9d1c"


def test_the_packet_names_its_author_and_what_it_was_derived_from(tmp_path: Path):
    photo = tmp_path / "export.jpg"
    photo.write_bytes(
        _jpeg(
            _app1_xmp(
                _packet(
                    "<dc:creator><rdf:Seq><rdf:li>Maria Wolf</rdf:li></rdf:Seq></dc:creator>"
                    '<xmpMM:DerivedFrom rdf:parseType="Resource">'
                    "<stRef:documentID>xmp.did:4b77</stRef:documentID>"
                    "</xmpMM:DerivedFrom>"
                )
            )
        )
    )

    packet = read_xmp(photo)[0]

    # "document" rather than a bare identifier: the report also prints a
    # `derived from` line naming an actual file when one is in the same scan,
    # and two lines with one wording meaning two things is a report that reads
    # as though it said something twice.
    assert packet.note == "author Maria Wolf; derived from document xmp.did:4b77"


def _png(*chunks: tuple[bytes, bytes]) -> bytes:
    """A PNG whose chunk lengths and CRCs are computed, never typed."""
    out = b"\x89PNG\r\n\x1a\n"
    for chunk_type, payload in chunks:
        out += struct.pack(">I", len(payload)) + chunk_type + payload
        out += struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
    return out


def _itxt(keyword: str, text: str, *, compressed: bool = False) -> tuple[bytes, bytes]:
    body = zlib.compress(text.encode("utf-8")) if compressed else text.encode("utf-8")
    return b"iTXt", (
        keyword.encode("latin-1")
        + b"\x00"
        + bytes([1 if compressed else 0, 0])  # compression flag, compression method
        + b"\x00"  # language tag
        + b"\x00"  # translated keyword
        + body
    )


_IHDR = (b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))


def test_reads_xmp_from_a_png(tmp_path: Path):
    image = tmp_path / "render.png"
    image.write_bytes(
        _png(
            _IHDR,
            _itxt("XML:com.adobe.xmp", _packet("<xmp:CreatorTool>GIMP 2.10.36</xmp:CreatorTool>")),
            (b"IEND", b""),
        )
    )

    assert read_xmp(image)[0].tool == "GIMP 2.10.36"


def test_reads_xmp_from_a_deflated_png_chunk(tmp_path: Path):
    """PNG may compress its text chunks, which puts the packet out of reach of
    any scan over the raw bytes."""
    image = tmp_path / "compressed.png"
    image.write_bytes(
        _png(
            _IHDR,
            _itxt(
                "XML:com.adobe.xmp",
                _packet("<xmp:CreatorTool>Krita 5.2.2</xmp:CreatorTool>"),
                compressed=True,
            ),
            (b"IEND", b""),
        )
    )

    assert read_xmp(image)[0].tool == "Krita 5.2.2"


# --- the other containers ----------------------------------------------------
#
# Every one of them stores the packet as literal XML, which is what the standard
# requires so that a reader can find it without understanding the format around
# it. These tests hold that claim to each container in turn.


def test_reads_xmp_from_a_tiff(tmp_path: Path):
    packet = _packet("<xmp:CreatorTool>Capture One 23</xmp:CreatorTool>").encode("utf-8")
    values_at = 8 + 2 + 12 + 4  # header, entry count, one entry, next-IFD pointer
    raw = tmp_path / "scan.tiff"
    raw.write_bytes(
        b"MM\x00\x2a"
        + struct.pack(">I", 8)
        + struct.pack(">H", 1)
        + struct.pack(">HHII", 0x02BC, 1, len(packet), values_at)  # tag 700, type BYTE
        + struct.pack(">I", 0)
        + packet
    )

    assert read_xmp(raw)[0].tool == "Capture One 23"


def test_reads_xmp_from_a_pdf(tmp_path: Path):
    packet = _packet("<xmp:CreatorTool>Adobe InDesign 19.0</xmp:CreatorTool>").encode("utf-8")
    document = tmp_path / "brochure.pdf"
    document.write_bytes(
        b"%PDF-1.7\n1 0 obj\n<< /Type /Metadata /Subtype /XML /Length "
        + str(len(packet)).encode()
        + b" >>\nstream\n"
        + packet
        + b"\nendstream\nendobj\n"
    )

    assert read_xmp(document)[0].tool == "Adobe InDesign 19.0"


def test_reads_xmp_from_an_mp4(tmp_path: Path):
    """ISO base media keeps the packet in a uuid box under a fixed GUID."""
    packet = _packet("<xmp:CreatorTool>DaVinci Resolve 18</xmp:CreatorTool>").encode("utf-8")
    payload = bytes.fromhex("be7acfcb97a942e89c71999491e3afac") + packet
    ftyp = b"isom" + struct.pack(">I", 512) + b"isomiso2mp41"
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(
        struct.pack(">I", len(ftyp) + 8)
        + b"ftyp"
        + ftyp
        + struct.pack(">I", len(payload) + 8)
        + b"uuid"
        + payload
    )

    assert read_xmp(clip)[0].tool == "DaVinci Resolve 18"


def test_reads_xmp_from_an_svg(tmp_path: Path):
    drawing = tmp_path / "diagram.svg"
    drawing.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><metadata>'
        + _packet("<xmp:CreatorTool>Inkscape 1.3.2</xmp:CreatorTool>")
        + "</metadata></svg>",
        encoding="utf-8",
    )

    assert read_xmp(drawing)[0].tool == "Inkscape 1.3.2"


def test_a_scan_surfaces_xmp_beside_the_other_evidence(tmp_path: Path):
    """A reader nothing calls is not a feature."""
    home = tmp_path / "home"
    home.mkdir()
    case = tmp_path / "case"
    case.mkdir()
    (case / "export.jpg").write_bytes(
        _jpeg(
            _app1_xmp(
                _packet(
                    "<xmp:CreatorTool>Adobe Photoshop 22.0 (Windows)</xmp:CreatorTool>" + HISTORY
                )
            )
        )
    )

    record = scan(case, home=home, use_shell_history=False)[0]

    assert [origin.source for origin in record.evidence if origin.source.startswith("xmp")] == [
        "xmp",
        "xmp-history",
        "xmp-history",
    ]


def test_an_undated_edit_does_not_become_a_dated_event(tmp_path: Path):
    """The timeline falls back to a file's own timestamps when a claim carries
    none, which would place an editing action at a moment nothing recorded. The
    step is kept as a field instead, where it invents no time."""
    photo = tmp_path / "partial.jpg"
    photo.write_bytes(
        _jpeg(
            _app1_xmp(
                _packet(
                    "<xmpMM:History><rdf:Seq>"
                    '<rdf:li rdf:parseType="Resource">'
                    "<stEvt:action>derived</stEvt:action>"
                    "<stEvt:parameters>converted from PSD</stEvt:parameters>"
                    "</rdf:li>"
                    '<rdf:li rdf:parseType="Resource">'
                    "<stEvt:action>saved</stEvt:action>"
                    "<stEvt:when>2019-03-04T12:41:55Z</stEvt:when>"
                    "</rdf:li>"
                    "</rdf:Seq></xmpMM:History>"
                )
            )
        )
    )

    origins = read_xmp(photo)
    history = [origin for origin in origins if origin.source == "xmp-history"]

    assert [origin.at for origin in history] == ["2019-03-04T12:41:55Z"]
    assert origins[0].fields["xmpMM:History[1]"] == "derived converted from PSD"


# --- hostile and broken packets ----------------------------------------------
#
# Files come from wherever the investigation found them, so every one of these
# is an ordinary input rather than an error.


def test_an_entity_declaration_cannot_be_expanded(tmp_path: Path):
    """ElementTree expands internal entities, so a packet that declares them can
    turn a reader into a denial of service. Reading from the root element down
    leaves any declaration outside it out of reach."""
    bomb = (
        "<!DOCTYPE x:xmpmeta ["
        '<!ENTITY a "aaaaaaaaaa">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
        '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">'
        "]>"
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/">'
        "<xmp:CreatorTool>&c;</xmp:CreatorTool>"
        "</rdf:Description></rdf:RDF></x:xmpmeta>"
    )
    photo = tmp_path / "hostile.jpg"
    photo.write_bytes(_jpeg(_app1_xmp(bomb)))

    assert read_xmp(photo) == []


def test_a_packet_that_never_closes_is_left_alone(tmp_path: Path):
    photo = tmp_path / "truncated.jpg"
    photo.write_bytes(_jpeg(_app1_xmp('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF>')))

    assert read_xmp(photo) == []


def test_markup_that_is_not_rdf_yields_nothing(tmp_path: Path):
    photo = tmp_path / "wrong.jpg"
    photo.write_bytes(
        _jpeg(_app1_xmp('<x:xmpmeta xmlns:x="adobe:ns:meta/"><nonsense/></x:xmpmeta>'))
    )

    assert read_xmp(photo) == []


def test_one_hostile_file_does_not_end_a_scan(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    case = tmp_path / "case"
    case.mkdir()
    (case / "a-hostile.jpg").write_bytes(
        _jpeg(_app1_xmp('<x:xmpmeta xmlns:x="adobe:ns:meta/">' + "<a>" * 200))
    )
    (case / "b-sound.jpg").write_bytes(
        _jpeg(_app1_xmp(_packet("<xmp:CreatorTool>darktable 4.6.1</xmp:CreatorTool>")))
    )

    records = scan(case, home=home, use_shell_history=False)

    assert len(records) == 2
    assert any(origin.tool == "darktable 4.6.1" for origin in records[1].evidence)


def test_a_packet_carrying_an_xml_declaration_is_still_read(tmp_path: Path):
    """Some writers emit an XML declaration ahead of the packet. It is handed
    over whole by the PNG path, where no byte scan has already trimmed it."""
    declared = '<?xml version="1.0" encoding="UTF-8"?>' + _packet(
        "<xmp:CreatorTool>Krita 5.2.2</xmp:CreatorTool>"
    )
    image = tmp_path / "declared.png"
    image.write_bytes(
        _png(
            _IHDR,
            _itxt("XML:com.adobe.xmp", declared, compressed=True),
            (b"IEND", b""),
        )
    )

    assert read_xmp(image)[0].tool == "Krita 5.2.2"


def test_a_namespace_written_without_its_trailing_slash_still_names_its_prefix(tmp_path: Path):
    """Real files declare http://ns.microsoft.com/photo/1.0 where the standard
    writes the same namespace with a trailing slash. A field name a reader can
    look up must not depend on which spelling the encoder chose."""
    photo = tmp_path / "rated.jpg"
    photo.write_bytes(
        _jpeg(
            _app1_xmp(
                '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
                '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
                '<rdf:Description rdf:about=""'
                ' xmlns:MicrosoftPhoto="http://ns.microsoft.com/photo/1.0">'
                "<MicrosoftPhoto:Rating>75</MicrosoftPhoto:Rating>"
                "</rdf:Description></rdf:RDF></x:xmpmeta>"
            )
        )
    )

    assert read_xmp(photo)[0].fields["MicrosoftPhoto:Rating"] == "75"


def test_a_packet_whose_root_uses_another_prefix_is_found(tmp_path: Path):
    """Windows Photo Gallery binds the meta namespace to `xmp` where Adobe binds
    it to `x`. The prefix is the encoder's choice; only the local name is fixed."""
    photo = tmp_path / "gallery.jpg"
    photo.write_bytes(
        _jpeg(
            _app1_xmp(
                '<xmp:xmpmeta xmlns:xmp="adobe:ns:meta/">'
                '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
                '<rdf:Description rdf:about=""'
                ' xmlns:xmp="http://ns.adobe.com/xap/1.0/">'
                "<xmp:CreatorTool>Windows Photo Gallery 6.0.6001.18000</xmp:CreatorTool>"
                "</rdf:Description></rdf:RDF></xmp:xmpmeta>"
            )
        )
    )

    assert read_xmp(photo)[0].tool == "Windows Photo Gallery 6.0.6001.18000"


def test_a_property_name_in_the_wrong_case_is_still_recognised(tmp_path: Path):
    """Windows Photo Gallery writes xmp:creatortool where the standard says
    CreatorTool. It is the same fact under either spelling."""
    photo = tmp_path / "lowercase.jpg"
    photo.write_bytes(
        _jpeg(
            _app1_xmp(
                _packet(
                    "<xmp:creatortool>Windows Photo Gallery 6.0</xmp:creatortool>"
                    "<xmp:createdate>2008-04-11T09:00:00Z</xmp:createdate>"
                )
            )
        )
    )

    packet = read_xmp(photo)[0]

    assert packet.tool == "Windows Photo Gallery 6.0"
    assert packet.at == "2008-04-11T09:00:00Z"
