"""Maker notes, where the serial number of a camera body usually lives.

Standard EXIF has a place for a body serial and most cameras leave it empty,
writing it into the vendor block instead. The same block carries the shutter
count, which is the closest thing a photograph has to an odometer reading. Both
are worth the awkwardness of a format every vendor invented separately.
"""

from __future__ import annotations

import struct
from pathlib import Path

from filegrail.sources.embedded.exif import read_exif

from .photo import ifd, jpeg_with_maker_note


def nikon_note(serial: str, shutter: int) -> bytes:
    """A Nikon type-3 note: a signature, then a TIFF of its own.

    Offsets inside count from the first byte of the note rather than from the
    file's TIFF header, which is the detail that breaks a parser written for
    Canon and pointed at a Nikon.
    """
    preamble = b"Nikon\x00\x02\x10\x00\x00"
    # Offsets are counted from the inner TIFF header, which starts after the
    # preamble, so the value block is addressed in that space and not in the
    # note's. Getting this wrong is the whole reason Nikon needs its own path.
    inner_header = b"II\x2a\x00" + struct.pack("<I", 8)
    directory, values = ifd(
        [(0x001D, 2, serial.encode() + b"\x00"), (0x00A7, 4, struct.pack("<I", shutter))],
        "<",
        value_base=len(inner_header) + 2 + 2 * 12 + 4,
    )
    return preamble + inner_header + directory + values


def canon_note(endian: str, serial: int, file_number: int) -> bytes:
    """Canon writes a bare directory, with no signature and no header.

    Only values that fit in four bytes are used here, because anything longer
    is addressed in the file's own TIFF space and a fixture cannot know where
    the note will land until after it has been built.
    """
    directory, _values = ifd(
        [
            (0x0008, 4, struct.pack(endian + "I", file_number)),
            (0x000C, 4, struct.pack(endian + "I", serial)),
        ],
        endian,
        value_base=0,
    )
    return directory


def test_nikon_notes_name_the_body_and_its_shutter_count(tmp_path: Path):
    path = tmp_path / "nikon.jpg"
    jpeg_with_maker_note(path, "NIKON CORPORATION", "NIKON D300", nikon_note("3105364", 241575))

    tags = read_exif(path)

    assert tags is not None
    assert tags.maker is not None
    assert tags.maker.vendor == "Nikon"
    assert tags.maker.fields["SerialNumber"] == "3105364"
    assert tags.maker.fields["ShutterCount"] == "241575"


def test_a_note_written_in_the_other_byte_order_is_read_and_reported(tmp_path: Path):
    """A note that disagrees with its container was not written by the camera.

    The body writes both in one byte order. A note in the opposite order means
    something rewrote the TIFF around it and copied the block through
    untouched, which is worth saying out loud rather than silently repairing.
    """
    path = tmp_path / "canon.jpg"
    # The fixture's container is big-endian; this note is little-endian.
    jpeg_with_maker_note(path, "Canon", "Canon EOS 40D", canon_note("<", 1230405678, 1242489))

    tags = read_exif(path)

    assert tags is not None and tags.maker is not None
    assert tags.maker.vendor == "Canon"
    assert tags.maker.byte_order == "opposite to the container"
    assert tags.maker.fields["SerialNumber"] == "1230405678"
    assert tags.maker.fields["FileNumber"] == "124-2489"


def test_an_unreadable_note_is_counted_rather_than_invented(tmp_path: Path):
    """Garbage in the block must not become fields, and must not stop the scan."""
    path = tmp_path / "broken.jpg"
    jpeg_with_maker_note(path, "Pentax", "Pentax K-3", b"\xff" * 64)

    tags = read_exif(path)

    assert tags is not None and tags.maker is not None
    assert tags.maker.vendor == "Pentax"
    assert tags.maker.entries == 0
    assert tags.maker.fields == {}
    assert tags.maker.size == 64


