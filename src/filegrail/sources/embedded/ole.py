"""Compound File Binary documents: the Office formats that predate OOXML.

A `.doc`, `.xls` or `.ppt` is a small filesystem in a file. Its provenance sits
in two streams that every Office release has written since 1995:

    \\x05SummaryInformation          the application, the author, the last
                                    editor, the title and the creation date
    \\x05DocumentSummaryInformation  the company, and the manager

Both are property sets, a format shared with Windows shell metadata, so the
parser here is a general one pointed at two known FMTIDs. The compound-file
directory also carries storage timestamps and CLSIDs, while selected stream
structures expose bounded VBA, XLM and embedded-object evidence.

These files are still everywhere - government portals, journal supplements and
scanned archives hand them out daily - and their metadata is often richer than
the modern equivalent, because nobody has thought to strip it.
"""

from __future__ import annotations

import functools
import struct
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

SUFFIXES = {".doc", ".xls", ".ppt", ".dot", ".xlt", ".pps", ".pot", ".msg"}

_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_ENDOFCHAIN = 0xFFFFFFFE
_FREESECT = 0xFFFFFFFF

#: A directory entry is fixed width, and its name is UTF-16.
_ENTRY_SIZE = 128
_STORAGE = 1
_STREAM = 2
_ROOT = 5

#: Guards against a crafted file describing a chain that never ends.
_MAX_SECTORS = 1 << 18
_MAX_ENTRIES = 4096
_MAX_PROPERTIES = 256
_MAX_STRING = 1024
_MAX_PACKAGE_STRING = 4096
_MAX_BIFF_RECORDS = 100_000

# Property set format identifiers, little-endian on disk.
_SUMMARY = bytes.fromhex("e0859ff2f94f6810ab9108002b27b3d9")
_DOCUMENT_SUMMARY = bytes.fromhex("02d5cdd59c2e1b10939708002b2cf9ae")

# SummaryInformation property ids.
_TITLE = 2
_AUTHOR = 4
_LAST_AUTHOR = 8
_CREATED = 12
_APPLICATION = 18

# DocumentSummaryInformation property ids.
_COMPANY = 15

_VT_I2 = 2
_VT_I4 = 3
_VT_LPSTR = 30
_VT_LPWSTR = 31
_VT_FILETIME = 64

#: FILETIME counts 100ns intervals from 1601-01-01.
_EPOCH_1601 = datetime(1601, 1, 1, tzinfo=timezone.utc)


@dataclass(slots=True)
class Storage:
    """Directory metadata recorded for one compound-file storage."""

    name: str
    clsid: str | None = None
    created: str | None = None
    modified: str | None = None


@dataclass(slots=True)
class EmbeddedObject:
    """Paths and payload size exposed by an OLE Packager object."""

    filename: str | None
    source_path: str | None
    temp_path: str | None
    size: int


@dataclass(slots=True)
class OrphanedEntry:
    """An allocated directory entry unreachable from the root tree."""

    name: str
    kind: str
    clsid: str | None
    created: str | None
    modified: str | None
    size: int


@dataclass(slots=True)
class Document:
    """What a compound document says about its own creation."""

    tool: str | None = None
    author: str | None = None
    last_author: str | None = None
    company: str | None = None
    created: str | None = None
    title: str | None = None
    root_clsid: str | None = None
    storages: list[Storage] = field(default_factory=list)
    vba_storage: bool = False
    xlm_macro_sheets: int = 0
    native_streams: int = 0
    embedded_objects: list[EmbeddedObject] = field(default_factory=list)
    orphaned_entries: list[OrphanedEntry] = field(default_factory=list)

    def __bool__(self) -> bool:
        return any(
            (
                self.tool,
                self.author,
                self.last_author,
                self.company,
                self.created,
                self.title,
                self.root_clsid,
                self.storages,
                self.vba_storage,
                self.xlm_macro_sheets,
                self.native_streams,
                self.embedded_objects,
                self.orphaned_entries,
            )
        )


