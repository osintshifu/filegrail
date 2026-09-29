"""One file per route through the metadata dispatcher, and what must come out of it.

`docs/FORMATS.md` names ninety-odd extensions this project says it reads, and
nothing held that list to account. Most of them are names for a container
something else already proves: `.jpe` reaches the same reader as `.jpg`, and a
test that reads a JPEG proves both. But nothing said so, and nothing stopped an
extension being added to a reader's set, written into the table and never read
at all. It would have passed every test in the suite.

A route is one path through `read_embedded_metadata`, which chooses by
extension and by nothing else. So the routes are exactly the suffix sets the
readers declare, and `exif` is four of them rather than one: a camera's EXIF
reaches that reader inside a JPEG, inside a TIFF, inside a HEIF and inside a
RIFF WebP, which are four different searches for one payload. Taking the list
from those sets rather than writing it out again is what keeps it true - a new
set with no specimen fails a test instead of going unread.

Each specimen carries a value no reader could produce by accident, and what is
checked is that the value comes back under the name it was written with. A
check that asked only whether *something* was read would pass on a reader that
returned the wrong block, which is most of what can go wrong here.

The builders are the suite's own, imported rather than copied. Where a route
had no whole-file builder - a Photoshop document, a web page - one is here.
"""

from __future__ import annotations

import shutil
import struct
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from filegrail.models import EvidenceRecord
from filegrail.sources.embedded import (
    aiff,
    ape,
    containers,
    documents,
    exif,
    fonts,
    id3,
    isobmff,
    matroska,
    ole,
    pe,
    photoshop,
    png,
    riff,
    vorbis,
    web,
)

from .compound import ole as cfb
from .test_aiff import _aiff
from .test_ape import _ape
from .test_blocks import _audio, _epub, _movie, _notebook, _odf, _ooxml, _rtf, _svg
from .test_fonts import TABLES, _sfnt
from .test_formats import _jpeg, _png, _tiff
from .test_matroska import matroska as _mkv
from .test_ole import _property_set
from .test_pe import executable
from .test_riff import info
from .test_riff import riff as _riff_form
from .test_vorbis import comments, flac, ogg

#: The value most specimens carry. Nothing decodes to it by chance, so a field
#: holding it was read out of the file rather than defaulted or invented.
MARK = "Fieldwork Example"

#: The format identifier of the summary property set a compound document holds.
_SUMMARY_FMTID = bytes.fromhex("e0859ff2f94f6810ab9108002b27b3d9")


@dataclass(frozen=True, slots=True)
class Specimen:
    """A file the readers have to read, and what they have to find in it."""

    #: The route, named the way a person would say it out loud.
    route: str

    #: Every extension this route claims. All of them get the same bytes.
    suffixes: frozenset[str]

    #: The metadata block the reader has to say it read.
    block: str

    #: What has to come back, keyed the way `reported` keys it: a field name,
    #: or `tool`, `note` or `at` for what a record says about itself.
    expect: dict[str, str]

    #: Writes the specimen at exactly this path.
    write: Callable[[Path], None]


def reported(record: EvidenceRecord) -> dict[str, str]:
    """Everything a record says, under the names a specimen uses to ask for it.

    A reader puts the creating tool, the moment and a one-line summary on the
    record itself rather than among the fields, and for some formats that is
    the whole of what it found: an ID3 tag naming only its encoder produces a
    record with no fields at all. Flattening the two lets a specimen say what
    it expects without also having to know where the reader chose to put it.
    """
    said = dict(record.fields)
    for name in ("tool", "note", "at"):
        value = getattr(record, name)
        if value:
            said.setdefault(name, value)
    return said


def _bytes(make: Callable[[], bytes]) -> Callable[[Path], None]:
    """A specimen assembled as bytes, which most of them are."""

    def write(path: Path) -> None:
        path.write_bytes(make())

    return write


def _built(builder: Callable[..., Path], *args: object) -> Callable[[Path], None]:
    """A specimen from a fixture that writes into a directory of its own.

    Several of these name the file themselves. The corpus needs those bytes
    under a name it chooses, so the fixture builds where it likes and the
    result is copied across.
    """

    def write(path: Path) -> None:
        workshop = path.parent / f".build-{path.name}"
        workshop.mkdir(parents=True, exist_ok=True)
        try:
            path.write_bytes(builder(workshop, *args).read_bytes())
        finally:
            shutil.rmtree(workshop, ignore_errors=True)

    return write


