"""Every reader, against files that are not the shape their format says.

An interrupted download, a copy off a failing disk and a file built to end where
a parser will not expect it all arrive the same way, and `filegrail` gives all
three the same answer: read what is there, report what can be shown, and carry
on to the next file. The readers are written for that - `_RECOVERABLE` in
`sources/embedded` exists for nothing else - but a list of exception types is a
claim about which ones can be raised, and the only way to check that claim is to
raise them.

Each fixture here is a valid file of its format. It is then cut at a ladder of
lengths and handed to every reader that will look at that suffix. Nothing is
asserted about what comes back: a prefix may still hold a readable block, and
which one it holds is not this module's business. What is asserted is that the
reader answers at all. The cuts are a fixed ladder rather than a random sample,
so a failure here reproduces by running the suite again rather than by
recovering a seed.

The fixtures are built here rather than shared with the format tests, which
need a file rich enough to have something to find. What a cut needs is
structure to cut through, which is a different requirement and a smaller file.
"""

from __future__ import annotations

import io
import struct
import zipfile
import zlib
from collections.abc import Callable
from pathlib import Path

import pytest

from filegrail.clean import clean_file
from filegrail.sources.archives import list_members, read_members
from filegrail.sources.c2pa import read_c2pa_manifest
from filegrail.sources.content import read_passages
from filegrail.sources.embedded import read_embedded_metadata
from filegrail.sources.iptc import read_iptc
from filegrail.sources.mail import read_mail
from filegrail.sources.messenger import read_messenger_name
from filegrail.sources.shortcut import read_link
from filegrail.sources.sidecar import read_sidecar
from filegrail.sources.torrent import read_torrent
from filegrail.sources.xmp import read_xmp
from tests.compound import ole
from tests.pdf import document as pdf_document
from tests.photo import jpeg_with_exif
from tests.shortcut import link_info, shortcut, volume_id

#: Every reader a scan points at one file, by the path of that file. They guard
#: themselves by suffix, so all of them are offered every fixture: a reader that
#: opens a file it should have skipped is worth knowing about too.
_READERS: tuple[Callable[[Path], object], ...] = (
    read_c2pa_manifest,
    read_members,
    read_passages,
    read_embedded_metadata,
    read_iptc,
    list_members,
    read_mail,
    read_messenger_name,
    read_sidecar,
    read_torrent,
    read_xmp,
)


# --- the whole files ----------------------------------------------------------


def _png(chunks: list[tuple[bytes, bytes]]) -> bytes:
    def chunk(category: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + category
            + payload
            + struct.pack(">I", zlib.crc32(category + payload))
        )

    header = (b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunk(*part) for part in [header, *chunks])


def _box(category: bytes, payload: bytes) -> bytes:
    """A length, a type and a payload - the shape of an atom and of a JUMBF box."""
    return struct.pack(">I", len(payload) + 8) + category + payload


def _manifest() -> bytes:
    def description(content_type: bytes, label: str) -> bytes:
        uuid = content_type + b"\x00\x11\x00\x10\x80\x00\x00\xaa\x008\x9bq"
        return _box(b"jumd", uuid + b"\x03" + label.encode() + b"\x00")

    claim = _box(
        b"jumb",
        description(b"c2cl", "c2pa.claim.v2") + _box(b"cbor", b"\xa1\x63alg\x66sha256"),
    )
    return _box(b"jumb", description(b"c2pa", "c2pa") + claim)


def _riff(category: bytes, chunks: list[tuple[bytes, bytes]]) -> bytes:
    body = category + b"".join(
        name + struct.pack("<I", len(payload)) + payload + (b"\x00" if len(payload) % 2 else b"")
        for name, payload in chunks
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _id3(frames: list[tuple[bytes, str]]) -> bytes:
    body = b"".join(
        name + struct.pack(">I", len(text) + 1) + b"\x00\x00" + b"\x00" + text.encode()
        for name, text in frames
    )
    size = bytes(((len(body) >> shift) & 0x7F) for shift in (21, 14, 7, 0))
    return b"ID3\x03\x00\x00" + size + body + b"\xff\xfb\x90\x00" * 4


def _zip(members: dict[str, str]) -> bytes:
    written = io.BytesIO()
    with zipfile.ZipFile(written, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, text in members.items():
            bundle.writestr(name, text)
    return written.getvalue()


_CORE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
    'metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">'
    "<dc:creator>A Person</dc:creator></cp:coreProperties>"
)

_META_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
    ' xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0">'
    "<office:meta><meta:generator>LibreOffice/7.4</meta:generator></office:meta>"
    "</office:document-meta>"
)

