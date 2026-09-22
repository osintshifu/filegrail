"""The dedicated photo report is offline, explicit and safe for untrusted metadata."""

import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from filegrail.models import NAME_AND_SIZE, EvidenceRecord
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
            "Working image",
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
                else "1 analytical output produced",
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
    assert "Digital Image Examination Report" in page
    # The report names itself once, at the top, where the nav's home link lands.
    assert '<header class="mast report-head" id="top">' in page
    assert page.count("<dt>Generated</dt>") == 1
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
        "<h2>Recorded dates</h2>",
        "<h2>Key findings</h2>",
        "<h2>Shared attributes</h2>",
        "<h2>Evidence records</h2>",
        "<h2>Recorded locations</h2>",
        "<h2>Images</h2>",
    ):
        assert heading in page
    for title in (
        "Image comparison",
        "File information",
        "Evidence sources",
        "Findings",
        "Analyses performed",
        "File structure",
        "Shared attributes",
    ):
        assert f'<span class="t">{title}</span>' in page
    assert "<b>Limitations</b>" in page
    # Every limitation stands under the panel it limits; there is no closing essay.
    assert 'id="scope"' not in page
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

    for term in (
        "Digital Image Examination Report",
        "Working image",
        "Analytical output",
        "JPEG encoding fingerprint",
    ):
        assert term in page
    assert ">original</button>" not in page
    assert ">processed</button>" not in page
    assert "Common source" not in page


def test_summary_kpis_follow_navigation_and_link_to_their_records():
    page = render_photo_html(_collection(), now=NOW)
    head, _shell, body = page.partition('<div class="shell">')
    assert '<div class="cards">' not in head
    assert '<div class="cards">' in body
    positions = [
        body.index(f'<section id="{key}">')
        for key in ("summary", "gallery", "findings", "collection", "timeline", "evidence")
    ]
    assert positions == sorted(positions)
    assert "data-time-year=" in body
    assert "Recorded date distribution" not in body
    assert "within 25 km of its listed coordinate" in body
    assert ">Group 1" not in body


def test_inline_inspector_keeps_all_panels_in_document_order():
    """The panels stand on a grid in the order the rail's tree names them.

    Newspaper columns read top to bottom and then start again, which put the
    marker stream between two maps and the coverage under everything. On a grid
    the order in the markup is the order on the page: the image, what the file
    is and says, what was done to it, how it is built, the outputs, and the
    marker stream last.
    """
    photo = _collection().photos[0]
    page = render_photo_html(_collection(), now=NOW)

    keys = re.findall(
        r'<section data-detail-group="[^"]*" class="panel[^"]*" id="photo-001-([a-z0-9-]+)"', page
    )
    order = ["image", "fileinfo", "findings", "fields", "coverage", "structure"]
    order += [a.key for a in photo.artifacts if a.key != "main-preview"] + ["markers"]
    ranks = [order.index(key) for key in keys]
    assert keys[0] == "image"
    assert ranks == sorted(ranks), keys
    # An analytical output takes a third of a row; the file's own panels take half or all.
    assert re.search(
        r'<section data-detail-group="analysis" class="panel[^"]*\bthird\b[^"]*" id="photo-001-',
        page,
    )
    assert 'class="panel wide" id="photo-001-image"' in page