def test_offsets_are_dropped_when_the_byte_order_disagrees():
    """A rewritten container leaves the note's offsets addressing the old file.

    A value short enough to sit inside its own entry survives the rewrite. One
    addressed by an offset does not: the bytes it points at now belong to
    whatever the rewrite put there. Reading them produces a field that looks
    like evidence and is not, so those entries are dropped instead.
    """
    from filegrail.sources.embedded import makernotes

    # A little-endian note inside a big-endian container. `SerialNumber` is
    # inline; `OwnerName` is addressed, and the offset is made to land on real
    # bytes inside the file so that the reader has every chance to use them.
    entries = [(0x000C, 4, struct.pack("<I", 4242)), (0x0009, 2, b"Not really the owner\x00")]
    note_at = 8
    note_length = 2 + len(entries) * 12 + 4
    note, values = ifd(entries, "<", value_base=note_at + note_length)
    tiff = b"MM\x00\x2a" + struct.pack(">I", note_at) + note + values
    assert len(note) == note_length
    assert b"Not really the owner" in tiff

    notes = makernotes.read(tiff, note_at, note_length, ">", "Canon")

    assert notes is not None
    assert notes.byte_order == "opposite to the container"
    assert notes.fields == {"SerialNumber": "4242"}


def test_a_scan_records_the_maker_note_as_its_own_block(tmp_path: Path):
    """The vendor block is evidence in its own right, not a footnote to EXIF.

    It is read by a different parser, it is trusted differently, and it names
    things standard EXIF does not. Folding it into the EXIF record would hide
    all three behind one source.
    """
    from filegrail.scan import scan

    photo = tmp_path / "case" / "nikon.jpg"
    photo.parent.mkdir()
    jpeg_with_maker_note(photo, "NIKON CORPORATION", "NIKON D300", nikon_note("3105364", 241575))

    records = scan(photo, use_shell_history=False, home=tmp_path / "empty")
    blocks = {record.block: record for record in records[0].evidence if record.block}

    assert "maker-notes" in blocks
    note = blocks["maker-notes"]
    assert note.fields["SerialNumber"] == "3105364"
    assert note.fields["ShutterCount"] == "241575"
    assert note.fields["Vendor"] == "Nikon"


def test_photographs_group_by_a_serial_only_the_maker_note_carries(tmp_path: Path):
    """The point of reading the block: bodies that standard EXIF never named.

    Clustering already knows how to group by `SerialNumber`. Until now nothing
    produced one for these files, so every photograph stood alone.
    """
    from filegrail.cluster import cluster
    from filegrail.scan import scan

    case = tmp_path / "case"
    case.mkdir()
    for name in ("one.jpg", "two.jpg"):
        jpeg_with_maker_note(
            case / name, "NIKON CORPORATION", "NIKON D300", nikon_note("3105364", 241575)
        )

    records = scan(case, use_shell_history=False, home=tmp_path / "empty")
    groups = cluster(records)

    # Grouping by model happens too and always did; the serial is the new one,
    # and it is the stronger claim because a model name identifies a product.
    devices = [group for group in groups if group.axis == "device"]

    assert [(group.name, len(group.paths)) for group in devices] == [("3105364", 2)]
    assert devices[0].basis == "Maker notes · SerialNumber"


def test_the_photo_report_names_the_block_and_the_body_it_identifies(tmp_path: Path):
    """A serial from the vendor block is still a serial, and still says whose.

    The photo report reads the body serial for its identity panel and groups
    photographs by it. Looking only at the standard EXIF tag meant that the one
    place cameras actually write it was the one place it did not look.
    """
    from filegrail.photo import analyse_photos
    from filegrail.photohtml import render_photo_html
    from filegrail.scan import scan

    case = tmp_path / "case"
    case.mkdir()
    for name in ("one.jpg", "two.jpg"):
        jpeg_with_maker_note(
            case / name, "NIKON CORPORATION", "NIKON D300", nikon_note("3105364", 241575)
        )

    records = scan(case, use_shell_history=False, home=tmp_path / "empty")
    collection = analyse_photos(records, case)

    assert [photo.serial for photo in collection.photos] == ["3105364", "3105364"]
    assert [value for _serial, value in collection.camera_groups] != []

    page = render_photo_html(collection)
    assert "Maker notes" in page
    assert "3105364" in page