def read_ole(path: Path) -> Document | None:
    """Return what a compound document says about itself, or None."""
    try:
        with path.open("rb") as handle:
            data = handle.read()
    except OSError:
        return None
    if not data.startswith(_SIGNATURE):
        return None

    try:
        container = _Container(data)
        found = Document()
        _apply(found, container.stream("\x05SummaryInformation"), _SUMMARY)
        _apply(found, container.stream("\x05DocumentSummaryInformation"), _DOCUMENT_SUMMARY)
        _apply_directory(found, container)
    except (struct.error, ValueError, IndexError):
        return None
    return found if found else None


def read_streams(path: Path, names: Iterable[str]) -> dict[str, bytes]:
    """Return whichever of the named streams a compound document holds.

    Exposed because not every compound document is an Office one. An Outlook
    `.msg` is this same container carrying a message instead of a spreadsheet,
    and its reader has no business walking a FAT of its own.
    """
    try:
        with path.open("rb") as handle:
            data = handle.read()
    except OSError:
        return {}
    if not data.startswith(_SIGNATURE):
        return {}

    try:
        container = _Container(data)
        found = {}
        for name in names:
            raw = container.stream(name)
            if raw is not None:
                found[name] = raw
    except (struct.error, ValueError, IndexError):
        return {}
    return found


def entries(data: bytes) -> dict[str, Callable[[], bytes] | None]:
    """Every storage and stream of a compound document given as bytes, by path.

    A stream maps to a function reading it, so a caller asking only which
    entries exist reads none of them; a storage maps to None.
    """
    if not data.startswith(_SIGNATURE):
        return {}
    found: dict[str, Callable[[], bytes] | None] = {}
    try:
        container = _Container(data)
        for path, entry in container.walk():
            found[path] = (
                functools.partial(container.entry_stream, entry) if entry.kind == _STREAM else None
            )
    except (struct.error, ValueError, IndexError):
        return found
    return found


def packaged_objects(data: bytes) -> list[tuple[str, bytes]]:
    """The files wrapped by OLE Packager in a compound document given as bytes.

    Each is named by its place: the storage that holds the Ole10Native stream,
    then the file name Packager recorded, `ObjectPool/_1234/invoice.pdf`.
    """
    if not data.startswith(_SIGNATURE):
        return []
    found = []
    try:
        container = _Container(data)
        for path, entry in container.walk():
            if entry.kind != _STREAM or entry.name.casefold() != "\x01ole10native":
                continue
            parsed = _parse_packager(container.entry_stream(entry))
            if parsed is None or not parsed[0].filename:
                continue
            folder = path.rpartition("/")[0]
            name = Path(parsed[0].filename).name
            found.append((f"{folder}/{name}" if folder else name, parsed[1]))
    except (struct.error, ValueError, IndexError):
        return found
    return found


#: [MS-OXMSG]: each attachment is a storage named for its index, holding the
#: bytes under property 3701 typed binary and the name under 3707 (long) or
#: 3704 (short), typed 001F for UTF-16 text and 001E for 8-bit.
_ATTACHMENT_STORAGE = "__attach_version1.0_#"
_ATTACHMENT_DATA = "__substg1.0_37010102"
_ATTACHMENT_NAMES = (
    "__substg1.0_3707001F",
    "__substg1.0_3707001E",
    "__substg1.0_3704001F",
    "__substg1.0_3704001E",
)


def attachments(data: bytes) -> list[tuple[str, bytes]]:
    """The files attached to a message stored as a compound document.

    An attachment that is itself a message is a storage rather than a byte
    stream, and its own attachments are its own; neither is listed here.
    """
    if not data.startswith(_SIGNATURE):
        return []
    storages: dict[str, dict[str, bytes]] = {}
    try:
        container = _Container(data)
        for path, entry in container.walk():
            folder, _, name = path.rpartition("/")
            if entry.kind != _STREAM or not folder.startswith(_ATTACHMENT_STORAGE):
                continue
            if name == _ATTACHMENT_DATA or name in _ATTACHMENT_NAMES:
                storages.setdefault(folder, {})[name] = container.entry_stream(entry)
    except (struct.error, ValueError, IndexError):
        return []
    found = []
    for folder in sorted(storages):
        streams = storages[folder]
        raw = streams.get(_ATTACHMENT_DATA)
        filename = next(
            (text for key in _ATTACHMENT_NAMES if (text := _property_text(key, streams.get(key)))),
            None,
        )
        if raw is not None and filename:
            found.append((Path(filename).name, raw))
    return found


