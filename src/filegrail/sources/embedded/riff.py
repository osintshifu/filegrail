"""RIFF chunks, for WAV and AVI.

A RIFF file is a list of chunks, and two of them say where the file came from:

    LIST/INFO   ``ISFT`` names the software, ``ICRD`` the date, ``IART``
                whoever is credited - the fields an editor fills in on save
    bext        the broadcast extension: what machine made the recording, when
                it started, and every processing step since
    id3         the tag MP3 made familiar, carried here in a chunk rather than
                at the start of the file, which is why the ID3 reader alone
                could never find one in a WAV

The walk seeks over payloads instead of reading them, so an hour of video costs
the same handful of reads as a one-second sample.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from . import id3

#: Split by what an analyst would call them rather than by container, so a
#: filter can ask for the audio without dragging the video along.
WAVE_SUFFIXES = {".wav", ".wave", ".rmi"}
AVI_SUFFIXES = {".avi"}
SUFFIXES = WAVE_SUFFIXES | AVI_SUFFIXES

#: AVI writes its INFO list after the frames, so the walk has to be free to
#: reach the end of a large file. It only ever seeks, and a recording does not
#: have this many chunks at one level - a file that does is malformed.
_MAX_CHUNKS = 4096

#: A payload this large is audio or video, never metadata. Refusing to read it
#: is what keeps the walk cheap.
_MAX_PAYLOAD = 4 * 1024 * 1024

#: How far a LIST may nest. INFO sits at the top level in every file anyone
#: writes; the limit is here so a crafted file cannot exhaust the stack.
_MAX_DEPTH = 3

_MAX_TEXT = 4096

_ID3_CHUNKS = (b"id3 ", b"ID3 ")

#: The fixed part of a BWF `bext` chunk, ahead of the coding history. Every
#: field in it is found by counting bytes - the layout carries no names - so a
#: chunk shorter than this is not one, whatever it calls itself.
_BEXT_FIXED = 602

#: EBU Tech 3285 writes the date as yyyy-mm-dd and the time as hh:mm:ss, and
#: then leaves the separator to the writer, so it is read as anything at all.
_DATE = re.compile(r"(\d{4}).(\d{2}).(\d{2})")
_TIME = re.compile(r"(\d{2}).(\d{2}).(\d{2})")

#: Lists holding sample data rather than description. Anything at all can turn
#: up inside a frame, chunk headers included, so this is where the walk stops
#: looking: a file must not be able to forge its own provenance in its payload.
_OPAQUE = (b"movi", b"rec ", b"wavl")

#: The INFO fields, by their four-character code. The list is the one RIFF
#: published in 1991 and it shows: half of it describes print media. It is kept
#: whole because a field this tool does not summarise is still evidence.
INFO_NAMES = {
    b"IARL": "ArchivalLocation",
    b"IART": "Artist",
    b"ICMS": "Commissioned",
    b"ICMT": "Comment",
    b"ICOP": "Copyright",
    b"ICRD": "DateCreated",
    b"ICRP": "Cropped",
    b"IDIM": "Dimensions",
    b"IDPI": "DotsPerInch",
    b"IENG": "Engineer",
    b"IGNR": "Genre",
    b"IKEY": "Keywords",
    b"ILGT": "Lightness",
    b"IMED": "Medium",
    b"INAM": "Title",
    b"IPLT": "PaletteSetting",
    b"IPRD": "Product",
    b"ISBJ": "Subject",
    b"ISFT": "Software",
    b"ISHP": "Sharpness",
    b"ISRC": "Source",
    b"ISRF": "SourceForm",
    b"ITCH": "Technician",
    # Written in practice, though never standardised.
    b"ICNM": "Cinematographer",
    b"IENC": "EncodedBy",
    b"ILNG": "Language",
}


@dataclass(slots=True)
class Riff:
    """What a RIFF container says about its own making."""

    #: The INFO fields, under the names above. A code with no published meaning
    #: keeps the code itself: an unrecognised field is not a worthless one.
    info: dict[str, str] = field(default_factory=dict)

    #: Frames from an embedded ID3 tag, keyed by meaning as the tag reader
    #: returns them.
    frames: dict[str, str] = field(default_factory=dict)

    #: The BWF `bext` fields, under the names EBU Tech 3285 gives them.
    broadcast: dict[str, str] = field(default_factory=dict)

    #: When the recording started, from the broadcast date and time fields read
    #: together. Kept apart from `broadcast` because it is this tool's reading
    #: of two fields rather than a third field anybody wrote.
    originated: str | None = None

    def __bool__(self) -> bool:
        return bool(self.info or self.frames or self.broadcast)


def read_riff(path: Path) -> Riff | None:
    """Return what the container declares, or None when it declares nothing."""
    found = Riff()
    try:
        with path.open("rb") as handle:
            header = handle.read(12)
            if len(header) < 12 or header[:4] != b"RIFF":
                return None
            (declared,) = struct.unpack_from("<I", header, 4)
            # The declared length is a claim like any other. A recorder that
            # lost power wrote the length it intended; trusting it would make
            # every impossible chunk length inside look reasonable.
            end = min(8 + declared, handle.seek(0, 2))
            _walk(handle, 12, end, found, depth=0, inside=header[8:12])
    except (OSError, struct.error, ValueError):
        return None
    return found or None


def _walk(handle: BinaryIO, start: int, end: int, found: Riff, depth: int, inside: bytes) -> None:
    """Read every chunk between `start` and `end`, descending into lists."""
    at = start
    for _ in range(_MAX_CHUNKS):
        if at + 8 > end:
            return
        handle.seek(at)
        entry = handle.read(8)
        if len(entry) < 8:
            return
        name, size = struct.unpack("<4sI", entry)
        body = at + 8
        if size > end - body:
            # A length running past the end means the walk has lost its place.
            # Reading on would take arbitrary offsets for chunk headers, which
            # is how a parser starts inventing evidence.
            return
        at = body + size + size % 2

        if name in (b"LIST", b"RIFF"):
            kind = handle.read(4)  # the header read above left us at `body`
            if depth < _MAX_DEPTH and size >= 4 and kind not in _OPAQUE:
                _walk(handle, body + 4, body + size, found, depth + 1, kind)
            continue
        _leaf(handle, name, body, size, found, inside)


def _leaf(handle: BinaryIO, name: bytes, body: int, size: int, found: Riff, inside: bytes) -> None:
    if not 0 < size <= _MAX_PAYLOAD:
        return
    if name in _ID3_CHUNKS:
        handle.seek(body)
        found.frames.update(id3.read_tag(handle.read(size)))
        return
    if name == b"bext":
        handle.seek(body)
        found.broadcast.update(_broadcast(handle.read(size)))
        found.originated = _originated(found.broadcast)
        return
    if inside != b"INFO":
        return
    handle.seek(body)
    text = _text(handle.read(min(size, _MAX_TEXT)))
    if text:
        found.info.setdefault(INFO_NAMES.get(name, _code(name)), text)


def _broadcast(raw: bytes) -> dict[str, str]:
    """Decode a BWF `bext` chunk, whose fields sit at fixed offsets."""
    if len(raw) < _BEXT_FIXED:
        return {}

    found = {}
    for name, start, stop in (
        ("Description", 0, 256),
        ("Originator", 256, 288),
        ("OriginatorReference", 288, 320),
        ("OriginationDate", 320, 330),
        ("OriginationTime", 330, 338),
    ):
        if value := _text(raw[start:stop]):
            found[name] = value

    reference, version = struct.unpack_from("<QH", raw, 338)
    if reference:
        # Samples since midnight: where in the day's timeline this take sits.
        found["TimeReference"] = str(reference)
    found["Version"] = str(version)

    umid = raw[348:412]
    if any(umid):
        found["UMID"] = umid.hex()
    if history := _history(raw[_BEXT_FIXED:]):
        found["CodingHistory"] = history
    return found


def _originated(broadcast: dict[str, str]) -> str | None:
    """When the recording started, from the two fields that say so together.

    Neither is worth much alone, and a writer that leaves them as nulls has
    said nothing - which is not the same as midnight at the start of 1970.
    """
    date = _DATE.match(broadcast.get("OriginationDate", ""))
    if not date:
        return None
    clock = _TIME.match(broadcast.get("OriginationTime", ""))
    return "-".join(date.groups()) + "T" + ":".join(clock.groups() if clock else ("00",) * 3)


def _history(raw: bytes) -> str | None:
    """The coding history, one line per processing step.

    The steps are kept apart. The chain is the evidence - a take that went
    through an analogue deck before it was digitised says so on its first line,
    and folding the lines into one sentence loses where each step began.
    """
    steps = [" ".join(line.split()) for line in _decode(raw).splitlines()]
    return " | ".join(step for step in steps if step) or None


def _text(raw: bytes) -> str | None:
    """Decode an INFO value.

    RIFF says these are Latin-1, and every tagger written since has said
    otherwise by putting UTF-8 there. UTF-8 is tried first because it is the
    one of the two that can fail: bytes that decode as UTF-8 were almost
    certainly written as UTF-8, and Latin-1 then accepts whatever is left.
    """
    return " ".join(_decode(raw).split()) or None


def _decode(raw: bytes) -> str:
    trimmed = raw.split(b"\x00", 1)[0]
    try:
        return trimmed.decode("utf-8")
    except UnicodeDecodeError:
        return trimmed.decode("latin-1")


def _code(name: bytes) -> str:
    """An unlisted chunk keeps its four-character code, if it is printable."""
    readable = name.decode("latin-1")
    return readable.strip() if readable.isprintable() else name.hex()