def test_a_note_that_is_itself_an_image_is_read_as_a_preview(tmp_path: Path):
    """Some cameras put a whole JPEG where a directory is supposed to go.

    A Samsung Digimax writes a 320x240 preview into the block and nothing else,
    while the standard EXIF thumbnail beside it is 75x56. Read as a directory
    the block is noise; read as what it is, it is the largest picture the file
    carries apart from the photograph.
    """
    from PIL import Image

    rendered = tmp_path / "preview.jpg"
    Image.new("RGB", (320, 240), (40, 90, 140)).save(rendered, quality=70)
    path = tmp_path / "samsung.jpg"
    jpeg_with_maker_note(path, "Samsung Techwin", "<Digimax i50 MP3>", rendered.read_bytes())

    tags = read_exif(path)

    assert tags is not None and tags.maker is not None
    assert tags.maker.vendor == "Samsung"
    assert tags.maker.entries == 0
    preview = tags.maker.preview
    assert preview is not None
    assert (preview.width, preview.height) == (320, 240)
    assert preview.mime == "image/jpeg"
    assert preview.source == "maker note"
    assert preview.data.startswith(b"\xff\xd8") and preview.data.endswith(b"\xff\xd9")


def test_the_photo_report_shows_a_preview_the_maker_note_carries(tmp_path: Path):
    """Two previews in one file are two pieces of evidence, not a duplicate.

    They are written by different parts of the camera at different sizes, and
    either can be the stale one. Showing only the EXIF thumbnail would hide the
    larger of the two behind the smaller.
    """
    from PIL import Image

    from filegrail.photo import analyse_photos
    from filegrail.scan import scan

    rendered = tmp_path / "preview.jpg"
    Image.new("RGB", (320, 240), (40, 90, 140)).save(rendered, quality=70)
    case = tmp_path / "case"
    case.mkdir()
    jpeg_with_maker_note(
        case / "samsung.jpg", "Samsung Techwin", "<Digimax i50 MP3>", rendered.read_bytes()
    )

    records = scan(case, use_shell_history=False, home=tmp_path / "empty")
    note = next(r for r in records[0].evidence if r.block == "maker-notes")

    assert note.fields["Preview:Dimensions"] == "320x240"
    assert note.fields["Preview:Format"] == "JPEG"
    assert "Preview:SHA256" in note.fields
    assert b"\xff\xd8" not in note.fields["Preview:SHA256"].encode()

    photo = analyse_photos(records, case).photos[0]
    keys = [artifact.key for artifact in photo.artifacts]

    assert "maker-preview" in keys
    labels = [fact.label for fact in photo.facts]
    assert "Maker note preview" in labels


def apple_note(unique_id: str, content_id: str) -> bytes:
    """An `Apple iOS` note: signature, byte-order mark, then a directory.

    Offsets count from the first byte of the note, and the order is Apple's own
    rather than the file's, which is why the mark is there to be read.
    """
    preamble = b"Apple iOS\x00\x00\x01MM"
    directory, values = ifd(
        [(0x0020, 2, unique_id.encode() + b"\x00"), (0x002B, 2, content_id.encode() + b"\x00")],
        ">",
        value_base=len(preamble) + 2 + 2 * 12 + 4,
    )
    return preamble + directory + values


def test_apple_notes_name_the_identifiers_that_tie_files_together(tmp_path: Path):
    """An iPhone writes two identifiers here and neither is anywhere else.

    `ImageUniqueID` names the photograph inside its library. `ContentIdentifier`
    is shared with the short film a Live Photo records beside it, so it is the
    thing that says a still and a video are one exposure.
    """
    unique = "A90ABD4D-79FE-45F3-837C-3B769EF04210"
    content = "38CA8C91-85BC-45CE-A12B-26FD40383CD6"
    path = tmp_path / "iphone.jpg"
    jpeg_with_maker_note(path, "Apple", "iPhone 13 Pro Max", apple_note(unique, content))

    tags = read_exif(path)

    assert tags is not None and tags.maker is not None
    assert tags.maker.vendor == "Apple"
    assert tags.maker.entries == 2
    assert tags.maker.fields["ImageUniqueID"] == unique
    assert tags.maker.fields["ContentIdentifier"] == content


def panasonic_note(serial: bytes, note_at: int) -> bytes:
    """A `Panasonic` note: a twelve-byte signature, then a bare directory.

    Its offsets are counted in the container's TIFF space, so the note has to
    know where it will be placed before it can address anything.
    """
    entries = [(0x0025, 7, serial)]
    directory, values = ifd(entries, "<", value_base=note_at + 12 + 2 + len(entries) * 12 + 4)
    return b"Panasonic\x00\x00\x00" + directory + values