def test_evidence_table_preserves_category_source_match_basis_and_recorded_fields():
    """The image report must not flatten origin and activity into metadata."""
    collection = _collection()
    photo = replace(
        collection.photos[0],
        evidence=(
            EvidenceRecord(
                source="browser-download",
                url="https://download.example/image.jpg",
                referrer="https://referrer.example/gallery",
                tool="Firefox",
                at="2026-09-19T10:00:00Z",
                bytes=4096,
                mime="image/jpeg",
                sha256="b" * 64,
                match=NAME_AND_SIZE,
                match_note="record matched after the file moved",
            ),
            EvidenceRecord(
                source="device-metadata",
                block="exif",
                location="Warsaw, Poland",
                geo="52.100000, 21.000000",
                fields={"Software": "Darktable"},
                where={"path": "IFD0/ExifIFD"},
            ),
            EvidenceRecord(
                source="recent-documents",
                tool="Image Viewer",
                at="2026-09-20T08:00:00Z",
                note="opened locally",
            ),
        ),
    )

    page = render_photo_html(replace(collection, photos=(photo,)), now=NOW)

    assert "<h2>Evidence records</h2>" in page
    assert '<span class="blk org">origin</span>' in page
    assert '<span class="blk meta">metadata</span>' in page
    assert '<span class="blk act">activity</span>' in page
    for value in (
        "browser download",
        "device metadata / EXIF",
        "Recent Documents",
        "https://download.example/image.jpg",
        "https://referrer.example/gallery",
        "record matched after the file moved",
        "Warsaw, Poland",
        "52.100000, 21.000000",
        "IFD0/ExifIFD",
        "opened locally",
        "name+size",
        "embedded",
        "recorded-path",
    ):
        assert value in page


def test_findings_are_numbered_once_across_the_collection_and_listed_in_the_summary():
    """A finding a reader cannot cite is one they have to describe instead.

    The investigation report numbers what it finds, F01 upward, so a note can
    say which one it means. Here the numbers run across every image in order,
    only a flagged row takes one - an ordinary fact is an observation, not a
    finding - and the summary lists them all, each a link to the row it names.
    """
    single = _collection()
    first = single.photos[0]
    second = replace(first, number=2, path="/case/second.jpg", name="second.jpg")
    page = render_photo_html(replace(single, photos=(first, second)), now=NOW)

    assert "<h2>Key findings</h2>" in page
    for anchor in ("photo-001-F01", "photo-001-F02", "photo-002-F03", "photo-002-F04"):
        assert f'id="{anchor}"' in page
        assert f'href="#{anchor}"' in page
    assert not re.search(r"\bF0[5-9]\b", page)


def test_the_title_block_names_the_case_and_the_examiner_when_given():
    """A report that gets filed has to say which case it belongs to and who made it.

    Both are what the person running the tool types, so both are escaped like
    anything else read from outside, and a report made without them carries no
    empty rows standing in for them.
    """
    page = render_photo_html(_collection(), now=NOW, case="2026/014 <x>", examiner="J. Nowak")
    plain = render_photo_html(_collection(), now=NOW)

    assert "<dt>Case</dt><dd>2026/014 &lt;x&gt;</dd>" in page
    assert "<dt>Examiner</dt><dd>J. Nowak</dd>" in page
    assert "<title>2026/014 &lt;x&gt; - Digital Image Examination Report</title>" in page
    assert '<h1 class="report-title">Image examination</h1>' in plain
    assert "<dt>Examiner</dt>" not in plain


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

    The report gets a bounded working copy of every image and never renders the
    mutable evidence path directly. The maps are written beside that working
    image. The page then weighs kilobytes and the browser loads only what a
    reader has scrolled to, instead of parsing every image before showing the
    first.
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
    assert 'src="one.jpg"' not in page
    assert 'src="report.files/001-main-preview.jpg"' in page
    assert (images / "001-main-preview.jpg").is_file()
    # The original path and digest remain evidence, but are not the rendered pixels.
    assert collection.photos[0].sha256 is not None
    assert collection.photos[0].sha256 in page


@pytest.mark.skipif(not pixels_available(), reason="photo extra is not installed")
def test_every_source_is_shown_through_a_controlled_working_image(tmp_path: Path):
    """Browser-readable and specialist formats use the same bounded sidecar model."""
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

    assert 'src="web.jpg"' not in page
    assert 'src="plate.tiff"' not in page
    assert 'src="report.files/001-main-preview.jpg"' in page
    assert 'src="report.files/002-main-preview.jpg"' in page


