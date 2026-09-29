"""What macOS wrote down when something downloaded the file.

LaunchServices records a download twice. It tags the file itself with
`com.apple.quarantine`, which names the application, the moment and an event
identifier; and it writes a row into a database under the user's home holding
what that identifier means - the URL the bytes came from and the page that
linked to it.

They are two halves of one record rather than two witnesses, so they are
reported as one claim. Counting them as corroboration would be counting a
single subsystem twice.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from filegrail.scan import scan
from filegrail.sources.quarantine import (
    QUARANTINE_DB,
    collect_quarantine_events,
    read_quarantine,
)
from tests.xattrs import supported, write

#: The attribute is `com.apple.quarantine` on macOS itself. Nothing outside the
#: `user.` namespace can be written on Linux, so a copy carries it there - and
#: both are tried, so a macOS runner exercises the native spelling and a Linux
#: one exercises the spelling a copy arrives under.
ATTRIBUTES = ("com.apple.quarantine", "user.com.apple.quarantine")

EVENT = "1A2B3C4D-5E6F-4071-8293-A4B5C6D7E8F9"

#: Hexadecimal seconds since 1970, which is the attribute's epoch and not the
#: database's: 0x68b4bd35 is 2025-08-31T21:23:01Z.
STAMP = "68b4bd35"


def _tag(path: Path, value: str) -> None:
    """Write the attribute under whichever name this platform will take."""
    if not supported():  # pragma: no cover - depends on the platform
        pytest.skip("no interface for extended attributes on this platform")
    for name in ATTRIBUTES:
        if write(path, name, value.encode("ascii")):
            return
    pytest.skip("this filesystem refuses extended attributes")  # pragma: no cover


def _database(home: Path, rows: list[tuple]) -> None:
    path = home / QUARANTINE_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE LSQuarantineEvent (
          LSQuarantineEventIdentifier TEXT PRIMARY KEY,
          LSQuarantineTimeStamp REAL,
          LSQuarantineAgentBundleIdentifier TEXT,
          LSQuarantineAgentName TEXT,
          LSQuarantineDataURLString TEXT,
          LSQuarantineSenderName TEXT,
          LSQuarantineSenderAddress TEXT,
          LSQuarantineTypeNumber INTEGER,
          LSQuarantineOriginTitle TEXT,
          LSQuarantineOriginURLString TEXT,
          LSQuarantineOriginAlias BLOB);
    """)
    connection.executemany(
        "INSERT INTO LSQuarantineEvent VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    connection.commit()
    connection.close()


def _row(identifier: str = EVENT, url: str = "https://cdn.example.org/evidence.zip") -> tuple:
    # 809_871_200.0 seconds after 2001-01-01 is 2026-08-31T12:13:20Z; the same
    # number read as seconds after 1970 would be 1995, which is the point.
    return (
        identifier,
        809_871_200.0,
        "com.apple.Safari",
        "Safari",
        url,
        None,
        None,
        0,
        "Example downloads",
        "https://example.org/downloads",
        None,
    )


@pytest.fixture
def carved(tmp_path: Path) -> Path:
    case = tmp_path / "case"
    case.mkdir()
    (case / "evidence.zip").write_bytes(b"bytes")
    return case


# --- the attribute on the file ------------------------------------------------


def test_the_attribute_alone_names_who_and_when(carved: Path, tmp_path: Path):
    """No database, so no URL - but the agent and the moment are still a record."""
    _tag(carved / "evidence.zip", f"0083;{STAMP};Safari;{EVENT}")

    found = read_quarantine(carved / "evidence.zip", collect_quarantine_events(tmp_path))

    assert len(found) == 1
    assert found[0].source == "macos-quarantine"
    assert found[0].tool == "Safari"
    assert found[0].at == "2025-08-31T21:23:01Z"
    assert found[0].url is None


def test_a_file_with_no_attribute_says_nothing(carved: Path, tmp_path: Path):
    assert read_quarantine(carved / "evidence.zip", collect_quarantine_events(tmp_path)) == []


def test_an_attribute_that_is_not_four_fields_is_refused(carved: Path, tmp_path: Path):
    """Half a record read as a whole one would put a flag word where a name goes."""
    _tag(carved / "evidence.zip", "0083;Safari")

    assert read_quarantine(carved / "evidence.zip", collect_quarantine_events(tmp_path)) == []


def test_an_unreadable_timestamp_loses_the_time_and_keeps_the_rest(carved: Path, tmp_path: Path):
    _tag(carved / "evidence.zip", f"0083;notahexnumber;Safari;{EVENT}")

    found = read_quarantine(carved / "evidence.zip", collect_quarantine_events(tmp_path))

    assert found[0].tool == "Safari"
    assert found[0].at is None


# --- the database under the home ---------------------------------------------


def test_the_identifier_resolves_to_the_url_it_stands_for(carved: Path, tmp_path: Path):
    _database(tmp_path, [_row()])
    _tag(carved / "evidence.zip", f"0083;{STAMP};Safari;{EVENT}")

    found = read_quarantine(carved / "evidence.zip", collect_quarantine_events(tmp_path))

    assert len(found) == 1, "one record read from two places, not two records"
    assert found[0].url == "https://cdn.example.org/evidence.zip"
    assert found[0].referrer == "https://example.org/downloads"


def test_the_database_keeps_its_own_epoch(carved: Path, tmp_path: Path):
    """The attribute counts from 1970 and the database counts from 2001.

    Reading either with the other's epoch puts the download decades away, which
    is the category of error a timeline would then be built on.
    """
    _database(tmp_path, [_row()])

    events = collect_quarantine_events(tmp_path)

    assert events.by_uuid[EVENT].at == "2026-08-31T12:13:20Z"


def test_an_identifier_the_database_does_not_know_still_reports_the_file(
    carved: Path, tmp_path: Path
):
    _database(tmp_path, [_row(identifier="99999999-0000-0000-0000-000000000000")])
    _tag(carved / "evidence.zip", f"0083;{STAMP};Safari;{EVENT}")

    found = read_quarantine(carved / "evidence.zip", collect_quarantine_events(tmp_path))

    assert found[0].tool == "Safari"
    assert found[0].url is None


def test_a_download_is_matched_by_name_where_the_attribute_did_not_survive(
    carved: Path, tmp_path: Path
):
    """A copied profile keeps the database; a copied file rarely keeps its xattr.

    Without the attribute there is no identifier to join on, so the file name
    against the last segment of the recorded URL is all that is left - the same
    fallback a browser download already gets, and marked the same way.
    """
    _database(tmp_path, [_row()])

    found = read_quarantine(carved / "evidence.zip", collect_quarantine_events(tmp_path))

    assert found[0].url == "https://cdn.example.org/evidence.zip"
    assert found[0].matched_by == "filename"


def test_a_name_that_matches_nothing_in_the_database_is_left_alone(carved: Path, tmp_path: Path):
    _database(tmp_path, [_row(url="https://cdn.example.org/something-else.zip")])

    assert read_quarantine(carved / "evidence.zip", collect_quarantine_events(tmp_path)) == []


def test_a_database_that_is_not_there_is_not_an_error(tmp_path: Path):
    assert collect_quarantine_events(tmp_path).by_uuid == {}


def test_a_database_that_is_not_a_database_is_not_an_error(tmp_path: Path):
    path = tmp_path / QUARANTINE_DB
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not sqlite at all")

    assert collect_quarantine_events(tmp_path).by_uuid == {}


# --- through a scan -----------------------------------------------------------


def test_a_scan_reaches_the_quarantine_record(carved: Path, tmp_path: Path):
    _database(tmp_path, [_row()])
    _tag(carved / "evidence.zip", f"0083;{STAMP};Safari;{EVENT}")

    record = scan(carved, home=tmp_path, use_shell_history=False)[0]

    claims = [origin for origin in record.evidence if origin.source == "macos-quarantine"]
    assert len(claims) == 1
    assert claims[0].url == "https://cdn.example.org/evidence.zip"


def test_the_name_match_says_what_it_was_matched_against(carved: Path, tmp_path: Path):
    """The browser's wording claims something this source never recorded.

    A download record keeps the path the file was saved to, so a name match
    there really does mean it was moved or renamed. The quarantine database
    keeps the URL and no path at all, and saying otherwise would describe a
    disagreement between two things where only one of them exists.
    """
    _database(tmp_path, [_row()])

    found = read_quarantine(carved / "evidence.zip", collect_quarantine_events(tmp_path))

    assert found[0].match_note == ("the database recorded the URL and no path to match instead")


def test_the_attribute_is_a_file_attribute_and_not_a_name_match(carved: Path, tmp_path: Path):
    """The attribute sits on this file. Only the fallback by name is weak."""
    _tag(carved / "evidence.zip", f"0083;{STAMP};Safari;{EVENT}")

    found = read_quarantine(carved / "evidence.zip", collect_quarantine_events(tmp_path))

    assert found[0].matched_by == "file-attribute"
