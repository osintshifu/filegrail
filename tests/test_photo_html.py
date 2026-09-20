"""The dedicated photo report is offline, explicit and safe for untrusted metadata."""

import re
from datetime import datetime, timezone
from pathlib import Path

from filegrail.models import EvidenceRecord
from filegrail.photo import (
    MethodCoverage,
    PhotoArtifact,
    PhotoCollection,
    PhotoFact,
    PhotoResult,
)
from filegrail.photohtml import render_photo_html

NOW = datetime(2026, 9, 20, 12, 30, tzinfo=timezone.utc)


def _collection(*, redacted: bool = False) -> PhotoCollection:
    hostile = '<camera onmouseover="alert(1)">'
    artifacts = (
        PhotoArtifact(
            "main-preview",
            "Main image preview",
            "bounded RGB decode",
            "image/png",
            b"\x89PNG\r\n\x1a\nmain",
            320,
            240,
            "RGB; longest edge <= 1024 px",
        ),
        PhotoArtifact(
            "embedded-preview",
            "Embedded EXIF preview",
            "EXIF IFD1",
            "image/jpeg",
            b"\xff\xd8\xff\xd9",
            160,
            120,
        ),
        PhotoArtifact(
            "ela-q90",
            "Error level analysis, quality 90",
            "error level analysis",
            "image/png",
            b"\x89PNG\r\n\x1a\nela",
            320,
            240,
            "JPEG recompression quality=90; absolute RGB difference; normalized per image",
        ),
    )
    photo = PhotoResult(
        1,
        f"/case/{hostile}.jpg",
        f"{hostile}.jpg",
        "JPEG",
        4096,
        "2026-09-20T09:00:00Z",
        "a" * 64,
        320,
        240,
        "NIKON D750",
        "CAM-0123",
        (
            EvidenceRecord(
                source="device-metadata",
                at="2025-04-01T12:30:00Z",
                geo="52.100000, 21.000000",
                fields={"UserComment": hostile, "Software": "Darktable"},
            ),
        ),
        None,
        (
            PhotoFact("JPEG dimensions", "320 x 240 px", "fact", "JPEG SOF"),
            PhotoFact(
                "Dimension mismatch",
                "JPEG 320 x 240 px; EXIF 640 x 480 px",
                "conflict",
                "JPEG SOF versus EXIF",
            ),
            PhotoFact(
                "Preview aspect ratio",
                "main 1.333; preview 1.600",
                "signal",
                "JPEG SOF versus embedded preview",
            ),
        ),
        () if redacted else artifacts,
        (
            MethodCoverage("JPEG structure", "evaluated", "marker stream parsed"),
            MethodCoverage("EXIF metadata", "evaluated", "EXIF directories parsed"),
            MethodCoverage(
                "Pixel diagnostics",
                "not evaluated" if redacted else "evaluated",
                "pixel-bearing artifacts omitted by redaction"
                if redacted
                else "1 derived map produced",
            ),
        ),
    )
    return PhotoCollection(
        "/case",
        (photo,),
        redacted,
        (("CAM-0123", (photo.path, "/case/other.jpg")),),
    )


def test_renders_offline_photo_plate_artifacts_and_evidence_states():
    page = render_photo_html(_collection(), output=Path("reports/photos.html"), now=NOW)

    assert page.startswith("<!doctype html>")
    assert "default-src 'none'" in page
    assert "img-src data:" in page
    assert "FileGrail Photo Lab" in page
    assert '<article class="plate" id="photo-001">' in page
    assert '<span class="plate-number">#001</span>' in page
    assert 'class="finding conflict"' in page
    assert 'class="finding signal"' in page
    assert 'class="method not-evaluated"' not in page
    assert "data:image/png;base64," in page
    assert "data:image/jpeg;base64," in page
    assert "JPEG recompression quality=90" in page
    assert "reports/photos.html" in page
    assert "2026-09-20 12:30 UTC" in page

    outward = r"""\b(?:src|href|action)\s*=\s*["'](?!#|data:image/)"""
    assert not re.search(outward, page)
    assert "<camera onmouseover" not in page
    assert "&lt;camera onmouseover=&quot;alert(1)&quot;&gt;" in page


def test_redacted_and_empty_reports_state_what_was_not_evaluated():
    redacted = render_photo_html(_collection(redacted=True), now=NOW)
    empty = render_photo_html(PhotoCollection("/empty", (), False, ()), now=NOW)

    assert "No pixel-bearing image is embedded in this redacted report." in redacted
    assert 'class="method not-evaluated"' in redacted
    assert "data:image/" not in redacted
    assert "No supported photographs were included in this report." in empty


def test_includes_responsive_print_focus_and_reduced_motion_rules():
    page = render_photo_html(_collection(), now=NOW)

    assert "@media(max-width:760px)" in page
    assert "@media print" in page
    assert "@media(prefers-reduced-motion:reduce)" in page
    assert ":focus-visible" in page
    assert "registration-corner" in page
