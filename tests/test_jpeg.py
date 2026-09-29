"""JPEG application metadata outside the EXIF APP1 segment."""

from __future__ import annotations

import struct
from pathlib import Path

from filegrail.sources.embedded import read_embedded_metadata
from filegrail.sources.embedded.jpeg import read_jpeg_metadata


def _segment(marker: int, payload: bytes) -> bytes:
    return b"\xff" + bytes((marker,)) + struct.pack(">H", len(payload) + 2) + payload


def _jpeg(*segments: bytes) -> bytes:
    return b"\xff\xd8" + b"".join(segments) + b"\xff\xd9"


def _icc(
    description: str = "Forensic RGB",
    *,
    manufacturer: bytes = b"APPL",
    model: bytes = b"DISP",
) -> bytes:
    assert len(manufacturer) == len(model) == 4
    text = description.encode("ascii") + b"\x00"
    tag = b"desc" + b"\x00" * 4 + struct.pack(">I", len(text)) + text
    tag += b"\x00" * (-len(tag) % 4)
    tag_offset = 132 + 12
    size = tag_offset + len(tag)

    header = bytearray(128)
    struct.pack_into(">I", header, 0, size)
    header[8:12] = b"\x04\x30\x00\x00"
    header[12:16] = b"mntr"
    header[16:20] = b"RGB "
    header[20:24] = b"XYZ "
    struct.pack_into(">6H", header, 24, 2020, 1, 2, 3, 4, 5)
    header[36:40] = b"acsp"
    header[40:44] = b"MSFT"
    header[48:52] = manufacturer
    header[52:56] = model
    header[80:84] = b"TEST"
    table = struct.pack(">I4sII", 1, b"desc", tag_offset, len(tag))
    return bytes(header) + table + tag


def _icc_segment(sequence: int, count: int, payload: bytes) -> bytes:
    return _segment(0xE2, b"ICC_PROFILE\x00" + bytes((sequence, count)) + payload)


JFIF = b"JFIF\x00" + bytes((1, 2, 1)) + struct.pack(">HH", 72, 72) + b"\x00\x00"


def test_segmented_icc_profile_is_reassembled_and_reported(tmp_path: Path):
    profile = _icc()
    split = len(profile) // 2
    image = tmp_path / "profile.jpg"
    image.write_bytes(
        _jpeg(
            _segment(0xE0, JFIF),
            _icc_segment(2, 2, profile[split:]),
            _icc_segment(1, 2, profile[:split]),
        )
    )

    origin = read_embedded_metadata(image)

    assert origin.block == "exif"
    assert origin.note == "ICC profile Forensic RGB"
    assert origin.fields["JFIF:Version"] == "1.02"
    assert origin.fields["JFIF:DensityUnits"] == "dpi"
    assert origin.fields["ICC:Description"] == "Forensic RGB"
    assert origin.fields["ICC:DeviceClass"] == "mntr"
    assert origin.fields["ICC:Manufacturer"] == "APPL"
    assert origin.fields["ICC:Created"] == "2020-01-02T03:04:05"


def test_missing_icc_chunk_does_not_create_partial_profile(tmp_path: Path):
    profile = _icc()
    image = tmp_path / "partial.jpg"
    image.write_bytes(_jpeg(_segment(0xE0, JFIF), _icc_segment(1, 2, profile[:80])))

    found = read_jpeg_metadata(image)

    assert found.fields["JFIF:Version"] == "1.02"
    assert not any(name.startswith("ICC:") for name in found.fields)
    assert read_embedded_metadata(image) is None


def test_generic_srgb_profile_does_not_claim_image_provenance(tmp_path: Path):
    profile = _icc("sRGB IEC61966-2.1", manufacturer=b"IEC ", model=b"sRGB")
    image = tmp_path / "srgb.jpg"
    image.write_bytes(_jpeg(_icc_segment(1, 1, profile)))

    found = read_jpeg_metadata(image)

    assert found.fields["ICC:Description"] == "sRGB IEC61966-2.1"
    assert found.icc_evidence is False
    assert read_embedded_metadata(image) is None


def test_jfxx_rgb_thumbnail_is_reported_without_decoding_pixels(tmp_path: Path):
    jfxx = b"JFXX\x00\x13\x01\x01\x10\x20\x30"
    image = tmp_path / "thumbnail.jpg"
    image.write_bytes(_jpeg(_segment(0xE0, JFIF), _segment(0xE0, jfxx)))

    origin = read_embedded_metadata(image)

    assert origin.note == "JFXX thumbnail present"
    assert origin.fields["JFXX:ThumbnailFormat"] == "RGB"
    assert origin.fields["JFXX:ThumbnailSize"] == "1x1"


def test_truncated_jfif_and_jfxx_are_ignored(tmp_path: Path):
    image = tmp_path / "broken.jpg"
    image.write_bytes(
        _jpeg(_segment(0xE0, b"JFIF\x00\x01"), _segment(0xE0, b"JFXX\x00\x13\x02\x02\x00"))
    )

    assert read_jpeg_metadata(image) is None
    assert read_embedded_metadata(image) is None


def test_invalid_icc_signature_is_not_reported(tmp_path: Path):
    profile = bytearray(_icc())
    profile[36:40] = b"nope"
    image = tmp_path / "fake-profile.jpg"
    image.write_bytes(_jpeg(_icc_segment(1, 1, bytes(profile))))

    assert read_jpeg_metadata(image) is None
    assert read_embedded_metadata(image) is None