# --- the containers nothing had a whole-file builder for ---------------------


def _psd(path: Path) -> None:
    """A Photoshop document around the resource that names the application.

    The resource block and the version resource are the suite's own. What was
    missing was a document to put them in, which two test files each wrote
    inline. The header ends where the resource section does: the resources are
    reachable in a `.psd` carrying no layers and no pixels.
    """
    from .test_photoshop import _irb, _version

    resources = _irb(0x0421, _version())
    path.write_bytes(
        b"8BPS"
        + struct.pack(">H", 1)
        + b"\x00" * 6
        + struct.pack(">HIIHH", 3, 1, 1, 8, 3)
        + struct.pack(">I", 0)
        + struct.pack(">I", len(resources))
        + resources
    )


def _web_page() -> bytes:
    """A page with its metadata in the places the reader looks."""
    return (
        "<!doctype html><html><head>"
        '<meta charset="utf-8">'
        f'<meta name="author" content="{MARK}">'
        '<meta name="generator" content="Static Forge 4.2">'
        "<title>Field notes</title>"
        "</head><body><p>Nothing here matters but the head.</p></body></html>"
    ).encode()


def _compound(path: Path) -> None:
    """A compound document carrying the summary property set a real one has."""
    author, title = 0x04, 0x02
    path.write_bytes(
        cfb(
            {
                "\x05SummaryInformation": _property_set(
                    _SUMMARY_FMTID, {author: (30, MARK), title: (30, "Field notes")}
                )
            }
        )
    )


def _matroska(path: Path) -> None:
    """A Matroska with a writing application and one open tag.

    Both on purpose. With the tag alone the dispatcher reports nothing, and
    rightly: a performer's name is not an account of where a file came from.
    The writing application is what makes the record worth returning, and the
    tag is what proves the open tag list is read rather than a fixed one.
    """
    from .test_matroska import INFO, TAG, TAGS, WRITING_APP, element, simple_tag

    _mkv(
        path.parent,
        element(INFO, element(WRITING_APP, b"mkvmerge v82.0")),
        element(TAGS, element(TAG, simple_tag(b"ARTIST", MARK.encode("ascii")))),
        name=path.name,
    )


def _exif_payload() -> bytes:
    return _tiff([(0x010F, 2, MARK), (0x0110, 2, "Model One")])


