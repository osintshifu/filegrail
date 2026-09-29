"""What a `.torrent` file says about the files it distributes.

A torrent is a container in the same sense an archive is: it lists members by
name and exact size, so a file on disk matching both was very likely part of
it. Unlike an archive it carries an origin of its own - the trackers it was
announced to, the client that made it, and an info hash that names the content
itself.

The fixtures are encoded by a helper rather than written as byte literals, so
a miscounted length cannot produce a passing test on malformed input.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from filegrail.doctor import AVAILABLE, survey
from filegrail.models import ORIGIN, category
from filegrail.scan import scan
from filegrail.sources.torrent import collect_torrents, is_torrent, read_torrent


def _bencode(value) -> bytes:
    """Encode the bencode subset the fixtures need. Independent of the reader."""
    if isinstance(value, int):
        return b"i%de" % value
    if isinstance(value, bytes):
        return b"%d:%s" % (len(value), value)
    if isinstance(value, str):
        return _bencode(value.encode("utf-8"))
    if isinstance(value, list):
        return b"l" + b"".join(_bencode(item) for item in value) + b"e"
    if isinstance(value, dict):
        return (
            b"d"
            + b"".join(
                _bencode(k) + _bencode(v) for k, v in sorted(value.items(), key=lambda kv: kv[0])
            )
            + b"e"
        )
    raise TypeError(value)


def _torrent(path: Path, info: dict, **top) -> bytes:
    """Write a torrent and return the exact bytes of its `info` value."""
    document = {"announce": "http://tracker.example.org:6969/announce", "info": info, **top}
    path.write_bytes(_bencode(document))
    return _bencode(info)


def _single(name: str = "film.mkv", length: int = 4096) -> dict:
    return {"name": name, "length": length, "piece length": 262144, "pieces": b"\x00" * 20}


def test_a_single_file_torrent_lists_its_one_member(tmp_path: Path):
    path = tmp_path / "a.torrent"
    _torrent(path, _single())

    assert read_torrent(path).members == {"film.mkv": {4096}}


def test_a_multi_file_torrent_lists_each_member_by_its_base_name(tmp_path: Path):
    path = tmp_path / "a.torrent"
    _torrent(
        path,
        {
            "name": "A Release",
            "piece length": 262144,
            "pieces": b"\x00" * 20,
            "files": [
                {"length": 10, "path": ["subdir", "one.jpg"]},
                {"length": 20, "path": ["two.jpg"]},
            ],
        },
    )

    assert read_torrent(path).members == {"one.jpg": {10}, "two.jpg": {20}}


def test_the_content_is_named_by_its_info_hash(tmp_path: Path):
    path = tmp_path / "a.torrent"
    info = _torrent(path, _single())
    expected = hashlib.sha1(info).hexdigest()  # noqa: S324 - the protocol says SHA-1

    assert read_torrent(path).record.url == f"magnet:?xt=urn:btih:{expected}&dn=film.mkv"


def test_the_trackers_are_reported(tmp_path: Path):
    path = tmp_path / "a.torrent"
    _torrent(path, _single(), **{"announce-list": [["http://second.example.net/announce"]]})

    fields = read_torrent(path).record.fields

    assert "tracker.example.org" in fields["trackers"]
    assert "second.example.net" in fields["trackers"]


def test_the_claim_is_not_dated_by_the_torrent_being_made(tmp_path: Path):
    """A torrent can be years older than the download of anything in it, so its
    creation date says when the torrent was made and nothing about arrival."""
    path = tmp_path / "a.torrent"
    _torrent(path, _single(), **{"creation date": 1415628355, "created by": "mktorrent 1.1"})

    origin = read_torrent(path).record

    assert origin.at is None
    assert origin.fields["created"] == "2014-11-10T14:05:55Z"
    assert origin.tool == "mktorrent 1.1"


def test_something_that_is_not_a_torrent(tmp_path: Path):
    path = tmp_path / "a.torrent"
    path.write_bytes(b"not bencode at all")

    assert read_torrent(path) is None


def test_the_suffix_is_what_marks_one(tmp_path: Path):
    assert is_torrent(Path("a.torrent"))
    assert not is_torrent(Path("a.mkv"))


def test_a_scan_gives_a_matching_file_its_torrent(tmp_path: Path):
    (tmp_path / "film.mkv").write_bytes(b"x" * 4096)
    _torrent(tmp_path / "a.torrent", _single())

    record = next(r for r in scan(tmp_path, use_shell_history=False) if r.path.endswith(".mkv"))
    found = [o for o in record.evidence if o.source == "torrent"]

    assert len(found) == 1
    assert category(found[0]) == ORIGIN
    assert found[0].priority > 0
    assert found[0].container == str(tmp_path / "a.torrent")


def test_a_file_whose_size_disagrees_is_not_claimed(tmp_path: Path):
    """The name alone matches far too much. A torrent lists an exact size and
    a file that is not that size is not the file the torrent lists."""
    (tmp_path / "film.mkv").write_bytes(b"x" * 99)
    _torrent(tmp_path / "a.torrent", _single())

    record = next(r for r in scan(tmp_path, use_shell_history=False) if r.path.endswith(".mkv"))

    assert not [o for o in record.evidence if o.source == "torrent"]


# --- the copy the client keeps ----------------------------------------------


def test_the_clients_own_store_is_read(tmp_path: Path):
    """qBittorrent keeps a copy of every torrent it has ever loaded, so the
    file on disk usually has no `.torrent` beside it and one exists anyway."""
    store = tmp_path / ".local/share/qBittorrent/BT_backup"
    store.mkdir(parents=True)
    _torrent(store / "abcdef.torrent", _single())

    found = collect_torrents(home=tmp_path)

    assert [t.members for t in found] == [{"film.mkv": {4096}}]


def test_a_scan_pairs_against_the_clients_store(tmp_path: Path):
    home = tmp_path / "home"
    store = home / ".config/transmission/torrents"
    store.mkdir(parents=True)
    _torrent(store / "abcdef.torrent", _single())

    tree = tmp_path / "case"
    tree.mkdir()
    (tree / "film.mkv").write_bytes(b"x" * 4096)

    record = next(iter(scan(tree, use_shell_history=False, home=home)))

    assert [o.source for o in record.evidence] == ["torrent"]
    assert record.evidence[0].container == str(store / "abcdef.torrent")


def test_the_survey_reports_a_client_store(tmp_path: Path):
    """`doctor` promises to say what could be searched, and a scan reads these."""
    store = tmp_path / ".config/transmission/torrents"
    store.mkdir(parents=True)
    _torrent(store / "abcdef.torrent", _single())

    found = survey(tmp_path)
    stores = [check for check in found.checks if check.name.startswith("Torrent client")]

    assert [check.state for check in stores] == [AVAILABLE]
