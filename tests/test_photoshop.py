"""Photoshop Image Resource Blocks shared by JPEG, TIFF, PSD and PSB."""

from __future__ import annotations

import struct
from pathlib import Path

from filegrail.sources.embedded import read_embedded_metadata
from filegrail.sources.embedded.photoshop import read_photoshop_metadata


def _irb(identifier: int, payload: bytes, name: str = "") -> bytes:
    encoded = name.encode("latin-1")
    named = bytes((len(encoded),)) + encoded
    named += b"\x00" * (-len(named) % 2)
    block = b"8BIM" + struct.pack(">H", identifier) + named + struct.pack(">I", len(payload))
    return block + payload + b"\x00" * (len(payload) % 2)


def _jpeg(*resources: bytes) -> bytes:
    payload = b"Photoshop 3.0\x00" + b"".join(resources)
    return b"\xff\xd8\xff\xed" + struct.pack(">H", len(payload) + 2) + payload + b"\xff\xd9"


def _unicode(value: str) -> bytes:
    return struct.pack(">I", len(value)) + value.encode("utf-16-be")


def _version() -> bytes:
    return (
        struct.pack(">IB", 1, 1)
        + _unicode("Adobe Photoshop 25.0")
        + _unicode("Adobe Photoshop")
        + struct.pack(">I", 1)
    )


def _thumbnail() -> bytes:
    image = b"\xff\xd8\xff\xd9"
    return struct.pack(">6I2H", 1, 160, 120, 480, 57_600, len(image), 24, 1) + image


def _resolution() -> bytes:
    def fixed(value: int) -> int:
        return value * 65536

    return struct.pack(">IHHIHH", fixed(300), 1, 1, fixed(300), 1, 1)


def test_reads_photoshop_workflow_evidence_from_jpeg(tmp_path: Path):
    photo = tmp_path / "edited.jpg"
    photo.write_bytes(
        _jpeg(
            _irb(0x03ED, _resolution()),
            _irb(0x0406, struct.pack(">hHH", 10, 1, 3)),
            _irb(0x040C, _thumbnail()),
            _irb(0x041B, b"https://workflow.example/case/17\x00"),
            _irb(0x0421, _version()),
            _irb(0x07D0, b"\x00" * 52, "Subject outline"),
        )
    )

    origin = read_embedded_metadata(photo)

    assert origin.block == "photoshop-irb"
    assert origin.tool == "Adobe Photoshop 25.0"
    assert origin.note == "Photoshop thumbnails 1; Photoshop paths 1; Photoshop URLs 1"
    assert origin.fields["Photoshop:XResolution"] == "300"
    assert origin.fields["Photoshop:JPEGQuality"] == "10"
    assert origin.fields["Photoshop:Thumbnail[1]:Size"] == "160x120"
    assert origin.fields["Photoshop:Writer"] == "Adobe Photoshop 25.0"
    assert origin.fields["Photoshop:Path[1]:Name"] == "Subject outline"
    assert origin.fields["Photoshop:URL[1]"] == "https://workflow.example/case/17"


def test_reads_resources_from_a_photoshop_document(tmp_path: Path):
    resources = _irb(0x0421, _version()) + _irb(0x040C, _thumbnail())
    header = (
        b"8BPS"
        + struct.pack(">H", 1)
        + b"\x00" * 6
        + struct.pack(">HIIHH", 3, 1, 1, 8, 3)
        + struct.pack(">I", 0)
        + struct.pack(">I", len(resources))
    )
    document = tmp_path / "layered.psd"
    document.write_bytes(header + resources)

    origin = read_embedded_metadata(document)

    assert origin.block == "photoshop-irb"
    assert origin.tool == "Adobe Photoshop 25.0"
    assert origin.fields["Photoshop:Thumbnail[1]:Format"] == "JPEG"


def test_resolution_alone_stays_available_without_inventing_provenance(tmp_path: Path):
    photo = tmp_path / "resolution.jpg"
    photo.write_bytes(_jpeg(_irb(0x03ED, _resolution())))

    metadata = read_photoshop_metadata(photo)

    assert metadata.fields["Photoshop:XResolution"] == "300"
    assert read_embedded_metadata(photo) is None


def test_truncated_resource_is_ignored(tmp_path: Path):
    photo = tmp_path / "broken.jpg"
    payload = b"Photoshop 3.0\x00" + b"8BIM\x04\x21\x00\x00" + struct.pack(">I", 4096)
    photo.write_bytes(
        b"\xff\xd8\xff\xed" + struct.pack(">H", len(payload) + 2) + payload + b"\xff\xd9"
    )

    assert read_photoshop_metadata(photo) is None
    assert read_embedded_metadata(photo) is None
