"""Windows executables: what a PE file says about its own building.

Three parts of a portable executable record how it came to exist, and none of
them is needed to run it, which is why they survive:

    COFF header        the machine it targets, the linker version and the
                       moment it was linked
    debug directory    the path of the program database on the build machine,
                       which often names the developer and the project
    version resource   what the publisher says it is: company, product, the
                       original file name before anyone renamed it

The reader follows the headers by their own offsets and reads only the parts it
names. It never maps the image, follows an import, or reads a section it has no
question for.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

SUFFIXES = {".exe", ".dll", ".sys", ".scr", ".ocx", ".cpl", ".drv", ".efi"}

_DOS_MAGIC = b"MZ"
_PE_MAGIC = b"PE\x00\x00"
_RICH_END = b"Rich"
_RICH_START = b"DanS"
_CODEVIEW = b"RSDS"

_MAX_HEADERS = 4 * 1024 * 1024
_MAX_SECTIONS = 96
_MAX_RESOURCE = 1024 * 1024
_MAX_DEBUG_ENTRIES = 32
_MAX_RICH_ENTRIES = 64
_MAX_RICH_LISTED = 8
_MAX_STRINGS = 32
_MAX_TEXT = 512
_MAX_RESOURCE_DEPTH = 4

_DIRECTORY_RESOURCE = 2
_DIRECTORY_SECURITY = 4
_DIRECTORY_DEBUG = 6
_RT_VERSION = 16
_DEBUG_CODEVIEW = 2
_DEBUG_REPRO = 16

_MACHINES = {
    0x014C: "x86",
    0x8664: "x64",
    0x01C0: "ARM",
    0x01C4: "ARM Thumb-2",
    0xAA64: "ARM64",
    0x0200: "Itanium",
}

_SUBSYSTEMS = {
    1: "native",
    2: "Windows GUI",
    3: "Windows console",
    5: "OS/2 console",
    7: "POSIX console",
    9: "Windows CE GUI",
    10: "EFI application",
    11: "EFI boot service driver",
    12: "EFI runtime driver",
    13: "EFI ROM",
    14: "Xbox",
    16: "Windows boot application",
}

_FILE_TYPES = {
    1: "application",
    2: "DLL",
    3: "driver",
    4: "font",
    5: "virtual device",
    7: "static library",
}

#: Link times before Windows NT shipped are not link times, and a time in the
#: future is not one either. Either is kept as a field and never as the date
#: the record is placed at: a reproducible build writes a hash here on purpose.
_EARLIEST = datetime(1993, 1, 1, tzinfo=timezone.utc)


@dataclass(slots=True)
class Section:
    virtual_address: int
    virtual_size: int
    raw_pointer: int
    raw_size: int


@dataclass(slots=True)
class Executable:
    """What a PE file records about its own building."""

    machine: str | None = None
    subsystem: str | None = None
    linker: str | None = None
    linked: str | None = None
    link_stamp: int = 0
    reproducible: bool = False
    pdb_path: str | None = None
    pdb_guid: str | None = None
    pdb_age: int | None = None
    rich: list[tuple[int, int, int]] = field(default_factory=list)
    signature_size: int | None = None
    file_type: str | None = None
    file_version: str | None = None
    product_version: str | None = None
    strings: dict[str, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.machine)


def read_executable(path: Path) -> Executable | None:
    """Return what a PE file says about its own building, or None."""
    try:
        with path.open("rb") as handle:
            return _read(handle)
    except (OSError, struct.error, ValueError, UnicodeDecodeError):
        return None


def _read(handle: BinaryIO) -> Executable | None:
    dos = handle.read(64)
    if len(dos) < 64 or dos[:2] != _DOS_MAGIC:
        return None
    (pe_offset,) = struct.unpack_from("<I", dos, 60)
    if pe_offset < 64 or pe_offset > _MAX_HEADERS:
        return None

    handle.seek(0)
    stub = handle.read(pe_offset)
    handle.seek(pe_offset)
    signature = handle.read(4)
    if signature != _PE_MAGIC:
        return None

    coff = handle.read(20)
    if len(coff) < 20:
        return None
    machine, sections, stamp, _, _, optional_size, _ = struct.unpack("<HHIIIHH", coff)
    if sections > _MAX_SECTIONS:
        return None
    found = Executable(machine=_MACHINES.get(machine, f"0x{machine:04x}"), link_stamp=stamp)
    found.linked = _stamp(stamp)
    found.rich = _rich(stub)

    optional = handle.read(optional_size)
    directories = _optional(optional, found)
    table = handle.read(40 * sections)
    layout = [
        Section(
            virtual_address=struct.unpack_from("<I", table, at * 40 + 12)[0],
            virtual_size=struct.unpack_from("<I", table, at * 40 + 8)[0],
            raw_pointer=struct.unpack_from("<I", table, at * 40 + 20)[0],
            raw_size=struct.unpack_from("<I", table, at * 40 + 16)[0],
        )
        for at in range(len(table) // 40)
    ]

    if debug := directories.get(_DIRECTORY_DEBUG):
        _debug(handle, layout, debug, found)
    if security := directories.get(_DIRECTORY_SECURITY):
        offset, size = security
        if offset and size:
            found.signature_size = size
    if resource := directories.get(_DIRECTORY_RESOURCE):
        _version(handle, layout, resource, found)
    return found if found else None


def _optional(optional: bytes, found: Executable) -> dict[int, tuple[int, int]]:
    """The data directories, and the fields of the optional header worth having."""
    if len(optional) < 96:
        return {}
    (magic,) = struct.unpack_from("<H", optional, 0)
    found.linker = f"{optional[2]}.{optional[3]}"
    (subsystem,) = struct.unpack_from("<H", optional, 68)
    found.subsystem = _SUBSYSTEMS.get(subsystem)
    if magic == 0x20B:
        count_at, first = 108, 112
    elif magic == 0x10B:
        count_at, first = 92, 96
    else:
        return {}
    (count,) = struct.unpack_from("<I", optional, count_at)
    directories: dict[int, tuple[int, int]] = {}
    for index in range(min(count, 16)):
        at = first + index * 8
        if at + 8 > len(optional):
            break
        address, size = struct.unpack_from("<II", optional, at)
        if address and size:
            directories[index] = (address, size)
    return directories


def _stamp(seconds: int) -> str | None:
    if not seconds:
        return None
    try:
        moment = datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return moment.isoformat().replace("+00:00", "Z")


def plausible(linked: str | None) -> bool:
    """Whether a link time can be placed on a timeline as a moment in time."""
    if not linked:
        return False
    moment = datetime.fromisoformat(linked.replace("Z", "+00:00"))
    return _EARLIEST <= moment <= datetime.now(timezone.utc)


def _offset(layout: list[Section], rva: int) -> int | None:
    """The file offset an RVA is stored at, through the section table."""
    for section in layout:
        span = max(section.virtual_size, section.raw_size)
        if section.virtual_address <= rva < section.virtual_address + span:
            inside = rva - section.virtual_address
            if inside >= section.raw_size:
                return None  # in the zero-filled tail, nothing on disk
            return section.raw_pointer + inside
    return None


# --- the Rich header --------------------------------------------------------


def _rich(stub: bytes) -> list[tuple[int, int, int]]:
    """The tool records Microsoft's linker hides between the DOS stub and the
    PE header: which compiler and which build of it, and how many objects each
    contributed. Each entry is (product id, build number, count)."""
    end = stub.rfind(_RICH_END)
    if end < 0 or end + 8 > len(stub):
        return []
    (key,) = struct.unpack_from("<I", stub, end + 4)
    entries: list[tuple[int, int, int]] = []
    at = end - 8
    while at >= 64 and len(entries) < _MAX_RICH_ENTRIES:
        word, count = struct.unpack_from("<II", stub, at)
        word ^= key
        count ^= key
        if word.to_bytes(4, "little") == _RICH_START:
            return entries[::-1]
        if word or count:  # the header pads itself with three masked zeros
            entries.append((word >> 16, word & 0xFFFF, count))
        at -= 8
    return []


# --- the debug directory ----------------------------------------------------


def _debug(
    handle: BinaryIO, layout: list[Section], directory: tuple[int, int], found: Executable
) -> None:
    rva, size = directory
    offset = _offset(layout, rva)
    if offset is None:
        return
    handle.seek(offset)
    table = handle.read(min(size, 28 * _MAX_DEBUG_ENTRIES))
    for at in range(0, len(table) - 27, 28):
        kind, data_size, _, pointer = struct.unpack_from("<IIII", table, at + 12)
        if kind == _DEBUG_REPRO:
            found.reproducible = True
        elif kind == _DEBUG_CODEVIEW and pointer and data_size >= 24:
            handle.seek(pointer)
            data = handle.read(min(data_size, 24 + _MAX_TEXT))
            if data[:4] != _CODEVIEW:
                continue
            raw_guid = data[4:20]
            fields = struct.unpack("<IHH8s", raw_guid)
            found.pdb_guid = (
                f"{fields[0]:08x}-{fields[1]:04x}-{fields[2]:04x}-"
                f"{fields[3][:2].hex()}-{fields[3][2:].hex()}"
            )
            (found.pdb_age,) = struct.unpack_from("<I", data, 20)
            path = data[24:].split(b"\x00", 1)[0]
            found.pdb_path = path.decode("utf-8", "replace").strip() or None


# --- the version resource ---------------------------------------------------


def _version(
    handle: BinaryIO, layout: list[Section], directory: tuple[int, int], found: Executable
) -> None:
    rva, size = directory
    base = _offset(layout, rva)
    if base is None:
        return
    handle.seek(base)
    tree = handle.read(min(size, _MAX_RESOURCE))
    data = _resource_data(tree, _RT_VERSION)
    if data is None:
        return
    data_rva, data_size = data
    offset = _offset(layout, data_rva)
    if offset is None:
        return
    handle.seek(offset)
    _version_info(handle.read(min(data_size, _MAX_RESOURCE)), found)


def _resource_data(tree: bytes, wanted: int) -> tuple[int, int] | None:
    """The first data entry under the resource type asked for."""
    at = _resource_child(tree, 0, wanted)
    for _ in range(_MAX_RESOURCE_DEPTH):
        if at is None:
            return None
        if not at & 0x80000000:
            if at + 8 > len(tree):
                return None
            rva, size = struct.unpack_from("<II", tree, at)
            return (rva, size) if size else None
        at = _resource_child(tree, at & 0x7FFFFFFF, None)
    return None


def _resource_child(tree: bytes, at: int, wanted: int | None) -> int | None:
    """The offset an entry of one directory points at: the entry with the
    identifier `wanted`, or the first entry where any will do."""
    if at + 16 > len(tree):
        return None
    named, numbered = struct.unpack_from("<HH", tree, at + 12)
    first = at + 16
    for index in range(min(named + numbered, 256)):
        entry = first + index * 8
        if entry + 8 > len(tree):
            return None
        name, offset = struct.unpack_from("<II", tree, entry)
        if wanted is None or (index >= named and name == wanted):
            return int(offset)
    return None


def _version_info(raw: bytes, found: Executable) -> None:
    """Walk VS_VERSIONINFO: a fixed block of numbers, then string tables."""
    header = _block(raw, 0)
    if header is None:
        return
    length, value_length, _, key, value_at = header
    if key != "VS_VERSION_INFO":
        return
    if value_length >= 52 and value_at + 52 <= len(raw):
        fixed = struct.unpack_from("<IIIIIIIIIIIII", raw, value_at)
        if fixed[0] == 0xFEEF04BD:
            found.file_version = _quad(fixed[2], fixed[3])
            found.product_version = _quad(fixed[4], fixed[5])
            found.file_type = _FILE_TYPES.get(fixed[9])
    at = _align(value_at + value_length)
    end = min(length, len(raw))
    while at + 6 <= end:
        child = _block(raw, at)
        if child is None:
            return
        child_length, _, _, child_key, child_value_at = child
        if child_length < 6:
            return
        if child_key == "StringFileInfo":
            _string_tables(raw, child_value_at, min(at + child_length, end), found)
        at = _align(at + child_length)


def _string_tables(raw: bytes, at: int, end: int, found: Executable) -> None:
    while at + 6 <= end:
        table = _block(raw, at)
        if table is None:
            return
        table_length, _, _, _, strings_at = table
        if table_length < 6:
            return
        table_end = min(at + table_length, end)
        inner = strings_at
        while inner + 6 <= table_end and len(found.strings) < _MAX_STRINGS:
            entry = _block(raw, inner)
            if entry is None:
                return
            entry_length, value_words, _, name, value_at = entry
            if entry_length < 6:
                return
            value = raw[value_at : min(value_at + value_words * 2, table_end)]
            text = value.decode("utf-16-le", "replace").split("\x00", 1)[0].strip()
            if name and text and name not in found.strings:
                found.strings[name] = text[:_MAX_TEXT]
            inner = _align(inner + entry_length)
        at = _align(at + table_length)


def _block(raw: bytes, at: int) -> tuple[int, int, int, str, int] | None:
    """One version-resource block header: length, value length, type, the
    UTF-16 key, and where the value starts after alignment."""
    if at + 6 > len(raw):
        return None
    length, value_length, kind = struct.unpack_from("<HHH", raw, at)
    key_at = at + 6
    key_end = raw.find(b"\x00\x00", key_at)
    while key_end >= 0 and (key_end - key_at) % 2:
        key_end = raw.find(b"\x00\x00", key_end + 1)
    if key_end < 0:
        return None
    key = raw[key_at:key_end].decode("utf-16-le", "replace")
    return length, value_length, kind, key, _align(key_end + 2)


def _align(at: int) -> int:
    return (at + 3) & ~3


def _quad(high: int, low: int) -> str:
    return f"{high >> 16}.{high & 0xFFFF}.{low >> 16}.{low & 0xFFFF}"
