"""Assembling a compound file, for the readers of formats that are one.

The fixtures are computed rather than committed, so every offset in them is
derived. A hand-counted length that happens to agree with a hand-counted reader
proves nothing; `test_corpus.py` checks the same readers against real files,
which is what proves the layout right.

A `.doc` and a `.msg` are the same container holding different streams, so the
container is assembled here once and the streams belong to whoever wants them.
"""

from __future__ import annotations

import struct

SECTOR = 512
MINI_SECTOR = 64
MINI_CUTOFF = 4096

FREE = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECT = 0xFFFFFFFD

SUMMARY_FMTID = bytes.fromhex("e0859ff2f94f6810ab9108002b27b3d9")
DOCSUMMARY_FMTID = bytes.fromhex("02d5cdd59c2e1b10939708002b2cf9ae")

VT_LPSTR = 30
VT_FILETIME = 64


# --- compound file -----------------------------------------------------------


def directory_entry(
    name: str,
    category: int,
    start: int,
    size: int,
    child: int = FREE,
    *,
    left: int = FREE,
    right: int = FREE,
    clsid: bytes = b"\x00" * 16,
    created: int = 0,
    modified: int = 0,
) -> bytes:
    assert len(clsid) == 16
    raw = name.encode("utf-16-le") + b"\x00\x00"
    entry = raw.ljust(64, b"\x00")[:64]
    entry += struct.pack("<HBB", len(raw), category, 1)
    entry += struct.pack("<III", left, right, child)
    entry += clsid + b"\x00" * 4 + struct.pack("<QQ", created, modified)
    entry += struct.pack("<IQ", start, size)
    assert len(entry) == 128
    return entry


def chain(first: int, count: int) -> list[int]:
    return [first + step + 1 for step in range(count - 1)] + [ENDOFCHAIN]


def ole(
    streams: dict[str, bytes],
    *,
    storages: dict[str, dict[str, bytes]] | None = None,
    directory_entries: tuple[bytes, ...] = (),
    orphan_entries: tuple[bytes, ...] = (),
) -> bytes:
    """Assemble a v3 compound file holding `streams`.

    A stream shorter than the cutoff goes into the mini stream, exactly as an
    encoder writes it, so the mini-FAT path is exercised rather than assumed.
    `storages` places further streams one storage below the root, the way a
    message keeps each attachment or a document its object pool.
    """
    groups = [("", streams), *(storages or {}).items()]

    sectors: list[bytes] = []
    fat: list[int] = []
    directory: list[bytes] = []

    def allocate(payload: bytes, unit: int) -> tuple[int, int]:
        """Append `payload` as whole sectors, returning its start and count."""
        start = len(sectors)
        padded = payload + b"\x00" * (-len(payload) % unit)
        for offset in range(0, len(padded), unit):
            sectors.append(padded[offset : offset + unit].ljust(unit, b"\x00"))
        return start, (len(padded) // unit) or 0

    placed: dict[str, list[tuple[str, int, int, int]]] = {name: [] for name, _ in groups}

    for group, members in groups:
        for name, data in members.items():
            if len(data) >= MINI_CUTOFF:
                start, count = allocate(data, SECTOR)
                fat.extend(chain(start, count))
                placed[group].append((name, 2, start, len(data)))

    mini_stream = b""
    mini_fat: list[int] = []
    for group, members in groups:
        for name, data in members.items():
            if len(data) < MINI_CUTOFF:
                index = len(mini_stream) // MINI_SECTOR
                padded = data + b"\x00" * (-len(data) % MINI_SECTOR)
                count = len(padded) // MINI_SECTOR
                mini_stream += padded
                mini_fat.extend(chain(index, count))
                placed[group].append((name, 2, index, len(data)))

    mini_start = ENDOFCHAIN
    if mini_stream:
        mini_start, count = allocate(mini_stream, SECTOR)
        fat.extend(chain(mini_start, count))

    mini_fat_start, mini_fat_count = ENDOFCHAIN, 0
    if mini_fat:
        blob = b"".join(struct.pack("<I", entry) for entry in mini_fat)
        mini_fat_start, mini_fat_count = allocate(blob, SECTOR)
        fat.extend(chain(mini_fat_start, mini_fat_count))

    def link(indices: list[int]) -> None:
        """Chain siblings to the right: a right-leaning tree reaches them all."""
        for position, index in enumerate(indices):
            right = indices[position + 1] if position + 1 < len(indices) else FREE
            linked = bytearray(directory[index])
            struct.pack_into("<I", linked, 72, right)
            directory[index] = bytes(linked)

    directory.append(b"")  # the root, written once its first child is known
    top: list[int] = []
    for name, category, start, size in placed[""]:
        top.append(len(directory))
        directory.append(directory_entry(name, category, start, size))
    for storage, _ in groups[1:]:
        top.append(len(directory))
        first_child = len(directory) + 1 if placed[storage] else FREE
        directory.append(directory_entry(storage, 1, 0, 0, child=first_child))
        below: list[int] = []
        for name, category, start, size in placed[storage]:
            below.append(len(directory))
            directory.append(directory_entry(name, category, start, size))
        link(below)
    for raw in directory_entries:
        top.append(len(directory))
        directory.append(raw)
    link(top)
    directory[0] = directory_entry(
        "Root Entry", 5, mini_start, len(mini_stream), child=top[0] if top else FREE
    )
    # Entries appended afterward are intentionally allocated but unreachable,
    # matching deleted/orphaned directory records.
    directory.extend(orphan_entries)

    directory_start, directory_count = allocate(b"".join(directory), SECTOR)
    fat.extend(chain(directory_start, directory_count))

    # The FAT describes the sectors it occupies too, so its own length has to
    # settle before it can be written: n data entries plus its own count must
    # fit in that same count of sectors.
    per_sector = SECTOR // 4
    fat_start = len(sectors)
    fat_count = 1
    while len(fat) + fat_count > fat_count * per_sector:
        fat_count += 1
        if fat_count > 64:  # pragma: no cover - fixtures are far smaller
            raise AssertionError("fixture too large")

    assert len(fat) == fat_start, "one FAT entry per allocated sector"
    fat.extend([FATSECT] * fat_count)
    table = b"".join(struct.pack("<I", entry) for entry in fat)
    table += struct.pack("<I", FREE) * (fat_count * per_sector - len(fat))
    for offset in range(0, len(table), SECTOR):
        sectors.append(table[offset : offset + SECTOR])

    header = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 16
    header += struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6)
    header += b"\x00" * 6
    header += struct.pack("<III", 0, fat_count, directory_start)
    header += struct.pack("<II", 0, MINI_CUTOFF)
    header += struct.pack("<III", mini_fat_start, mini_fat_count, ENDOFCHAIN)
    header += struct.pack("<I", 0)
    difat = [fat_start + step for step in range(fat_count)]
    difat += [FREE] * (109 - len(difat))
    header += b"".join(struct.pack("<I", entry) for entry in difat)
    assert len(header) == SECTOR

    return header + b"".join(sectors)
