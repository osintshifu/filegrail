"""Bounds on the total work of a scan and the total size of a photo report.

Every reader here is already bounded on its own: so many members per archive,
so many bytes per member, so many pixels per diagnostic map. None of that bounds
a run, because the work is the number of carriers times the work of each. These
are the two ceilings that apply to the whole of it.
"""

from __future__ import annotations

from pathlib import Path


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
