"""Reading the traces of a machine that is not this one.

Every source that answers *how did this arrive* lives under a home directory,
and `scan` and `doctor` have always taken one as an argument. Nothing offered
it on the command line, so the answer was always about the machine doing the
asking - which is the wrong machine whenever the interesting one is a mounted
image, a copied profile or a colleague's laptop.

The profile globs were already written for all three platforms, so a Windows
profile read from Linux needs no porting. What it does need is for the report
to stop saying `this machine` about somebody else's.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from filegrail.cli import main
from filegrail.correlate import correlate
from filegrail.explain import assessment
from filegrail.models import FileRecord
from filegrail.util import basename

CHROMIUM_SCHEMA = """
CREATE TABLE downloads (
  id INTEGER PRIMARY KEY, target_path LONGVARCHAR NOT NULL,
  start_time INTEGER NOT NULL, total_bytes INTEGER NOT NULL,
  state INTEGER NOT NULL, referrer VARCHAR NOT NULL,
  tab_url VARCHAR NOT NULL, mime_type VARCHAR(255) NOT NULL);
CREATE TABLE downloads_url_chains (
  id INTEGER NOT NULL, chain_index INTEGER NOT NULL, url LONGVARCHAR NOT NULL);
"""

# 2026-08-31T10:49:33Z expressed as microseconds since 1601-01-01.
START_TIME = (1788173373 + 11644473600) * 1_000_000

#: What the download record on the other machine says, in that machine's own
#: spelling. Nothing on this side can resolve it as a path, which is the whole
#: reason the name index exists.
RECORDED_PATH = r"C:\Users\Alice\Downloads\evidence.zip"


@pytest.fixture(autouse=True)
def nowhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Make the real home unreadable to the test, so a pass cannot come from it."""
    empty = tmp_path / "not-a-home"
    empty.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: empty))
    return empty


@pytest.fixture
def mounted(tmp_path: Path) -> Path:
    """A Windows user profile as it looks mounted read-only on this machine."""
    home = tmp_path / "mnt" / "case" / "Users" / "Alice"
    profile = home / "AppData" / "Local" / "Google" / "Chrome" / "User Data" / "Default"
    profile.mkdir(parents=True)
    connection = sqlite3.connect(profile / "History")
    connection.executescript(CHROMIUM_SCHEMA)
    connection.execute(
        "INSERT INTO downloads VALUES (1,?,?,?,?,?,?,?)",
        (
            RECORDED_PATH,
            START_TIME,
            5,
            1,
            "https://example.org/page",
            "https://example.org/page",
            "application/zip",
        ),
    )
    connection.execute(
        "INSERT INTO downloads_url_chains VALUES (1,0,'https://cdn.example.org/evidence.zip')"
    )
    connection.commit()
    connection.close()
    return home


@pytest.fixture
def carved(tmp_path: Path) -> Path:
    """The files themselves, copied out of the image into a case directory."""
    case = tmp_path / "case"
    case.mkdir()
    (case / "evidence.zip").write_bytes(b"bytes")
    return case


def _json(capsys, *argv: str) -> dict:
    assert main([*argv, "--json"]) == 0
    return json.loads(capsys.readouterr().out)


# --- reading a path another operating system wrote ----------------------------


def test_a_windows_path_yields_its_file_name():
    """`Path` knows only the separator of the machine reading it.

    Split with `PosixPath`, a Windows download record has no directory at all
    and its whole spelling is the name, so it matches nothing on this side.
    """
    assert basename(r"C:\Users\Alice\Downloads\evidence.zip") == "evidence.zip"


def test_a_unc_path_yields_its_file_name():
    assert basename(r"\\server\share\evidence.zip") == "evidence.zip"


def test_a_posix_path_yields_its_file_name():
    assert basename("/home/alice/evidence.zip") == "evidence.zip"


def test_a_backslash_in_a_posix_name_is_not_a_separator():
    """A backslash is a legal character in a POSIX file name.

    Treating every one as a separator would trade a silent failure on Windows
    records for a silent failure on Linux ones, so it counts only where the
    path announces itself - a drive letter, or a UNC prefix.
    """
    assert basename("/home/alice/a\\b.txt") == "a\\b.txt"


def test_a_scan_reads_the_profile_it_is_given(carved: Path, mounted: Path, capsys):
    """The point of the whole feature, in one test.

    A Windows download record, read from Linux, matched to a file that no
    longer lives at the path the record kept.
    """
    payload = _json(capsys, "scan", str(carved), "--home", str(mounted))

    origins = payload["files"][0]["evidence"]
    assert any(origin["url"] == "https://cdn.example.org/evidence.zip" for origin in origins)


def test_without_the_flag_the_same_scan_finds_nothing(carved: Path, mounted: Path, capsys):
    """Proof that the fixture is not leaking in by some other route."""
    payload = _json(capsys, "scan", str(carved))

    assert payload["files"][0]["evidence"] == []


def test_the_match_basis_says_a_path_was_not_what_matched(carved: Path, mounted: Path, capsys):
    """A record kept under a Windows path cannot match by path here.

    It matched on the name, and the size the record kept agrees - which the
    document says as `name+size` rather than leaving a consumer to read a
    sentence. Under a foreign profile this is the usual case, not the
    exception, so the basis is the field that carries the difference.
    """
    payload = _json(capsys, "scan", str(carved), "--home", str(mounted))

    found = payload["files"][0]["evidence"][0]
    assert found["match"]["method"] == "name+size"
    assert "moved or renamed" in found["match"]["note"]


