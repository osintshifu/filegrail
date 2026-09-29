"""Which format a file is, by its bytes, in the terms of the PRONOM registry.

PRONOM is the registry of file formats kept by The National Archives. Each
format has a persistent identifier, its PUID, and the byte patterns that
identify it. DROID and Siegfried identify files against the same registry, so a
PUID from here means the same thing in their reports and in any archive that
recorded one.

The registry ships compiled inside the package, as `data/pronom.json`, built by
`tools/build_pronom.py` from one signature file and one container signature
file. Their versions travel with every identification, because the same bytes
can be named differently by a later release of the registry.

What is read, following DROID's defaults: the first and the last 64 KiB of the
file. A pattern that needs bytes from the middle of a larger file is not
matched, and a file matched by nothing is not identified - no guess from its
name is offered in place of the bytes. A zip or a compound document is opened
when the registry says its internal signature is only a container, and the
container's members decide the format: a `.docx` is a zip, and PRONOM names it
by `word/document.xml`.

Where several formats match and none has priority over the others, all of them
are returned. The registry does not choose between them and neither does this.
"""

from __future__ import annotations

import json
import re
import struct
import zipfile
import zlib
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

#: How much of each end of the file is read, as in DROID's default profile.
WINDOW = 64 * 1024

#: How much of one member of a container its signatures may read.
MEMBER_LIMIT = WINDOW

#: A compound document is read whole to find its streams. Past this size it is
#: not opened, and is named by its own signature as a compound document.
OLE_LIMIT = 256 * 1024 * 1024

_ZIP = "ZIP"
_OLE2 = "OLE2"


@dataclass(frozen=True, slots=True)
class Format:
    """One format the bytes of a file match."""

    puid: str
    name: str
    version: str
    mime: str
    extensions: tuple[str, ...]
    #: `signature` where the file's own bytes matched, `container` where the
    #: members of the zip or compound document it is decided the format.
    basis: str

    def to_dict(self) -> dict[str, object]:
        return {
            "puid": self.puid,
            "name": self.name,
            "version": self.version,
            "mime": self.mime,
            "basis": self.basis,
        }


@dataclass(frozen=True, slots=True)
class _Piece:
    alternatives: tuple[tuple[int, re.Pattern[bytes]], ...]


class _Registry:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.signature_file = raw["signature_file"]
        self.container_file = raw["container_file"]
        self.formats: dict[str, dict[str, Any]] = raw["formats"]
        self.signatures = {
            key: _ordered([_sequence(sequence) for sequence in sequences])
            for key, sequences in raw["signatures"].items()
        }
        # Most signatures open with a byte at offset 0. Filed under that byte,
        # a file is tried only against the ones its first byte can start.
        self.opening: dict[int, list[str]] = {}
        self.always: list[str] = []
        for key, sequences in self.signatures.items():
            firsts = _opening(sequences)
            if firsts is None:
                self.always.append(key)
            for first in firsts or ():
                self.opening.setdefault(first, []).append(key)
        self.by_signature: dict[str, list[str]] = {}
        for key, entry in self.formats.items():
            for signature in entry["signatures"]:
                self.by_signature.setdefault(signature, []).append(key)
        self.by_puid: dict[str, list[str]] = {}
        for key, entry in self.formats.items():
            self.by_puid.setdefault(entry["puid"], []).append(key)
        containers = raw["containers"]
        self.triggers: dict[str, set[str]] = {
            kind: set(puids) for kind, puids in containers["triggers"].items()
        }
        self.containers = [
            (
                signature["type"],
                signature["puid"],
                [
                    (
                        path,
                        None
                        if binary is None
                        else [
                            _ordered([_sequence(sequence) for sequence in one]) for one in binary
                        ],
                    )
                    for path, binary in signature["files"]
                ],
            )
            for signature in containers["signatures"]
        ]

    def describe(self) -> dict[str, str]:
        """Which release of the registry named the formats."""
        return {
            "registry": "PRONOM",
            "signature_file": f"DROID_SignatureFile_V{self.signature_file['version']}.xml",
            "container_file": self.container_file["name"],
        }

    def formats_of(self, keys: set[str], basis: str) -> list[Format]:
        beaten = {loser for key in keys for loser in self.formats[key]["over"]}
        found = []
        for key in sorted(keys - beaten, key=lambda k: self.formats[k]["puid"]):
            entry = self.formats[key]
            found.append(
                Format(
                    puid=entry["puid"],
                    name=entry["name"],
                    version=entry["version"],
                    mime=entry["mime"],
                    extensions=tuple(entry["extensions"]),
                    basis=basis,
                )
            )
        return found