_XMP_PACKET = (
    '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF'
    ' xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"'
    ' xmlns:xmp="http://ns.adobe.com/xap/1.0/">'
    '<rdf:Description rdf:about=""><xmp:CreatorTool>Darktable</xmp:CreatorTool>'
    '</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
)

#: Named up front so the parametrised test can be collected without building
#: anything, and checked against the built corpus below so that a fixture
#: dropped from one list and not the other is a failure rather than a silence.
_NAMES = (
    "photo.jpg",
    "shot.png",
    "credentials.png",
    "clip.mp4",
    "notes.docx",
    "notes.odt",
    "bundle.zip",
    "linux.torrent",
    "message.eml",
    "message.msg",
    "page.html",
    "photo.xmp",
    "report.doc",
    "voice.wav",
    "song.mp3",
    "track.gpx",
    "brief.pdf",
)


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> dict[str, bytes]:
    """One valid file per format, built once for every cut that follows."""
    photo = tmp_path_factory.mktemp("whole") / "photo.jpg"
    jpeg_with_exif(photo, "NIKON", "COOLPIX P6000", "2008:10:22 16:28:39")

    movie = _box(b"ftyp", b"isom" + b"\x00\x00\x02\x00" + b"isomiso2avc1") + _box(
        b"moov",
        _box(b"mvhd", b"\x00" * 4 + b"\xd0\x00\x00\x00" * 2 + b"\x00" * 92)
        + _box(
            b"udta",
            _box(b"\xa9nam", _box(b"data", b"\x00\x00\x00\x01" + b"\x00" * 4 + b"A clip")),
        ),
    )

    return {
        "photo.jpg": photo.read_bytes(),
        "shot.png": _png([(b"tEXt", b"Software\x00GIMP 2.10"), (b"IDAT", b"\x00"), (b"IEND", b"")]),
        "credentials.png": _png([(b"caBX", _manifest()), (b"IDAT", b"\x00"), (b"IEND", b"")]),
        "clip.mp4": movie,
        "notes.docx": _zip({"docProps/core.xml": _CORE_XML, "word/document.xml": "<w:document/>"}),
        "notes.odt": _zip(
            {
                "mimetype": "application/vnd.oasis.opendocument.text",
                "meta.xml": _META_XML,
                "content.xml": "<office:document-content/>",
            }
        ),
        "bundle.zip": _zip({"holiday/photo.jpg": "not really a photo", "readme.txt": "hello"}),
        # Cut anywhere, a PDF loses the table that says where its pages are.
        "brief.pdf": pdf_document([b"BT /F1 12 Tf 72 720 Td (write to press@example.org) Tj ET"]),
        "linux.torrent": b"d8:announce20:http://tracker.test4:infod4:name9:linux.iso"
        b"12:piece lengthi262144e6:pieces20:" + b"\xa5" * 20 + b"ee",
        "message.eml": (
            b"From: sender@example.test\r\nTo: someone@example.test\r\n"
            b"Subject: the file\r\nDate: Tue, 22 Oct 2008 16:28:39 +0000\r\n"
            b"Content-Type: text/plain\r\n\r\nHere it is.\r\n"
        ),
        "message.msg": ole(
            {"__substg1.0_1000001F": "write to ann.shaw@acme.example".encode("utf-16-le")}
        ),
        "page.html": (
            b"<html><head><title>Invoice</title></head><body><p>Invoice from Acme</p>"
            b'<a href="https://acme-legal.example/pay">pay</a></body></html>'
        ),
        "photo.xmp": _XMP_PACKET.encode(),
        "report.doc": ole({"WordDocument": b"\xec\xa5" + b"\x00" * 512}),
        "voice.wav": _riff(
            b"WAVE",
            [
                (b"fmt ", b"\x01\x00\x01\x00" + b"\x00" * 12),
                (b"LIST", b"INFO" + b"ISFT" + struct.pack("<I", 10) + b"Audacity\x00\x00"),
                (b"data", b"\x00" * 16),
            ],
        ),
        "song.mp3": _id3([(b"TSSE", "Lavf58.76.100"), (b"TPE1", "Someone")]),
        "track.gpx": (
            b'<gpx><wpt lat="52.2297" lon="21.0122"><name>Warsaw</name></wpt>'
            b'<trk><trkseg><trkpt lat="52.1" lon="21.1"/><trkpt lat="52.3" lon="21.3"/>'
            b"</trkseg></trk></gpx>"
        ),
    }