def _webp() -> bytes:
    """A WebP carrying its EXIF in the RIFF chunk reserved for it."""
    payload = _exif_payload()
    body = (
        b"WEBP"
        + b"VP8 "
        + struct.pack("<I", 4)
        + b"\x00" * 4
        + b"EXIF"
        + struct.pack("<I", len(payload))
        + payload
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _heif_image() -> bytes:
    from .test_formats import _heif

    return _heif(_exif_payload())


def _wave() -> bytes:
    return _riff_form(b"WAVE", [info([(b"IART", MARK.encode("ascii"))])])


def _avi() -> bytes:
    """An AVI writes the same list under a different form type."""
    return _riff_form(b"AVI ", [info([(b"IART", MARK.encode("ascii"))])])


def _comment_block() -> bytes:
    return comments(b"reference libFLAC 1.4.3", f"ARTIST={MARK}".encode(), b"DATE=2026")


def _ape_file() -> bytes:
    return b"MAC \x00" * 40 + _ape([("Artist", MARK.encode(), 0), ("Year", b"2026", 0)])


def _aiff_file() -> bytes:
    comm = struct.pack(">hIh", 2, 44100 * 30, 16) + b"\x40\x0e\xac\x44" + b"\x00" * 6
    name = MARK.encode("ascii")
    return _aiff(
        b"AIFF",
        [
            b"COMM" + struct.pack(">I", len(comm)) + comm,
            b"AUTH" + struct.pack(">I", len(name)) + name + (b"\x00" if len(name) % 2 else b""),
        ],
    )


def _pdf_file() -> bytes:
    """A PDF whose Info dictionary the cross reference table actually lists."""
    from .pdf import document

    return document([b""], info=f"<< /Author ({MARK}) /Creator (Field Press 2.1) >>".encode())


#: Every route, and what proves it. The suffix sets come from the readers, so
#: this list cannot claim a coverage the code does not have.
SPECIMENS: tuple[Specimen, ...] = (
    Specimen("PDF", documents.PDF_SUFFIXES, "pdf-info", {"Author": MARK}, _bytes(_pdf_file)),
    Specimen(
        "OOXML package",
        documents.OOXML_SUFFIXES,
        "ooxml-properties",
        {"creator": "Jan Kowalski"},
        _ooxml,
    ),
    Specimen(
        "EXIF in JPEG",
        exif.JPEG_SUFFIXES,
        "exif",
        {"Make": MARK},
        _bytes(lambda: _jpeg(_exif_payload())),
    ),
    Specimen("EXIF in TIFF", exif.TIFF_SUFFIXES, "exif", {"Make": MARK}, _bytes(_exif_payload)),
    Specimen("EXIF in HEIF", exif.HEIF_SUFFIXES, "exif", {"Make": MARK}, _bytes(_heif_image)),
    Specimen("EXIF in WebP", exif.WEBP_SUFFIXES, "exif", {"Make": MARK}, _bytes(_webp)),
    Specimen(
        "PNG text",
        png.SUFFIXES,
        "png-text",
        {"Author": MARK},
        _bytes(lambda: _png([(b"tEXt", b"Author\x00" + MARK.encode("ascii"))])),
    ),
    # The HEIF extensions belong to the EXIF reader, which runs first and
    # answers for them. What is left over is the route this specimen is about.
    Specimen(
        "ISO base media",
        isobmff.SUFFIXES - exif.SUFFIXES,
        "isobmff",
        {"Encoder": "HandBrake 1.7.3"},
        _movie,
    ),
    Specimen(
        "ODF package",
        containers.ODF_SUFFIXES,
        "odf-meta",
        {"generator": "LibreOffice/24.2"},
        _odf,
    ),
    Specimen(
        "EPUB package",
        containers.EPUB_SUFFIXES,
        "epub-package",
        {"note": "author Mary Shelley"},
        _epub,
    ),
    Specimen(
        "RTF", containers.RTF_SUFFIXES, "rtf-generator", {"tool": "Riched20 10.0.19041"}, _rtf
    ),
    Specimen("SVG", containers.SVG_SUFFIXES, "svg-metadata", {"tool": "Inkscape 1.3.2"}, _svg),
    Specimen(
        "Notebook",
        containers.NOTEBOOK_SUFFIXES,
        "notebook-kernel",
        {"tool": "Jupyter (Python 3)"},
        _notebook,
    ),
    Specimen("ID3 tag", id3.SUFFIXES, "id3", {"tool": "Lavf58.44.100"}, _audio),
    Specimen("RIFF WAVE", riff.WAVE_SUFFIXES, "riff", {"Artist": MARK}, _bytes(_wave)),
    Specimen("RIFF AVI", riff.AVI_SUFFIXES, "riff", {"Artist": MARK}, _bytes(_avi)),
    Specimen("Matroska", matroska.SUFFIXES, "matroska", {"ARTIST": MARK}, _matroska),
    Specimen(
        "FLAC",
        vorbis.FLAC_SUFFIXES,
        "vorbis-comment",
        {"ARTIST": MARK},
        _built(flac, _comment_block()),
    ),
    Specimen(
        "Ogg",
        vorbis.OGG_SUFFIXES,
        "vorbis-comment",
        {"ARTIST": MARK},
        _built(ogg, b"\x03vorbis", _comment_block()),
    ),
    Specimen("Compound document", ole.SUFFIXES, "ole-summary", {"Author": MARK}, _compound),
    Specimen(
        "Photoshop document",
        photoshop.DOCUMENT_SUFFIXES,
        "photoshop-irb",
        {"tool": "Adobe Photoshop 25.0"},
        _psd,
    ),
    Specimen("Web page", web.SUFFIXES, "web-document", {"author": MARK}, _bytes(_web_page)),
    Specimen(
        "PE image",
        pe.SUFFIXES,
        "pe-header",
        {"CompanyName": MARK},
        _built(executable, {"CompanyName": MARK}),
    ),
    Specimen(
        "SFNT font",
        fonts.SUFFIXES,
        "font-tables",
        {"Designer": "Anna Nowak"},
        _bytes(lambda: _sfnt(TABLES)),
    ),
    Specimen("AIFF", aiff.SUFFIXES, "aiff", {"Author": MARK}, _bytes(_aiff_file)),
    Specimen("APE tag", ape.SUFFIXES, "ape-tag", {"Artist": MARK}, _bytes(_ape_file)),
)