#: A pattern that is nothing but bytes, as the compiler writes them.
_LITERAL = re.compile(r"(?:[0-9A-Za-z]|\\x[0-9a-f]{2})+")


def _needle(steps: list[Any]) -> bytes:
    """The longest run of plain bytes every match of the sequence contains."""
    longest = b""
    for step in steps:
        if isinstance(step[0], int) or len(step) != 1:
            continue
        pattern = step[0][1]
        if _LITERAL.fullmatch(pattern):
            value = pattern.encode("latin-1").decode("unicode_escape").encode("latin-1")
            longest = max(longest, value, key=len)
    return longest


def _sequence(raw: list[Any]) -> tuple[str, bytes, list[Any]]:
    anchor, steps = raw
    compiled: list[Any] = []
    for step in steps:
        if isinstance(step[0], int):
            compiled.append((step[0], step[1]))
        else:
            compiled.append(
                _Piece(
                    tuple(
                        (length, re.compile(pattern.encode("latin-1"), re.S))
                        for length, pattern in step
                    )
                )
            )
    # Worth looking for only where the sequence may sit anywhere: a scan for
    # the needle costs more than trying a sequence tied to either end.
    return anchor, _needle(steps) if anchor == "V" else b"", compiled


_FIRST = re.compile(rb"([0-9A-Za-z])|\\x([0-9a-f]{2})")


def _opening(sequences: list[tuple[str, bytes, list[Any]]]) -> set[int] | None:
    """The bytes a match must open the file with, or None where any may."""
    anchor, _, steps = sequences[0]
    if anchor != "B" or not steps or not isinstance(steps[0], _Piece):
        return None
    firsts = set()
    for _, pattern in steps[0].alternatives:
        found = _FIRST.match(pattern.pattern)
        if found is None:
            return None
        firsts.add(found.group(1)[0] if found.group(1) else int(found.group(2), 16))
    return firsts


#: Cheapest first: a sequence at the start is tried at one offset, one at the
#: end at a few, and one that may sit anywhere is searched for.
_COST = {"B": 0, "E": 1, "V": 2}


def _ordered(sequences: list[tuple[str, bytes, list[Any]]]) -> list[tuple[str, bytes, list[Any]]]:
    return sorted(sequences, key=lambda sequence: _COST[sequence[0]])


@cache
def registry() -> _Registry:
    path = Path(__file__).parent / "data" / "pronom.json"
    return _Registry(json.loads(path.read_text(encoding="utf-8")))


class _View:
    """The first and the last bytes of a file, as far as they were read.

    A sequence tied to the start is looked for in the head and one tied to the
    end in the tail, the way DROID reads them. Nothing is assumed of the bytes
    between the two in a larger file: a sequence that would need them is not
    matched.
    """

    def __init__(self, head: bytes, tail: bytes, size: int) -> None:
        self.head = head
        self.tail = tail
        self.size = size

    @classmethod
    def of(cls, data: bytes) -> _View:
        return cls(data[:WINDOW], data[-WINDOW:], len(data))

    def holds(self, needle: bytes) -> bool:
        """Whether the bytes occur in the head."""
        return needle in self.head

    def starts(
        self, anchor: str, length: int, pattern: re.Pattern[bytes], low: int, high: int
    ) -> list[int]:
        """Every offset in `low..high` where `length` bytes match in full."""
        data, offset = (self.tail, self.size - len(self.tail)) if anchor == "E" else (self.head, 0)
        first = max(low, offset) - offset
        last = min(high, offset + len(data) - length) - offset
        found = []
        while first <= last:
            match = pattern.search(data, first, last + length)
            if match is None:
                break
            found.append(offset + match.start())
            first = match.start() + 1
        return found


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if start > end:
            continue
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _matches(view: _View, anchor: str, steps: list[Any]) -> bool:
    """Whether the steps of one byte sequence can all be placed in the file.

    Walked as sets of offsets rather than by backtracking: each piece turns the
    offsets it may start at into the offsets it ends at, and each gap widens
    them. The work is bounded by the bytes read, whatever the pattern.
    From the end of the file the same walk runs right to left, over the offsets
    where pieces end.
    """
    size = view.size
    if anchor == "E":
        spans = [(size, size)]
        for step in reversed(steps):
            if isinstance(step, _Piece):
                starts = [
                    (start, start)
                    for length, pattern in step.alternatives
                    for low, high in spans
                    for start in view.starts(anchor, length, pattern, low - length, high - length)
                ]
                spans = _merge(starts)
            else:
                low, high = step
                spans = _merge(
                    [(0 if high is None else start - high, end - low) for start, end in spans]
                )
            if not spans:
                return False
        return True
    spans = [(0, size)] if anchor == "V" else [(0, 0)]
    for step in steps:
        if isinstance(step, _Piece):
            ends = [
                (start + length, start + length)
                for length, pattern in step.alternatives
                for low, high in spans
                for start in view.starts(anchor, length, pattern, low, high)
            ]
            spans = _merge(ends)
        else:
            low, high = step
            spans = _merge(
                [(start + low, size if high is None else end + high) for start, end in spans]
            )
        if not spans:
            return False
    return True


