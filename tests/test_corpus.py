"""Invariants checked against a real corpus, when one is present.

The synthetic fixtures elsewhere in this suite are built from the spec. That is
exactly what they cannot catch: a reader that agrees with the spec but disagrees
with what encoders actually write. Both defects fixed in `test_formats.py` were
of that category, and both survived a fully green suite.

`test-data/` is not committed - it holds whatever real files the developer has
put there. These tests read it when it exists and skip when it does not, so the
invariant is enforced locally without third-party binaries entering the tree.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

from filegrail.correlate import ATTRIBUTION_CONFLICT, MIRRORS, correlate
from filegrail.models import FileRecord
from filegrail.sources import iptc as iptc_reader
from filegrail.sources import xmp as xmp_reader
from filegrail.sources.embedded import exif as exif_reader
from filegrail.sources.embedded import ole as ole_reader
from filegrail.sources.embedded import read_embedded_metadata

CORPUS = Path(__file__).resolve().parent.parent / "test-data"

#: Enough of the file to find a metadata block near the front.
_SCAN = 4 * 1024 * 1024


def _corpus_files(suffixes: set[str]) -> list[Path]:
    if not CORPUS.is_dir():
        return []
    return sorted(path for path in CORPUS.rglob("*") if path.suffix.lower() in suffixes)


#: Tags that say something about origin. Resolution and colour tags do not, and
#: a payload holding only those is correctly reported as nothing.
IDENTIFYING = (
    exif_reader.MAKE,
    exif_reader.MODEL,
    exif_reader.SOFTWARE,
    exif_reader.DATETIME,
    exif_reader.DATETIME_ORIGINAL,
    exif_reader.ARTIST,
)


def _identifying_payload(path: Path) -> bool:
    """True when the file holds an EXIF payload with something worth reporting.

    The payload is located independently of the reader under test - by its
    marker and the TIFF header behind it - and then decoded with the project's
    own TIFF parser. That splits locating from reporting, which is precisely
    where a container-specific bug hides: the parser is fine, the reader hands
    it the wrong bytes, and the file silently comes back empty.

    Deliberately stricter than "the string Exif appears": encoders write it as
    an item type too, and a file may store the payload out of line where no
    marker scan can reach it.
    """
    try:
        with path.open("rb") as handle:
            data = handle.read(_SCAN)
    except OSError:
        return False

    start = 0
    while True:
        marker = data.find(b"Exif\x00\x00", start)
        if marker < 0:
            return False
        payload = data[marker + 6 :]
        if payload[:2] in (b"II", b"MM"):
            try:
                tags = exif_reader._parse_tiff(payload)
            except Exception:
                tags = None
            if tags and (any(tag in tags for tag in IDENTIFYING) or tags.gps):
                return True
        start = marker + 1


IMAGES = _corpus_files(exif_reader.SUFFIXES)


@pytest.mark.skipif(not CORPUS.is_dir(), reason="no test-data corpus present")
@pytest.mark.parametrize("path", IMAGES, ids=lambda path: path.name)
def test_an_embedded_exif_payload_is_never_missed(path: Path):
    """A decodable payload must produce an origin, whatever the container."""
    if not _identifying_payload(path):
        pytest.skip("carries no reachable, identifying EXIF payload")

    assert read_embedded_metadata(path) is not None, (
        f"{path.name} holds an EXIF payload the reader did not decode"
    )


@pytest.mark.skipif(not CORPUS.is_dir(), reason="no test-data corpus present")
def test_the_corpus_holds_something_to_check():
    """Guard against the corpus silently becoming empty and proving nothing."""
    assert IMAGES, "test-data exists but holds no image this reader claims"


# --- compound documents ------------------------------------------------------

COMPOUND = _corpus_files(ole_reader.SUFFIXES)


def _has_summary(path: Path) -> bool:
    """True when the raw bytes hold a SummaryInformation property set.

    The format identifier is looked for directly rather than through the
    container reader, so the check stays independent of the code it guards.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return False
    return data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1") and ole_reader._SUMMARY in data


@pytest.mark.skipif(not CORPUS.is_dir(), reason="no test-data corpus present")
@pytest.mark.parametrize("path", COMPOUND, ids=lambda path: path.name)
def test_a_compound_document_summary_is_never_missed(path: Path):
    """A real Office document carrying a summary must report something."""
    if not _has_summary(path):
        pytest.skip("no SummaryInformation property set")

    assert ole_reader.read_ole(path) is not None, (
        f"{path.name} holds a SummaryInformation stream the reader did not decode"
    )


# --- XMP packets -------------------------------------------------------------

XMP_ROOT = re.compile(rb"<(\w+:)?xmpmeta\b.*?</(\w+:)?xmpmeta>", re.DOTALL)

XMP_CANDIDATES = _corpus_files(
    exif_reader.SUFFIXES | {".png", ".pdf", ".svg", ".mp4", ".mov", ".psd", ".ai"}
)


