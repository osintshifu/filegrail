"""Bounds on the total work of a scan and the total size of a photo report.

Every reader here is already bounded on its own: so many members per archive,
so many bytes per member, so many pixels per diagnostic map. None of that bounds
a run, because the work is the number of carriers times the work of each. These
are the two ceilings that apply to the whole of it.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from filegrail.photopixels import available

from .photo import jpeg_with_exif


def photograph(path: Path, taken: str = "2024:01:02 03:04:05") -> None:
    """A real JPEG carrying real EXIF, big enough that diagnostics cost bytes.

    The metadata goes in through the encoder rather than being spliced in after
    it, so the file is a photograph these tests can read a camera out of. That
    half of the record is the half a budget must never touch.
    """
    from PIL import Image

    tags = Image.Exif()
    tags[0x010F] = "Canon"
    tags[0x0110] = "Canon EOS 40D"
    tags[0x0132] = taken
    Image.new("RGB", (900, 700), (90, 120, 60)).save(path, quality=90, exif=tags)


@pytest.mark.skipif(not available(), reason="photo extra is not installed")
def test_a_photo_report_stops_producing_images_once_its_budget_is_spent(tmp_path: Path):
    """A report nobody can open is not a report.

    Every diagnostic map is bounded on its own, and a collection is not: two
    hundred photographs make a page of a couple of hundred megabytes, which no
    browser opens. The allowance is spent in file order, so what comes back is
    the first photographs in full rather than all of them at a fidelity nobody
    stated, and the ones left out still carry every fact read from them.
    """
    from filegrail.photo import analyse_photos
    from filegrail.scan import scan

    case = tmp_path / "case"
    case.mkdir()
    for index in range(3):
        photograph(case / f"{index}.jpg")

    records = scan(case, use_shell_history=False, home=tmp_path / "empty")
    collection = analyse_photos(records, case, budget=1)

    assert len(collection.photos) == 3
    assert collection.rendered == 1
    assert [bool(photo.artifacts) for photo in collection.photos] == [True, False, False]
    # Left out of the pictures, not out of the evidence.
    for photo in collection.photos:
        assert photo.facts
        assert photo.camera == "Canon EOS 40D"
    skipped = collection.photos[1]
    assert any(
        method.name == "Pixel diagnostics" and "budget" in method.detail
        for method in skipped.methods
    )


def archive_of_members(path: Path, count: int) -> None:
    """A zip whose members carry evidence, so opening it is work worth bounding."""
    with zipfile.ZipFile(path, "w") as package:
        for index in range(count):
            member = path.parent / f"{path.stem}-{index}.jpg"
            jpeg_with_exif(member, "Canon", "Canon EOS 40D", "2024:01:02 03:04:05")
            package.write(member, f"inside/{index}.jpg")
            member.unlink()


def test_a_scan_stops_opening_carriers_once_its_budget_is_spent(tmp_path: Path):
    """The work of a scan is the number of carriers times the work of each.

    A directory of archives multiplies a bound that only ever applied to one of
    them. When the allowance for carried content is gone the remaining carriers
    are left closed and named, so the reader knows what was not looked inside
    and can come back to it.
    """
    from filegrail.scan import ScanCoverage, scan

    case = tmp_path / "case"
    case.mkdir()
    for name in ("one.zip", "two.zip", "three.zip"):
        archive_of_members(case / name, 2)

    coverage = ScanCoverage()
    records = scan(
        case,
        use_shell_history=False,
        home=tmp_path / "empty",
        coverage=coverage,
        carried_budget=1,
    )

    opened = {record.parent for record in records if record.parent is not None}

    assert len(opened) == 1
    assert len(coverage.beyond_budget) == 2
    # The carriers themselves are still scanned; only their contents are not.
    assert sum(1 for record in records if record.parent is None) == 3


def test_the_scan_allowance_counts_what_was_extracted_not_what_carried_evidence(tmp_path: Path):
    """The allowance bounds decompression, which happens before anything is read.

    A member is extracted, then offered to the readers, then kept only if one of
    them had something to say. Charging for the ones that were kept leaves the
    work of the rest uncounted, so a directory of archives holding nothing this
    tool reads passes an allowance of any size without touching it.
    """
    from filegrail.scan import ScanCoverage, scan

    case = tmp_path / "case"
    case.mkdir()
    for name in ("one.zip", "two.zip", "three.zip"):
        with zipfile.ZipFile(case / name, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("unreadable.bin", b"x" * 4096)

    coverage = ScanCoverage()
    records = scan(
        case,
        use_shell_history=False,
        home=tmp_path / "empty",
        coverage=coverage,
        carried_budget=1,
    )

    # Nothing inside is evidence, so nothing inside becomes a record either way.
    assert not [record for record in records if record.parent is not None]
    assert len(coverage.beyond_budget) == 2