# --- the cuts -----------------------------------------------------------------


def _cuts(size: int) -> list[int]:
    """Where to stop the file.

    A geometric ladder, plus the halfway point and one byte short of the whole:
    enough to land inside a header, inside a length field and inside a payload,
    without running a reader once per byte of every fixture.
    """
    ladder = {0, 1, 2, 3, 4, 5, 6, 7, size // 2, size - 1}
    step = 8
    while step < size:
        ladder.add(step)
        step *= 2
    return sorted(cut for cut in ladder if 0 <= cut < size)


def test_every_fixture_is_named(corpus: dict[str, bytes]):
    """The list the test parametrises over and the corpus cannot drift apart."""
    assert sorted(corpus) == sorted(_NAMES)


@pytest.mark.parametrize("name", _NAMES)
def test_a_file_that_stops_in_the_middle_is_read_rather_than_raised_at(
    name: str, corpus: dict[str, bytes], tmp_path: Path
):
    whole = corpus[name]
    target = tmp_path / name

    for cut in _cuts(len(whole)):
        target.write_bytes(whole[:cut])
        for reader in _READERS:
            try:
                reader(target)
            except Exception as problem:
                pytest.fail(
                    f"{reader.__module__}.{reader.__name__} raised "
                    f"{type(problem).__name__}: {problem} "
                    f"on {name} cut to {cut} of {len(whole)} bytes"
                )


@pytest.mark.parametrize("name", _NAMES)
def test_a_file_that_stops_in_the_middle_is_cleaned_or_declined(
    name: str, corpus: dict[str, bytes], tmp_path: Path
):
    """`clean` reads the same broken files, and it is the command that writes.

    A stripper that raises where it meant to decline does not merely lose one
    file: the command ends there, and the copies it had already made are a
    partial job nobody was told was partial.
    """
    whole = corpus[name]
    target = tmp_path / name
    destination = tmp_path / "cleaned"

    for cut in _cuts(len(whole)):
        target.write_bytes(whole[:cut])
        try:
            clean_file(target, destination, below=tmp_path, overwrite=True)
        except Exception as problem:
            pytest.fail(
                f"clean_file raised {type(problem).__name__}: {problem} "
                f"on {name} cut to {cut} of {len(whole)} bytes"
            )


def test_a_shortcut_that_stops_in_the_middle_is_read_rather_than_raised_at():
    """The shell link reader takes bytes rather than a path, so it is cut here."""
    whole = shortcut(
        info=link_info(r"C:\Users\someone\Downloads\report.pdf", volume=volume_id(3, 0x1234, "OS")),
        name="report",
        relative=r".\report.pdf",
    )

    for cut in _cuts(len(whole)):
        try:
            read_link(whole[:cut])
        except Exception as problem:
            pytest.fail(
                f"read_link raised {type(problem).__name__}: {problem} "
                f"on a shortcut cut to {cut} of {len(whole)} bytes"
            )


# --- files that are whole and still wrong -------------------------------------


def _with_compression_method(raw: bytes, method: int) -> bytes:
    """The same package, claiming a compression nothing here can undo.

    Truncation is the accident; this is the crafted case. The method lives in
    both the local header and the central directory, and `zipfile` reads it out
    of the second - so both are patched, because a package that disagrees with
    itself is a third thing and not what is being tested.
    """
    body = bytearray(raw)
    for magic, field in ((b"PK\x03\x04", 8), (b"PK\x01\x02", 10)):
        at = 0
        while (at := body.find(magic, at)) >= 0:
            struct.pack_into("<H", body, at + field, method)
            at += 4
    return bytes(body)


@pytest.mark.parametrize("name", ("notes.docx", "notes.odt", "bundle.zip"))
def test_a_package_claiming_an_unknown_compression_is_declined(
    name: str, corpus: dict[str, bytes], tmp_path: Path
):
    """`zipfile` answers a method it does not know with `NotImplementedError`.

    Which is neither `ValueError` nor `OSError` nor anything else the readers
    were listing, so two patched bytes per member used to end a whole scan.
    """
    document = tmp_path / name
    document.write_bytes(_with_compression_method(corpus[name], 99))

    for reader in _READERS:
        try:
            reader(document)
        except Exception as problem:
            pytest.fail(
                f"{reader.__module__}.{reader.__name__} raised "
                f"{type(problem).__name__}: {problem} on {name}"
            )
    assert clean_file(document, tmp_path / "cleaned").written is None