def _well_formed_packet(path: Path) -> bool:
    """True when a packet is locatable by a search independent of the reader.

    The reader narrows the file to two windows and matches the root element's
    local name. This finds the block with a regular expression over the same
    windows and then insists it parses, so what is under test is the decoding
    rather than the search.
    """
    try:
        with path.open("rb") as handle:
            data = handle.read(xmp_reader._WINDOW)
            if path.stat().st_size > xmp_reader._WINDOW:
                handle.seek(max(0, path.stat().st_size - xmp_reader._WINDOW))
                data += handle.read(xmp_reader._WINDOW)
    except OSError:
        return False

    found = XMP_ROOT.search(data)
    if not found or b"rdf:Description" not in found.group(0):
        return False
    try:
        ElementTree.fromstring(found.group(0).decode("utf-8", "replace"))
    except ElementTree.ParseError:
        return False
    return True


@pytest.mark.skipif(not CORPUS.is_dir(), reason="no test-data corpus present")
@pytest.mark.parametrize("path", XMP_CANDIDATES, ids=lambda path: path.name)
def test_a_well_formed_xmp_packet_is_never_missed(path: Path):
    """Every defect found here so far was a packet the reader could not locate:
    a root element under an unexpected prefix, a namespace spelled without its
    trailing slash. Both parsed perfectly and both came back empty."""
    if not _well_formed_packet(path):
        pytest.skip("carries no locatable, well-formed XMP packet")

    assert xmp_reader.read_xmp(path), f"{path.name} holds an XMP packet the reader did not decode"


# --- IPTC blocks -------------------------------------------------------------

IPTC_CANDIDATES = _corpus_files(exif_reader.SUFFIXES | {".psd", ".jpg", ".jpeg"})


def _has_iim_datastream(path: Path) -> bool:
    """True when an 8BIM resource 0x0404 is present and holds record-2 entries.

    Found by its marker rather than through the reader's own block walk, so a
    resource whose header this project parses wrongly still counts as present.
    """
    try:
        with path.open("rb") as handle:
            data = handle.read(iptc_reader._WINDOW)
    except OSError:
        return False

    at = data.find(b"8BIM\x04\x04")
    return at >= 0 and data.find(b"\x1c\x02", at, at + 4096) > 0


@pytest.mark.skipif(not CORPUS.is_dir(), reason="no test-data corpus present")
@pytest.mark.parametrize("path", IPTC_CANDIDATES, ids=lambda path: path.name)
def test_a_present_iptc_block_is_never_missed(path: Path):
    """The corpus holds one file with an IIM block, which is thin cover for a
    reader built from a specification. What it can still prove is that the block
    a marker search finds is a block this reader decodes."""
    if not _has_iim_datastream(path):
        pytest.skip("no IIM datastream present")

    assert iptc_reader.read_iptc(path) is not None, (
        f"{path.name} holds an IIM datastream the reader did not decode"
    )


#: Files that could carry two accounts of themselves at once.
MIRROR_CANDIDATES = _corpus_files(exif_reader.SUFFIXES | {".pdf", ".png", ".psd", ".heic", ".avif"})


def _self_descriptions(path: Path) -> FileRecord:
    record = FileRecord(path=str(path), size=path.stat().st_size, mtime="")
    for reader in (read_embedded_metadata, iptc_reader.read_iptc):
        if (claim := reader(path)) is not None:
            record.evidence.append(claim)
    record.evidence.extend(xmp_reader.read_xmp(path))
    return record


def _one_fact(value: str) -> str:
    """Reduce a value the way a reader would, without asking the code under test.

    Anything date-shaped keeps its digits and loses its zone, which is how EXIF,
    IIM and XMP each spell one moment differently; anything else loses only case
    and spacing.
    """
    digits = re.sub(r"\D", "", value)
    if re.match(r"\d{4}\D?\d{2}\D?\d{2}", value.strip()):
        return digits[:14]
    return "".join(value.split()).casefold()


@pytest.mark.skipif(not CORPUS.is_dir(), reason="no test-data corpus present")
@pytest.mark.parametrize("path", MIRROR_CANDIDATES, ids=lambda path: path.name)
def test_two_spellings_of_one_fact_are_not_reported_as_a_conflict(path: Path):
    """A camera writes `2004:08:27 13:52:55` and its XMP mirror writes the same
    reading with a zone attached; IIM writes a bare day where XMP writes a full
    stamp. A comparison reading characters would find a contested attribution in
    almost every photograph ever taken, and every one of them would be invented.
    """
    record = _self_descriptions(path)
    reported = {
        finding.text.split(":", 1)[0]
        for finding in correlate(record).findings
        if finding.kind == ATTRIBUTION_CONFLICT
    }

    for mirror in MIRRORS:
        left = next((o for o in record.evidence if o.block == mirror.left), None)
        right = next((o for o in record.evidence if o.block == mirror.right), None)
        if left is None or right is None:
            continue
        theirs = {name.lower(): value for name, value in left.fields.items()}
        ours = {name.lower(): value for name, value in right.fields.items()}
        for name, other in mirror.text + mirror.moments:
            said, also = theirs.get(name.lower()), ours.get(other.lower())
            if said and also and _one_fact(said) == _one_fact(also):
                assert name not in reported, f"{name}: {said!r} and {also!r} are one fact"
