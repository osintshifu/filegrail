"""The dedicated photo report is offline, explicit and safe for untrusted metadata."""

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from filegrail.models import EvidenceRecord
from filegrail.photo import (
    MethodCoverage,
    PhotoArtifact,
    PhotoCollection,
    PhotoFact,
    PhotoResult,
)
from filegrail.photohtml import render_photo_html
from filegrail.photojpeg import (
    HuffmanTable,
    JpegAnalysis,
    JpegMarker,
    QualityEstimate,
    QuantizationTable,
)
from filegrail.photopixels import available as pixels_available

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
    jpeg = JpegAnalysis(
        320,
        240,
        "baseline DCT",
        8,
        ((1, 2, 2, 0),),
        1,
        8,
        (
            JpegMarker("SOI", 0xD8, 0, 2, b"\xff\xd8"),
            JpegMarker("EOI", 0xD9, 122, 2, b"\xff\xd9"),
        ),
        (QuantizationTable(0, 8, tuple(range(1, 65))),),
        (HuffmanTable("DC", 0, 12),),
        ("camera note",),
        122,
        4,
        QualityEstimate(85, False, 17),
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
        jpeg,
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


def test_renders_an_offline_image_report_with_artifacts_and_evidence_states():
    destination = Path("reports") / "photos.html"
    page = render_photo_html(_collection(), output=destination, now=NOW)

    assert page.startswith("<!doctype html>")
    assert "default-src 'none'" in page
    assert "img-src data:" in page
    assert "Image examination report" in page
    # The report names itself once, at the top, where the nav's home link lands.
    assert '<header class="mast" id="top">' in page
    assert page.count("<dt>analysed</dt>") == 1
    assert '<article class="frame" id="photo-001"' in page
    assert 'data-no="001"' in page
    assert '<tr class="conflict">' in page
    assert '<tr class="signal">' in page
    assert ">not evaluated<" not in page
    assert "data:image/png;base64," in page
    assert "data:image/jpeg;base64," in page
    assert "JPEG recompression quality=90" in page
    assert "JPEG marker stream" in page
    assert "0x0000" in page
    # The file structure map prints the bytes it names rather than describing them.
    assert "ff d8" in page
    assert "camera note" in page
    # Built from `Path`, never from a literal: the report prints the platform's
    # own separator and a literal with a slash in it passes everywhere but Windows.
    assert str(destination) in page
    assert "2026-09-20 12:30 UTC" in page

    outward = r"""\b(?:src|href|action)\s*=\s*["'](?!#|data:image/)"""
    assert not re.search(outward, page)
    assert "<camera onmouseover" not in page
    assert "&lt;camera onmouseover=&quot;alert(1)&quot;&gt;" in page


def test_the_report_names_its_sections_the_way_the_investigation_report_does():
    """One vocabulary across the tool, so a reader learns the names once.

    `filegrail report --html` calls these things Summary, Key findings and
    Evidence coverage, and an examination report is read by someone who expects
    the section names a report of this kind carries. The words this page reached
    for before - docket, field ledger, locator, light table - were this
    renderer's own inventions. A replacement design may move these panels
    anywhere it likes; it may not name them something only this file knows.
    """
    page = render_photo_html(_collection(), now=NOW)

    for heading in (
        "<h2>Case summary</h2>",
        "<h2>Metadata</h2>",
        "<h2>Geolocation</h2>",
        '<h2>Images <span class="n">',
        "<h2>Analyses</h2>",
    ):
        assert heading in page
    for title in (
        "Image comparison",
        "File information",
        "Metadata sources",
        "Findings",
        "Analyses performed",
        "File structure",
        "Common source",
    ):
        assert f'<span class="t">{title}</span>' in page
    assert "<b>Limitations</b>" in page
    assert "<b>Scope and limitations</b>" in page
    for invented in (
        "Docket",
        "Field ledger",
        "Locator",
        "Light table",
        "File digest",
        "Recorded blocks",
        "Structural findings",
        "Method coverage",
        "Byte map",
        "Instruments",
        "Interpretation boundary",
        "Cannot settle",
        "Photo Lab",
        "bench",
    ):
        assert invented not in page


def test_redacted_and_empty_reports_state_what_was_not_evaluated():
    redacted = render_photo_html(_collection(redacted=True), now=NOW)
    empty = render_photo_html(PhotoCollection("/empty", (), False, ()), now=NOW)

    assert "No pixel-bearing image is embedded in this redacted report." in redacted
    assert ">not evaluated<" in redacted
    # The page still carries the brand mark as drawn geometry. What redaction
    # promises is that no encoded image payload rides along with it.
    assert ";base64," not in redacted
    assert "No supported images were included in this report." in empty


def test_includes_responsive_print_focus_and_reduced_motion_rules():
    page = render_photo_html(_collection(), now=NOW)

    assert "@media(max-width:760px)" in page
    assert "@media print" in page
    assert "@media(prefers-reduced-motion:reduce)" in page
    assert ":focus-visible" in page
    assert 'class="rm tl"' in page


def photograph(path: Path) -> None:
    """A real JPEG on disk, so a report has something to point at."""
    from PIL import Image

    tags = Image.Exif()
    tags[0x010F] = "Canon"
    tags[0x0110] = "Canon EOS 40D"
    Image.new("RGB", (800, 600), (70, 110, 90)).save(path, quality=90, exif=tags)


@pytest.mark.skipif(not pixels_available(), reason="photo extra is not installed")
def test_a_linked_report_points_at_the_images_and_keeps_its_maps_beside_it(tmp_path: Path):
    """The everyday report: a page a browser opens, beside the files it shows.

    An image is already on disk, so the page points at it rather than
    carrying a second copy encoded as text. The maps are not on disk anywhere -
    they are computed - so they are written out beside the page. The page then
    weighs kilobytes and the browser loads only what a reader has scrolled to,
    instead of parsing every image before showing the first.
    """
    from filegrail.photo import analyse_photos
    from filegrail.photohtml import render_photo_html
    from filegrail.scan import scan

    case = tmp_path / "case"
    case.mkdir()
    for name in ("one.jpg", "two.jpg"):
        photograph(case / name)

    records = scan(case, use_shell_history=False, home=tmp_path / "empty", hash_files=True)
    collection = analyse_photos(records, case, budget=None)
    out = case / "report.html"
    images = case / "report.files"

    page = render_photo_html(collection, output=out, assets=images, now=NOW)

    assert ";base64," not in page
    assert 'src="report.files/001-ela-q90.jpg"' in page
    assert sorted(item.name for item in images.iterdir())[:2] == [
        "001-bit-planes.png",
        "001-ela-q75.jpg",
    ]
    # The photograph itself is pointed at where it lies, not copied.
    assert 'src="one.jpg"' in page
    assert not any(item.name.endswith("main-preview.jpg") for item in images.iterdir())
    # A link is only a record if a reader can tell the file is still the one read.
    assert collection.photos[0].sha256 is not None
    assert collection.photos[0].sha256 in page


@pytest.mark.skipif(not pixels_available(), reason="photo extra is not installed")
def test_a_source_a_browser_cannot_decode_is_shown_through_its_preview(tmp_path: Path):
    """A linked report points at the image, where a browser can display one.

    A TIFF is read here and not by any browser, so pointing an `<img>` at it puts
    a broken image where the pixel reader had already produced a preview. The
    image is still named by its path in the frame.
    """
    from filegrail.photo import analyse_photos
    from filegrail.scan import scan

    case = tmp_path / "case"
    case.mkdir()
    photograph(case / "web.jpg")
    from PIL import Image

    Image.new("RGB", (400, 300), (120, 80, 70)).save(case / "plate.tiff")

    records = scan(case, use_shell_history=False, home=tmp_path / "empty")
    collection = analyse_photos(records, case, budget=None)
    page = render_photo_html(
        collection, output=case / "report.html", assets=case / "report.files", now=NOW
    )

    assert 'src="web.jpg"' in page
    assert 'src="plate.tiff"' not in page
    assert 'src="report.files/001-main-preview.jpg"' in page


def test_every_derived_image_and_its_reading_are_in_the_page_before_any_script_runs():
    """The report is a document first and an instrument second.

    A script lays a map over the image and moves the opacity; that is the
    instrument. What it must not decide is whether a map is in the report at
    all, nor what the map means: every one of them is in the page either way,
    carrying what it shows and the limitations on reading it as text. The controls that
    only a pointer can work start hidden rather than dead.
    """
    page = render_photo_html(_collection(), now=NOW)

    assert 'class="image-stage' in page
    for key in ("embedded-preview", "ela-q90"):
        assert f'data-lens="{key}"' in page
    # What the panel is for, beside the panel, with no button between them.
    assert "The image compared against itself saved again at a fixed quality." in page
    assert page.count('<div class="caution"><b>Limitations</b>') > 1
    # Empty until a script fills it: no script, no overlay, and no broken image.
    assert '<img class="plate-over" alt="" hidden>' in page
    assert 'class="seg needs-js"' in page
    assert not re.search(r'<section class="panel[^"]*"[^>]*\shidden', page)
    assert not re.search(r'<button class="btn"[^>]*\shidden', page)


def test_a_chart_is_never_framed_as_registered_to_the_image():
    """Two frames, and never the same frame.

    A map measured on the image's own pixels can be laid over it, and a solid
    frame with corner marks says so. A chart describes the image without
    standing on it; framed the same way a reader would read a place into it that
    is not there, so it carries a dashed frame and says off register.
    """
    page = render_photo_html(_collection(), now=NOW)

    registered = page.index('<span class="reg">')
    assert '<i class="rm tl" aria-hidden="true">' in page[registered : registered + 300]
    assert 'class="regtag in">registered' in page
    assert 'class="chart">' in page
    assert "off register" in page


def test_the_geolocation_section_draws_an_outline_the_page_carries_once():
    """The map is a map, and it still asks the network for nothing.

    A report shows the same coastline at several scales; drawn each time it would
    put sixty kilobytes of path data into the page over and over, so it is defined
    once and referenced. What a reader sees is the outline, the recorded point on
    it, and a plot in metres that says it has no basemap under it.
    """
    page = render_photo_html(_collection(), now=NOW)

    assert 'id="geolocation"' in page
    assert len(re.findall(r'id="m-(?:world|borders)"', page)) == 2
    assert len(re.findall(r'<use href="#m-', page)) > 2
    assert "no basemap" in page
    # The coordinate is written both ways a reader may need to compare it.
    assert "52.100000 N" in page
    assert "52\u00b006\u203200.0\u2033" in page
    assert not re.search(r"""\b(?:src|href|action)\s*=\s*["'](?!#|data:image/)""", page)