def _property_text(name: str, raw: bytes | None) -> str | None:
    """Decode a property stream by the type its name declares."""
    if raw is None:
        return None
    if name.endswith("001F"):
        if len(raw) % 2:
            return None
        return raw.decode("utf-16-le", "replace").rstrip("\x00") or None
    return raw.decode("utf-8", "replace").rstrip("\x00") or None


# --- the container -----------------------------------------------------------


class _Container:
    """Enough of the compound file to resolve a named stream to its bytes."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        (minor,) = struct.unpack_from("<H", data, 24)
        sector_shift, mini_shift = struct.unpack_from("<HH", data, 30)
        if not 6 <= sector_shift <= 20 or not 2 <= mini_shift <= sector_shift:
            raise ValueError("implausible sector size")

        self.sector_size = 1 << sector_shift
        self.mini_size = 1 << mini_shift
        (fat_count,) = struct.unpack_from("<I", data, 44)
        (self.directory_start,) = struct.unpack_from("<I", data, 48)
        (self.cutoff,) = struct.unpack_from("<I", data, 56)
        mini_fat_start, mini_fat_count = struct.unpack_from("<II", data, 60)
        difat_start, difat_count = struct.unpack_from("<II", data, 68)
        self.version = minor

        self.fat = self._read_fat(fat_count, difat_start, difat_count)
        self.mini_fat = self._read_table(mini_fat_start, mini_fat_count * self.sector_size)
        self.entries = self._read_directory()

        root = self.entries[0] if self.entries else None
        self.active = self._active_indices(root)
        self.mini_stream = b""
        if root and root.kind == _ROOT and root.size:
            self.mini_stream = self._read_chain(root.start, root.size, self.fat, self.sector_size)

    # -- sector plumbing --

    def _sector(self, index: int) -> bytes:
        offset = (index + 1) * self.sector_size
        chunk = self.data[offset : offset + self.sector_size]
        if len(chunk) < self.sector_size:
            raise ValueError("sector past end of file")
        return chunk

    def _read_fat(self, count: int, difat_start: int, difat_count: int) -> list[int]:
        """Collect the FAT from the sectors the DIFAT points at."""
        locations = [
            value
            for (value,) in struct.iter_unpack("<I", self.data[76 : 76 + 109 * 4])
            if value < _FREESECT - 1
        ][:count]

        sector = difat_start
        seen = 0
        while sector < _FREESECT - 1 and seen < difat_count and seen < _MAX_SECTORS:
            block = self._sector(sector)
            entries = [value for (value,) in struct.iter_unpack("<I", block)]
            locations.extend(value for value in entries[:-1] if value < _FREESECT - 1)
            sector = entries[-1]
            seen += 1

        table: list[int] = []
        for location in locations[:_MAX_SECTORS]:
            table.extend(value for (value,) in struct.iter_unpack("<I", self._sector(location)))
        return table

    def _read_table(self, start: int, size: int) -> list[int]:
        if start >= _FREESECT - 1 or size <= 0:
            return []
        blob = self._read_chain(start, size, self.fat, self.sector_size)
        return [value for (value,) in struct.iter_unpack("<I", blob[: len(blob) // 4 * 4])]

    def _read_chain(self, start: int, size: int, table: list[int], unit: int) -> bytes:
        """Follow a sector chain, stopping at its end or at the declared size."""
        out = bytearray()
        sector = start
        visited = 0
        while sector < _FREESECT - 1 and len(out) < size and visited < _MAX_SECTORS:
            if unit == self.sector_size:
                out += self._sector(sector)
            else:
                offset = sector * unit
                out += self.mini_stream[offset : offset + unit]
            if sector >= len(table):
                break
            sector = table[sector]
            visited += 1
        return bytes(out[:size])

    # -- directory --

    def _read_directory(self) -> list[_Entry | None]:
        blob = self._read_chain(
            self.directory_start, _MAX_ENTRIES * _ENTRY_SIZE, self.fat, self.sector_size
        )
        entries: list[_Entry | None] = []
        for offset in range(0, len(blob) - _ENTRY_SIZE + 1, _ENTRY_SIZE):
            entries.append(_Entry.parse(blob[offset : offset + _ENTRY_SIZE]))
        return entries

    def _active_indices(self, root: _Entry | None) -> set[int]:
        """Walk the directory's sibling trees from the root storage."""
        if root is None or root.kind != _ROOT:
            return set()
        active = {0}
        pending = [root.child]
        while pending and len(active) <= _MAX_ENTRIES:
            index = pending.pop()
            if index in active or not 0 <= index < len(self.entries):
                continue
            entry = self.entries[index]
            if entry is None:
                continue
            active.add(index)
            pending.extend((entry.left, entry.right))
            if entry.kind == _STORAGE:
                pending.append(entry.child)
        return active

    def active_entries(self) -> Iterable[_Entry]:
        for index in sorted(self.active):
            entry = self.entries[index]
            if entry is not None:
                yield entry

    def walk(self) -> Iterable[tuple[str, _Entry]]:
        """Every reachable entry with its path below the root, `storage/stream`."""
        root = self.entries[0] if self.entries else None
        if root is None or root.kind != _ROOT:
            return
        seen: set[int] = set()
        pending = [(root.child, "")]
        while pending and len(seen) <= _MAX_ENTRIES:
            index, folder = pending.pop()
            if index in seen or not 0 <= index < len(self.entries):
                continue
            entry = self.entries[index]
            if entry is None:
                continue
            seen.add(index)
            pending.extend(((entry.left, folder), (entry.right, folder)))
            path = f"{folder}/{entry.name}" if folder else entry.name
            yield path, entry
            if entry.kind == _STORAGE:
                pending.append((entry.child, path))

    def orphaned_entries(self) -> Iterable[_Entry]:
        if 0 not in self.active:
            return
        for index, entry in enumerate(self.entries):
            if index not in self.active and entry is not None:
                yield entry

    def stream(self, name: str) -> bytes | None:
        for entry in self.active_entries():
            if entry.kind == _STREAM and entry.name == name:
                return self.entry_stream(entry)
        return None

    def entry_stream(self, entry: _Entry) -> bytes:
        """Read one already-resolved stream entry."""
        if entry.size < self.cutoff and self.mini_stream:
            return self._read_chain(entry.start, entry.size, self.mini_fat, self.mini_size)
        return self._read_chain(entry.start, entry.size, self.fat, self.sector_size)


