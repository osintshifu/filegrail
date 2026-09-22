"""The files inside an archive, read as files of their own.

An archive tells the scan what it contains by name and size. The members that
carry evidence - a photograph with its EXIF, a document with its properties -
are read under their own names and reported as files inside the archive: each
with its own record, its own evidence, and the archive as its parent.

What a member says stays the member's. A photograph taken in 2008 inside a zip
made in 2024 does not date the zip, and its GPS fix is not the zip's location,
so nothing a member carries is restated as a property of the container.
"""

from __future__ import annotations

import hashlib
import json
import tarfile
import zipfile
from pathlib import Path

from filegrail.models import METADATA, ORIGIN, category
from filegrail.report import render_json
from filegrail.scan import scan
from filegrail.sources.archives import read_members
from tests.photo import jpeg_with_exif

#: A minimal XMP packet, stored uncompressed inside the archive so that a
#: reader sweeping the container's own bytes would find it there.
PACKET = (
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/">'
    b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    b'<rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/">'
    b"<xmp:CreatorTool>Adobe Photoshop</xmp:CreatorTool>"
    b"</rdf:Description></rdf:RDF></x:xmpmeta>"
)


def _case(tmp_path: Path, name: str = "holiday.jpg") -> Path:
    case = tmp_path / "case"
    case.mkdir()
    photo = tmp_path / "source.jpg"
    jpeg_with_exif(photo, "NIKON", "COOLPIX P6000", "2008:10:22 16:28:39")
    with zipfile.ZipFile(case / "pack.zip", "w") as bundle:
        bundle.write(photo, name)
    return case


def _child(records, member: str):
    return next(record for record in records if record.member == member)


def test_a_photograph_inside_a_zip_is_a_file_of_its_own(tmp_path: Path):
    case = _case(tmp_path, "images/holiday.jpg")

    records = scan(case, use_shell_history=False)
    child = _child(records, "images/holiday.jpg")

    assert child.parent == str(case / "pack.zip")
    assert child.path == str(case / "pack.zip") + "/images/holiday.jpg"
    assert child.size == (tmp_path / "source.jpg").stat().st_size
    exif = next(found for found in child.evidence if found.block == "exif")
    assert exif.fields["Model"] == "COOLPIX P6000"
    assert exif.at == "2008-10-22T16:28:39Z"


def test_the_member_is_inside_the_archive_and_says_so(tmp_path: Path):
    case = _case(tmp_path)

    child = _child(scan(case, use_shell_history=False), "holiday.jpg")
    inside = next(found for found in child.evidence if category(found) == ORIGIN)

    assert inside.source == "archive-member"
    assert inside.container == str(case / "pack.zip")
    assert inside.matched_by == "container-member"
    assert inside.where == {"member": "holiday.jpg"}
    assert "name and exact size" not in (inside.match_note or "")


def test_the_archive_is_not_described_by_what_is_inside_it(tmp_path: Path):
    """A photograph from 2008 in a zip made last week does not date the zip."""
    case = _case(tmp_path)

    records = scan(case, use_shell_history=False)
    archive = next(record for record in records if record.path == str(case / "pack.zip"))

    assert not [found for found in archive.evidence if found.block == "exif"]
    assert not [found for found in archive.evidence if found.at and category(found) == METADATA]


def test_a_member_inherits_the_archives_download(tmp_path: Path):
    from tests.test_archives import _download_record

    case = _case(tmp_path)
    _download_record(tmp_path, str(case / "pack.zip"))

    child = _child(scan(case, home=tmp_path, use_shell_history=False), "holiday.jpg")
    inside = next(found for found in child.evidence if category(found) == ORIGIN)

    assert inside.url == "https://example.org/pack.zip"
    assert inside.where == {"member": "holiday.jpg"}


def test_a_tar_is_read_the_same_way(tmp_path: Path):
    case = tmp_path / "case"
    case.mkdir()
    photo = tmp_path / "source.jpg"
    jpeg_with_exif(photo, "Canon", "Canon EOS 5D", "2026:04:19 21:43:48")
    with tarfile.open(case / "pack.tar", "w") as bundle:
        bundle.add(photo, arcname="holiday.jpg")

    child = _child(scan(case, use_shell_history=False), "holiday.jpg")

    assert (
        next(found for found in child.evidence if found.block == "exif").fields["Model"]
        == "Canon EOS 5D"
    )


