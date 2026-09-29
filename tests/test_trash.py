"""The freedesktop trash: where a file was before somebody threw it away.

Nothing else on a Linux desktop writes down where a file used to be, and the
record sits beside the file rather than being matched to it - which is what
makes this stronger than the other sources of its category and worth reading.
"""

from __future__ import annotations

from pathlib import Path

from filegrail.doctor import survey
from filegrail.models import ACTIVITY, category, label
from filegrail.sources.trash import collect_trash, read_trash


def _trash(root: Path, name: str, *, path: str, deleted: str = "2026-08-14T09:41:07") -> Path:
    """A file in a trash, with the record the trash writes beside it."""
    (root / "files").mkdir(parents=True, exist_ok=True)
    (root / "info").mkdir(parents=True, exist_ok=True)
    thrown = root / "files" / name
    thrown.write_bytes(b"the deleted bytes")
    (root / "info" / f"{name}.trashinfo").write_text(
        f"[Trash Info]\nPath={path}\nDeletionDate={deleted}\n", encoding="utf-8"
    )
    return thrown


# --- the record beside the file -----------------------------------------------


def test_a_deleted_file_says_where_it_was_deleted_from(tmp_path: Path):
    thrown = _trash(tmp_path / "Trash", "report.pdf", path="/home/ann/Documents/report.pdf")

    origin = read_trash(thrown)

    assert origin is not None
    assert origin.source == "freedesktop-trash"
    assert origin.note == "deleted from /home/ann/Documents/report.pdf"
    assert origin.fields["Path"] == "/home/ann/Documents/report.pdf"


def test_the_moment_is_read_as_utc_and_kept_as_it_was_written(tmp_path: Path):
    """The format writes the deleting machine's local time and records no
    offset, so the string stays in the record for anybody who knows better."""
    thrown = _trash(
        tmp_path / "Trash",
        "report.pdf",
        path="/home/ann/report.pdf",
        deleted="2026-08-14T09:41:07",
    )

    origin = read_trash(thrown)

    assert origin.at == "2026-08-14T09:41:07Z"
    assert origin.fields["DeletionDate"] == "2026-08-14T09:41:07"


def test_the_path_is_percent_decoded(tmp_path: Path):
    """The specification stores it as it would appear in a URI."""
    thrown = _trash(
        tmp_path / "Trash", "note.txt", path="/home/ann/My%20Documents/a%2Bb%20%C5%9B.txt"
    )

    assert read_trash(thrown).fields["Path"] == "/home/ann/My Documents/a+b ś.txt"


def test_a_deletion_date_nothing_can_read_still_leaves_the_path(tmp_path: Path):
    thrown = _trash(tmp_path / "Trash", "report.pdf", path="/home/ann/report.pdf", deleted="soon")

    origin = read_trash(thrown)

    assert origin.at is None
    assert origin.note == "deleted from /home/ann/report.pdf"


def test_a_repeated_key_is_read_once(tmp_path: Path):
    """The specification says the first value is the one that counts."""
    root = tmp_path / "Trash"
    thrown = _trash(root, "report.pdf", path="/home/ann/first.pdf")
    (root / "info" / "report.pdf.trashinfo").write_text(
        "[Trash Info]\nPath=/home/ann/first.pdf\nPath=/home/ann/second.pdf\n"
        "DeletionDate=2026-08-14T09:41:07\n",
        encoding="utf-8",
    )

    assert read_trash(thrown).fields["Path"] == "/home/ann/first.pdf"


# --- what is not a trash ------------------------------------------------------


def test_a_file_with_no_record_says_nothing(tmp_path: Path):
    root = tmp_path / "Trash"
    thrown = _trash(root, "report.pdf", path="/home/ann/report.pdf")
    (root / "info" / "report.pdf.trashinfo").unlink()

    assert read_trash(thrown) is None


def test_a_directory_that_merely_looks_like_a_trash_is_not_one(tmp_path: Path):
    """The pairing has to be the trash's own. `files` is what says it is."""
    root = tmp_path / "Trash"
    _trash(root, "report.pdf", path="/home/ann/report.pdf")
    (root / "documents").mkdir()
    elsewhere = root / "documents" / "report.pdf"
    elsewhere.write_bytes(b"a different file entirely")

    assert read_trash(elsewhere) is None


def test_a_record_without_the_header_is_not_a_record(tmp_path: Path):
    root = tmp_path / "Trash"
    thrown = _trash(root, "report.pdf", path="/home/ann/report.pdf")
    (root / "info" / "report.pdf.trashinfo").write_text(
        "Path=/home/ann/report.pdf\nDeletionDate=2026-08-14T09:41:07\n", encoding="utf-8"
    )

    assert read_trash(thrown) is None


