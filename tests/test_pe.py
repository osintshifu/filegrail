"""Windows executables: what a PE file records about its own building."""

import struct
from pathlib import Path

from filegrail.sources.embedded import read_embedded_metadata

_KEY = 0x11223344
_LINKED = 1_726_650_000  # 2024-09-18T09:00:00Z


def _rich(entries: list[tuple[int, int, int]]) -> bytes:
    """The linker's hidden tool record, XOR-masked the way `link.exe` writes it."""
    words = [int.from_bytes(b"DanS", "little") ^ _KEY, _KEY, _KEY, _KEY]
    for product, build, count in entries:
        words += [(product << 16 | build) ^ _KEY, count ^ _KEY]
    body = struct.pack(f"<{len(words)}I", *words) + b"Rich" + struct.pack("<I", _KEY)
    return body + b"\x00" * (64 - len(body))


def _vblock(key: str, value: bytes, value_length: int, kind: int, children: list[bytes]) -> bytes:
    head = struct.pack("<HHH", 0, value_length, kind) + (key + "\x00").encode("utf-16-le")
    head += b"\x00" * (-len(head) % 4)
    body = head + value
    for child in children:
        body += b"\x00" * (-len(body) % 4) + child
    return struct.pack("<H", len(body)) + body[2:]


def _version_info(strings: dict[str, str]) -> bytes:
    fixed = struct.pack(
        "<13I",
        0xFEEF04BD,
        0x10000,
        1 << 16 | 2,
        3 << 16 | 4,
        1 << 16 | 2,
        3 << 16 | 4,
        0x3F,
        0,
        4,
        1,
        0,
        0,
        0,
    )
    entries = [
        _vblock(name, (text + "\x00").encode("utf-16-le"), len(text) + 1, 1, [])
        for name, text in strings.items()
    ]
    table = _vblock("040904B0", b"", 0, 1, entries)
    info = _vblock("StringFileInfo", b"", 0, 1, [table])
    return _vblock("VS_VERSION_INFO", fixed, len(fixed), 0, [info])


def _resources(version: bytes, rva: int) -> bytes:
    def directory(entry_name: int, target: int) -> bytes:
        return struct.pack("<IIHHHH", 0, 0, 0, 0, 0, 1) + struct.pack("<II", entry_name, target)

    tree = directory(16, 0x80000000 | 0x18)  # RT_VERSION -> name directory
    tree += directory(1, 0x80000000 | 0x30)  # name 1 -> language directory
    tree += directory(0x409, 0x48)  # en-US -> data entry
    tree += struct.pack("<IIII", rva + 0x58, len(version), 0, 0)
    return tree + version