def test_every_analytical_output_and_its_reading_are_in_the_page_before_any_script_runs():
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
    assert len(re.findall(r'<use href="#m-', page)) == 2
    assert "no basemap" in page
    # The coordinate is written both ways a reader may need to compare it.
    assert "52.100000 N" in page
    assert "52\u00b006\u203200.0\u2033" in page
    assert not re.search(r"""\b(?:src|href|action)\s*=\s*["'](?!#|data:image/)""", page)


def test_timeline_keeps_seconds_validates_dates_and_names_the_source():
    from filegrail.photohtml import _moment, _time_value

    photo = _collection().photos[0]

    def stamped(value):
        return replace(
            photo,
            evidence=(
                EvidenceRecord(source="device-metadata", fields={"DateTimeOriginal": value}),
            ),
        )

    first = stamped("2024:02:29 16:28:39")
    last = stamped("2024:02:29 16:46:53")
    assert _moment(last) - _moment(first) == 1094
    assert _moment(stamped("2023:02:29 16:28:39")) is None
    assert "DateTimeOriginal" in _time_value(first)[1]
    fallback = replace(photo, evidence=(EvidenceRecord(source="device-metadata", at="2024-01-01"),))
    assert "recorded time" in _time_value(fallback)[1]


def test_geographic_groups_do_not_connect_distant_places_or_invent_routes():
    from filegrail.photohtml import _location_groups
    from filegrail.photomap import Fix, site

    fixes = [Fix(1, "a", 43.46, 11.88), Fix(2, "b", -0.37, 36.05), Fix(3, "c", 43.461, 11.881)]
    groups = _location_groups(fixes)
    assert [[fix.number for fix in group] for group in groups] == [[1, 3], [2]]
    assert "<polyline" not in site(groups[0])[0]
    wrapped = _location_groups([Fix(1, "west", 0, 179.99), Fix(2, "east", 0, -179.99)])
    assert len(wrapped) == 1
    assert site(wrapped[0])[2] < 20


def test_collection_links_identify_members_and_evidence_has_addressable_rows():
    page = render_photo_html(_collection(), now=NOW)
    assert 'data-members="1"' in page
    assert 'id="evidence-00001" data-image="001"' in page
    assert '<a href="#photo-001-fields">' in page
    assert '<a href="#evidence-00001">' in page


def test_inspector_is_in_gallery_without_sidebar_and_keeps_evidence_links():
    page = render_photo_html(_collection(), now=NOW)
    assert '<aside class="rail"' not in page
    assert 'data-view="images"' not in page.split("<script>")[0]
    assert 'id="image-inspector" role="region"' in page
    assert 'aria-controls="image-inspector"' in page
    assert 'data-detail-group="overview analysis"' in page
    assert 'data-detail-group="evidence"' in page
    assert 'data-detail-tab="analysis"' in page
    assert 'data-output="ela-q90" aria-pressed="false" aria-controls="photo-001-ela-q90"' in page
    assert "<select data-output>" not in page
    assert 'aria-label="Analytical outputs and previews"' in page
    assert (
        page.index('id="gallery"')
        < page.index('id="image-inspector"')
        < page.index('id="findings"')
    )
    assert "working images" in page
    assert "without working image" in page


def test_gallery_offers_grid_and_list_without_a_second_set_of_images():
    page = render_photo_html(_collection(), now=NOW)
    assert 'data-gallery-layout="grid" aria-pressed="true"' in page
    assert 'data-gallery-layout="list" aria-pressed="false"' in page
    assert page.count('class="contact" data-member="1"') == 1


def test_the_inspector_leaves_the_thumbnails_whole_on_paper_and_without_a_script():
    # It sits inside the gallery grid, so only its order keeps 42 analyses from
    # landing between two rows of thumbnails.
    page = render_photo_html(_collection(), now=NOW)
    assert ".inline-inspector{grid-column:1/-1;order:9999;" in page
    assert ".js .inline-inspector{order:0}" in page
    assert ".js .inline-inspector{order:9999}" in page.split("@media print{.inline-inspector")[1]
