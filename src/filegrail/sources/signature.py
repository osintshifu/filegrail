"""What the leading bytes say the file is, where its name says something else.

An extension is a claim, and renaming a file is one command. A format's own
mark is harder to argue with: it sits at a fixed place in the bytes and travels
with them through every copy. Where the two disagree, the disagreement is the
finding - a spreadsheet that opens as an executable and a photograph that is
really a PDF are both a rename away from looking ordinary in a file listing.

Only the disagreement is recorded. A `.jpg` that is a JPEG has confirmed what
the name already said, and adding a record for it would put a line on every
file in the scan to say that nothing happened.

Three things are deliberately left unsaid, because none of them is a misnamed
file. A format written under many names is not one: a zip is a `.docx`, a
`.epub` and a `.jar`, and every one of those carries it legitimately. Bytes
matching no mark here are not one: this module cannot say what the file is, and
saying so of every plain-text file in a directory would be noise standing in
for a finding. An extension nothing here expects anything of is not one either:
there is no claim to contradict.
"""

from __future__ import annotations

from pathlib import Path

from ..models import EvidenceRecord

#: How much of the file a mark can be found in. `tar` writes its own 257 bytes
#: in, which is the furthest anything here looks.
HEAD = 512

#: What each format is called in the report, and the extensions that carry it
#: legitimately. Many-to-many on purpose: one format is written under several
#: names, and one extension can hold either of two formats - an `.html` holding
#: XHTML opens with an XML declaration and is not thereby mislabelled.
CARRIED_BY: dict[str, frozenset[str]] = {
    "JPEG": frozenset({".jpg", ".jpeg", ".jpe", ".jfif"}),
    "PNG": frozenset({".png"}),
    "GIF": frozenset({".gif"}),
    "TIFF": frozenset({".tif", ".tiff"}),
    "WebP": frozenset({".webp"}),
    "PDF": frozenset({".pdf"}),
    "RTF": frozenset({".rtf"}),
    "ZIP": frozenset(
        {
            ".zip",
            ".docx",
            ".docm",
            ".xlsx",
            ".xlsm",
            ".pptx",
            ".pptm",
            ".odt",
            ".ods",
            ".odp",
            ".odg",
            ".epub",
            ".jar",
            ".apk",
            ".kmz",
            ".xpi",
        }
    ),
    "gzip": frozenset({".gz", ".tgz", ".svgz"}),
    "bzip2": frozenset({".bz2", ".tbz2"}),
    "XZ": frozenset({".xz", ".txz"}),
    "Zstandard": frozenset({".zst", ".tzst"}),
    "7-Zip": frozenset({".7z"}),
    "RAR": frozenset({".rar"}),
    "tar": frozenset({".tar"}),
    "OLE compound file": frozenset({".doc", ".xls", ".ppt", ".msg", ".msi"}),
    "ISO base media (MP4, MOV, HEIC)": frozenset(
        {".mp4", ".m4a", ".m4b", ".m4v", ".mov", ".3gp", ".3g2", ".heic", ".heif", ".avif"}
    ),
    "Matroska (MKV, WebM)": frozenset({".mkv", ".mka", ".mks", ".webm"}),
    "Ogg": frozenset({".ogg", ".oga", ".ogv", ".opus"}),
    "FLAC": frozenset({".flac"}),
    "MP3": frozenset({".mp3"}),
    "WAV": frozenset({".wav"}),
    "AVI": frozenset({".avi"}),
    "SQLite database": frozenset({".sqlite", ".sqlite3"}),
    "ELF binary": frozenset({".so", ".elf", ".ko"}),
    "Windows executable": frozenset({".exe", ".dll", ".sys", ".scr", ".ocx", ".cpl"}),
    "Mach-O binary": frozenset({".dylib", ".bundle"}),
    "HTML": frozenset({".html", ".htm", ".xhtml"}),
    "SVG": frozenset({".svg"}),
    "XML": frozenset({".xml", ".svg", ".xhtml", ".html", ".htm", ".rss", ".atom", ".plist"}),
}