def executable(tmp_path: Path, strings: dict[str, str], *, reproducible: bool = False) -> Path:
    """A PE32+ image with a Rich header, a CodeView record, a version resource
    and an Authenticode blob, laid out with real section offsets."""
    pdb = b"C:\\Users\\dev\\src\\tool\\x64\\Release\\tool.pdb\x00"
    codeview = b"RSDS" + bytes(range(16)) + struct.pack("<I", 7) + pdb
    debug_entries = 2 if reproducible else 1
    rdata_rva, rdata_at = 0x1000, 0x400
    debug = struct.pack(
        "<IIHHIIII",
        0,
        0,
        0,
        0,
        2,
        len(codeview),
        rdata_rva + 28 * debug_entries,
        rdata_at + 28 * debug_entries,
    )
    if reproducible:
        debug += struct.pack("<IIHHIIII", 0, 0, 0, 0, 16, 0, 0, 0)
    rdata = debug + codeview
    rdata += b"\x00" * (-len(rdata) % 0x200)

    rsrc_rva, rsrc_at = 0x2000, rdata_at + len(rdata)
    rsrc = _resources(_version_info(strings), rsrc_rva)
    rsrc += b"\x00" * (-len(rsrc) % 0x200)
    certificate_at = rsrc_at + len(rsrc)
    certificate = struct.pack("<IHH", 16, 0x200, 2) + b"\x30\x06\x02\x01\x01\x05\x00\x00"

    directories = [(0, 0)] * 16
    directories[2] = (rsrc_rva, len(rsrc))
    directories[4] = (certificate_at, len(certificate))
    directories[6] = (rdata_rva, 28 * debug_entries)
    optional = struct.pack(
        "<HBBIIIIIQIIHHHHHHIIIIHHQQQQII",
        0x20B,
        14,
        36,
        0,
        0,
        0,
        0x1000,
        0x1000,
        0x140000000,
        0x1000,
        0x200,
        6,
        0,
        0,
        0,
        6,
        0,
        0,
        0x3000,
        0x400,
        0,
        2,
        0x8160,
        0x100000,
        0x1000,
        0x100000,
        0x1000,
        0,
        16,
    ) + b"".join(struct.pack("<II", *entry) for entry in directories)
    assert len(optional) == 240

    def section(name: bytes, rva: int, size: int, at: int) -> bytes:
        return struct.pack("<8sIIIIIIHHI", name, size, rva, size, at, 0, 0, 0, 0, 0x40000040)

    coff = struct.pack("<HHIIIHH", 0x8664, 2, _LINKED, 0, 0, len(optional), 0x22)
    headers = (
        b"MZ"
        + b"\x00" * 58
        + struct.pack("<I", 0x80)
        + _rich([(0x00FD, 31424, 3), (0x0104, 31424, 1)])
        + b"PE\x00\x00"
        + coff
        + optional
        + section(b".rdata", rdata_rva, len(rdata), rdata_at)
        + section(b".rsrc", rsrc_rva, len(rsrc), rsrc_at)
    )
    headers += b"\x00" * (rdata_at - len(headers))

    path = tmp_path / "tool.exe"
    path.write_bytes(headers + rdata + rsrc + certificate)
    return path


def test_reads_what_the_executable_records_about_its_building(tmp_path: Path):
    path = executable(
        tmp_path,
        {
            "CompanyName": "Example Corp",
            "ProductName": "Example Tool",
            "ProductVersion": "1.2.3.4",
            "OriginalFilename": "tool.exe",
            "FileDescription": "Example command line tool",
        },
    )

    found = read_embedded_metadata(path)

    assert found is not None
    assert found.block == "pe-header"
    assert found.tool == "Example Tool 1.2.3.4"
    assert found.at == "2024-09-18T09:00:00Z"
    assert found.note == (
        "company Example Corp; original name tool.exe; "
        "PDB C:\\Users\\dev\\src\\tool\\x64\\Release\\tool.pdb; "
        "Authenticode signature present; linker 14.36"
    )
    assert found.fields["Machine"] == "x64"
    assert found.fields["Subsystem"] == "Windows GUI"
    assert found.fields["FileType"] == "application"
    assert found.fields["FileVersion"] == "1.2.3.4"
    assert found.fields["PDBGuid"] == "03020100-0504-0706-0809-0a0b0c0d0e0f"
    assert found.fields["PDBAge"] == "7"
    assert found.fields["RichHeader"] == "2 entries"
    assert found.fields["RichEntry[1]"] == "id 253, build 31424, count 3"
    assert found.fields["Authenticode"] == "present, 16 bytes"
    assert found.fields["FileDescription"] == "Example command line tool"


def test_a_reproducible_build_keeps_its_stamp_off_the_timeline(tmp_path: Path):
    """The COFF stamp of a reproducible build is a hash, not a moment."""
    path = executable(tmp_path, {"ProductName": "Example Tool"}, reproducible=True)

    found = read_embedded_metadata(path)

    assert found is not None
    assert found.at is None
    assert found.fields["ReproducibleBuild"] == "yes"
    assert found.fields["LinkTime"] == "2024-09-18T09:00:00Z"
    assert "reproducible build" in found.note


def test_a_dos_program_without_a_pe_header_is_not_an_error(tmp_path: Path):
    path = tmp_path / "old.exe"
    path.write_bytes(b"MZ" + b"\x00" * 200)

    assert read_embedded_metadata(path) is None