def test_the_record_is_read_with_a_bound(tmp_path: Path):
    """A directory a scan was pointed at can hold anything at all."""
    from filegrail.sources.trash import _MAX_RECORD_BYTES

    root = tmp_path / "Trash"
    thrown = _trash(root, "report.pdf", path="/home/ann/report.pdf")
    (root / "info" / "report.pdf.trashinfo").write_text(
        "[Trash Info]\n" + "#\n" * _MAX_RECORD_BYTES + "Path=/home/ann/report.pdf\n",
        encoding="utf-8",
    )

    assert read_trash(thrown) is None


# --- a trash on another volume ------------------------------------------------


def test_a_relative_path_resolves_against_the_volume_the_trash_is_on(tmp_path: Path):
    """A file deleted from a mounted disk goes to a trash on that disk, and its
    record names the path relative to the top of it."""
    volume = tmp_path / "media" / "ann" / "archive"
    thrown = _trash(volume / ".Trash-1000", "report.pdf", path="Cases/2026/report.pdf")

    assert read_trash(thrown).fields["Path"] == str(volume / "Cases/2026/report.pdf")


def test_the_administrator_created_trash_puts_the_user_one_level_down(tmp_path: Path):
    volume = tmp_path / "media" / "ann" / "archive"
    thrown = _trash(volume / ".Trash" / "1000", "report.pdf", path="Cases/report.pdf")

    assert read_trash(thrown).fields["Path"] == str(volume / "Cases/report.pdf")


def test_a_relative_path_in_a_trash_that_names_no_volume_is_left_alone(tmp_path: Path):
    """Joining it to the wrong root would turn a real path into a wrong one."""
    thrown = _trash(tmp_path / "Trash", "report.pdf", path="Documents/report.pdf")

    assert read_trash(thrown).fields["Path"] == "Documents/report.pdf"


# --- what a scan and a survey do with it --------------------------------------


def test_a_trash_record_is_activity_and_is_registered_as_a_source(tmp_path: Path):
    """It proves this machine held the file and removed it. Nothing more.

    `category` raises for a source nobody registered, so the presentation rank
    is what says this one was actually written into the tables rather than
    falling through them.
    """
    thrown = _trash(tmp_path / "Trash", "report.pdf", path="/home/ann/report.pdf")
    origin = read_trash(thrown)

    assert category(origin) == ACTIVITY
    assert origin.priority == 45
    assert label(origin) == "trash record"


def test_a_scan_of_a_trash_reports_where_its_files_were(tmp_path: Path):
    from filegrail.scan import scan

    root = tmp_path / "Trash"
    _trash(root, "report.pdf", path="/home/ann/Documents/report.pdf")

    records = scan(root / "files", use_shell_history=False, home=tmp_path)

    assert [origin.note for record in records for origin in record.evidence] == [
        "deleted from /home/ann/Documents/report.pdf"
    ]


def test_the_home_trash_can_be_surveyed(tmp_path: Path):
    home = tmp_path / "home"
    _trash(home / ".local" / "share" / "Trash", "report.pdf", path="/home/ann/report.pdf")
    _trash(home / ".local" / "share" / "Trash", "notes.txt", path="/home/ann/notes.txt")

    found = collect_trash(home)

    assert sorted(origin.fields["Path"] for origin in found) == [
        "/home/ann/notes.txt",
        "/home/ann/report.pdf",
    ]


def test_a_home_with_no_trash_surveys_to_nothing(tmp_path: Path):
    assert collect_trash(tmp_path) == []


def test_the_doctor_says_what_the_trash_holds(tmp_path: Path):
    home = tmp_path / "home"
    _trash(home / ".local" / "share" / "Trash", "report.pdf", path="/home/ann/report.pdf")

    checks = {check.name: check for check in survey(home).checks}

    assert "Deleted files" in checks
    assert "1 file" in checks["Deleted files"].detail


def test_the_doctor_says_so_when_there_is_no_trash(tmp_path: Path):
    checks = {check.name: check for check in survey(tmp_path).checks}

    assert checks["Deleted files"].detail == "no trash directory"


def test_the_doctor_does_not_guess_why_a_trash_is_empty(tmp_path: Path):
    """An emptied trash and one whose records nothing can read give a survey
    the same answer, and it cannot tell them apart without claiming to know."""
    home = tmp_path / "home"
    (home / ".local" / "share" / "Trash" / "info").mkdir(parents=True)

    checks = {check.name: check for check in survey(home).checks}

    assert checks["Deleted files"].detail == "the trash holds no readable record"