@dataclass(slots=True)
class _Entry:
    name: str
    kind: int
    start: int
    size: int
    clsid: str | None
    created: str | None
    modified: str | None
    left: int
    right: int
    child: int

    @classmethod
    def parse(cls, raw: bytes) -> _Entry | None:
        (length,) = struct.unpack_from("<H", raw, 64)
        kind = raw[66]
        if kind not in (_STORAGE, _STREAM, _ROOT) or not 2 <= length <= 64:
            return None
        name = raw[: length - 2].decode("utf-16-le", "replace")
        left, right, child = struct.unpack_from("<III", raw, 68)
        clsid = _guid(raw[80:96])
        created, modified = struct.unpack_from("<QQ", raw, 100)
        start, size = struct.unpack_from("<IQ", raw, 116)
        return cls(
            name=name,
            kind=kind,
            start=start,
            size=size,
            clsid=clsid,
            created=_timestamp(created),
            modified=_timestamp(modified),
            left=left,
            right=right,
            child=child,
        )


def _apply_directory(found: Document, container: _Container) -> None:
    """Keep bounded directory evidence without interpreting document content."""
    root = container.entries[0] if container.entries else None
    if root is not None and root.kind == _ROOT:
        found.root_clsid = root.clsid
    workbook = container.stream("Workbook") or container.stream("Book")
    found.xlm_macro_sheets = _xlm_macro_sheets(workbook)

    for entry in container.active_entries():
        if entry.kind == _STORAGE:
            if entry.name.casefold() == "vba":
                found.vba_storage = True
            if entry.clsid or entry.created or entry.modified:
                found.storages.append(
                    Storage(entry.name, entry.clsid, entry.created, entry.modified)
                )
        elif entry.kind == _STREAM and entry.name.casefold() == "\x01ole10native":
            found.native_streams += 1
            if package := _read_packager(container.entry_stream(entry)):
                found.embedded_objects.append(package)

    for entry in container.orphaned_entries():
        is_storage = entry.kind == _STORAGE
        found.orphaned_entries.append(
            OrphanedEntry(
                name=entry.name,
                kind="storage" if is_storage else "stream",
                clsid=entry.clsid if is_storage else None,
                created=entry.created if is_storage else None,
                modified=entry.modified if is_storage else None,
                size=entry.size,
            )
        )


