"""Collection-level photo analysis built from structural evidence."""

from pathlib import Path

import pytest

from filegrail.models import EvidenceRecord, FileRecord
from filegrail.photo import analyse_photos
from filegrail.photopixels import available as pixels_available
from filegrail.sources.embedded import read_embedded_metadata
from tests.test_photo_exif import _jpeg_with_ifd1, _thumbnail


@pytest.fixture(autouse=True)
def _disable_optional_pixels(monkeypatch):
    monkeypatch.setattr("filegrail.photopixels.available", lambda: False)


def _record(path: Path) -> FileRecord:
    embedded = read_embedded_metadata(path)
    return FileRecord(
        path=str(path),
        size=path.stat().st_size,
        mtime="2026-09-20T10:00:00Z",
        evidence=[embedded] if embedded is not None else [],
    )


def _photo_bytes(*, width: int = 32, height: int = 24, preview=(160, 120)) -> bytes:
    data = _jpeg_with_ifd1(_thumbnail(*preview))
    frame = bytes((8,)) + height.to_bytes(2, "big") + width.to_bytes(2, "big")
    frame += b"\x01\x01\x11\x00"
    sof = b"\xff\xc0" + (len(frame) + 2).to_bytes(2, "big") + frame
    return data[:-2] + sof + data[-2:]


def test_collects_structural_facts_preview_and_method_coverage(tmp_path: Path):
    photo = tmp_path / "camera.jpg"
    photo.write_bytes(_photo_bytes())

    collection = analyse_photos([_record(photo)], tmp_path)

    assert collection.summary == (
        ("photographs", "1"),
        ("formats", "JPEG: 1"),
        ("embedded previews", "1"),
        ("conflicts", "0"),
        ("signals", "0"),
    )
    assert len(collection.photos) == 1
    result = collection.photos[0]
    assert (result.number, result.path, result.name, result.format) == (
        1,
        str(photo),
        "camera.jpg",
        "JPEG",
    )
    assert (result.width, result.height) == (32, 24)
    assert [
        (item.key, item.method, item.mime, item.width, item.height) for item in result.artifacts
    ] == [("embedded-preview", "EXIF IFD1", "image/jpeg", 160, 120)]
    assert [(item.label, item.value, item.state) for item in result.facts] == [
        ("JPEG dimensions", "32 x 24 px", "fact"),
        ("JPEG encoding", "baseline DCT, 8-bit, 1 component", "fact"),
        ("JPEG scans", "0", "fact"),
        ("Embedded preview", "160 x 120 px, 17 bytes", "fact"),
    ]
    assert [(item.name, item.status) for item in result.methods] == [
        ("JPEG structure", "evaluated"),
        ("EXIF metadata", "evaluated"),
        ("Pixel diagnostics", "not evaluated"),
    ]


def test_marks_dimension_conflict_and_preview_aspect_signal(tmp_path: Path):
    photo = tmp_path / "mismatch.jpg"
    photo.write_bytes(_photo_bytes(width=32, height=24, preview=(160, 100)))
    record = _record(photo)
    record.evidence.append(
        EvidenceRecord(
            source="device-metadata",
            fields={"ExifImageWidth": "40", "ExifImageHeight": "30"},
        )
    )

    result = analyse_photos([record], tmp_path).photos[0]

    assert [(item.label, item.state) for item in result.facts[-2:]] == [
        ("Dimension mismatch", "conflict"),
        ("Preview aspect ratio", "signal"),
    ]
    assert result.facts[-2].value == "JPEG 32 x 24 px; EXIF 40 x 30 px"
    assert result.facts[-1].value == "main 1.333; preview 1.600"


def test_groups_files_by_camera_body_serial(tmp_path: Path):
    records = []
    for name in ("one.jpg", "two.jpg"):
        path = tmp_path / name
        path.write_bytes(_photo_bytes())
        record = _record(path)
        record.evidence.append(
            EvidenceRecord(
                source="device-metadata",
                fields={
                    "Make": "NIKON",
                    "Model": "D750",
                    "BodySerialNumber": "CAM-0123",
                },
            )
        )
        records.append(record)

    collection = analyse_photos(records, tmp_path)

    assert collection.camera_groups == (
        ("CAM-0123", (str(tmp_path / "one.jpg"), str(tmp_path / "two.jpg"))),
    )
    assert [photo.camera for photo in collection.photos] == ["NIKON", "NIKON"]


def test_redaction_omits_pixel_bearing_artifacts(tmp_path: Path):
    photo = tmp_path / "camera.jpg"
    photo.write_bytes(_photo_bytes())

    result = analyse_photos([_record(photo)], tmp_path, redact=True).photos[0]

    assert result.artifacts == ()
    assert any(fact.label == "Embedded preview" for fact in result.facts)


def test_ignores_unsupported_files_and_isolates_analyser_failure(tmp_path: Path, monkeypatch):
    text = tmp_path / "notes.txt"
    text.write_text("not a photograph")
    photo = tmp_path / "broken.jpg"
    photo.write_bytes(_photo_bytes())

    def fail(_path):
        raise RuntimeError("decoder failed")

    monkeypatch.setattr("filegrail.photo.analyse_jpeg", fail)
    collection = analyse_photos([_record(text), _record(photo)], tmp_path)

    assert [item.name for item in collection.photos] == ["broken.jpg"]
    assert collection.photos[0].methods[0].status == "failed"
    assert collection.photos[0].methods[1].status == "evaluated"


@pytest.mark.skipif(not pixels_available(), reason="photo extra is not installed")
def test_integrates_optional_pixel_artifacts(tmp_path: Path, monkeypatch):
    from io import BytesIO

    from PIL import Image

    photo = tmp_path / "camera.jpg"
    encoded = BytesIO()
    Image.new("RGB", (8, 8), (100, 120, 140)).save(encoded, format="JPEG")
    jpeg = encoded.getvalue()
    thumbnail = BytesIO()
    Image.new("RGB", (4, 4), (120, 80, 40)).save(thumbnail, format="JPEG")
    exif_segment = _jpeg_with_ifd1(thumbnail.getvalue())[2:-2]
    photo.write_bytes(jpeg[:2] + exif_segment + jpeg[2:])
    monkeypatch.setattr("filegrail.photopixels.available", lambda: True)

    result = analyse_photos([_record(photo)], tmp_path).photos[0]

    assert result.methods[-1].status == "evaluated"
    assert result.methods[-1].detail == "7 derived maps produced"
    assert "main-preview" in {item.key for item in result.artifacts}
    assert "embedded-preview-comparison" in {item.key for item in result.artifacts}
