"""The Windows Recent folder, which keeps a shortcut per file that was opened.

A `.lnk` there is the counterpart of a `recently-used.xbel` entry and answers
the same question at the same strength: something on that machine handled this
file. Opening a file proves contact, not origin, and this does not pretend
otherwise.

What it adds is where the file was when it was opened. The shortcut records the
volume - its type, its serial number, its label - and a network share by name,
and the machine that created the shortcut. That supports a statement nothing
else here can make: this file was opened from a disk that is not this one.

Spec-only in one direction. Nothing available writes a `.lnk`, so the fixtures
are assembled from [MS-SHLLINK]; the folder walk and the matching around it are
ordinary.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from filegrail.scan import scan
from filegrail.sources.shortcut import RECENT_LINKS, collect_windows_recent, read_link
from tests.shortcut import (
    DRIVE_CDROM,
    DRIVE_FIXED,
    DRIVE_REMOTE,
    DRIVE_REMOVABLE,
    link_info,
    network_link,
    shortcut,
    tracker,
    volume_id,
)

TARGET = r"C:\Users\Alice\Downloads\report.docx"

#: 2026-08-31T10:49:33Z as a POSIX timestamp.
WRITTEN = 1788173373.0


def _local(
    path: str = TARGET,
    drive: int = DRIVE_FIXED,
    serial: int = 0x1A2B3C4D,
    label: str = "Windows",
    **rest,
) -> bytes:
    return shortcut(info=link_info(path, volume=volume_id(drive, serial, label)), **rest)


@pytest.fixture
def recent(tmp_path: Path):
    """Write shortcuts into a Windows Recent folder under a home directory."""
    folder = tmp_path / RECENT_LINKS
    folder.mkdir(parents=True)

    def write(name: str, raw: bytes) -> Path:
        path = folder / name
        path.write_bytes(raw)
        return path

    return write


@pytest.fixture
def carved(tmp_path: Path) -> Path:
    case = tmp_path / "case"
    case.mkdir()
    (case / "report.docx").write_bytes(b"a document")
    return case


# --- reading one shortcut -----------------------------------------------------


def test_a_shortcut_names_the_file_it_points_at():
    found = read_link(_local())

    assert found is not None
    assert found.fields["OpenedFrom"] == TARGET


def test_a_file_that_is_not_a_shortcut_is_left_alone():
    """Everything in Recent is read, and not everything there is a link."""
    assert read_link(b"PK\x03\x04 this is a zip") is None


def test_a_shortcut_with_the_wrong_class_is_refused():
    """The header size matches by coincidence more often than the class does."""
    raw = bytearray(_local())
    raw[4] = 0xFF

    assert read_link(bytes(raw)) is None


def test_a_shortcut_that_is_truncated_is_refused():
    assert read_link(_local()[:40]) is None


# --- which volume it was opened from ------------------------------------------


def test_a_removable_volume_is_named_as_one():
    """The claim nothing else here can make."""
    found = read_link(
        _local(path=r"E:\photos\report.docx", drive=DRIVE_REMOVABLE, label="KINGSTON")
    )

    assert found.fields["Volume"] == "removable"
    assert found.fields["VolumeLabel"] == "KINGSTON"
    assert "removable volume" in found.note


def test_an_optical_volume_is_named_as_one():
    found = read_link(_local(drive=DRIVE_CDROM, label="AUDIT2019"))

    assert found.fields["Volume"] == "optical"


def test_a_fixed_disk_says_so_without_making_a_point_of_it():
    found = read_link(_local())

    assert found.fields["Volume"] == "fixed"
    assert "removable" not in found.note


def test_the_volume_serial_is_kept_as_windows_writes_it():
    """Eight hexadecimal digits, which is how the number is quoted everywhere."""
    found = read_link(_local(serial=0x1A2B3C4D))

    assert found.fields["VolumeSerial"] == "1A2B3C4D"


def test_a_network_share_is_named(carved: Path):
    raw = shortcut(info=link_info("", network=network_link(r"\\fileserver\projects")))

    found = read_link(raw)

    assert found.fields["NetworkShare"] == r"\\fileserver\projects"
    assert "network share" in found.note


def test_the_machine_that_made_the_shortcut_is_named():
    found = read_link(_local(extra=tracker("ALICE-LAPTOP")))

    assert found.fields["MachineID"] == "ALICE-LAPTOP"


def test_a_shortcut_with_no_tracker_block_names_no_machine():
    assert "MachineID" not in read_link(_local()).fields


def test_the_recorded_size_and_time_are_kept_for_checking_against_the_file():
    found = read_link(_local(size=4096, written=WRITTEN))

    assert found.bytes == 4096
    assert found.fields["TargetWritten"] == "2026-08-31T10:49:33Z"


# --- the folder ---------------------------------------------------------------


def test_the_folder_is_indexed_by_the_name_the_shortcut_points_at(recent, tmp_path: Path):
    recent("report.docx.lnk", _local())

    found = collect_windows_recent(tmp_path)

    assert "report.docx" in found


def test_a_target_path_written_by_windows_is_split_by_windows_rules(recent, tmp_path: Path):
    """`PosixPath` would make the whole `C:\\...` string the file name."""
    recent("report.docx.lnk", _local(path=r"D:\Cases\2026\report.docx"))

    assert "report.docx" in collect_windows_recent(tmp_path)


def test_a_folder_that_is_not_there_is_not_an_error(tmp_path: Path):
    assert collect_windows_recent(tmp_path) == {}


def test_anything_in_the_folder_that_is_not_a_link_is_skipped(recent, tmp_path: Path):
    """Two ways of not being one, and the second is the one that needs saying.

    `desktop.ini` would be refused by the header check anyway. A valid shortcut
    saved under some other name would not be, and reading it would count an
    editor's leftover as a record of a file being opened - as well as sending
    the walk into the Jump List files that share the folder.
    """
    recent("desktop.ini", b"[.ShellClassInfo]\n")
    recent("report.docx.lnk.tmp", _local())
    recent("report.docx.lnk", _local())

    found = collect_windows_recent(tmp_path)

    assert list(found) == ["report.docx"]
    assert len(found["report.docx"]) == 1


# --- through a scan -----------------------------------------------------------


def test_a_scan_reports_the_volume_a_file_was_opened_from(recent, carved: Path, tmp_path: Path):
    recent("report.docx.lnk", _local(path=r"E:\report.docx", drive=DRIVE_REMOVABLE, label="USB"))

    record = scan(carved, home=tmp_path, use_shell_history=False)[0]

    claims = [o for o in record.evidence if o.source == "windows-recent"]
    assert len(claims) == 1
    assert claims[0].fields["Volume"] == "removable"


def test_the_claim_is_about_handling_and_not_about_arrival(recent, carved: Path, tmp_path: Path):
    """A shortcut proves the file was opened. It says nothing about how it came."""
    from filegrail.models import ACTIVITY, category

    recent("report.docx.lnk", _local())

    record = scan(carved, home=tmp_path, use_shell_history=False)[0]

    claim = next(o for o in record.evidence if o.source == "windows-recent")
    assert category(claim) == ACTIVITY


def test_a_shortcut_for_a_different_file_is_not_attached(recent, carved: Path, tmp_path: Path):
    recent("other.docx.lnk", _local(path=r"C:\other.docx"))

    record = scan(carved, home=tmp_path, use_shell_history=False)[0]

    assert not [o for o in record.evidence if o.source == "windows-recent"]


def test_a_recorded_size_that_disagrees_is_reported(recent, carved: Path, tmp_path: Path):
    """Same name, different bytes: very likely a different file of that name."""
    recent("report.docx.lnk", _local(size=999_999))

    record = scan(carved, home=tmp_path, use_shell_history=False)[0]

    claim = next(o for o in record.evidence if o.source == "windows-recent")
    assert "differs" in claim.match_note


def test_a_target_id_list_is_stepped_over_rather_than_parsed(recent, tmp_path: Path):
    """It sits between the header and the LinkInfo and is not needed here."""
    ids = struct.pack("<H", 4) + b"\x01\x02" + b"\x00\x00"
    raw = shortcut(
        target_ids=ids,
        info=link_info(TARGET, volume=volume_id(DRIVE_REMOTE, 0, "")),
    )

    assert read_link(raw).fields["OpenedFrom"] == TARGET