def _xlm_macro_sheets(blob: bytes | None) -> int:
    """Count BIFF BoundSheet records explicitly typed as macro sheets."""
    if not blob or len(blob) < 8:
        return 0
    first, first_size = struct.unpack_from("<HH", blob)
    if first != 0x0809 or first_size < 4 or first_size + 4 > len(blob):
        return 0
    (version,) = struct.unpack_from("<H", blob, 4)
    if version not in (0x0500, 0x0600):  # BIFF5 and BIFF8
        return 0

    found = 0
    offset = 0
    records = 0
    while offset + 4 <= len(blob) and records < _MAX_BIFF_RECORDS:
        identifier, size = struct.unpack_from("<HH", blob, offset)
        body = offset + 4
        end = body + size
        if end > len(blob):
            break
        # BoundSheet8: stream position, visibility, then the sheet type.
        if identifier == 0x0085 and size >= 6 and blob[body + 5] == 0x01:
            found += 1
        offset = end
        records += 1
    return found


def _guid(raw: bytes) -> str | None:
    """Decode a CFB CLSID, leaving the all-zero sentinel absent."""
    if len(raw) != 16 or not any(raw):
        return None
    return str(uuid.UUID(bytes_le=raw))


def _read_packager(blob: bytes) -> EmbeddedObject | None:
    parsed = _parse_packager(blob)
    return parsed[0] if parsed is not None else None


def _parse_packager(blob: bytes) -> tuple[EmbeddedObject, bytes] | None:
    """Decode the common OLE Packager layout inside an Ole10Native stream.

    Ole10Native itself only promises a sized opaque payload. Packager adds the
    three paths below, so the layout is accepted only when every boundary and
    terminator is present rather than treating arbitrary native data as paths.
    """
    if len(blob) < 6:
        return None
    (declared,) = struct.unpack_from("<I", blob)
    if declared < 2 or declared > len(blob) - 4:
        return None
    body = blob[4 : 4 + declared]
    cursor = 2  # Packager's leading marker; not provenance evidence.
    filename, cursor = _package_text(body, cursor)
    if cursor < 0:
        return None
    source_path, cursor = _package_text(body, cursor)
    if cursor < 0 or cursor + 8 > len(body):
        return None
    cursor += 8  # Two Packager implementation fields.
    temp_path, cursor = _package_text(body, cursor)
    if cursor < 0 or cursor + 4 > len(body):
        return None
    (size,) = struct.unpack_from("<I", body, cursor)
    cursor += 4
    if size > len(body) - cursor or not any((filename, source_path, temp_path)):
        return None
    return EmbeddedObject(filename, source_path, temp_path, size), body[cursor : cursor + size]


