"""MP4, MOV and the rest of the ISO base media family.

Video is where provenance most often survives untouched, because the writing
device stamps the container and few tools rewrite it afterwards. Three things
are worth reading:

    the encoder or camera        udta atoms, ``\\xa9too``, ``\\xa9swr``, ``\\xa9mak``
    the creation time            ``mvhd``, or ``\\xa9day``
    where it was recorded        ``\\xa9xyz``, an ISO 6709 coordinate string

Two more things are read where a camera wrote them. GoPro puts its firmware,
lens and camera serial in plain `udta` atoms of its own. An action camera or a
phone may also write a metadata track - GPMF or CAMM - and that track is
located through the sample tables and summarised: device, streams, and the GPS
track's start, end, count and clock.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO

from . import gpmf

SUFFIXES = {".mp4", ".m4v", ".m4a", ".mov", ".qt", ".3gp", ".heic", ".heif", ".avif"}

# ISO base media times count seconds from 1904-01-01.
_EPOCH_1904 = datetime(1904, 1, 1, tzinfo=timezone.utc)

_CONTAINERS = {b"moov", b"udta", b"trak", b"mdia", b"meta", b"ilst", b"minf", b"stbl"}
_MAX_DEPTH = 8
_MAX_ATOMS = 2048
_MAX_TEXT = 512

#: Sample tables are read whole, up to this much: a chunk offset table for a
#: long recording is a few hundred kilobytes.
_TABLE_ATOMS = {b"stco", b"co64", b"stsz", b"stsc"}
_MAX_TABLE = 1024 * 1024
_MAX_TRACKS = 32

#: How much of a telemetry track is read. Samples arrive about once a second
#: and a few kilobytes each, so this is hours of recording.
_MAX_SAMPLES = 8192
_MAX_TELEMETRY = 16 * 1024 * 1024
_TELEMETRY_FORMATS = {b"gpmd": "GPMF", b"camm": "CAMM"}

#: GoPro's own `udta` atoms: plain payloads, no `data` box and no length.
_GOPRO_TEXT = {b"FIRM": "firmware", b"LENS": "lens"}
_GOPRO_BINARY = {b"CAME": "camera_serial", b"MUID": "media_uid"}

ENCODER_ATOMS = (b"\xa9too", b"\xa9swr", b"\xa9enc")
MAKE_ATOMS = (b"\xa9mak", b"\xa9xmk")
MODEL_ATOMS = (b"\xa9mod", b"\xa9xmd")
DATE_ATOMS = (b"\xa9day", b"\xa9cre")
LOCATION_ATOMS = (b"\xa9xyz", b"loci")

_ISO6709 = re.compile(r"^([-+]\d{1,3}(?:\.\d+)?)([-+]\d{1,3}(?:\.\d+)?)")


@dataclass(slots=True)
class Track:
    """The parts of one track's sample tables that locate its samples."""

    handler: bytes | None = None
    format: bytes | None = None
    chunks: list[int] = field(default_factory=list)
    sizes: list[int] = field(default_factory=list)
    fixed_size: int = 0
    runs: list[tuple[int, int]] = field(default_factory=list)  # (first chunk, per chunk)
    language: str | None = None

    def ranges(self) -> list[tuple[int, int]]:
        """Every sample as (offset, size), in order, bounded."""
        found: list[tuple[int, int]] = []
        sample = 0
        total = 0
        for index, chunk in enumerate(self.chunks, 1):
            per = 0
            for first, count in self.runs:
                if first <= index:
                    per = count
            offset = chunk
            for _ in range(per):
                size = self.fixed_size or (self.sizes[sample] if sample < len(self.sizes) else 0)
                if not size or len(found) >= _MAX_SAMPLES or total + size > _MAX_TELEMETRY:
                    return found
                found.append((offset, size))
                offset += size
                total += size
                sample += 1
        return found


class Movie:
    """What an ISO base media file says about its own creation."""

    def __init__(self) -> None:
        self.encoder: str | None = None
        self.make: str | None = None
        self.model: str | None = None
        self.created: str | None = None
        self.coordinates: tuple[float, float] | None = None
        self.gopro: dict[str, str] = {}
        self.telemetry: gpmf.Telemetry | None = None
        self.tracks: list[Track] = []
        #: The `mdta` key names of the `moov/meta` atom, in order; an `ilst`
        #: item under it is numbered rather than named.
        self.keys: list[str] = []
        #: The `mdta` items nothing above stands for, by key.
        self.items: dict[str, str] = {}

    def __bool__(self) -> bool:
        return any(
            (
                self.encoder,
                self.make,
                self.model,
                self.created,
                self.coordinates,
                self.gopro,
                self.telemetry,
            )
        )


