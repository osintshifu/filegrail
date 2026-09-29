"""Writing a copy of a file with its metadata taken out.

This is the one thing in the project that produces a file, and it does so under
a rule the rest of the tool depends on: **the original is never touched**. A
cleaned copy is written somewhere else, and the source is left exactly as it
was found - which is what keeps `filegrail` safe to point at evidence.

Removal is claimed only where it can be verified. Every stripper here is held
against the readers that find metadata in the first place: if a reader can
still see something in the output, the copy is not clean and says so.
"""

from __future__ import annotations

import base64
import struct
import xml.etree.ElementTree as ElementTree
import zipfile
import zlib
from pathlib import Path

from filegrail.clean import clean_file
from filegrail.sources.c2pa import read_c2pa_manifest
from filegrail.sources.embedded import read_embedded_metadata
from tests.photo import jpeg_with_exif


def test_a_photographs_exif_does_not_survive_the_copy(tmp_path: Path):
    photo = tmp_path / "holiday.jpg"
    jpeg_with_exif(photo, "NIKON", "COOLPIX P6000", "2008:10:22 16:28:39")
    out = tmp_path / "clean"
    out.mkdir()

    result = clean_file(photo, out)

    assert result.written == out / "holiday.jpg"
    assert read_embedded_metadata(result.written) is None
    assert "exif" in result.removed


def test_the_original_is_left_exactly_as_it_was(tmp_path: Path):
    """The rest of the tool promises never to write to what it inspects, and
    the one command that writes anything must not be the exception."""
    photo = tmp_path / "holiday.jpg"
    jpeg_with_exif(photo, "NIKON", "COOLPIX P6000", "2008:10:22 16:28:39")
    before = photo.read_bytes()
    out = tmp_path / "clean"
    out.mkdir()

    clean_file(photo, out)

    assert photo.read_bytes() == before
    assert read_embedded_metadata(photo) is not None


def test_the_image_itself_is_still_there(tmp_path: Path):
    """Stripping metadata is not the same as damaging the file. What is left
    has to remain a readable image, or the copy is useless."""
    photo = tmp_path / "holiday.jpg"
    jpeg_with_exif(photo, "NIKON", "COOLPIX P6000", "2008:10:22 16:28:39")
    out = tmp_path / "clean"
    out.mkdir()

    written = clean_file(photo, out).written
    raw = written.read_bytes()

    assert raw.startswith(b"\xff\xd8")  # still a JPEG
    assert raw.endswith(b"\xff\xd9")  # with its end marker intact


def test_a_file_with_nothing_to_remove_says_so(tmp_path: Path):
    plain = tmp_path / "notes.txt"
    plain.write_text("nothing here", encoding="utf-8")
    out = tmp_path / "clean"
    out.mkdir()

    result = clean_file(plain, out)

    assert result.written is None
    assert result.removed == []


# --- PNG ---------------------------------------------------------------------


def _chunk(category: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + category
        + payload
        + struct.pack(">I", zlib.crc32(category + payload))
    )


def _png(path: Path, *extra: bytes) -> None:
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + b"".join(extra)
        + _chunk(b"IDAT", b"\x00")
        + _chunk(b"IEND", b"")
    )


def test_a_pngs_text_chunks_do_not_survive(tmp_path: Path):
    image = tmp_path / "chart.png"
    _png(image, _chunk(b"tEXt", b"Author\x00A. Person"), _chunk(b"tEXt", b"Software\x00Some Tool"))
    out = tmp_path / "clean"
    out.mkdir()

    result = clean_file(image, out)

    assert "png-text" in result.removed
    assert read_embedded_metadata(result.written) is None


def test_the_png_is_still_a_png(tmp_path: Path):
    """Every chunk that makes it an image has to survive, and the stream has to
    still end where a decoder expects it to."""
    image = tmp_path / "chart.png"
    _png(image, _chunk(b"tEXt", b"Author\x00A. Person"))
    out = tmp_path / "clean"
    out.mkdir()

    raw = clean_file(image, out).written.read_bytes()

    assert raw.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"IHDR" in raw and b"IDAT" in raw
    assert raw.endswith(_chunk(b"IEND", b""))
    assert b"A. Person" not in raw


