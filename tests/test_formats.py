"""One test per container family, built from minimal valid files."""

import json
import struct
import tracemalloc
import zipfile
import zlib
from pathlib import Path

from filegrail.sources.embedded import read_embedded_metadata
from filegrail.sources.embedded.exif import camera, coordinates, read_exif

# --- EXIF, and the containers that carry it ----------------------------------


def _ifd(entries: list[tuple[int, int, object]], base: int) -> tuple[bytes, bytes]:
    """Build a big-endian IFD plus its out-of-line value block."""
    directory = struct.pack(">H", len(entries))
    values = b""
    value_base = base + 2 + len(entries) * 12 + 4

    for tag, category, value in entries:
        if category == 2:
            raw = value.encode("ascii") + b"\x00"
            count = len(raw)
        elif category == 5:
            raw = b"".join(struct.pack(">II", n, d) for n, d in value)
            count = len(value)
        else:
            raw = struct.pack(">I", value)
            count = 1

        directory += struct.pack(">HHI", tag, category, count)
        if category == 4 or len(raw) <= 4:
            directory += raw.ljust(4, b"\x00")[:4]
        else:
            directory += struct.pack(">I", value_base + len(values))
            values += raw
    return directory + struct.pack(">I", 0), values


def _tiff(main: list, gps: list | None = None) -> bytes:
    """Assemble a TIFF header with an optional GPS sub-IFD."""
    header = b"MM\x00\x2a" + struct.pack(">I", 8)
    if not gps:
        directory, values = _ifd(main, 8)
        return header + directory + values

    main_dir, main_vals = _ifd(main + [(0x8825, 4, 0)], 8)
    gps_offset = 8 + len(main_dir) + len(main_vals)
    main_dir, main_vals = _ifd(main + [(0x8825, 4, gps_offset)], 8)
    gps_dir, gps_vals = _ifd(gps, gps_offset)
    return header + main_dir + main_vals + gps_dir + gps_vals


def _jpeg(tiff: bytes) -> bytes:
    app1 = b"Exif\x00\x00" + tiff
    return b"\xff\xd8\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + b"\xff\xd9"


NIKON = [(0x010F, 2, "NIKON"), (0x0110, 2, "COOLPIX P6000"), (0x9003, 2, "2008:10:22 16:28:39")]
FLORENCE_GPS = [
    (0x0001, 2, "N"),
    (0x0002, 5, [(43, 1), (28, 1), (281, 100)]),
    (0x0003, 2, "E"),
    (0x0004, 5, [(11, 1), (53, 1), (646, 100)]),
]


def test_jpeg_gps_becomes_decimal_coordinates(tmp_path: Path):
    photo = tmp_path / "geotagged.jpg"
    photo.write_bytes(_jpeg(_tiff(NIKON, FLORENCE_GPS)))

    tags = read_exif(photo)

    assert camera(tags) == "NIKON COOLPIX P6000"
    latitude, longitude = coordinates(tags)
    assert round(latitude, 4) == 43.4674
    assert round(longitude, 4) == 11.8851


def test_southern_and_western_hemispheres_are_negative(tmp_path: Path):
    photo = tmp_path / "south.jpg"
    photo.write_bytes(
        _jpeg(
            _tiff(
                NIKON,
                [
                    (0x0001, 2, "S"),
                    (0x0002, 5, [(33, 1), (0, 1), (0, 1)]),
                    (0x0003, 2, "W"),
                    (0x0004, 5, [(70, 1), (0, 1), (0, 1)]),
                ],
            )
        )
    )

    assert coordinates(read_exif(photo)) == (-33.0, -70.0)


def test_out_of_range_coordinates_are_rejected(tmp_path: Path):
    photo = tmp_path / "bogus.jpg"
    photo.write_bytes(
        _jpeg(
            _tiff(
                NIKON,
                [
                    (0x0001, 2, "N"),
                    (0x0002, 5, [(200, 1), (0, 1), (0, 1)]),
                    (0x0003, 2, "E"),
                    (0x0004, 5, [(10, 1), (0, 1), (0, 1)]),
                ],
            )
        )
    )

    assert coordinates(read_exif(photo)) is None


def test_gps_reaches_the_origin(tmp_path: Path):
    photo = tmp_path / "geotagged.jpg"
    photo.write_bytes(_jpeg(_tiff(NIKON, FLORENCE_GPS)))

    origin = read_embedded_metadata(photo)

    assert origin.source == "device-metadata"
    assert origin.geo.startswith("43.4674")