#: The marks that identify a format: every offset and its bytes has to be there
#: for the row to match. A format written more than one way gets a row for each,
#: and a container several formats share is named as the container, because the
#: bytes at the front really do say no more than that.
MARKS: tuple[tuple[str, tuple[tuple[int, bytes], ...]], ...] = (
    ("JPEG", ((0, b"\xff\xd8\xff"),)),
    ("PNG", ((0, b"\x89PNG\r\n\x1a\n"),)),
    ("GIF", ((0, b"GIF8"),)),
    ("TIFF", ((0, b"II*\x00"),)),
    ("TIFF", ((0, b"MM\x00*"),)),
    ("WebP", ((0, b"RIFF"), (8, b"WEBP"))),
    ("WAV", ((0, b"RIFF"), (8, b"WAVE"))),
    ("AVI", ((0, b"RIFF"), (8, b"AVI "))),
    ("PDF", ((0, b"%PDF-"),)),
    ("RTF", ((0, b"{\\rtf"),)),
    ("ZIP", ((0, b"PK\x03\x04"),)),
    ("ZIP", ((0, b"PK\x05\x06"),)),
    ("ZIP", ((0, b"PK\x07\x08"),)),
    ("gzip", ((0, b"\x1f\x8b"),)),
    ("bzip2", ((0, b"BZh"),)),
    ("XZ", ((0, b"\xfd7zXZ\x00"),)),
    ("Zstandard", ((0, b"\x28\xb5\x2f\xfd"),)),
    ("7-Zip", ((0, b"7z\xbc\xaf\x27\x1c"),)),
    ("RAR", ((0, b"Rar!\x1a\x07"),)),
    ("OLE compound file", ((0, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),)),
    ("ISO base media (MP4, MOV, HEIC)", ((4, b"ftyp"),)),
    ("Matroska (MKV, WebM)", ((0, b"\x1a\x45\xdf\xa3"),)),
    ("Ogg", ((0, b"OggS"),)),
    ("FLAC", ((0, b"fLaC"),)),
    ("MP3", ((0, b"ID3"),)),
    ("SQLite database", ((0, b"SQLite format 3\x00"),)),
    ("ELF binary", ((0, b"\x7fELF"),)),
    ("Windows executable", ((0, b"MZ"),)),
    ("Mach-O binary", ((0, b"\xcf\xfa\xed\xfe"),)),
    ("Mach-O binary", ((0, b"\xce\xfa\xed\xfe"),)),
    ("Mach-O binary", ((0, b"\xfe\xed\xfa\xcf"),)),
    ("Mach-O binary", ((0, b"\xfe\xed\xfa\xce"),)),
    # Last of the byte marks: 257 bytes in, and a short file cannot hold it.
    ("tar", ((257, b"ustar"),)),
)

#: Formats whose mark is text rather than bytes. Matched past a byte-order mark
#: and any leading blank space, and without regard to case, because an author
#: is free to write all three however they like and every browser accepts it.
TEXT_MARKS: tuple[tuple[str, tuple[bytes, ...]], ...] = (
    ("HTML", (b"<!doctype html", b"<html")),
    ("SVG", (b"<svg",)),
    ("XML", (b"<?xml",)),
)


def _expected() -> dict[str, frozenset[str]]:
    """`CARRIED_BY` read the other way round: what an extension may hold."""
    found: dict[str, set[str]] = {}
    for name, suffixes in CARRIED_BY.items():
        for suffix in suffixes:
            found.setdefault(suffix, set()).add(name)
    return {suffix: frozenset(names) for suffix, names in found.items()}


EXPECTED = _expected()


def _sniff(head: bytes) -> str | None:
    """Which format writes these leading bytes, where one here does."""
    for name, marks in MARKS:
        if all(head[at : at + len(mark)] == mark for at, mark in marks):
            return name
    opening = head.removeprefix(b"\xef\xbb\xbf").lstrip().lower()
    for name, starts in TEXT_MARKS:
        if opening.startswith(starts):
            return name
    return None


def read_signature(path: Path) -> EvidenceRecord | None:
    """What the file's own bytes say it is, where its name says otherwise."""
    expected = EXPECTED.get(path.suffix.lower())
    if not expected:
        return None
    try:
        with path.open("rb") as handle:
            head = handle.read(HEAD)
    except OSError:
        return None
    found = _sniff(head)
    if found is None or found in expected:
        return None
    suffix = path.suffix.lower()
    return EvidenceRecord(
        source="file-signature",
        note=f"the name says {suffix}, the bytes say {found}",
        fields={"extension": suffix, "content": found},
    )
