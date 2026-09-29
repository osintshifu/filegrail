"""Assembling a Windows shell link, for the reader of the Recent folder.

Every offset is computed from the encoded parts rather than counted by hand. A
length that happens to agree with a hand-counted reader proves only that the
same mistake was made twice.

The layout is [MS-SHLLINK]. Nothing on the developer's machine writes a `.lnk`,
so these fixtures are the whole of the evidence that the reader is right about
the format, and they are built to the specification deliberately rather than
copied from an example that already worked.
"""

from __future__ import annotations

import struct

#: 00021401-0000-0000-C000-000000000046, in the mixed-endian order a GUID is
#: stored in: three little-endian integers then eight bytes as written.
LINK_CLSID = bytes.fromhex("01140200") + bytes.fromhex("0000") + bytes.fromhex("0000")
LINK_CLSID += bytes.fromhex("C000000000000046")

HAS_TARGET_ID_LIST = 0x00000001
HAS_LINK_INFO = 0x00000002
HAS_NAME = 0x00000004
HAS_RELATIVE_PATH = 0x00000008
IS_UNICODE = 0x00000080

DRIVE_UNKNOWN = 0
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5

_TRACKER_SIGNATURE = 0xA0000003


def filetime(seconds: float) -> bytes:
    """A Windows FILETIME: 100-nanosecond ticks since 1601."""
    return struct.pack("<Q", int((seconds + 11_644_473_600) * 10_000_000))


def volume_id(drive_type: int, serial: int, label: str = "") -> bytes:
    """A VolumeID with an ANSI label, whose offset is fixed at 0x10."""
    data = label.encode("latin-1") + b"\x00"
    size = 0x10 + len(data)
    return struct.pack("<IIII", size, drive_type, serial, 0x10) + data


def network_link(share: str, device: str = "") -> bytes:
    """A CommonNetworkRelativeLink naming the share the file was opened from."""
    net = share.encode("latin-1") + b"\x00"
    dev = device.encode("latin-1") + b"\x00" if device else b""
    net_offset = 0x14
    device_offset = net_offset + len(net) if dev else 0
    size = net_offset + len(net) + len(dev)
    flags = 0x00000002 | (0x00000001 if dev else 0)
    return struct.pack("<IIIII", size, flags, net_offset, device_offset, 0x00020000) + net + dev


def link_info(path: str, volume: bytes | None = None, network: bytes | None = None) -> bytes:
    """The LinkInfo structure, with whichever of its two halves are present."""
    header = 0x1C
    body = b""
    flags = 0
    volume_offset = local_offset = network_offset = 0

    if volume is not None:
        flags |= 0x00000001
        volume_offset = header + len(body)
        body += volume
        local_offset = header + len(body)
        body += path.encode("latin-1") + b"\x00"
    if network is not None:
        flags |= 0x00000002
        network_offset = header + len(body)
        body += network

    suffix_offset = header + len(body)
    body += b"\x00"

    size = header + len(body)
    return (
        struct.pack(
            "<IIIIIII",
            size,
            header,
            flags,
            volume_offset,
            local_offset,
            network_offset,
            suffix_offset,
        )
        + body
    )


def tracker(machine: str) -> bytes:
    """A TrackerDataBlock, whose MachineID names where the link was made."""
    name = machine.encode("latin-1")[:15].ljust(16, b"\x00")
    return (
        struct.pack("<IIII", 0x60, _TRACKER_SIGNATURE, 0x58, 0) + name + b"\x11" * 32 + b"\x22" * 32
    )


def _string(text: str) -> bytes:
    """A StringData entry: a character count, then UTF-16 characters."""
    encoded = text.encode("utf-16-le")
    return struct.pack("<H", len(encoded) // 2) + encoded


def shortcut(
    *,
    info: bytes | None = None,
    relative: str | None = None,
    name: str | None = None,
    size: int = 0,
    written: float | None = None,
    extra: bytes = b"",
    target_ids: bytes | None = None,
) -> bytes:
    """Assemble a shell link out of the parts it was given."""
    flags = IS_UNICODE
    if info is not None:
        flags |= HAS_LINK_INFO
    if relative is not None:
        flags |= HAS_RELATIVE_PATH
    if name is not None:
        flags |= HAS_NAME
    if target_ids is not None:
        flags |= HAS_TARGET_ID_LIST

    stamp = filetime(written) if written is not None else b"\x00" * 8
    header = struct.pack("<I", 0x4C) + LINK_CLSID
    header += struct.pack("<II", flags, 0x00000020)
    header += b"\x00" * 8 + b"\x00" * 8 + stamp
    header += struct.pack("<IIIH", size, 0, 1, 0)
    header += b"\x00" * 2 + b"\x00" * 4 + b"\x00" * 4
    assert len(header) == 0x4C, len(header)

    body = b""
    if target_ids is not None:
        body += struct.pack("<H", len(target_ids)) + target_ids
    if info is not None:
        body += info
    if name is not None:
        body += _string(name)
    if relative is not None:
        body += _string(relative)

    # ExtraData runs until a block whose size is under four bytes.
    return header + body + extra + b"\x00\x00\x00\x00"