def test_a_bare_tiff_is_read_directly(tmp_path: Path):
    scan = tmp_path / "scan.tiff"
    scan.write_bytes(_tiff([(0x0131, 2, "Nikon Scan 4.0")]))

    assert read_embedded_metadata(scan).tool == "Nikon Scan 4.0"


def _heif(tiff: bytes) -> bytes:
    """A HEIF whose item table names an `Exif` item before the payload appears.

    Real encoders write the literal ``Exif`` as the item type in `infe`, long
    before the EXIF itself. A reader that stops at the first marker finds the
    item table and decodes nothing.
    """
    infe = b"Exif\x00\x00" + b"\x00\x00\x00\x15infe\x02\x00\x00\x00"
    meta = b"\x00\x00\x00\x00" + infe
    boxes = struct.pack(">I", len(meta) + 8) + b"meta" + meta
    payload = b"Exif\x00\x00" + tiff
    mdat = struct.pack(">I", len(payload) + 8) + b"mdat" + payload
    return b"\x00\x00\x00\x14ftypheic\x00\x00\x00\x00heic" + boxes + mdat


def test_heif_exif_is_read_past_the_item_table(tmp_path: Path):
    photo = tmp_path / "photo.heic"
    photo.write_bytes(_heif(_tiff(NIKON, FLORENCE_GPS)))

    origin = read_embedded_metadata(photo)

    assert origin is not None
    assert origin.tool == "NIKON COOLPIX P6000"
    assert origin.geo.startswith("43.4674")


def test_heif_without_exif_reports_nothing(tmp_path: Path):
    photo = tmp_path / "empty.heic"
    photo.write_bytes(b"\x00\x00\x00\x14ftypheic\x00\x00\x00\x00heic")

    assert read_embedded_metadata(photo) is None


def test_webp_exif_chunk(tmp_path: Path):
    tiff = _tiff([(0x010F, 2, "Google"), (0x0110, 2, "Pixel 9")])
    chunk = b"EXIF" + struct.pack("<I", len(tiff)) + tiff
    body = b"WEBP" + b"VP8 " + struct.pack("<I", 4) + b"\x00\x00\x00\x00" + chunk
    image = tmp_path / "photo.webp"
    image.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)

    assert read_embedded_metadata(image).tool == "Google Pixel 9"


# --- PNG text chunks ---------------------------------------------------------


def _png(chunks: list[tuple[bytes, bytes]]) -> bytes:
    def chunk(category: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + category
            + payload
            + struct.pack(">I", zlib.crc32(category + payload))
        )

    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    for category, payload in chunks:
        out += chunk(category, payload)
    return out + chunk(b"IDAT", b"\x00") + chunk(b"IEND", b"")


def test_png_software_chunk(tmp_path: Path):
    image = tmp_path / "chart.png"
    image.write_bytes(_png([(b"tEXt", b"Software\x00matplotlib 3.9.0")]))

    assert read_embedded_metadata(image).tool == "matplotlib 3.9.0"


def test_png_generation_parameters_are_reported(tmp_path: Path):
    image = tmp_path / "generated.png"
    image.write_bytes(_png([(b"tEXt", b"parameters\x00a red bicycle, Steps: 30, Model: sdxl")]))

    note = read_embedded_metadata(image).note
    assert "generation parameters recorded" in note
    assert "a red bicycle" in note


def test_png_compressed_text_chunk(tmp_path: Path):
    payload = b"Software\x00\x00" + zlib.compress(b"Adobe Photoshop 25.0")
    image = tmp_path / "edited.png"
    image.write_bytes(_png([(b"zTXt", payload)]))

    assert read_embedded_metadata(image).tool == "Adobe Photoshop 25.0"


# --- ISO base media ----------------------------------------------------------