def test_a_png_with_no_text_is_left_alone(tmp_path: Path):
    image = tmp_path / "plain.png"
    _png(image)
    out = tmp_path / "clean"
    out.mkdir()

    assert clean_file(image, out).written is None


# --- ISO base media (MP4, MOV) -----------------------------------------------


def _atom(category: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + category + payload


def _itunes_text(category: bytes, text: str) -> bytes:
    raw = text.encode("utf-8")
    return _atom(category, _atom(b"data", struct.pack(">II", 1, 0) + raw))


def _mvhd(created: int = 3_500_000_000) -> bytes:
    return _atom(b"mvhd", struct.pack(">IIIII", 0, created, created, 1000, 0) + b"\x00" * 80)


def test_a_movies_recording_metadata_does_not_survive(tmp_path: Path):
    clip = tmp_path / "clip.mp4"
    udta = _atom(
        b"udta",
        _itunes_text(b"\xa9too", "Lavf58.44.100") + _itunes_text(b"\xa9xyz", "+43.4674+011.8851/"),
    )
    clip.write_bytes(_atom(b"ftyp", b"isom") + _atom(b"moov", _mvhd() + udta))
    out = tmp_path / "clean"
    out.mkdir()

    result = clean_file(clip, out)

    assert read_embedded_metadata(result.written) is None
    assert b"Lavf58.44.100" not in result.written.read_bytes()
    assert b"43.4674" not in result.written.read_bytes()


def test_the_movie_keeps_its_length_so_its_offsets_still_point_somewhere(tmp_path: Path):
    """A movie's sample tables address the media by absolute offset, so cutting
    bytes out of the header would leave every one of them pointing at the wrong
    place. The metadata is overwritten in place instead, and the file is
    exactly as long as it was."""
    clip = tmp_path / "clip.mp4"
    udta = _atom(b"udta", _itunes_text(b"\xa9too", "Lavf58.44.100"))
    clip.write_bytes(
        _atom(b"ftyp", b"isom") + _atom(b"moov", _mvhd() + udta) + _atom(b"mdat", b"x" * 64)
    )
    out = tmp_path / "clean"
    out.mkdir()

    written = clean_file(clip, out).written

    assert written.stat().st_size == clip.stat().st_size
    assert b"x" * 64 in written.read_bytes()  # the media itself is untouched


# --- the zip-based document formats ------------------------------------------


def _docx(path: Path) -> None:
    core = (
        '<?xml version="1.0"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/'
        'core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:creator>A. Person</dc:creator>"
        "<cp:lastModifiedBy>Someone Else</cp:lastModifiedBy>"
        "</cp:coreProperties>"
    )
    app = (
        '<?xml version="1.0"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
        'extended-properties"><Company>A Company</Company><Application>Word</Application>'
        "</Properties>"
    )
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        bundle.writestr("docProps/core.xml", core)
        bundle.writestr("docProps/app.xml", app)
        bundle.writestr("word/document.xml", "<w:document>the text itself</w:document>")


def test_a_documents_author_does_not_survive(tmp_path: Path):
    document = tmp_path / "report.docx"
    _docx(document)
    out = tmp_path / "clean"
    out.mkdir()

    result = clean_file(document, out)

    assert read_embedded_metadata(result.written) is None
    assert b"A. Person" not in result.written.read_bytes()
    assert b"A Company" not in result.written.read_bytes()


def test_the_document_is_still_a_document(tmp_path: Path):
    """The properties are emptied rather than deleted: a package whose parts
    are named in its relationships and are then missing is a broken one."""
    document = tmp_path / "report.docx"
    _docx(document)
    out = tmp_path / "clean"
    out.mkdir()

    with zipfile.ZipFile(clean_file(document, out).written) as bundle:
        names = set(bundle.namelist())
        assert bundle.read("word/document.xml") == b"<w:document>the text itself</w:document>"

    assert {"[Content_Types].xml", "docProps/core.xml", "word/document.xml"} <= names


# --- checking the work -------------------------------------------------------


def test_a_clean_copy_reports_nothing_left(tmp_path: Path):
    photo = tmp_path / "holiday.jpg"
    jpeg_with_exif(photo, "NIKON", "COOLPIX P6000", "2008:10:22 16:28:39")
    out = tmp_path / "clean"
    out.mkdir()

    assert clean_file(photo, out).remaining == []


def test_what_the_stripper_missed_is_reported_rather_than_hidden(tmp_path: Path):
    """A packet appended after the end-of-image marker is outside the segment
    stream, so rebuilding the segments does not touch it. Somebody publishing
    on the strength of "cleaned" needs to be told that, so the copy is read
    back with the same readers that find metadata in the first place."""
    photo = tmp_path / "holiday.jpg"
    jpeg_with_exif(photo, "NIKON", "COOLPIX P6000", "2008:10:22 16:28:39")
    photo.write_bytes(
        photo.read_bytes() + b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
        b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description '
        b'xmlns:xmp="http://ns.adobe.com/xap/1.0/"><xmp:CreatorTool>Some Editor'
        b"</xmp:CreatorTool></rdf:Description></rdf:RDF></x:xmpmeta>"
    )
    out = tmp_path / "clean"
    out.mkdir()

    result = clean_file(photo, out)

    assert "xmp" in result.remaining


# --- where the copy goes -----------------------------------------------------
#
# The destination is a directory, and until now every copy was written straight
# into it under the file's own name. That is right for one file and wrong for a
# tree: two folders holding a `photo.jpg` produced one copy, and the second one
# silently replaced the first while the report said both had been written. The
# copies mirror the source tree instead, and a name already taken is a refusal
# rather than a replacement - this command writes files, so the one thing it
# must never do is remove one nobody asked it about.


def _tree(root: Path) -> tuple[Path, Path]:
    """Two photographs sharing a name, in two folders, from two cameras."""
    for folder, make in (("a", "NIKON"), ("b", "CANON")):
        (root / folder).mkdir(parents=True)
        jpeg_with_exif(root / folder / "photo.jpg", make, "MODEL", "2008:10:22 16:28:39")
    return root / "a" / "photo.jpg", root / "b" / "photo.jpg"


def test_a_copy_keeps_the_folder_it_came_from(tmp_path: Path):
    source = tmp_path / "case"
    first, _ = _tree(source)
    out = tmp_path / "clean"
    out.mkdir()

    result = clean_file(first, out, below=source)

    assert result.written == out / "a" / "photo.jpg"
    assert result.written.is_file()


def test_two_folders_holding_one_name_produce_two_copies(tmp_path: Path):
    """The report said two files were cleaned and one file existed."""
    source = tmp_path / "case"
    first, second = _tree(source)
    out = tmp_path / "clean"
    out.mkdir()

    written = [clean_file(path, out, below=source).written for path in (first, second)]

    assert written == [out / "a" / "photo.jpg", out / "b" / "photo.jpg"]
    # What is on disk, against what was reported. The two copies are byte for
    # byte the same here and that is correct: everything these fixtures differ
    # by lived in the block that was removed.
    assert sorted(out.rglob("*.jpg")) == written


def test_a_file_already_there_is_left_alone(tmp_path: Path):
    source = tmp_path / "case"
    first, _ = _tree(source)
    out = tmp_path / "clean"
    (out / "a").mkdir(parents=True)
    standing = out / "a" / "photo.jpg"
    standing.write_bytes(b"someone else's file")

    result = clean_file(first, out, below=source)

    assert standing.read_bytes() == b"someone else's file"
    assert result.written is None
    assert result.note and "--overwrite" in result.note


def test_overwrite_replaces_it_when_asked_to(tmp_path: Path):
    source = tmp_path / "case"
    first, _ = _tree(source)
    out = tmp_path / "clean"
    (out / "a").mkdir(parents=True)
    standing = out / "a" / "photo.jpg"
    standing.write_bytes(b"someone else's file")

    result = clean_file(first, out, below=source, overwrite=True)

    assert result.written == standing
    assert standing.read_bytes().startswith(b"\xff\xd8")


# --- checking without writing -------------------------------------------------
#
# `--check` is the same work with the writing left out. The answer it gives -
# what would come out, and what a reader would still find afterwards - is worth
# having before the copy exists rather than after, because the copy is the thing
# somebody is about to publish. Nothing is written where anybody could reach it:
# the readers open a path, so the bytes get a scratch one that lasts for the
# length of the question.


def _photo_with_a_packet_after_the_end(path: Path) -> None:
    """A JPEG whose XMP sits past the end-of-image marker, where no stripper reaches."""
    jpeg_with_exif(path, "NIKON", "COOLPIX P6000", "2008:10:22 16:28:39")
    path.write_bytes(
        path.read_bytes() + b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
        b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description '
        b'xmlns:xmp="http://ns.adobe.com/xap/1.0/"><xmp:CreatorTool>Some Editor'
        b"</xmp:CreatorTool></rdf:Description></rdf:RDF></x:xmpmeta>"
    )


def test_a_check_says_what_would_come_out_and_writes_nothing(tmp_path: Path):
    photo = tmp_path / "holiday.jpg"
    jpeg_with_exif(photo, "NIKON", "COOLPIX P6000", "2008:10:22 16:28:39")
    out = tmp_path / "clean"

    result = clean_file(photo, out, write=False)

    assert result.removed == ["exif"]
    assert result.written is None
    assert not out.exists()


def test_a_check_needs_no_destination_at_all(tmp_path: Path):
    """Nothing is going anywhere, so there is nowhere to name."""
    photo = tmp_path / "holiday.jpg"
    jpeg_with_exif(photo, "NIKON", "COOLPIX P6000", "2008:10:22 16:28:39")

    assert clean_file(photo, None, write=False).removed == ["exif"]


def test_a_check_reads_back_what_the_stripper_would_have_missed(tmp_path: Path):
    """The warning arrives before the copy does, which is the point of the mode."""
    photo = tmp_path / "holiday.jpg"
    _photo_with_a_packet_after_the_end(photo)

    result = clean_file(photo, None, write=False)

    assert "xmp" in result.remaining
    assert list(tmp_path.iterdir()) == [photo]


def test_a_check_still_reports_a_name_already_taken(tmp_path: Path):
    """A dry run that skips the destination is a dry run of a different command."""
    photo = tmp_path / "holiday.jpg"
    jpeg_with_exif(photo, "NIKON", "COOLPIX P6000", "2008:10:22 16:28:39")
    out = tmp_path / "clean"
    out.mkdir()
    (out / "holiday.jpg").write_bytes(b"someone else's file")

    assert "already there" in clean_file(photo, out, write=False).note


def test_a_package_with_an_encrypted_member_is_declined_rather_than_crashed(tmp_path: Path):
    from tests.test_archives import _mark_members_encrypted

    document = tmp_path / "locked.docx"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("docProps/core.xml", "<cp:coreProperties/>")
        archive.writestr("word/document.xml", "<w:document/>")
    document.write_bytes(_mark_members_encrypted(document.read_bytes()))
    out = tmp_path / "clean"
    out.mkdir()

    result = clean_file(document, out)

    assert result.written is None
    assert "could not be taken apart" in (result.note or "")


def test_a_pngs_content_credentials_do_not_survive_the_copy(tmp_path: Path):
    """The manifest was read out of the `caBX` chunk and then left in the copy,
    so the one format where the tool could show a manifest was the one where it
    could not take it out."""
    from tests.test_c2pa import GENERATED_CLAIM, _manifest, _png_with

    image = tmp_path / "generated.png"
    _png_with(image, _manifest(GENERATED_CLAIM))
    out = tmp_path / "clean"
    out.mkdir()

    result = clean_file(image, out)

    assert "c2pa" in result.removed
    assert result.remaining == []
    assert read_c2pa_manifest(result.written) is None


def test_an_svg_loses_what_is_written_around_the_drawing(tmp_path: Path):
    from tests.test_c2pa import GENERATED_CLAIM, _manifest

    drawing = tmp_path / "mark.svg"
    payload = base64.b64encode(_manifest(GENERATED_CLAIM)).decode()
    drawing.write_text(
        '<?xml version="1.0"?><!-- drawn by an editor -->'
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:c2pa="http://c2pa.org/manifest"'
        ' viewBox="0 0 10 10">'
        f"<metadata><c2pa:manifest>{payload}</c2pa:manifest></metadata>"
        '<path d="M0 0 L10 10"/></svg>',
        encoding="utf-8",
    )
    out = tmp_path / "clean"
    out.mkdir()

    result = clean_file(drawing, out)
    copy = result.written.read_text(encoding="utf-8")

    assert result.removed == ["c2pa", "comment"]
    assert read_c2pa_manifest(result.written) is None
    assert 'd="M0 0 L10 10"' in copy
    assert "c2pa" not in copy
    assert ElementTree.fromstring(copy).get("viewBox") == "0 0 10 10"
