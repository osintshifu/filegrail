"""The record a download tool leaves beside the file it fetched.

`yt-dlp --write-info-json` writes `<name>.info.json` next to `<name>.<ext>`,
and that file names the page the media came from, who published it and when
the fetch happened. It is an origin record in the plainest sense - a
program wrote down where it got the bytes - and unlike a browser database it
travels with the file.

The fixtures here are built from the field names of a real document produced
by yt-dlp 2026.08.19, not from memory of the documentation.
"""

from __future__ import annotations

import json
from pathlib import Path

from filegrail.models import ORIGIN, category
from filegrail.scan import scan
from filegrail.sources.sidecar import read_sidecar


def _beside(media: Path, **fields) -> None:
    """Write the sidecar yt-dlp would have written for `media`."""
    document = {
        "id": "aqz-KE-bpKQ",
        "title": "A Short Film",
        "webpage_url": "https://www.example.org/watch?v=aqz-KE-bpKQ",
        "uploader": "A Studio",
        "channel": "A Studio",
        "upload_date": "20141110",
        "extractor": "example",
        "ext": "webm",
        "epoch": 1788606753,
        "_version": {"version": "2026.08.19"},
        **fields,
    }
    media.with_suffix(".info.json").write_text(json.dumps(document), encoding="utf-8")


def test_the_page_the_media_came_from_is_reported(tmp_path: Path):
    media = tmp_path / "film.mp4"
    media.write_bytes(b"\x00")
    _beside(media)

    origin = read_sidecar(media)

    assert origin is not None
    assert origin.url == "https://www.example.org/watch?v=aqz-KE-bpKQ"


def test_a_file_with_no_sidecar_beside_it(tmp_path: Path):
    media = tmp_path / "film.mp4"
    media.write_bytes(b"\x00")

    assert read_sidecar(media) is None


def test_the_moment_recorded_is_the_fetch_not_the_publication(tmp_path: Path):
    """`epoch` is when the download ran. `upload_date` is when the video became
    available, which can be years earlier - reading that into the claim would
    date the arrival before the file was ever on this machine."""
    media = tmp_path / "film.mp4"
    media.write_bytes(b"\x00")
    _beside(media)

    assert read_sidecar(media).at == "2026-09-05T11:12:33Z"


def test_an_estimated_size_is_not_reported_as_the_size(tmp_path: Path):
    """`filesize_approx` is an estimate for the chosen format. Carried as a
    byte count it would contradict the file on disk and be reported as a size
    mismatch that nothing is actually wrong about."""
    media = tmp_path / "film.mp4"
    media.write_bytes(b"\x00")
    _beside(media, filesize_approx=722647490)

    assert read_sidecar(media).bytes is None


def test_a_sidecar_that_is_not_json_is_not_an_error(tmp_path: Path):
    media = tmp_path / "film.mp4"
    media.write_bytes(b"\x00")
    media.with_suffix(".info.json").write_text("{ truncated", encoding="utf-8")

    assert read_sidecar(media) is None


def test_a_sidecar_with_no_address_says_nothing(tmp_path: Path):
    """Without a URL the document says who published a video, not where this
    file came from, and an origin record with no address is not one."""
    media = tmp_path / "film.mp4"
    media.write_bytes(b"\x00")
    media.with_suffix(".info.json").write_text('{"uploader": "A Studio"}', encoding="utf-8")

    assert read_sidecar(media) is None


def test_the_claim_says_how_the_file_arrived(tmp_path: Path):
    media = tmp_path / "film.mp4"
    media.write_bytes(b"\x00")
    _beside(media)

    origin = read_sidecar(media)

    assert category(origin) == ORIGIN
    assert origin.priority > 0


def test_a_scan_attaches_it(tmp_path: Path):
    media = tmp_path / "film.mp4"
    media.write_bytes(b"\x00")
    _beside(media)

    record = next(r for r in scan(tmp_path, use_shell_history=False) if r.path.endswith(".mp4"))

    assert [o.url for o in record.evidence if o.source == "ytdlp-sidecar"] == [
        "https://www.example.org/watch?v=aqz-KE-bpKQ"
    ]