def test_members_no_reader_claims_are_not_listed(tmp_path: Path):
    case = tmp_path / "case"
    case.mkdir()
    with zipfile.ZipFile(case / "pack.zip", "w") as bundle:
        bundle.writestr("notes.txt", "nothing here")

    assert [record.path for record in scan(case, use_shell_history=False)] == [
        str(case / "pack.zip")
    ]


def test_something_that_is_not_an_archive(tmp_path: Path):
    plain = tmp_path / "plain.zip"
    plain.write_bytes(b"not a zip")

    assert read_members(plain) == []


def test_a_packet_belonging_to_a_member_is_the_members(tmp_path: Path):
    """The readers that sweep raw bytes for a block - XMP, IPTC - would find
    the member's inside the container. It was never the archive's own claim:
    a zip is not made by Photoshop."""
    case = tmp_path / "case"
    case.mkdir()
    photo = tmp_path / "source.jpg"
    jpeg_with_exif(photo, "NIKON", "COOLPIX P6000", "2008:10:22 16:28:39")
    photo.write_bytes(photo.read_bytes() + PACKET)
    with zipfile.ZipFile(case / "pack.zip", "w") as bundle:
        bundle.write(photo, "holiday.jpg", compress_type=zipfile.ZIP_STORED)

    records = scan(case, use_shell_history=False)
    archive = next(record for record in records if record.parent is None)
    child = _child(records, "holiday.jpg")

    assert not {found.source for found in archive.evidence} & {"xmp", "iptc"}
    assert "xmp" in {found.source for found in child.evidence}


def test_a_member_is_hashed_when_the_scan_hashes(tmp_path: Path):
    case = _case(tmp_path)

    child = _child(scan(case, use_shell_history=False, hash_files=True), "holiday.jpg")

    assert child.sha256 == hashlib.sha256((tmp_path / "source.jpg").read_bytes()).hexdigest()


def test_the_json_names_the_parent_and_the_member(tmp_path: Path):
    case = _case(tmp_path)

    records = scan(case, use_shell_history=False)
    document = json.loads(render_json(records, case))
    by_path = {entry["path"]: entry for entry in document["files"]}
    archive = by_path[str(case / "pack.zip")]
    child = by_path[str(case / "pack.zip") + "/holiday.jpg"]

    assert "parent" not in archive and "member" not in archive
    assert child["parent"] == str(case / "pack.zip")
    assert child["member"] == "holiday.jpg"
    inside = next(found for found in child["evidence"] if found["source"] == "archive-member")
    assert inside["where"] == {"member": "holiday.jpg"}


def test_coverage_counts_the_files_on_disk(tmp_path: Path):
    from filegrail.scan import ScanCoverage

    case = _case(tmp_path)
    coverage = ScanCoverage()

    scan(case, use_shell_history=False, coverage=coverage)

    assert coverage.files_discovered == coverage.files_scanned == 1


def test_a_single_compressed_file_is_read_under_its_own_name(tmp_path: Path):
    """A `.gz` that is not a tar holds one file, named by the archive's own name."""
    import gzip

    case = tmp_path / "case"
    case.mkdir()
    photo = tmp_path / "source.jpg"
    jpeg_with_exif(photo, "NIKON", "COOLPIX P6000", "2008:10:22 16:28:39")
    (case / "holiday.jpg.gz").write_bytes(gzip.compress(photo.read_bytes()))

    child = _child(scan(case, use_shell_history=False), "holiday.jpg")

    assert child.parent == str(case / "holiday.jpg.gz")
    assert child.size == photo.stat().st_size
    exif = next(found for found in child.evidence if found.block == "exif")
    assert exif.fields["Model"] == "COOLPIX P6000"


def test_a_member_keeps_the_vendor_block_of_the_photograph_it_is(tmp_path: Path):
    """A member is read as a file, which means by every reader a file gets.

    The body serial lives in the vendor block rather than in standard Exif, so a
    reader list that stops short of it loses the one field that groups a camera's
    photographs - and loses it only for the ones that arrived inside something.
    """
    from tests.photo import jpeg_with_maker_note
    from tests.test_makernotes import nikon_note

    photo = tmp_path / "nikon.jpg"
    jpeg_with_maker_note(photo, "NIKON CORPORATION", "NIKON D300", nikon_note("3105364", 241575))
    package = tmp_path / "case.zip"
    with zipfile.ZipFile(package, "w") as bundle:
        bundle.write(photo, "nikon.jpg")

    members = read_members(package)

    assert len(members) == 1
    blocks = {found.block for found in members[0].evidence}
    fields = {key: value for found in members[0].evidence for key, value in found.fields.items()}
    assert "maker-notes" in blocks
    assert fields["SerialNumber"] == "3105364"