def test_a_value_the_camera_pads_with_nulls_is_still_read():
    """Panasonic writes its serial into a field two bytes wider than the text.

    The padding sits in front of the value rather than after it, so a reader
    that stops at the first null byte reads nothing at all and the body goes
    unnamed. The bytes are what the camera wrote; only the reading was wrong.
    """
    from filegrail.sources.embedded import makernotes

    note_at = 8
    note = panasonic_note(b"\x00\x00S010604030293\x00", note_at)
    tiff = b"II\x2a\x00" + struct.pack("<I", 8) + note

    notes = makernotes.read(tiff, note_at, len(note), "<", "Panasonic")

    assert notes is not None
    assert notes.vendor == "Panasonic"
    assert notes.fields["InternalSerialNumber"] == "S010604030293"


def olympus_note(serial: str, lens_serial: str, lens: str) -> bytes:
    """An `OLYMPUS\\0II` note, whose identity fields sit in a sub-directory.

    The two letters in the signature are the note's own byte order, which is
    not promised to match the file around it. Everything inside is addressed
    from the note's first byte, including the sub-directory itself.
    """
    preamble = b"OLYMPUS\x00II\x03\x00"
    equipment_at = len(preamble) + 2 + 1 * 12 + 4
    equipment, values = ifd(
        [
            (0x0101, 2, serial.encode() + b"\x00"),
            (0x0202, 2, lens_serial.encode() + b"\x00"),
            (0x0203, 2, lens.encode() + b"\x00"),
        ],
        "<",
        value_base=equipment_at + 2 + 3 * 12 + 4,
    )
    directory, _none = ifd([(0x2010, 13, struct.pack("<I", equipment_at))], "<", value_base=0)
    return preamble + directory + equipment + values


def test_olympus_names_the_body_and_the_lens_from_a_sub_directory(tmp_path: Path):
    """The serials are one directory down, which is why they read as absent.

    Olympus puts nothing identifying in the note's own directory: the body
    serial, the lens serial and the lens model are in a sub-directory it points
    at. A lens serial is the more interesting of the two, because a lens outlives
    the body it was mounted on and appears again on the next one.
    """
    path = tmp_path / "olympus.jpg"
    jpeg_with_maker_note(
        path,
        "OLYMPUS IMAGING CORP.",
        "E-P3",
        olympus_note("B9V508278", "ABG366769", "OLYMPUS M.14-42mm F3.5-5.6 II R"),
    )

    tags = read_exif(path)

    assert tags is not None and tags.maker is not None
    assert tags.maker.vendor == "Olympus"
    assert tags.maker.fields["SerialNumber"] == "B9V508278"
    assert tags.maker.fields["LensSerialNumber"] == "ABG366769"
    assert tags.maker.fields["LensModel"] == "OLYMPUS M.14-42mm F3.5-5.6 II R"


def minolta_note(endian: str, preview_at: int, preview_length: int) -> bytes:
    """A Minolta note: a bare directory whose first entry is its own version.

    The preview it names lives outside the note and outside the Exif segment,
    among the image data, so the note carries only the pointer to it.
    """
    directory, _values = ifd(
        [
            (0x0000, 7, b"MLT0"),
            (0x0088, 4, struct.pack(endian + "I", preview_at)),
            (0x0089, 4, struct.pack(endian + "I", preview_length)),
        ],
        endian,
        value_base=0,
    )
    return directory


def test_a_note_that_names_a_preview_the_file_cannot_hold_says_so(tmp_path: Path):
    """The camera wrote a preview into the picture and an editor dropped it.

    Minolta puts a full preview among the image data and only the pointer to it
    in the note. When the file is later re-saved smaller, the pointer survives
    and the picture does not, so the note ends up describing something the file
    no longer contains. That is worth stating: it is the file saying what was
    taken out of it.
    """
    from filegrail.sources.embedded import read_maker_notes

    path = tmp_path / "minolta.jpg"
    jpeg_with_maker_note(path, "KONICA MINOLTA", "DiMAGE Z3", minolta_note(">", 2019319, 47355))

    record = read_maker_notes(path)

    assert record is not None
    assert record.fields["Vendor"] == "Konica Minolta"
    assert record.fields["Preview:Declared"] == "47355 bytes at offset 2019319 from the TIFF header"
    assert "not present in this file" in record.note
