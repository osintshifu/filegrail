"""Two questions, two answers, both always shown.

"Where did this file come from" and "what does this file say about its own
earlier life" are different questions, and a browser download record is not a
better answer to the second one than a camera's EXIF - it is not an answer to it
at all. Ranking them against each other means the stronger claim silently
deletes the weaker one, and for a geotagged photograph that was downloaded, the
thing deleted is the GPS fix.
"""

from __future__ import annotations

from pathlib import Path

from filegrail.models import METADATA, ORIGIN, SOURCE_PRIORITY, EvidenceRecord, FileRecord
from filegrail.report import render_text
from filegrail.theme import Theme

PLAIN = Theme(colour=False, unicode=True, width=88)

DOWNLOAD = EvidenceRecord(
    source="browser-download",
    url="https://example.org/holiday.jpg",
    tool="firefox",
    at="2026-08-24T19:02:11Z",
)
CAMERA = EvidenceRecord(
    source="device-metadata",
    tool="NIKON COOLPIX P6000",
    at="2008-10-22T16:28:39Z",
    geo="43.467448, 11.885127",
    fields={"BodySerialNumber": "3001234"},
)


def _record(*origins: EvidenceRecord) -> FileRecord:
    record = FileRecord(path="/case/holiday.jpg", size=4096, mtime="2026-08-24T19:00:00Z")
    record.evidence.extend(origins)
    return record


# --- the classification ------------------------------------------------------


def test_every_source_is_classified():
    """An unclassified source would silently vanish from every view."""
    from filegrail.models import ACTIVITY, category

    for source in SOURCE_PRIORITY:
        assert category(EvidenceRecord(source=source)) in (ORIGIN, ACTIVITY, METADATA)


def test_a_download_is_origin_and_exif_is_metadata():
    record = _record(DOWNLOAD, CAMERA)

    assert record.origin is DOWNLOAD
    assert record.metadata is CAMERA


def test_a_file_with_only_one_kind_has_no_other():
    record = _record(CAMERA)

    assert record.origin is None
    assert record.metadata is CAMERA


def test_the_strongest_of_each_kind_wins_within_its_own_half():
    weak = EvidenceRecord(
        source="shell-history", command="curl -o holiday.jpg https://example.org/"
    )
    record = _record(weak, DOWNLOAD, CAMERA)

    assert record.origin is DOWNLOAD


# --- what the report shows ---------------------------------------------------


def test_a_downloaded_photograph_keeps_its_gps():
    """The regression this whole change exists to fix."""
    output = render_text([_record(DOWNLOAD, CAMERA)], Path("/case"), theme=PLAIN)

    assert "https://example.org/holiday.jpg" in output
    assert "NIKON COOLPIX P6000" in output
    assert "43.467448" in output
    assert "BodySerialNumber" in output


def test_origin_is_reported_before_metadata():
    """How it got here first; what it says about itself second."""
    output = render_text([_record(CAMERA, DOWNLOAD)], Path("/case"), theme=PLAIN)

    assert output.index("example.org/holiday.jpg") < output.index("NIKON COOLPIX P6000")


def test_brief_shows_the_index_and_stops():
    output = render_text([_record(DOWNLOAD, CAMERA)], Path("/case"), theme=PLAIN, brief=True)

    assert "holiday.jpg" in output
    assert "BodySerialNumber" not in output
    assert "example.org/holiday.jpg" not in output


def test_verbose_still_shows_every_claim():
    also = EvidenceRecord(source="macos-wherefroms", url="https://mirror.example.net/holiday.jpg")
    output = render_text(
        [_record(DOWNLOAD, CAMERA, also)], Path("/case"), theme=PLAIN, verbose=True
    )

    assert "mirror.example.net" in output
    assert "example.org/holiday.jpg" in output
    assert "NIKON COOLPIX P6000" in output


# --- what stands where the score used to ---------------------------------------


def test_no_number_is_printed_beside_a_record():
    """`55` invited being read as a probability. It never was one, and the
    five-block meter it drew put "a browser wrote this down" and "a camera
    described itself" on one scale as more and less of the same thing."""
    output = render_text([_record(DOWNLOAD, CAMERA)], Path("/case"), theme=PLAIN)

    assert "90" not in output
    assert "55" not in output
    # The old scale's words, which were six different properties on one axis.
    for word in ("self-reported", "circumstantial", "credentialed", "inherited"):
        assert word not in output, word


def test_what_a_record_carries_instead_is_how_it_was_matched():
    output = render_text([_record(DOWNLOAD, CAMERA)], Path("/case"), theme=PLAIN)

    assert "recorded-path" in output
    assert "recorded-path" in output


def test_the_ranking_stays_internal_and_out_of_json():
    """It still orders sources against each other; it is not a claim about
    truth, so nothing exports it and nothing prints it."""
    import json

    from filegrail.report import render_json

    payload = json.loads(render_json([_record(DOWNLOAD, CAMERA)], Path("/case")))
    written = payload["files"][0]["evidence"]

    assert not any("confidence" in found for found in written)
    assert not any("priority" in found for found in written)
    assert {found["category"] for found in written} == {"origin", "metadata"}


def test_every_source_has_a_category():
    """`category()` raises for a source nobody classified, which is how EXIF
    stopped being able to land in a collection named `origins`."""
    from filegrail.models import CATEGORIES, SOURCE_CATEGORIES, SOURCE_LABELS

    assert set(SOURCE_CATEGORIES) == set(SOURCE_LABELS)
    assert set(SOURCE_CATEGORIES.values()) <= set(CATEGORIES)