def test_the_document_records_which_profile_was_read(carved: Path, mounted: Path, capsys):
    payload = _json(capsys, "scan", str(carved), "--home", str(mounted))

    assert payload["home"] == str(mounted)


def test_a_scan_of_this_machine_claims_no_profile(carved: Path, capsys):
    """The key is present only when the evidence came from somewhere else."""
    assert "home" not in _json(capsys, "scan", str(carved))


def test_explain_reads_the_profile_it_is_given(carved: Path, mounted: Path, capsys):
    payload = _json(capsys, "explain", str(carved / "evidence.zip"), "--home", str(mounted))

    assert payload["home"] == str(mounted)
    assert payload["file"]["evidence"]


def test_compare_reads_the_profile_it_is_given(carved: Path, mounted: Path, capsys):
    (carved / "other.zip").write_bytes(b"other")

    payload = _json(
        capsys,
        "compare",
        str(carved / "evidence.zip"),
        str(carved / "other.zip"),
        "--home",
        str(mounted),
    )

    assert payload["home"] == str(mounted)
    assert payload["origin"]


def test_doctor_surveys_the_profile_it_is_given(mounted: Path, capsys):
    payload = _json(capsys, "doctor", "--home", str(mounted))

    assert payload["home"] == str(mounted)
    states = {check["name"]: check["state"] for check in payload["sources"]}
    assert any("Chrom" in name for name in states)


def test_a_home_that_is_not_there_is_refused(carved: Path, capsys):
    """Silence from a mistyped path is the failure `doctor` exists to prevent.

    A run that finds nothing because the profile was never read looks exactly
    like a run that finds nothing because there was nothing to find.
    """
    assert main(["scan", str(carved), "--home", "/nowhere/at/all"]) == 2

    assert "no such" in capsys.readouterr().err


def test_the_explanation_does_not_claim_the_file_reached_this_machine(
    carved: Path, mounted: Path, capsys
):
    """`this machine` is false when the traces came from another one."""
    argv = ["explain", str(carved / "evidence.zip"), "--home", str(mounted), "--no-color"]
    assert main(argv) == 0

    out = capsys.readouterr().out
    assert "reached this machine" not in out
    assert "external" in out


def test_the_scan_report_names_the_profile_it_read(carved: Path, mounted: Path, capsys):
    """On paper a foreign-profile report is indistinguishable from a local one.

    Whoever reads it later has no way to know the claims describe a machine
    that is not the one the file is sitting on, so the report has to say.
    """
    assert main(["scan", str(carved), "--home", str(mounted), "--no-color"]) == 0

    assert "external" in capsys.readouterr().out


def test_the_timeline_names_the_profile_it_read(carved: Path, mounted: Path, capsys):
    """A timeline of another machine's events looks exactly like this one's.

    The announcement is added only when there is a profile, so the ordinary
    line-per-event output is unchanged for anything already parsing it.
    """
    assert main(["scan", str(carved), "--home", str(mounted), "--timeline", "--no-color"]) == 0

    assert "external" in capsys.readouterr().out


def test_a_timeline_of_this_machine_stays_one_line_per_event(carved: Path, capsys):
    assert main(["scan", str(carved), "--timeline", "--no-color"]) == 0

    assert "reached this machine" not in capsys.readouterr().out


def test_a_scan_of_this_machine_announces_no_profile(carved: Path, capsys):
    """The word `profile` appears in the source notes; the announcement must not."""
    assert main(["scan", str(carved), "--no-color"]) == 0

    assert "reached this machine" not in capsys.readouterr().out


def test_the_explanation_still_says_this_machine_when_it_is_this_machine(carved: Path, capsys):
    assert main(["explain", str(carved / "evidence.zip"), "--no-color"]) == 0

    assert "target" in capsys.readouterr().out


def test_an_empty_profile_points_the_reader_at_the_right_doctor(carved: Path, tmp_path: Path):
    """Telling a reader to run `doctor` on the wrong machine wastes their time.

    Asserted on the sentence rather than the rendering: a long mount path wraps
    across lines in the report, and what matters here is the advice, not where
    the terminal broke it.
    """
    bare = tmp_path / "bare"
    bare.mkdir()
    record = FileRecord(path=str(carved / "evidence.zip"), size=5, mtime="2026-08-24T19:00:00Z")

    said = assessment(record, correlate(record), bare)

    assert f"filegrail doctor --home {bare}" in said[0]


def test_the_same_advice_on_this_machine_names_no_profile(carved: Path):
    record = FileRecord(path=str(carved / "evidence.zip"), size=5, mtime="2026-08-24T19:00:00Z")

    said = assessment(record, correlate(record))

    assert "`filegrail doctor`" in said[0]
    assert "--home" not in said[0]


def test_the_explanation_names_the_profile_it_read(carved: Path, mounted: Path, capsys):
    """Same reason as the scan report: on paper it looks like a local finding."""
    argv = ["explain", str(carved / "evidence.zip"), "--home", str(mounted), "--no-color"]
    assert main(argv) == 0

    assert "external" in capsys.readouterr().out


def test_the_survey_names_the_profile_it_read(mounted: Path, capsys):
    assert main(["doctor", "--home", str(mounted), "--no-color"]) == 0

    assert "external" in capsys.readouterr().out


def test_a_survey_of_this_machine_announces_no_profile(capsys):
    assert main(["doctor", "--no-color"]) == 0

    assert "reached this machine" not in capsys.readouterr().out
