"""EXIF structures that carry embedded photographic previews."""

import hashlib
import struct
from pathlib import Path

from filegrail.sources.embedded import read_embedded_metadata
from filegrail.sources.embedded.exif import read_exif


def _thumbnail(width: int = 160, height: int = 120) -> bytes:
    sof = bytes((8,)) + struct.pack(">HHB", height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8\xff\xc0" + struct.pack(">H", len(sof) + 2) + sof + b"\xff\xd9"


def _jpeg_with_ifd1(thumbnail: bytes, *, thumbnail_length: int | None = None) -> bytes:
    make = b"NIKON\x00"
    ifd0 = 8
    ifd0_size = 2 + 12 + 4
    make_at = ifd0 + ifd0_size
    ifd1 = make_at + len(make)
    ifd1_size = 2 + 3 * 12 + 4
    thumbnail_at = ifd1 + ifd1_size

    first = (
        struct.pack(">H", 1)
        + struct.pack(">HHI", 0x010F, 2, len(make))
        + struct.pack(">I", make_at)
        + struct.pack(">I", ifd1)
    )
    second = (
        struct.pack(">H", 3)
        + struct.pack(">HHI", 0x0103, 3, 1)
        + struct.pack(">H", 6)
        + b"\x00\x00"
        + struct.pack(">HHII", 0x0201, 4, 1, thumbnail_at)
        + struct.pack(
            ">HHII", 0x0202, 4, 1, len(thumbnail) if thumbnail_length is None else thumbnail_length
        )
        + struct.pack(">I", 0)
    )
    tiff = b"MM\x00\x2a" + struct.pack(">I", ifd0) + first + make + second + thumbnail
    app1 = b"Exif\x00\x00" + tiff
    return b"\xff\xd8\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + b"\xff\xd9"


def test_reads_a_bounded_jpeg_preview_from_exif_ifd1(tmp_path: Path):
    embedded = _thumbnail()
    photo = tmp_path / "camera.jpg"
    photo.write_bytes(_jpeg_with_ifd1(embedded))

    tags = read_exif(photo)

    assert tags is not None
    assert tags.thumbnail == {
        0x0103: 6,
        0x0201: 74,
        0x0202: len(embedded),
    }
    assert tags.preview is not None
    assert tags.preview.source == "EXIF IFD1"
    assert tags.preview.mime == "image/jpeg"
    assert tags.preview.data == embedded
    assert (tags.preview.width, tags.preview.height) == (160, 120)
    assert tags.preview.sha256 == hashlib.sha256(embedded).hexdigest()


def test_exif_preview_is_reported_as_text_without_serializing_its_bytes(tmp_path: Path):
    embedded = _thumbnail(68, 46)
    photo = tmp_path / "camera.jpg"
    photo.write_bytes(_jpeg_with_ifd1(embedded))

    record = read_embedded_metadata(photo)

    assert record is not None
    assert record.note == "EXIF thumbnail present"
    assert record.fields["Thumbnail:Format"] == "JPEG"
    assert record.fields["Thumbnail:Dimensions"] == "68x46"
    assert record.fields["Thumbnail:Bytes"] == str(len(embedded))
    assert record.fields["Thumbnail:SHA256"] == hashlib.sha256(embedded).hexdigest()
    assert "data" not in record.to_dict()


def test_rejects_an_ifd1_preview_length_outside_the_exif_payload(tmp_path: Path):
    photo = tmp_path / "camera.jpg"
    photo.write_bytes(_jpeg_with_ifd1(_thumbnail(), thumbnail_length=50_000))

    tags = read_exif(photo)

    assert tags is not None
    assert tags.preview is None
