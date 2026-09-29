import sqlite3
import zipfile
from pathlib import Path

from filegrail.scan import scan
from filegrail.sources.archives import is_archive, list_members
from tests.photo import jpeg_with_exif

from .test_browser import CHROMIUM_SCHEMA, START_TIME


def _download_record(home: Path, target: str) -> None:
    profile = home / ".config" / "chromium" / "Default"
    profile.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(profile / "History")
    connection.executescript(CHROMIUM_SCHEMA)
    connection.execute(
        "INSERT INTO downloads VALUES (1,?,?,512,1,'','https://example.org/pack.zip','application/zip')",
        (target, START_TIME),
    )
    connection.commit()
    connection.close()


def _make_zip(path: Path, entries: dict[str, str | bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


def _mark_members_encrypted(raw: bytes) -> bytes:
    """Set the encrypted flag in every local and central ZIP header."""
    body = bytearray(raw)
    for magic, field in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        at = 0
        while (at := body.find(magic, at)) >= 0:
            flags = int.from_bytes(body[at + field : at + field + 2], "little")
            body[at + field : at + field + 2] = (flags | 1).to_bytes(2, "little")
            at += 4
    return bytes(body)


def test_recognises_archive_suffixes():
    assert is_archive(Path("a.zip"))
    assert is_archive(Path("a.TGZ"))
    assert not is_archive(Path("a.txt"))


def test_lists_zip_members_with_sizes(tmp_path: Path):
    archive = tmp_path / "pack.zip"
    _make_zip(archive, {"docs/notes.md": "hello", "data.csv": "a,b"})

    assert list_members(archive) == {"notes.md": {5}, "data.csv": {3}}


def test_same_base_name_at_two_sizes_is_kept(tmp_path: Path):
    archive = tmp_path / "pack.zip"
    _make_zip(archive, {"README.md": "top level readme", "examples/README.md": "short"})

    assert list_members(archive) == {"README.md": {16, 5}}


def test_nested_member_with_a_shared_name_still_inherits(tmp_path: Path):
    archive = tmp_path / "pack.zip"
    _make_zip(archive, {"README.md": "top level readme", "examples/README.md": "short"})
    _download_record(tmp_path, str(archive))

    case = tmp_path / "case"
    case.mkdir()
    (case / "README.md").write_text("top level readme", encoding="utf-8")

    record = scan(case, home=tmp_path, use_shell_history=False)[0]

    assert record.primary is not None
    assert record.primary.source == "archive-member"


def test_corrupt_archive_returns_no_members(tmp_path: Path):
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"not really a zip")
    assert list_members(broken) == {}


def test_encrypted_member_does_not_end_archive_inspection(tmp_path: Path):
    archive = tmp_path / "locked.zip"
    _make_zip(archive, {"photo.jpg": b"not important"})
    archive.write_bytes(_mark_members_encrypted(archive.read_bytes()))

    assert list_members(archive) == {"photo.jpg": {13}}
    assert scan(archive, home=tmp_path, use_shell_history=False)


def test_extracted_files_inherit_the_archive_origin(tmp_path: Path):
    archive = tmp_path / "pack.zip"
    _make_zip(archive, {"notes.md": "hello", "data.csv": "a,b"})
    _download_record(tmp_path, str(archive))

    case = tmp_path / "case"
    case.mkdir()
    (case / "notes.md").write_text("hello", encoding="utf-8")
    (case / "data.csv").write_text("a,b", encoding="utf-8")

    records = {Path(r.path).name: r for r in scan(case, home=tmp_path, use_shell_history=False)}

    for name in ("notes.md", "data.csv"):
        best = records[name].primary
        assert best is not None
        assert best.source == "archive-member"
        assert best.url == "https://example.org/pack.zip"
        assert best.container == str(archive)
        assert "extracted from pack.zip" in best.note


def test_a_member_that_describes_itself_still_inherits_the_archive_origin(tmp_path: Path):
    """EXIF says where a photograph was taken, never how it arrived here.

    The archive is the one record that answers that, so carrying metadata must
    not cost a file the answer. This guarded a real regression: the check began
    as one for a known origin and briefly became one for any evidence at all.
    """
    photo = tmp_path / "photo.jpg"
    jpeg_with_exif(photo, "Canon", "EOS R5", "2026:03:01 10:00:00")
    blob = photo.read_bytes()

    archive = tmp_path / "pack.zip"
    _make_zip(archive, {"photo.jpg": blob})
    _download_record(tmp_path, str(archive))

    case = tmp_path / "case"
    case.mkdir()
    (case / "photo.jpg").write_bytes(blob)

    record = scan(case, home=tmp_path, use_shell_history=False)[0]

    sources = [found.source for found in record.evidence]
    assert "device-metadata" in sources, "the file lost what it says about itself"
    assert "archive-member" in sources, "the file lost where the archive says it came from"


def test_member_modified_after_extraction_is_not_claimed(tmp_path: Path):
    archive = tmp_path / "pack.zip"
    _make_zip(archive, {"notes.md": "hello"})
    _download_record(tmp_path, str(archive))

    case = tmp_path / "case"
    case.mkdir()
    (case / "notes.md").write_text("hello, edited since", encoding="utf-8")

    record = scan(case, home=tmp_path, use_shell_history=False)[0]

    assert record.evidence == []


def test_inheritance_can_be_disabled(tmp_path: Path):
    archive = tmp_path / "pack.zip"
    _make_zip(archive, {"notes.md": "hello"})
    _download_record(tmp_path, str(archive))

    case = tmp_path / "case"
    case.mkdir()
    (case / "notes.md").write_text("hello", encoding="utf-8")

    record = scan(case, home=tmp_path, use_shell_history=False, follow_archives=False)[0]

    assert record.evidence == []


def test_the_archive_read_budget_bounds_members_opened_not_findings(tmp_path: Path, monkeypatch):
    from filegrail.sources import archives

    archive = tmp_path / "many.zip"
    _make_zip(archive, {f"blob-{n}.bin": b"x" for n in range(60)})
    opened = []
    monkeypatch.setattr(archives, "read_member", lambda name, extract: opened.append(name) or [])

    archives.read_members(archive)

    assert len(opened) <= archives._MAX_READ