def _atom(category: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + category + payload


def _itunes_text(category: bytes, text: str) -> bytes:
    raw = text.encode("utf-8")
    data = _atom(b"data", struct.pack(">II", 1, 0) + raw)
    return _atom(category, data)


def test_mp4_encoder_and_location(tmp_path: Path):
    udta = _atom(
        b"udta",
        _itunes_text(b"\xa9too", "Lavf58.44.100") + _itunes_text(b"\xa9xyz", "+43.4674+011.8851/"),
    )
    video = tmp_path / "clip.mp4"
    video.write_bytes(_atom(b"ftyp", b"isom") + _atom(b"moov", udta))

    origin = read_embedded_metadata(video)

    assert origin.tool == "Lavf58.44.100"
    assert origin.geo == "43.4674, 11.8851"


def test_mp4_data_box_does_not_leak_into_the_text(tmp_path: Path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(
        _atom(b"ftyp", b"isom")
        + _atom(b"moov", _atom(b"udta", _itunes_text(b"\xa9too", "HandBrake")))
    )

    assert read_embedded_metadata(video).tool == "HandBrake"


def test_mp4_camera_make_and_model(tmp_path: Path):
    udta = _atom(
        b"udta", _itunes_text(b"\xa9mak", "Apple") + _itunes_text(b"\xa9mod", "iPhone 15 Pro")
    )
    video = tmp_path / "iphone.mov"
    video.write_bytes(_atom(b"ftyp", b"qt  ") + _atom(b"moov", udta))

    origin = read_embedded_metadata(video)

    assert origin.tool == "Apple iPhone 15 Pro"
    assert origin.source == "device-metadata"


# --- zip and text containers -------------------------------------------------

ODF_META = """<?xml version="1.0"?>
<office:document-meta
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0"
  xmlns:dc="http://purl.org/dc/elements/1.1/">
  <office:meta>
    <meta:generator>LibreOffice/24.2.7.2$Linux_X86_64</meta:generator>
    <dc:creator>Jan Kowalski</dc:creator>
    <meta:creation-date>2026-02-22T16:15:38</meta:creation-date>
  </office:meta>
</office:document-meta>"""


def test_odf_generator_and_author(tmp_path: Path):
    document = tmp_path / "notes.odt"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("meta.xml", ODF_META)

    origin = read_embedded_metadata(document)

    assert origin.tool == "LibreOffice/24.2.7.2$Linux_X86_64"
    assert origin.at == "2026-02-22T16:15:38Z"
    assert "author Jan Kowalski" in origin.note


#: What a document that has passed through Word looks like: a statistics
#: element that keeps its counts in attributes, and a list of user-defined
#: properties whose names are attributes too. Both need attributes read, and
#: they need them read differently.
ODF_USER_DEFINED = """<?xml version="1.0"?>
<office:document-meta
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0"
  xmlns:dc="http://purl.org/dc/elements/1.1/">
  <office:meta>
    <meta:generator>LibreOffice/5.4.7.2$Linux_X86_64</meta:generator>
    <dc:creator>Debra Dalgleish</dc:creator>
    <meta:document-statistic meta:table-count="2" meta:cell-count="63"/>
    <meta:user-defined meta:name="AppVersion">16.0300</meta:user-defined>
    <meta:user-defined meta:name="DocSecurity" meta:value-type="float">0</meta:user-defined>
    <meta:user-defined meta:name="Case reference">OSINT-2026-014</meta:user-defined>
  </office:meta>
</office:document-meta>"""


def _user_defined(tmp_path: Path) -> dict[str, str]:
    document = tmp_path / "book.ods"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("meta.xml", ODF_USER_DEFINED)
    return read_embedded_metadata(document).fields


def test_every_user_defined_property_is_kept_under_its_own_name(tmp_path: Path):
    """They are a list, not one field, and their names live in an attribute.

    Read like every other child element they collapse into one: the first
    value wins, the rest are dropped, and a property called `Case reference`
    disappears from a document that was filed under it.
    """
    fields = _user_defined(tmp_path)

    assert fields["AppVersion"] == "16.0300"
    assert fields["DocSecurity"] == "0"
    assert fields["Case reference"] == "OSINT-2026-014"


def test_the_attributes_that_name_them_do_not_become_fields(tmp_path: Path):
    """`name AppVersion` and `value-type float` are not things a document said."""
    fields = _user_defined(tmp_path)

    assert "user-defined" not in fields
    assert "name" not in fields
    assert "value-type" not in fields


def test_the_statistics_element_still_reads_its_attributes(tmp_path: Path):
    """The reason attributes are read at all; the counts live nowhere else."""
    fields = _user_defined(tmp_path)

    assert fields["table-count"] == "2"
    assert fields["cell-count"] == "63"


def test_a_user_defined_property_does_not_shadow_a_real_field(tmp_path: Path):
    """Anyone may name one `creator`. The document's own element wins."""
    document = tmp_path / "sneaky.odt"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr(
            "meta.xml",
            ODF_USER_DEFINED.replace(
                '<meta:user-defined meta:name="AppVersion">16.0300</meta:user-defined>',
                '<meta:user-defined meta:name="creator">Somebody Else</meta:user-defined>',
            ),
        )

    assert read_embedded_metadata(document).fields["creator"] == "Debra Dalgleish"


def test_epub_package_metadata(tmp_path: Path):
    container = """<?xml version="1.0"?>
    <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
      <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
    </container>"""
    opf = """<?xml version="1.0"?>
    <package xmlns="http://www.idpf.org/2007/opf">
      <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
        <dc:title>Frankenstein</dc:title>
        <dc:creator>Mary Shelley</dc:creator>
        <dc:date>1993-10-01</dc:date>
      </metadata>
    </package>"""
    book = tmp_path / "book.epub"
    with zipfile.ZipFile(book, "w") as archive:
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", opf)

    origin = read_embedded_metadata(book)

    assert origin.at == "1993-10-01T00:00:00Z"
    assert "author Mary Shelley" in origin.note
    assert "title Frankenstein" in origin.note


def test_rtf_generator(tmp_path: Path):
    document = tmp_path / "letter.rtf"
    document.write_bytes(rb"{\rtf1\ansi{\*\generator Riched20 10.0.19041;}Hello}")

    assert read_embedded_metadata(document).tool == "Riched20 10.0.19041"


def test_svg_inkscape_version(tmp_path: Path):
    drawing = tmp_path / "logo.svg"
    drawing.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        'inkscape:version="1.3.2"><rect width="1" height="1"/></svg>',
        encoding="utf-8",
    )

    assert read_embedded_metadata(drawing).tool == "Inkscape 1.3.2"


def test_svg_illustrator_generator_comment(tmp_path: Path):
    drawing = tmp_path / "logo.svg"
    drawing.write_text(
        "<!-- Generator: Adobe Illustrator 24.0.1, SVG Export Plug-In -->\n"
        '<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>',
        encoding="utf-8",
    )

    assert read_embedded_metadata(drawing).tool.startswith("Adobe Illustrator 24.0.1")


def test_svg_created_with_comment(tmp_path: Path):
    drawing = tmp_path / "chart.svg"
    drawing.write_text(
        "<!-- Created with Matplotlib (https://matplotlib.org/) -->\n"
        '<svg xmlns="http://www.w3.org/2000/svg"/>',
        encoding="utf-8",
    )

    assert read_embedded_metadata(drawing).tool.startswith("Matplotlib")


def test_svg_without_a_generator(tmp_path: Path):
    drawing = tmp_path / "plain.svg"
    drawing.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")

    assert read_embedded_metadata(drawing) is None


def test_jupyter_notebook_kernel(tmp_path: Path):
    notebook = tmp_path / "analysis.ipynb"
    notebook.write_text(
        json.dumps(
            {
                "cells": [],
                "metadata": {
                    "kernelspec": {"display_name": "Python 3"},
                    "language_info": {"name": "python", "version": "3.12.1"},
                },
            }
        ),
        encoding="utf-8",
    )

    assert read_embedded_metadata(notebook).tool == "Jupyter (Python 3, python 3.12.1)"


# --- ID3 ---------------------------------------------------------------------


def test_id3v2_encoder_frame(tmp_path: Path):
    def frame(identifier: bytes, text: str) -> bytes:
        payload = b"\x03" + text.encode("utf-8")
        return identifier + struct.pack(">I", len(payload)) + b"\x00\x00" + payload

    body = frame(b"TSSE", "Lavf58.44.100") + frame(b"TPE1", "Someone")
    size = bytes(((len(body) >> shift) & 0x7F) for shift in (21, 14, 7, 0))
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"ID3\x03\x00\x00" + size + body)

    origin = read_embedded_metadata(audio)

    assert origin.tool == "Lavf58.44.100"
    assert "artist Someone" in origin.note


