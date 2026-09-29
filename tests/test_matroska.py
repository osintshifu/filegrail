"""Matroska and WebM: what an EBML container says about its own making.

The interesting elements are few and all near the front - the application that
wrote the file, the library that muxed it, the moment the segment was made and
a title someone typed. Everything after them is frames.
"""

from __future__ import annotations

import struct
from pathlib import Path

from filegrail.sources.embedded import read_embedded_metadata
from filegrail.sources.embedded.matroska import read_matroska

EBML = b"\x1a\x45\xdf\xa3"
SEGMENT = b"\x18\x53\x80\x67"
INFO = b"\x15\x49\xa9\x66"
TAGS = b"\x12\x54\xc3\x67"
TAG = b"\x73\x73"
SIMPLE_TAG = b"\x67\xc8"
TAG_NAME = b"\x45\xa3"
TAG_STRING = b"\x44\x87"
TITLE = b"\x7b\xa9"
MUXING_APP = b"\x4d\x80"
WRITING_APP = b"\x57\x41"
DATE_UTC = b"\x44\x61"

#: 2019-03-04T10:22:31Z, counted in nanoseconds from the Matroska epoch.
MOMENT = 573387751000000000


def _length(size: int) -> bytes:
    """An EBML variable-length integer, in the fewest bytes that hold it."""
    for width in range(1, 5):
        if size < (1 << (7 * width)) - 1:
            return (size | (1 << (7 * width))).to_bytes(width, "big")
    raise ValueError(size)


def element(identifier: bytes, payload: bytes) -> bytes:
    return identifier + _length(len(payload)) + payload


def matroska(tmp_path: Path, *children: bytes, name: str = "clip.mkv") -> Path:
    path = tmp_path / name
    path.write_bytes(
        element(EBML, element(b"\x42\x82", b"matroska")) + element(SEGMENT, b"".join(children))
    )
    return path


def simple_tag(name: bytes, value: bytes) -> bytes:
    return element(SIMPLE_TAG, element(TAG_NAME, name) + element(TAG_STRING, value))


# --- the segment information -------------------------------------------------


def test_the_writing_application_is_the_tool(tmp_path: Path):
    movie = matroska(
        tmp_path,
        element(
            INFO,
            element(MUXING_APP, b"libmatroska v1.7.1") + element(WRITING_APP, b"mkvmerge v75.0.0"),
        ),
    )

    assert read_embedded_metadata(movie).tool == "mkvmerge v75.0.0 (muxed with libmatroska v1.7.1)"


def test_one_application_that_did_both_is_named_once(tmp_path: Path):
    """ffmpeg writes its own name into both fields, and "Lavf60.16.100 (muxed
    with Lavf60.16.100)" is a sentence about nothing."""
    movie = matroska(
        tmp_path,
        element(
            INFO,
            element(MUXING_APP, b"Lavf60.16.100") + element(WRITING_APP, b"Lavf60.16.100"),
        ),
    )

    assert read_embedded_metadata(movie).tool == "Lavf60.16.100"


def test_the_segment_date_is_counted_from_the_matroska_epoch(tmp_path: Path):
    """Matroska counts nanoseconds from 2001, not from 1970. Read as a Unix
    time it puts every file made this century thirty-one years early."""
    movie = matroska(
        tmp_path,
        element(
            INFO,
            element(WRITING_APP, b"mkvmerge v75.0.0")
            + element(DATE_UTC, struct.pack(">q", MOMENT)),
        ),
    )

    assert read_embedded_metadata(movie).at == "2019-03-04T10:22:31Z"


def test_a_date_written_before_the_epoch_is_still_read(tmp_path: Path):
    """The field is signed, and a muxer handed a wrong clock writes what it was
    handed. Reading it as unsigned would turn 1999 into the year 586."""
    movie = matroska(
        tmp_path,
        element(
            INFO,
            element(WRITING_APP, b"mkvmerge")
            + element(DATE_UTC, struct.pack(">q", -86400 * 10**9)),
        ),
    )

    assert read_embedded_metadata(movie).at == "2000-12-31T00:00:00Z"


def test_the_title_reaches_the_note(tmp_path: Path):
    movie = matroska(
        tmp_path,
        element(INFO, element(WRITING_APP, b"mkvmerge") + element(TITLE, b"Interview take 3")),
    )

    assert "title Interview take 3" in read_embedded_metadata(movie).note


# --- the tag block -----------------------------------------------------------


def test_a_tag_keeps_the_name_the_writer_gave_it(tmp_path: Path):
    """Matroska tags are open: a newsroom writes whatever names it uses, and a
    reader that only knows a fixed list throws away the ones that mattered."""
    movie = matroska(
        tmp_path,
        element(INFO, element(WRITING_APP, b"mkvmerge")),
        element(
            TAGS,
            element(
                TAG,
                simple_tag(b"ENCODED_BY", b"Newsroom") + simple_tag(b"ORIGINAL_MEDIA_TYPE", b"DV"),
            ),
        ),
    )

    fields = read_embedded_metadata(movie).fields

    assert fields["ENCODED_BY"] == "Newsroom"
    assert fields["ORIGINAL_MEDIA_TYPE"] == "DV"


# --- files with nothing to say -----------------------------------------------


def test_a_segment_of_unknown_length_is_still_read(tmp_path: Path):
    """A muxer writing to a pipe cannot know how long the segment will be, so
    it writes every bit set and means "to the end". ffmpeg does exactly this
    for `-f webm pipe:1`, and refusing it loses the whole file."""
    movie = tmp_path / "streamed.webm"
    movie.write_bytes(
        element(EBML, element(b"\x42\x82", b"webm"))
        + SEGMENT
        + b"\x01\xff\xff\xff\xff\xff\xff\xff"
        + element(INFO, element(WRITING_APP, b"Lavf60.16.100") + element(TITLE, b"Streamed take"))
    )

    assert read_embedded_metadata(movie).tool == "Lavf60.16.100"


def test_a_leaf_of_unknown_length_is_refused(tmp_path: Path):
    """Only a master element may say it does not know its own length. On a leaf
    the value would be however much of the file happened to follow."""
    movie = tmp_path / "malformed.mkv"
    movie.write_bytes(
        element(EBML, element(b"\x42\x82", b"matroska"))
        + element(SEGMENT, element(INFO, WRITING_APP + b"\xff" + b"mkvmerge v75.0.0"))
    )

    assert read_matroska(movie) is None


def test_a_file_that_is_not_ebml_is_not_claimed(tmp_path: Path):
    movie = tmp_path / "misnamed.mkv"
    movie.write_bytes(b"RIFF" + b"\x00" * 60)

    assert read_matroska(movie) is None
    assert read_embedded_metadata(movie) is None


def test_a_length_running_past_the_end_stops_the_walk(tmp_path: Path):
    """Once a length is impossible the offsets after it are guesses, and a
    parser that keeps reading them starts inventing evidence."""
    movie = tmp_path / "truncated.mkv"
    movie.write_bytes(
        element(EBML, element(b"\x42\x82", b"matroska"))
        + SEGMENT
        + b"\x08\x00\x00\x00\x00\x00\x00\x01"  # a segment the size of the disk
        + element(INFO, element(WRITING_APP, b"mkvmerge v75.0.0"))
    )

    assert read_matroska(movie) is None