def read_movie(path: Path) -> Movie | None:
    movie = Movie()
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, 2)
            handle.seek(0)
            _walk(handle, 0, size, 0, movie)
            _telemetry(handle, size, movie)
    except (OSError, struct.error, ValueError):
        return movie if movie else None
    return movie if movie else None


def _telemetry(handle: BinaryIO, size: int, movie: Movie) -> None:
    for track in movie.tracks:
        kind = _TELEMETRY_FORMATS.get(track.format or b"")
        if kind is None:
            continue
        found = gpmf.Telemetry(kind)
        absorb = gpmf.absorb_gpmf if kind == "GPMF" else gpmf.absorb_camm
        for offset, length in track.ranges():
            if offset + length > size:
                break
            handle.seek(offset)
            absorb(handle.read(length), found)
        if found:
            movie.telemetry = found
            return


def _walk(handle: BinaryIO, start: int, end: int, depth: int, movie: Movie) -> None:
    if depth > _MAX_DEPTH:
        return
    offset = start
    atoms = 0

    while offset + 8 <= end and atoms < _MAX_ATOMS:
        atoms += 1
        handle.seek(offset)
        header = handle.read(8)
        if len(header) < 8:
            return
        size, atom = struct.unpack(">I4s", header)
        body = offset + 8

        if size == 1:
            extended = handle.read(8)
            if len(extended) < 8:
                return
            (size,) = struct.unpack(">Q", extended)
            body += 8
        elif size == 0:
            size = end - offset
        if size < 8 or offset + size > end:
            return

        atom_end = offset + size
        if atom == b"meta":
            # ISO's meta is a full box with version and flags before its
            # children; QuickTime's is not, and opens with `hdlr` at once.
            handle.seek(body)
            if handle.read(8)[4:8] != b"hdlr":
                body += 4
        if atom == b"trak" and len(movie.tracks) < _MAX_TRACKS:
            movie.tracks.append(Track())
        if atom in _CONTAINERS:
            _walk(handle, body, atom_end, depth + 1, movie)
        elif atom in _TABLE_ATOMS or atom in (b"stsd", b"hdlr", b"mdhd"):
            handle.seek(body)
            _track_atom(atom, handle.read(min(atom_end - body, _MAX_TABLE)), movie)
        elif atom == b"keys":
            handle.seek(body)
            _keys(handle.read(min(atom_end - body, _MAX_TABLE)), movie)
        else:
            handle.seek(body)
            _absorb(atom, handle.read(min(atom_end - body, _MAX_TEXT)), movie)

        offset = atom_end


