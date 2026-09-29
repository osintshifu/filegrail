"""Narrowing a scan to the file types you actually care about.

A case directory is rarely homogeneous. An analyst chasing camera provenance
does not want forty spreadsheets in the way, and reading their metadata is work
the scan did not need to do.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from filegrail.cli import main
from filegrail.filters import FAMILIES, UnknownType, selection
from filegrail.sources.embedded import SUFFIXES as READABLE

MIXED = ("holiday.jpg", "figure.PNG", "report.pdf", "notes.md", "clip.mp4", "book.epub")


def _folder(root: Path) -> Path:
    for name in MIXED:
        (root / name).write_text("x", encoding="utf-8")
    return root


# --- resolving what was asked for -------------------------------------------


def test_no_filter_selects_everything():
    assert selection([], []) is None


def test_an_extension_is_matched_with_or_without_its_dot():
    assert selection([], ["jpg"]) == selection([], [".jpg"]) == {".jpg"}


def test_extensions_are_lowercased():
    assert selection([], ["JPG", ".PnG"]) == {".jpg", ".png"}


def test_a_comma_separated_list_is_split():
    assert selection([], ["jpg,pdf"]) == {".jpg", ".pdf"}


def test_a_family_expands_to_its_extensions():
    chosen = selection(["image"], [])

    assert ".jpg" in chosen
    assert ".png" in chosen
    assert ".heic" in chosen
    assert ".pdf" not in chosen


def test_families_and_extensions_combine():
    chosen = selection(["image"], ["pdf"])

    assert ".jpg" in chosen
    assert ".pdf" in chosen


def test_every_family_is_non_empty():
    """A family that resolves to nothing would silently scan no files."""
    for name, suffixes in FAMILIES.items():
        assert suffixes, name


def test_every_readable_format_can_be_asked_for():
    """A family that cannot name a format this tool can read would exclude the
    very files a narrowed scan was meant to find - and say nothing about it."""
    selectable = set().union(*FAMILIES.values())

    assert READABLE <= selectable, sorted(READABLE - selectable)


def test_an_unknown_family_says_what_is_available():
    with pytest.raises(UnknownType) as raised:
        selection(["pictures"], [])

    message = str(raised.value)
    assert "pictures" in message
    for name in FAMILIES:
        assert name in message


# --- through the command line ------------------------------------------------


def test_filtering_by_extension_scans_only_those(tmp_path: Path, capsys):
    _folder(tmp_path)

    main([str(tmp_path), "--ext", "jpg", "--no-color", "--limit", "0"])

    out = capsys.readouterr().out
    assert "holiday.jpg" in out
    assert "report.pdf" not in out
    assert "FILE" in out


def test_the_match_ignores_case(tmp_path: Path, capsys):
    """A camera writing .JPG and a phone writing .jpg are the same request."""
    _folder(tmp_path)

    main([str(tmp_path), "--ext", "png", "--no-color", "--limit", "0"])

    assert "figure.PNG" in capsys.readouterr().out


def test_filtering_by_family(tmp_path: Path, capsys):
    _folder(tmp_path)

    main([str(tmp_path), "--type", "image", "--no-color", "--limit", "0"])

    out = capsys.readouterr().out
    assert "holiday.jpg" in out
    assert "figure.PNG" in out
    assert "clip.mp4" not in out
    assert "report.pdf" not in out


def test_types_can_be_repeated(tmp_path: Path, capsys):
    _folder(tmp_path)

    main([str(tmp_path), "--type", "image", "--type", "video", "--no-color", "--limit", "0"])

    out = capsys.readouterr().out
    assert "holiday.jpg" in out
    assert "clip.mp4" in out
    assert "report.pdf" not in out


def test_an_unknown_type_is_refused_before_scanning(tmp_path: Path, capsys):
    _folder(tmp_path)

    assert main(["scan", str(tmp_path), "--type", "pictures"]) == 2

    assert "pictures" in capsys.readouterr().err


def test_a_filter_that_matches_nothing_explains_itself(tmp_path: Path, capsys):
    """An empty report has to say it was the filter, not the folder."""
    _folder(tmp_path)

    main([str(tmp_path), "--ext", "xyz", "--no-color"])

    out = capsys.readouterr().out
    assert "No file matched" in out
    assert "xyz" in out