def test_file_without_an_id3_tag(tmp_path: Path):
    audio = tmp_path / "bare.mp3"
    audio.write_bytes(b"\xff\xfb\x90\x00" * 16)

    assert read_embedded_metadata(audio) is None


def test_png_text_chunks_do_not_repeat_the_raw_xmp_packet(tmp_path: Path):
    """The packet belongs to the XMP reader, which decodes it into named
    properties. Keeping the markup here too would put a clipped, unparseable
    copy of the same evidence in the field tree."""
    packet = '<x:xmpmeta xmlns:x="adobe:ns:meta/">' + "<!-- pad -->" * 500 + "</x:xmpmeta>"
    itxt = b"XML:com.adobe.xmp\x00" + b"\x00\x00" + b"\x00" + b"\x00" + packet.encode()
    image = tmp_path / "edited.png"
    image.write_bytes(_png([(b"iTXt", itxt), (b"tEXt", b"Software\x00Adobe Photoshop 25.0")]))

    origin = read_embedded_metadata(image)

    assert origin.tool == "Adobe Photoshop 25.0"
    assert "XML:com.adobe.xmp" not in origin.fields


def test_decoded_coordinates_land_in_geo_not_location(tmp_path: Path):
    """`location` has to be free to hold a place written as a name - IPTC says
    "Firenze, Italy" and means it. A decoded latitude/longitude pair is a
    different category of fact and gets a field that only ever means that."""
    photo = tmp_path / "geotagged.jpg"
    photo.write_bytes(_jpeg(_tiff(NIKON, FLORENCE_GPS)))

    origin = read_embedded_metadata(photo)

    assert origin.geo.startswith("43.4674")
    assert origin.location is None