def _signature_matches(view: _View, sequences: list[tuple[str, bytes, list[Any]]]) -> bool:
    return all(
        view.holds(needle) and _matches(view, anchor, steps) for anchor, needle, steps in sequences
    )


def _internal(view: _View) -> set[str]:
    """The registry's format keys whose internal signatures the bytes match."""
    found: set[str] = set()
    known = registry()
    candidates = known.always + known.opening.get(view.head[0], []) if view.head else known.always
    for key in candidates:
        if _signature_matches(view, known.signatures[key]):
            found.update(known.by_signature.get(key, ()))
    return found


def _read(path: Path) -> _View | None:
    try:
        with path.open("rb") as handle:
            head = handle.read(WINDOW)
            size = handle.seek(0, 2)
            if size <= WINDOW:
                return _View(head, head, size)
            handle.seek(size - WINDOW)
            return _View(head, handle.read(WINDOW), size)
    except OSError:
        return None


_TRIM = "".join(chr(value) for value in range(33))


def _zip_members(archive: zipfile.ZipFile) -> dict[str, Any]:
    """Each member of a zip by name, read on demand up to `MEMBER_LIMIT`."""
    members: dict[str, Any] = {}
    for info in archive.infolist():

        def read(info: zipfile.ZipInfo = info) -> bytes:
            with archive.open(info) as member:
                return member.read(MEMBER_LIMIT)

        members[info.filename] = None if info.is_dir() else (read, info.file_size)
        # A folder named only by the files inside it is still in the zip.
        folder = info.filename
        while "/" in folder.rstrip("/"):
            folder = folder.rstrip("/").rpartition("/")[0] + "/"
            members.setdefault(folder, None)
    return members


def _ole_members(path: Path) -> dict[str, Any]:
    from .sources.embedded.ole import entries

    try:
        if path.stat().st_size > OLE_LIMIT:
            return {}
        data = path.read_bytes()
    except OSError:
        return {}
    members: dict[str, Any] = {}
    for name, reader in entries(data).items():
        # DROID trims each name, which drops the control character that
        # opens `\x05SummaryInformation`; the registry names it without.
        trimmed = "/".join(part.strip(_TRIM) for part in name.split("/"))
        members[trimmed] = None if reader is None else (reader, None)
    return members


def _member_matches(member: Any, binary: list[list[tuple[str, bytes, list[Any]]]] | None) -> bool:
    if binary is None:
        return True
    if member is None:
        return False
    read, size = member
    try:
        data = read()
    except (
        OSError,
        EOFError,
        struct.error,
        zlib.error,
        zipfile.BadZipFile,
        NotImplementedError,
        # An encrypted member, which the zip module will not read.
        RuntimeError,
        ValueError,
        IndexError,
    ):
        return False
    # A zip member is read only as far as its head; the registry ties no
    # sequence in a zip member to its end.
    whole = size is None or len(data) >= size
    view = _View.of(data) if whole else _View(data, b"", size)
    return any(_signature_matches(view, signature) for signature in binary)


def _container(path: Path, kind: str) -> set[str]:
    if kind == _OLE2:
        return _decide(_ole_members(path), kind)
    if kind != _ZIP:
        return set()
    try:
        with zipfile.ZipFile(path) as archive:
            return _decide(_zip_members(archive), kind)
    except (OSError, zipfile.BadZipFile, NotImplementedError, ValueError):
        return set()


def _decide(members: dict[str, Any], kind: str) -> set[str]:
    """The formats whose container signatures these members satisfy."""
    if not members:
        return set()
    known = registry()
    found: set[str] = set()
    for container_kind, puid, files in known.containers:
        if container_kind != kind:
            continue
        if all(
            name in members and _member_matches(members[name], binary) for name, binary in files
        ):
            found.update(known.by_puid.get(puid, ()))
    return found


def identify(path: Path) -> list[Format]:
    """The formats the bytes of the file at `path` match, by PUID.

    Empty where nothing in the registry matches what was read.
    """
    view = _read(path)
    if view is None or view.size == 0:
        return []
    known = registry()
    keys = _internal(view)
    puids = {known.formats[key]["puid"] for key in keys}
    for kind, triggers in known.triggers.items():
        if puids & triggers:
            inside = _container(path, kind)
            if inside:
                return known.formats_of(inside, "container")
    return known.formats_of(keys, "signature")
