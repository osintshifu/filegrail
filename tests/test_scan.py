import os
import sqlite3
import struct
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from filegrail.scan import ScanCoverage, Unsearched, iter_files, scan
from filegrail.sources.fsattrs import read_file_attributes

from .test_browser import CHROMIUM_SCHEMA, START_TIME


def _profile_with(home: Path, target: str) -> None:
    profile = home / ".config" / "chromium" / "Default"
    profile.mkdir(parents=True)
    connection = sqlite3.connect(profile / "History")
    connection.executescript(CHROMIUM_SCHEMA)
    connection.execute(
        "INSERT INTO downloads VALUES (1,?,?,11,1,'','https://example.org/p','text/plain')",
        (target, START_TIME),
    )
    connection.commit()
    connection.close()


def test_exact_path_match_has_no_moved_note(tmp_path: Path):
    case = tmp_path / "case"
    case.mkdir()
    evidence = case / "evidence.txt"
    evidence.write_text("hello world", encoding="utf-8")
    _profile_with(tmp_path, str(evidence))

    record = scan(case, home=tmp_path, use_shell_history=False)[0]

    assert record.primary is not None
    assert record.primary.source == "browser-download"
    assert record.primary.note is None


def test_moved_file_is_matched_by_name_and_flagged(tmp_path: Path):
    case = tmp_path / "case"
    case.mkdir()
    (case / "evidence.txt").write_text("hello world", encoding="utf-8")
    _profile_with(tmp_path, "/somewhere/else/evidence.txt")

    record = scan(case, home=tmp_path, use_shell_history=False)[0]

    assert record.primary is not None
    assert "moved or renamed" in (record.primary.match_note or "")


def test_file_without_any_origin(tmp_path: Path):
    case = tmp_path / "case"
    case.mkdir()
    (case / "local.txt").write_text("made here", encoding="utf-8")

    record = scan(case, home=tmp_path, use_shell_history=False)[0]

    assert record.evidence == []
    assert record.primary is None
    assert record.size == 9


def test_hashing_is_opt_in(tmp_path: Path):
    case = tmp_path / "case"
    case.mkdir()
    # Bytes, not text: `write_text` translates the newline to CRLF on Windows,
    # and a file this test hashes has to be the same file on every platform.
    (case / "a.txt").write_bytes(b"hello repro\n")

    assert scan(case, home=tmp_path, use_shell_history=False)[0].sha256 is None
    hashed = scan(case, home=tmp_path, use_shell_history=False, hash_files=True)[0]
    assert hashed.sha256 == "4e17aeaa904104862a741775bf05b6cb883716b07589e088c94d46d192ef4614"


def test_coverage_records_what_the_scan_actually_read(tmp_path: Path):
    case = tmp_path / "case"
    case.mkdir()
    evidence = case / "evidence.txt"
    evidence.write_text("hello world", encoding="utf-8")
    _profile_with(tmp_path, str(evidence))
    coverage = ScanCoverage()

    scan(
        case,
        home=tmp_path,
        use_shell_history=False,
        follow_archives=False,
        coverage=coverage,
    )

    document = coverage.to_dict()
    assert document["files"] == {"discovered": 1, "scanned": 1}
    assert document["sources"]["browser-download"] == {
        "state": "searched",
        "records": 1,
        "artifacts_found": 1,
        "artifacts_read": 1,
    }
    assert document["sources"]["shell-history"]["state"] == "disabled"
    assert document["sources"]["archives"]["state"] == "disabled"
    assert document["unsearched"] == {
        "unreadable": [],
        "skipped_by_name": [],
        "beyond_budget": [],
    }


def test_noise_directories_are_skipped(tmp_path: Path):
    case = tmp_path / "case"
    (case / ".git").mkdir(parents=True)
    (case / "__pycache__").mkdir()
    (case / ".git" / "config").write_text("x", encoding="utf-8")
    (case / "__pycache__" / "m.pyc").write_bytes(b"x")
    (case / "real.txt").write_text("x", encoding="utf-8")

    records = scan(case, home=tmp_path, use_shell_history=False)

    assert [Path(record.path).name for record in records] == ["real.txt"]


def test_xdg_xattr_is_read_when_supported(tmp_path: Path):
    import os

    target = tmp_path / "downloaded.bin"
    target.write_bytes(b"x")
    try:
        os.setxattr(str(target), "user.xdg.origin.url", b"https://example.org/downloaded.bin")
    except (AttributeError, OSError):
        return  # platform or filesystem does not support user xattrs

    origins = read_file_attributes(target)

    assert any(o.source == "xdg-xattr" for o in origins)
    assert origins[0].url == "https://example.org/downloaded.bin"


class _ContraryOrder:
    """What `os.scandir` hands back, in the one order it never promises."""

    def __init__(self, entries):
        self._entries = iter(entries)

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._entries)

    def close(self) -> None:
        return None