def _track_atom(atom: bytes, payload: bytes, movie: Movie) -> None:
    """The sample-table atoms of the track being walked."""
    if not movie.tracks:
        return
    track = movie.tracks[-1]
    if atom == b"hdlr" and len(payload) >= 12:
        track.handler = payload[8:12]
    elif atom == b"mdhd" and len(payload) >= 24:
        at = 20 if payload[0] == 0 else 32  # version 1 widens the times
        if len(payload) >= at + 2:
            (packed,) = struct.unpack_from(">H", payload, at)
            letters = [((packed >> shift) & 0x1F) + 0x60 for shift in (10, 5, 0)]
            if all(0x61 <= letter <= 0x7A for letter in letters):
                track.language = bytes(letters).decode("ascii")
    elif atom == b"stsd" and len(payload) >= 16:
        track.format = payload[12:16]
    elif atom == b"stco" and len(payload) >= 8:
        (count,) = struct.unpack_from(">I", payload, 4)
        count = min(count, (len(payload) - 8) // 4)
        track.chunks = list(struct.unpack_from(f">{count}I", payload, 8))
    elif atom == b"co64" and len(payload) >= 8:
        (count,) = struct.unpack_from(">I", payload, 4)
        count = min(count, (len(payload) - 8) // 8)
        track.chunks = list(struct.unpack_from(f">{count}Q", payload, 8))
    elif atom == b"stsz" and len(payload) >= 12:
        fixed, count = struct.unpack_from(">II", payload, 4)
        track.fixed_size = fixed
        if not fixed:
            count = min(count, (len(payload) - 12) // 4)
            track.sizes = list(struct.unpack_from(f">{count}I", payload, 12))
    elif atom == b"stsc" and len(payload) >= 8:
        (count,) = struct.unpack_from(">I", payload, 4)
        count = min(count, (len(payload) - 8) // 12)
        track.runs = [
            (first, per)
            for first, per, _ in (
                struct.unpack_from(">III", payload, 8 + index * 12) for index in range(count)
            )
        ]


def _keys(payload: bytes, movie: Movie) -> None:
    """The key names an `mdta` metadata atom numbers its items by."""
    if len(payload) < 8:
        return
    (count,) = struct.unpack_from(">I", payload, 4)
    at = 8
    for _ in range(min(count, _MAX_ATOMS)):
        if at + 8 > len(payload):
            return
        size, namespace = struct.unpack_from(">I4s", payload, at)
        if size < 8 or at + size > len(payload):
            return
        name = (
            payload[at + 8 : at + size].decode("utf-8", "replace") if namespace == b"mdta" else ""
        )
        movie.keys.append(name)
        at += size


#: What each `mdta` key stands for, by the end of its name.
_MDTA_MEANS = {
    ".make": "make",
    ".model": "model",
    ".software": "encoder",
    ".creationdate": "created",
    ".location.iso6709": "coordinates",
}


def _absorb(atom: bytes, payload: bytes, movie: Movie) -> None:
    if atom == b"mvhd" and movie.created is None:
        movie.created = _mvhd_time(payload)
        return
    if movie.keys and len(atom) == 4 and atom[0] == 0:
        index = int.from_bytes(atom, "big")
        if 0 < index <= len(movie.keys):
            _mdta_item(movie.keys[index - 1], _atom_text(payload), movie)
        return
    if atom in _GOPRO_TEXT:
        plain = payload.decode("ascii", "replace").strip("\x00 ")
        if plain:
            movie.gopro.setdefault(_GOPRO_TEXT[atom], plain[:_MAX_TEXT])
        return
    if atom in _GOPRO_BINARY:
        if payload.strip(b"\x00"):
            movie.gopro.setdefault(_GOPRO_BINARY[atom], payload[:32].hex())
        return

    text = _atom_text(payload)
    if not text:
        return
    if atom in ENCODER_ATOMS and not movie.encoder:
        movie.encoder = text
    elif atom in MAKE_ATOMS and not movie.make:
        movie.make = text
    elif atom in MODEL_ATOMS and not movie.model:
        movie.model = text
    elif atom in DATE_ATOMS and not movie.created:
        movie.created = _normalise(text)
    elif atom in LOCATION_ATOMS and not movie.coordinates:
        movie.coordinates = _iso6709(text)


def _mdta_item(key: str, text: str | None, movie: Movie) -> None:
    if not text:
        return
    lowered = key.lower()
    meaning = next((meaning for end, meaning in _MDTA_MEANS.items() if lowered.endswith(end)), None)
    if meaning == "make" and not movie.make:
        movie.make = text
    elif meaning == "model" and not movie.model:
        movie.model = text
    elif meaning == "encoder" and not movie.encoder:
        movie.encoder = text
    elif meaning == "created":
        # A phone's own date carries its zone; `mvhd` before it did not.
        movie.created = _normalise(text) or movie.created
    elif meaning == "coordinates" and not movie.coordinates:
        movie.coordinates = _iso6709(text)
    elif meaning is None and len(movie.items) < _MAX_TRACKS:
        movie.items.setdefault(key, text[:_MAX_TEXT])


def _mvhd_time(payload: bytes) -> str | None:
    if len(payload) < 12:
        return None
    version = payload[0]
    try:
        if version == 1 and len(payload) >= 20:
            (seconds,) = struct.unpack_from(">Q", payload, 4)
        else:
            (seconds,) = struct.unpack_from(">I", payload, 4)
    except struct.error:
        return None
    if not seconds:
        return None
    try:
        return _iso(_EPOCH_1904 + timedelta(seconds=seconds))
    except (OverflowError, ValueError):
        return None


def _atom_text(payload: bytes) -> str | None:
    """Decode the text an atom carries, in either of the two layouts.

    QuickTime writes a two-byte length and a language code before the string.
    The iTunes-style metadata that ``ilst`` uses instead nests a ``data`` box
    holding a type and a locale, and reading that as text yields the literal
    word "data" in front of every value.
    """
    body = payload
    if len(body) >= 16 and body[4:8] == b"data":
        (size,) = struct.unpack_from(">I", body, 0)
        end = min(size, len(body)) if size > 16 else len(body)
        body = body[16:end]
    elif len(body) >= 4:
        (declared,) = struct.unpack_from(">H", body, 0)
        if 0 < declared <= len(body) - 4:
            body = body[4 : 4 + declared]

    text = body.decode("utf-8", "replace").strip().strip("\x00").strip()
    return text or None


def _iso6709(text: str) -> tuple[float, float] | None:
    match = _ISO6709.match(text.strip())
    if not match:
        return None
    latitude, longitude = float(match.group(1)), float(match.group(2))
    if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
        return None
    return round(latitude, 6), round(longitude, 6)


def _normalise(text: str) -> str | None:
    for pattern in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%Y"):
        try:
            parsed = datetime.strptime(text.strip(), pattern)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return _iso(parsed)
    return None


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