def _package_text(blob: bytes, offset: int) -> tuple[str | None, int]:
    limit = min(len(blob), offset + _MAX_PACKAGE_STRING + 1)
    end = blob.find(b"\x00", offset, limit)
    if end < 0:
        return None, -1
    raw = blob[offset:end]
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError:
        value = raw.decode("cp1252", "replace")
    cleaned = value.strip()
    if any(ord(character) < 32 for character in cleaned):
        return None, -1
    return cleaned or None, end + 1


# --- property sets -----------------------------------------------------------


def _apply(found: Document, blob: bytes | None, fmtid: bytes) -> None:
    if not blob:
        return
    properties = _read_property_set(blob, fmtid)
    if not properties:
        return

    if fmtid == _SUMMARY:
        found.tool = found.tool or _text(properties.get(_APPLICATION))
        found.author = found.author or _text(properties.get(_AUTHOR))
        found.last_author = found.last_author or _text(properties.get(_LAST_AUTHOR))
        found.title = found.title or _text(properties.get(_TITLE))
        found.created = found.created or _timestamp(properties.get(_CREATED))
    else:
        found.company = found.company or _text(properties.get(_COMPANY))


def _read_property_set(blob: bytes, fmtid: bytes) -> dict[int, object]:
    """Decode the first section whose format identifier matches."""
    if len(blob) < 48 or blob[:2] != b"\xfe\xff":
        return {}
    (count,) = struct.unpack_from("<I", blob, 24)

    for index in range(min(count, 8)):
        base = 28 + index * 20
        if base + 20 > len(blob):
            return {}
        identifier = blob[base : base + 16]
        (offset,) = struct.unpack_from("<I", blob, base + 16)
        if identifier == fmtid:
            return _read_section(blob, offset)
    return {}


def _read_section(blob: bytes, base: int) -> dict[int, object]:
    if base + 8 > len(blob):
        return {}
    size, count = struct.unpack_from("<II", blob, base)
    if size <= 0 or base + size > len(blob) + 1:
        size = len(blob) - base

    found: dict[int, object] = {}
    for index in range(min(count, _MAX_PROPERTIES)):
        entry = base + 8 + index * 8
        if entry + 8 > len(blob):
            break
        identifier, offset = struct.unpack_from("<II", blob, entry)
        value = _read_value(blob, base + offset)
        if value is not None:
            found[identifier] = value
    return found


def _read_value(blob: bytes, offset: int) -> object | None:
    if offset + 4 > len(blob) or offset < 0:
        return None
    (kind,) = struct.unpack_from("<I", blob, offset)
    body = offset + 4

    if kind in (_VT_LPSTR, _VT_LPWSTR):
        if body + 4 > len(blob):
            return None
        (length,) = struct.unpack_from("<I", blob, body)
        if kind == _VT_LPWSTR:
            length *= 2
        if not 0 < length <= _MAX_STRING or body + 4 + length > len(blob):
            return None
        raw = blob[body + 4 : body + 4 + length]
        encoding = "utf-16-le" if kind == _VT_LPWSTR else "utf-8"
        return raw.split(b"\x00\x00" if kind == _VT_LPWSTR else b"\x00")[0].decode(
            encoding, "replace"
        )

    if kind == _VT_FILETIME:
        if body + 8 > len(blob):
            return None
        (ticks,) = struct.unpack_from("<Q", blob, body)
        return ticks or None

    if kind in (_VT_I2, _VT_I4):
        width = 2 if kind == _VT_I2 else 4
        if body + width > len(blob):
            return None
        return int(struct.unpack_from("<h" if kind == _VT_I2 else "<i", blob, body)[0])

    return None


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().strip("\x00").strip()
    return cleaned or None


def _timestamp(value: object) -> str | None:
    """Turn a FILETIME into an ISO instant, rejecting implausible ones."""
    if not isinstance(value, int) or value <= 0:
        return None
    try:
        moment = _EPOCH_1601 + timedelta(microseconds=value // 10)
    except (OverflowError, OSError, ValueError):
        return None
    if not 1980 <= moment.year <= 2100:
        return None
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
