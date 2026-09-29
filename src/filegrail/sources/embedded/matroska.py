"""EBML elements, for Matroska and WebM.

The container is a tree of elements, each an identifier, a length and a payload,
and the ones that say where a file came from sit in two places:

    Info    the application that wrote the file, the library that muxed it, the
            moment the segment was made, and a title someone typed
    Tags    open-ended name/value pairs, which is where a muxer puts everything
            the format has no field for

Only those two are descended into. Everything else in a Matroska file is frames,
and the walk seeks over them rather than reading them.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

#: Split by what an analyst would call them rather than by container, the
#: way RIFF is, so a filter can ask for the audio without the video.
VIDEO_SUFFIXES = {".mkv", ".mk3d", ".webm"}
AUDIO_SUFFIXES = {".mka"}
SUFFIXES = VIDEO_SUFFIXES | AUDIO_SUFFIXES

_MAGIC = b"\x1a\x45\xdf\xa3"

#: Elements worth opening. Everything absent from this list is stepped over,
#: which is what keeps an hour of video as cheap to read as a second of it.
_SEGMENT = 0x18538067
_INFO = 0x1549A966
_TAGS = 0x1254C367
_TAG = 0x7373
_SIMPLE_TAG = 0x67C8
_CONTAINERS = frozenset({_SEGMENT, _INFO, _TAGS, _TAG, _SIMPLE_TAG})

_TITLE = 0x7BA9
_MUXING_APP = 0x4D80
_WRITING_APP = 0x5741
_DATE_UTC = 0x4461
_SEGMENT_UID = 0x73A4
_TAG_NAME = 0x45A3
_TAG_STRING = 0x4487

_NAMED = {
    _TITLE: "Title",
    _MUXING_APP: "MuxingApp",
    _WRITING_APP: "WritingApp",
}

#: Matroska counts nanoseconds from the start of 2001, not from 1970. Reading
#: the field as a Unix time puts every file made this century thirty-one years
#: early, which looks plausible enough to go unnoticed.
_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)

_MAX_ELEMENTS = 4096
_MAX_DEPTH = 5
_MAX_PAYLOAD = 64 * 1024

#: How far in to keep looking. Info and Tags are written near the front by every
#: muxer; a file that has not declared itself within this much is streaming, and
#: reading further would mean reading the video.
_WINDOW = 8 * 1024 * 1024


@dataclass(slots=True)
class Matroska:
    """What the container says about its own making."""

    #: Elements from Info under their published names, and tags under whichever
    #: names the writer chose - the tag block is open, and a reader that knows
    #: only a fixed list throws away the ones that mattered.
    fields: dict[str, str] = field(default_factory=dict)

    #: When the segment was made, already converted out of the Matroska epoch.
    at: str | None = None

    def __bool__(self) -> bool:
        return bool(self.fields or self.at)


def read_matroska(path: Path) -> Matroska | None:
    """Return what the container declares, or None when it declares nothing."""
    try:
        with path.open("rb") as handle:
            data = handle.read(_WINDOW)
    except OSError:
        return None
    if not data.startswith(_MAGIC):
        return None

    found = Matroska()
    try:
        _walk(data, 0, len(data), found, depth=0)
    except (struct.error, ValueError):
        return None
    return found or None


def _walk(data: bytes, start: int, end: int, found: Matroska, depth: int) -> None:
    at = start
    for _ in range(_MAX_ELEMENTS):
        if at >= end:
            return
        identifier, at = _number(data, at, end, marked=True)
        size, at = _number(data, at, end, marked=False)
        if identifier is None:
            return
        if size is None:
            # A muxer writing to a pipe cannot know how long the segment will
            # be, so it says so and means "to the end of the parent". Only a
            # master element may: on a leaf the value would be however much of
            # the file happened to follow it.
            if identifier not in _CONTAINERS:
                return
            size = end - at
        if size > end - at:
            # A length past the end means the walk has lost its place. Reading
            # on would take arbitrary offsets for element headers, which is how
            # a parser starts inventing evidence.
            return

        if identifier in _CONTAINERS:
            if depth < _MAX_DEPTH:
                _walk(data, at, at + size, found, depth + 1)
        elif size <= _MAX_PAYLOAD:
            _leaf(data, identifier, data[at : at + size], found)
        at += size


def _leaf(data: bytes, identifier: int, payload: bytes, found: Matroska) -> None:
    if name := _NAMED.get(identifier):
        if text := _text(payload):
            found.fields.setdefault(name, text)
    elif identifier == _DATE_UTC:
        found.at = found.at or _moment(payload)
    elif identifier == _SEGMENT_UID:
        found.fields.setdefault("SegmentUID", payload.hex())
    elif identifier == _TAG_NAME:
        found.fields.setdefault(_PENDING, _text(payload) or "")
    elif identifier == _TAG_STRING:
        # The name arrives in its own element just before the value, so the one
        # is held until the other turns up rather than parsed a second time.
        name = found.fields.pop(_PENDING, "")
        if name and (text := _text(payload)):
            found.fields.setdefault(name, text)


#: Where a tag's name waits for its value. Not a name any writer can produce,
#: so it cannot collide with one.
_PENDING = "\x00pending"


def _number(data: bytes, at: int, end: int, *, marked: bool) -> tuple[int | None, int]:
    """Read an EBML variable-length integer.

    The first byte says how long it is by where its highest bit sits. An
    identifier keeps that bit - it is part of what names the element - and a
    length does not, so the same encoding is read two ways.
    """
    if at >= end:
        return None, at
    first = data[at]
    if first == 0:
        return None, at
    width = 9 - first.bit_length()
    if at + width > end:
        return None, at
    if marked:
        return int.from_bytes(data[at : at + width], "big"), at + width
    value = int.from_bytes(bytes([first & (0xFF >> width)]) + data[at + 1 : at + width], "big")
    # All bits set is Matroska for "unknown", written while streaming. It is
    # not a length, and treating it as one would run the walk off the file.
    return (None if value == (1 << (7 * width)) - 1 else value), at + width


def _moment(payload: bytes) -> str | None:
    """The segment date, out of the Matroska epoch and into ISO 8601.

    The field is signed: a muxer handed a wrong clock writes what it was handed,
    and reading it as unsigned would turn 1999 into the year 586.
    """
    if not 0 < len(payload) <= 8:
        return None
    nanoseconds = int.from_bytes(payload, "big", signed=True)
    try:
        when = _EPOCH + timedelta(microseconds=nanoseconds // 1000)
    except (OverflowError, ValueError):
        return None
    return when.isoformat().replace("+00:00", "Z")


def _text(payload: bytes) -> str | None:
    trimmed = payload.split(b"\x00", 1)[0]
    return " ".join(trimmed.decode("utf-8", "replace").split()) or None