# --- RIFF --------------------------------------------------------------------


def _chunk(fourcc: bytes, payload: bytes) -> bytes:
    """One RIFF chunk: a name, a little-endian length, and even padding."""
    return fourcc + struct.pack("<I", len(payload)) + payload + b"\x00" * (len(payload) % 2)


def _riff(form: bytes, chunks: list[bytes]) -> bytes:
    body = form + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _info(entries: list[tuple[bytes, str]]) -> bytes:
    fields = b"".join(_chunk(name, text.encode("latin-1") + b"\x00") for name, text in entries)
    return _chunk(b"LIST", b"INFO" + fields)


def test_wav_info_chunk_names_the_editor(tmp_path: Path):
    audio = tmp_path / "interview.wav"
    audio.write_bytes(
        _riff(
            b"WAVE",
            [
                _chunk(b"fmt ", b"\x01\x00\x01\x00" + b"\x00" * 12),
                _info([(b"ISFT", "Adobe Audition 3.0"), (b"ICRD", "2019-03-04")]),
                _chunk(b"data", b"\x00" * 8),
            ],
        )
    )

    origin = read_embedded_metadata(audio)

    assert origin.tool == "Adobe Audition 3.0"
    assert origin.at == "2019-03-04T00:00:00Z"


# --- how much of a file the TIFF path reads ----------------------------------


#: Big enough that reading the file rather than mapping it is unmistakable in
#: the numbers, and small enough that writing one costs nothing. Real raw files
#: from a camera run from twenty-five megabytes to well past a hundred.
_LARGE = 24 * 1024 * 1024


def test_a_large_tiff_is_not_read_into_memory(tmp_path: Path):
    """The tags sit in the first few hundred bytes of a file that may be huge.

    `.dng`, `.nef`, `.cr2` and `.arw` all come through here, and a directory of
    them is the ordinary case rather than an attack: reading each one whole
    makes the peak the size of the largest file in the directory, for a few
    hundred bytes of answer.
    """
    scan = tmp_path / "scan.tiff"
    with scan.open("wb") as handle:
        handle.write(_tiff([(0x0131, 2, "Nikon Scan 4.0")]))
        handle.seek(_LARGE - 1)
        handle.write(b"\0")

    tracemalloc.start()
    try:
        origin = read_embedded_metadata(scan)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()

    assert origin is not None and origin.tool == "Nikon Scan 4.0"
    assert peak < _LARGE // 4


def test_an_empty_tiff_is_not_an_error(tmp_path: Path):
    """A file with nothing in it cannot be mapped, and is ordinary here.

    Asserted against `read_exif` and not only against the dispatcher above it.
    Reading the bytes returned an empty string for this file and mapping it
    raises, so the reader gained a way to fail that it did not have before, and
    the net in `read_embedded_metadata` would hide that from a test that only
    went through the front door.
    """
    empty = tmp_path / "truncated.tiff"
    empty.write_bytes(b"")

    assert read_exif(empty) is None
    assert read_embedded_metadata(empty) is None


def test_a_tiff_too_short_to_hold_a_header_is_not_an_error(tmp_path: Path):
    stub = tmp_path / "stub.tiff"
    stub.write_bytes(b"II*")

    assert read_exif(stub) is None