def test_directories_are_visited_in_name_order_whatever_the_disk_says(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Two scans of one tree must tell the same story in the same order.

    The filesystem hands directories back in whatever order suits it, and
    that order is what a report printed on another machine would differ by.
    File names are already sorted; the directories they sit in have to be.
    """
    case = tmp_path / "case"
    for name in ("beta", "alpha", "gamma"):
        (case / name).mkdir(parents=True)
        (case / name / "note.txt").write_text("x", encoding="utf-8")

    real = os.scandir

    def contrary(path):
        with real(path) as entries:
            return _ContraryOrder(sorted(entries, key=lambda entry: entry.name, reverse=True))

    monkeypatch.setattr(os, "scandir", contrary)

    visited = [Path(found).parent.name for found in iter_files(case)]

    assert visited == ["alpha", "beta", "gamma"]


def test_a_scan_links_a_file_to_the_one_it_was_made_from(tmp_path: Path):
    """The identifiers are per file and the relation is not. Working it out
    needs the whole scan, which is why it happens beside the pass that gives an
    extracted file the origin of the archive it came out of."""

    def photograph(name: str, properties: str) -> None:
        packet = (
            '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
            '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            '<rdf:Description rdf:about=""'
            ' xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/"'
            ' xmlns:stRef="http://ns.adobe.com/xap/1.0/sType/ResourceRef#">'
            f"{properties}"
            "</rdf:Description></rdf:RDF></x:xmpmeta>"
        )
        payload = b"http://ns.adobe.com/xap/1.0/\x00" + packet.encode("utf-8")
        (tmp_path / name).write_bytes(
            b"\xff\xd8\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload + b"\xff\xd9"
        )

    photograph("master.jpg", "<xmpMM:DocumentID>xmp.did:1111AAAA</xmpMM:DocumentID>")
    photograph(
        "export.jpg",
        "<xmpMM:DocumentID>xmp.did:2222BBBB</xmpMM:DocumentID>"
        '<xmpMM:DerivedFrom stRef:documentID="xmp.did:1111AAAA"/>',
    )

    records = {Path(r.path).name: r for r in scan(tmp_path, use_shell_history=False)}

    assert [link.others for link in records["export.jpg"].links] == [
        (str(tmp_path / "master.jpg"),)
    ]


# --- what the walk did not look inside ---------------------------------------
#
# `no evidence found` is a claim about a file the tool looked at. A directory it never
# entered produces no files at all, so nothing in the report is about them and
# nothing in the report says so. The two reasons a directory goes unvisited are
# different in category and are kept apart: one is a choice the tool made and can be
# told not to make, the other is a hole in the evidence.


@contextmanager
def unreadable(path: Path) -> Iterator[None]:
    """Make a directory impossible to walk into, or skip where that cannot be done."""
    path.chmod(0o000)
    if os.access(path, os.R_OK):
        path.chmod(0o755)
        pytest.skip("this user or platform can read a directory with no permissions")
    try:
        yield
    finally:
        path.chmod(0o755)


def test_a_directory_that_could_not_be_read_is_named(tmp_path: Path):
    case = tmp_path / "case"
    (case / "locked").mkdir(parents=True)
    (case / "locked" / "secret.txt").write_text("x", encoding="utf-8")
    (case / "open.txt").write_text("x", encoding="utf-8")

    missed = Unsearched()
    with unreadable(case / "locked"):
        records = scan(case, home=tmp_path, use_shell_history=False, unsearched=missed)

    assert [Path(record.path).name for record in records] == ["open.txt"]
    assert [Path(p).name for p in missed.unreadable] == ["locked"]
    assert missed.by_name == []


def test_a_directory_skipped_for_its_name_is_named_too(tmp_path: Path):
    case = tmp_path / "case"
    (case / "node_modules").mkdir(parents=True)
    (case / "node_modules" / "index.js").write_text("x", encoding="utf-8")
    (case / "real.txt").write_text("x", encoding="utf-8")

    missed = Unsearched()
    scan(case, home=tmp_path, use_shell_history=False, unsearched=missed)

    assert [Path(p).name for p in missed.by_name] == ["node_modules"]
    assert missed.unreadable == []


def test_the_skipped_names_can_be_visited_when_asked(tmp_path: Path):
    """The list is a default, not a rule about what evidence is."""
    case = tmp_path / "case"
    (case / "build").mkdir(parents=True)
    (case / "build" / "shipped.txt").write_text("x", encoding="utf-8")

    assert [p.name for p in iter_files(case)] == []
    assert [p.name for p in iter_files(case, skip_names=False)] == ["shipped.txt"]


def test_nothing_is_recorded_when_nothing_was_missed(tmp_path: Path):
    case = tmp_path / "case"
    case.mkdir()
    (case / "real.txt").write_text("x", encoding="utf-8")

    missed = Unsearched()
    scan(case, home=tmp_path, use_shell_history=False, unsearched=missed)

    assert not missed
