"""The desktop's recently-used list: activity, not origin."""

from __future__ import annotations

from pathlib import Path

from filegrail.models import ACTIVITY, SOURCE_PRIORITY, EvidenceRecord, category
from filegrail.sources.recent import collect_recent_files

XBEL = """<?xml version="1.0" encoding="UTF-8"?>
<xbel version="1.0"
      xmlns:bookmark="http://www.freedesktop.org/standards/desktop-bookmarks">
  <bookmark href="file:///case/a%20photo.jpg" added="2026-08-24T19:02:11Z">
    <info><metadata owner="http://freedesktop.org">
      <bookmark:applications>
        <bookmark:application name="GIMP" exec="gimp %u" count="2"/>
        <bookmark:application name="Eye of GNOME" exec="eog %u" count="1"/>
      </bookmark:applications>
    </metadata></info>
  </bookmark>
  <bookmark href="https://example.org/not-a-file" added="2026-08-24T19:02:11Z"/>
</xbel>
"""


def _home(tmp_path: Path, body: str = XBEL) -> Path:
    target = tmp_path / ".local" / "share"
    target.mkdir(parents=True)
    (target / "recently-used.xbel").write_text(body, encoding="utf-8")
    return tmp_path


def test_a_bookmark_names_the_application_that_opened_it(tmp_path: Path):
    found = collect_recent_files(home=_home(tmp_path))

    origin = found["/case/a photo.jpg"][0]
    assert origin.tool == "GIMP"
    assert "GIMP" in origin.note
    assert "Eye of GNOME" in origin.note


def test_the_percent_escapes_in_the_path_are_decoded(tmp_path: Path):
    found = collect_recent_files(home=_home(tmp_path))

    assert "/case/a photo.jpg" in found


def test_a_bookmark_that_is_not_a_file_is_ignored(tmp_path: Path):
    found = collect_recent_files(home=_home(tmp_path))

    assert len(found) == 1


def test_a_missing_list_is_not_an_error(tmp_path: Path):
    assert collect_recent_files(home=tmp_path) == {}


def test_a_corrupt_list_is_not_an_error(tmp_path: Path):
    assert collect_recent_files(home=_home(tmp_path, "<xbel>truncated")) == {}


def test_it_ranks_below_shell_history():
    """Opening a file proves contact, not origin."""
    assert SOURCE_PRIORITY["recent-documents"] < SOURCE_PRIORITY["shell-history"]


def test_it_is_activity_and_not_origin():
    """An application opening a file did not put it there, and a report that
    files it under origin says it did."""
    assert category(EvidenceRecord(source="recent-documents", tool="GIMP")) == ACTIVITY


def test_a_time_with_an_offset_keeps_its_offset(tmp_path: Path):
    """`+02:00` is a zone. Stamping a Z onto it turns 21:02 local into a moment
    two hours later than the one recorded."""
    body = XBEL.replace('added="2026-08-24T19:02:11Z"', 'added="2026-08-24T21:02:11+02:00"', 1)

    found = collect_recent_files(home=_home(tmp_path, body))

    assert found["/case/a photo.jpg"][0].at == "2026-08-24T21:02:11+02:00"
