"""What a file says, as distinct from what it records about itself.

Every other reader here answers *where did this come from*. This one answers
nothing on its own: it hands back the readable text of a document so that the
identifier detectors can be pointed at it, and the text is not a claim about
provenance. A body is not evidence of arrival, and turning one into an `EvidenceRecord`
would put a paragraph beside a download record as though the two said the same
kind of thing.

What makes it worth reading here rather than with `grep` is what sits beside
it. An address in a document is a lead. An address in a document that the
file's *arrival* record also names is a link, and only something that already
read the arrival record can see that.

**No new dependencies, and that is not a compromise.** The formats where a text
search fails hardest - a `.docx`, an `.odt`, a slide deck - are zip archives of
XML, and this package already opens them for their properties, with a bounded
member reader written for exactly this hazard. The body is a different member
of the same archive.

A PDF is read by `pdftext`, which is the one format here that needed a parser
rather than plumbing: the bytes a PDF draws are indices into whatever encoding
each font uses, so the text comes back through that font or does not come back
at all. What it refuses, and why, is in that module.

Deliberately not read, with reasons:

* **Source code** - a checkout is thousands of files whose identifiers are
  dependency hosts and licence URLs. `SKIP_DIRECTORIES` keeps a scan out of
  `node_modules` on the same principle.
* **RTF** - text under a layer of control words and hex escapes, which would
  need a parser to read honestly and yields noise without one.
"""

from __future__ import annotations

import codecs
import csv
import json
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import NamedTuple

from .embedded.containers import EPUB_SUFFIXES, ODF_SUFFIXES, SVG_SUFFIXES
from .embedded.documents import OOXML_SUFFIXES, PDF_SUFFIXES
from .embedded.parts import read_part
from .mail import OUTLOOK_SUFFIXES
from .mail import SUFFIXES as MAIL_SUFFIXES
from .pdftext import MAX_FILE_BYTES, read_pages

#: The most text taken from one file. Identifiers repeat; a document long
#: enough to exhaust this has said what it is going to say, and the point of
#: the number is that there be one - the same argument `parts.py` makes.
MAX_TEXT_BYTES = 1024 * 1024

#: How many members of one package are read. A deck can hold a thousand slides
#: and each one costs an open, a bounded read and a parse.
MAX_PARTS = 64


class Passage(NamedTuple):
    """A run of a document's text, and where in the document it sits.

    The place is written in whatever terms the format actually has - a line, a
    slide, a sheet, a chapter, the body of a message - and no others. It is the
    difference between an identifier a reader can go and look at and one they
    have to search the file for again.
    """

    place: str
    text: str


#: Files that already are text. Data formats are included - a JSON export from
#: an application is exactly the sort of file an examiner is handed - and
#: source code is not, for the reason in the module docstring.
PLAIN_SUFFIXES = {
    ".txt",
    ".text",
    ".md",
    ".markdown",
    ".rst",
    ".log",
    ".csv",
    ".tsv",
    ".json",
    ".ndjson",
    ".jsonl",
    ".ipynb",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".vcf",
    ".ics",
    # A map and a canvas are JSON too: an Obsidian board is text in nodes, and
    # GeoJSON is read a second time, below, for the positions its text hides.
    ".geojson",
    ".canvas",
}

#: Data formats read twice: once by line like any text, once for the
#: positions they carry as structure rather than prose.
GEOJSON_SUFFIXES = {".geojson"}

#: Formats whose rows are cells rather than prose, and what separates them.
#: Read by line, a value in one column takes the separator and its neighbour
#: with it - a URL ending in `/` swallows the `,` and the column after it.
TABULAR_SUFFIXES = {".csv": ",", ".tsv": "\t"}

#: Markup read twice for the same reason. A track and a map file are XML, so
#: their names and links come out like any markup; the positions need a
#: reader that knows which attribute is the latitude.
POSITION_SUFFIXES = {".gpx", ".kml"}

#: Markup, read for its text and its links rather than its tags.
MARKUP_SUFFIXES = (
    {".html", ".htm", ".xhtml", ".xml", ".graphml", ".gexf", ".mm"}
    | SVG_SUFFIXES
    | POSITION_SUFFIXES
)

#: Attributes that carry the text of a node, by the format that keeps it there.
#: A Gephi graph and a FreeMind map both write what a node says as an attribute
#: rather than as text, where a reader that keeps only addresses never looks.
#: Per suffix rather than global: `value` is every form field in HTML.
_LABEL_ATTRIBUTES: dict[str, frozenset[str]] = {
    ".gexf": frozenset({"label"}),
    ".mm": frozenset({"text"}),
}

#: Packages whose body lives in a named member beside the properties.
#: A zipped map, a mind map and a Maltego export are packages too: a `.kml`,
#: a JSON or XML body, and one GraphML per graph, each beside its metadata.
PACKAGE_SUFFIXES = OOXML_SUFFIXES | ODF_SUFFIXES | EPUB_SUFFIXES | {".kmz", ".xmind", ".mtgx"}

SUFFIXES = (
    PLAIN_SUFFIXES
    | MARKUP_SUFFIXES
    | PACKAGE_SUFFIXES
    | MAIL_SUFFIXES
    | OUTLOOK_SUFFIXES
    | PDF_SUFFIXES
)

#: Which members of a package hold what the document says, and what to call
#: each one. Word keeps the notes and comments outside the main part, a deck
#: keeps one member per slide, and a spreadsheet keeps every string it shows in
#: one table - so the body of a document is several members and never just one.
#:
#: The name on the right is what a reader is told, in the terms the format
#: actually has. A deck has slides and a workbook has sheets; a Word file has
#: neither pages nor lines, because pagination happens when something renders
#: it and the file does not record where the breaks fell. Naming a page there
#: would be inventing a number, which is the one thing a report of evidence
#: must not do.
_PARTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^word/document\d*\.xml$"), "body"),
    (re.compile(r"^word/footnotes\d*\.xml$"), "footnotes"),
    (re.compile(r"^word/endnotes\d*\.xml$"), "endnotes"),
    (re.compile(r"^word/comments\d*\.xml$"), "comments"),
    (re.compile(r"^ppt/slides/slide(\d+)\.xml$"), "slide {}"),
    (re.compile(r"^ppt/notesSlides/notesSlide(\d+)\.xml$"), "slide {} notes"),
    (re.compile(r"^xl/sharedStrings\.xml$"), "cell text"),
    (re.compile(r"^xl/worksheets/sheet(\d+)\.xml$"), "sheet {}"),
    (re.compile(r"^content\.xml$"), "body"),
    (re.compile(r"^styles\.xml$"), "headers and footers"),
    # A KMZ is one map at the root; an XMind file keeps its topics in a JSON
    # body, or an XML one in older versions, which the ODF row above already
    # names; a Maltego export is one GraphML per graph, numbered by the file.
    (re.compile(r"^[^/]+\.kml$", re.IGNORECASE), "map"),
    (re.compile(r"^content\.json$"), "body"),
    (re.compile(r"^Graphs/Graph(\d+)\.graphml$"), "graph {}"),
    # An EPUB is a book of chapters, each its own document, and the file name
    # is what the book itself calls them.
    (re.compile(r"^(?:.*/)?([^/]+\.x?html?)$", re.IGNORECASE), "{}"),
)

#: Elements whose text is not what the document says. A stylesheet is full of
#: things that match - a colour is a short hex digest - and a script carries
#: hosts a bundler wrote rather than hosts anybody typed.
_SILENT = {"script", "style"}

#: Attributes that carry an address a person put there. `xmlns` is excluded on
#: purpose: every XML document in the world names `w3.org`, and reporting that
#: as something a file said would be the loudest false positive available.
_LINK_ATTRIBUTES = {"href", "src", "cite", "action", "data", "longdesc", "poster"}

#: A body stream in a compound message, unicode first. Same shape as the
#: transport headers `mail.py` reads out of the same container.
_OUTLOOK_BODY = ("__substg1.0_1000001F", "__substg1.0_1000001E")

#: What a document raises when it is not the document its extension claims.
#: The list the readers beside this one keep, for the same reason - and with
#: the two `zipfile` contributes that are neither `OSError` nor `ValueError`.
_UNREADABLE = (
    OSError,
    ValueError,
    LookupError,
    zipfile.BadZipFile,
    NotImplementedError,
    csv.Error,
)


def read_passages(path: Path) -> list[Passage] | None:
    """The readable text of `path`, in pieces that each know where they are.

    None is the answer for a format nothing here handles, for a file that is
    not the format its name claims, and for a document that turns out to hold
    no text - all three of which are ordinary, and none of which is an error.
    """
    suffix = path.suffix.lower()
    if suffix not in SUFFIXES:
        return None

    try:
        if suffix in PLAIN_SUFFIXES:
            text = _decode(_head(path))
            delimiter = TABULAR_SUFFIXES.get(suffix)
            found = _lines(text) if delimiter is None else _cells(text, delimiter)
            if suffix in GEOJSON_SUFFIXES:
                found += _features(text)
        elif suffix in MARKUP_SUFFIXES:
            markup = _decode(_head(path))
            found = _read(markup, _LABEL_ATTRIBUTES.get(suffix, frozenset()))
            if suffix in POSITION_SUFFIXES:
                found += _positions(markup)
        elif suffix in PDF_SUFFIXES:
            found = [Passage(f"page {number}", text) for number, text in read_pages(_whole(path))]
        elif suffix in PACKAGE_SUFFIXES:
            found = _package(path)
        elif suffix in MAIL_SUFFIXES:
            found = _message(path)
        else:
            found = _outlook(path)
    except _UNREADABLE:
        return None

    return _bounded(found) or None


def _bounded(found: list[Passage]) -> list[Passage]:
    """The passages that fit in the budget, with the blank ones dropped.

    The budget is spent across the document rather than per piece, so a file
    cannot cost more by being cut into many pieces than by being one - which is
    the same reasoning `MAX_PARTS` applies to a package's members.
    """
    kept: list[Passage] = []
    budget = MAX_TEXT_BYTES
    for passage in found:
        text = passage.text.strip()
        if not text:
            continue
        kept.append(Passage(passage.place, text[:budget]))
        budget -= len(kept[-1].text)
        if budget <= 0:
            break
    return kept


def _lines(text: str) -> list[Passage]:
    """One passage per line, because a line is what a text file has."""
    return [Passage(f"line {number}", line) for number, line in enumerate(text.split("\n"), 1)]


def _cells(text: str, delimiter: str) -> list[Passage]:
    """One passage per cell, because a cell is what a table has.

    A row read as one line runs its columns together, and a value at the end of
    one takes the separator and the next column with it. The cell is also the
    more exact place to report: a reader given a row and a column can go and
    look at the value, where a line number leaves them searching it again.

    `splitlines(True)` keeps the line endings, so a quoted field that spans
    several lines stays one cell and the count stays a count of rows.
    """
    found = []
    for number, row in enumerate(csv.reader(text.splitlines(True), delimiter=delimiter), 1):
        for index, cell in enumerate(row, 1):
            found.append(Passage(f"row {number} · column {index}", cell))
    return found


def _whole(path: Path) -> bytes:
    """A PDF, all of it, or nothing.

    The front of the file is not enough: a PDF says where its pages are in a
    table at the end, and an object may sit anywhere between. So the bound is
    on the size of the document rather than on a prefix of it, and one past
    the bound is left unread rather than read in part - half a PDF is not a
    shorter PDF, it is an unreadable one.
    """
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return b""
        return path.read_bytes()
    except OSError:
        return b""


def _head(path: Path) -> bytes:
    """The front of the file, and one byte more than will be kept.

    Read rather than mapped: the bound here is the point, and a file larger
    than it is the ordinary case rather than the exception - a log grows
    without anybody deciding to make it big.
    """
    with path.open("rb") as handle:
        # Two bytes per character in the worst case this decodes, so the byte
        # budget is doubled to fill the character budget.
        return handle.read(MAX_TEXT_BYTES * 2 + 1)


def _decode(raw: bytes) -> str:
    """Bytes as text, without a character-set detector.

    Everything read from this afterwards is ASCII - an address, a host, a
    dotted quad, a hex digest, a coordinate - so a mis-decoded accent costs a
    character nothing was looking for, and guessing properly would cost a
    dependency this package does not have. UTF-16 is the exception worth
    handling: a Windows editor marks it, and reading it as UTF-8 puts a NUL
    between every letter, which breaks every pattern rather than one accent.
    """
    for mark, encoding in (
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    ):
        if raw.startswith(mark):
            return raw.decode(encoding, "replace")
    return raw.decode("utf-8", "replace")


class _Text(HTMLParser):
    """Markup reduced to what a person would have read, plus the links.

    A parser rather than a regular expression over angle brackets, because the
    two things that have to be got right - which elements to stay out of, and
    which attributes carry an address somebody typed - are both about
    structure. `HTMLParser` is in the standard library, is written in Python,
    and expands no entities of its own, so it adds no new way for a file to
    cost more than it is worth.
    """

    def __init__(self, labels: frozenset[str] = frozenset()) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[Passage] = []
        self._silent = 0
        self._labels = labels

    def _keep(self, text: str) -> None:
        # `getpos` is the line of the markup being handled, which is the line
        # of the file - the one number here a person can act on.
        self.found.append(Passage(f"line {self.getpos()[0]}", text))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SILENT:
            self._silent += 1
        for name, value in attrs:
            if value and (name.lower() in _LINK_ATTRIBUTES or name.lower() in self._labels):
                self._keep(value)

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag: str) -> None:
        if tag in _SILENT and self._silent:
            self._silent -= 1

    def handle_data(self, data: str) -> None:
        if not self._silent:
            self._keep(data)


def _read(markup: str, labels: frozenset[str] = frozenset()) -> list[Passage]:
    parser = _Text(labels)
    parser.feed(markup)
    parser.close()
    return parser.found


class _Positions(HTMLParser):
    """The positions a track or map file carries as structure, as `geo:` URIs.

    GPX writes a point as a `lat`/`lon` attribute pair; KML writes `lon,lat`
    with the longitude first. Each is rendered `geo:lat,lon`, the one spelling
    the coordinate detector takes on its own - so the detectors need not know
    these formats exist, and a bare pair of decimals in a document is still
    never believed. The digits are the document's own, not a float printed
    back: what is reported is what the file said.

    A track or a line is thousands of points and a report is not the place
    for them; where it began and where it stopped is what a reader wants to
    know, so those two are kept and the rest are not. A named point is kept
    whole. Not read: `gx:Track`, polygons and multi-geometries - each is a
    different element, and none has come up.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[Passage] = []
        self._waypoints = 0
        self._tracks = 0
        self._placemarks = 0
        #: The points of the track being read, or None outside one.
        self._track: list[tuple[str, str]] | None = None
        #: Which geometry the current placemark holds, once it says.
        self._shape: str | None = None
        #: The text of a `<coordinates>` element, which can arrive in pieces.
        self._coordinates: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "wpt":
            pair = _pair(dict(attrs))
            if pair is not None:
                self._waypoints += 1
                self.found.append(Passage(f"waypoint {self._waypoints}", _geo(pair)))
        elif tag == "trk":
            self._tracks += 1
            self._track = []
        elif tag == "trkpt" and self._track is not None:
            pair = _pair(dict(attrs))
            if pair is not None:
                self._track.append(pair)
        elif tag == "placemark":
            self._placemarks += 1
            self._shape = None
        elif tag in ("point", "linestring"):
            self._shape = tag
        elif tag == "coordinates":
            self._coordinates = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # `<trkpt .../>` is the common spelling; an empty `<trk/>` or
        # `<coordinates/>` opens and closes and must not stay open.
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._coordinates is not None:
            self._coordinates.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "trk":
            points, self._track = self._track or [], None
            if points:
                self.found.append(Passage(f"track {self._tracks} start", _geo(points[0])))
            if len(points) > 1:
                self.found.append(Passage(f"track {self._tracks} end", _geo(points[-1])))
        elif tag == "coordinates":
            text, self._coordinates = "".join(self._coordinates or []), None
            points = _turned(text)
            number = self._placemarks
            if self._shape == "point" and points:
                self.found.append(Passage(f"placemark {number}", _geo(points[0])))
            elif self._shape == "linestring" and points:
                self.found.append(Passage(f"placemark {number} start", _geo(points[0])))
                if len(points) > 1:
                    self.found.append(Passage(f"placemark {number} end", _geo(points[-1])))
            self._shape = None


def _positions(markup: str) -> list[Passage]:
    parser = _Positions()
    parser.feed(markup)
    parser.close()
    return parser.found


def _pair(attrs: dict[str, str | None]) -> tuple[str, str] | None:
    """A GPX point's latitude and longitude, if both are present and numbers."""
    latitude, longitude = attrs.get("lat"), attrs.get("lon")
    if latitude is None or longitude is None:
        return None
    try:
        float(latitude), float(longitude)
    except ValueError:
        return None
    return latitude.strip(), longitude.strip()


def _turned(text: str) -> list[tuple[str, str]]:
    """KML's whitespace-separated `lon,lat[,alt]` tuples, turned into (lat, lon)."""
    points: list[tuple[str, str]] = []
    for token in text.split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            float(parts[0]), float(parts[1])
        except ValueError:
            continue
        points.append((parts[1], parts[0]))
    return points


def _geo(pair: tuple[str, str]) -> str:
    return f"geo:{pair[0]},{pair[1]}"


def _position(value: object) -> tuple[str, str] | None:
    """One GeoJSON position, `[lon, lat, ...]`, as (lat, lon) - longitude first there too."""
    if not isinstance(value, list) or len(value) < 2:
        return None
    longitude, latitude = value[0], value[1]
    for number in (longitude, latitude):
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            return None
    return str(latitude), str(longitude)


def _features(text: str) -> list[Passage]:
    """The point and line features of a GeoJSON file, in the order it lists them.

    A file that does not parse - cut short by the budget, or not JSON at all -
    contributes no positions and keeps its lines.
    """
    try:
        document = json.loads(text)
    except ValueError:
        return []
    features = document.get("features") if isinstance(document, dict) else None
    if not isinstance(features, list):
        features = [document]
    found: list[Passage] = []
    for number, feature in enumerate(features, 1):
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry", feature)
        if not isinstance(geometry, dict):
            continue
        shape, coordinates = geometry.get("type"), geometry.get("coordinates")
        if shape == "Point":
            pair = _position(coordinates)
            if pair is not None:
                found.append(Passage(f"feature {number}", _geo(pair)))
        elif shape == "LineString" and isinstance(coordinates, list):
            points = [pair for pair in map(_position, coordinates) if pair is not None]
            if points:
                found.append(Passage(f"feature {number} start", _geo(points[0])))
            if len(points) > 1:
                found.append(Passage(f"feature {number} end", _geo(points[-1])))
    return found


def _stripped(markup: str) -> str:
    """The text of some markup as one string, for a place that has no lines.

    A member of a package is addressed by which member it is; the line it fell
    on inside `word/document.xml` is a fact about the writer's XML formatter
    and about nothing a reader could go and look at.
    """
    return " ".join(passage.text for passage in _read(markup))


def _place(member: str) -> str | None:
    """What to call this member of a package, or None if it holds no text."""
    for pattern, name in _PARTS:
        found = pattern.match(member)
        if found is not None:
            return name.format(*found.groups())
    return None


def _package(path: Path) -> list[Passage]:
    """The body members of a zip-based document, in the order it stores them.

    Read through `read_part`, so one member cannot cost more than the bound it
    already sets, and capped at `MAX_PARTS` members so a package cannot cost
    more by holding many small ones instead of one large one.
    """
    found: list[Passage] = []
    with zipfile.ZipFile(path) as archive:
        named = [(name, _place(name)) for name in archive.namelist()]
        bodies = [(name, place) for name, place in named if place is not None]
        for name, place in bodies[:MAX_PARTS]:
            payload = read_part(archive, name)
            if payload is None:
                continue
            text = _decode(payload)
            lowered = name.lower()
            if lowered.endswith(".kml"):
                # The map's names and links under the member's name, and its
                # positions under their own - a placemark is where a value
                # was, not the file it sat in.
                found.append(Passage(place, _stripped(text)))
                found += _positions(text)
            elif lowered.endswith(".json"):
                found.append(Passage(place, text))
            else:
                found.append(Passage(place, _stripped(text)))
    return found


def _message(path: Path) -> list[Passage]:
    """A message's body, and none of its headers.

    The headers are already read as evidence of delivery, so taking them again
    here would count one address twice and file the second copy under the wrong
    corpus. The body is decoded first: quoted-printable and base64 both hide an
    address from anything reading the bytes as they lie.
    """
    from email import policy
    from email.parser import BytesParser

    with path.open("rb") as handle:
        message = BytesParser(policy=policy.default).parsebytes(handle.read(MAX_TEXT_BYTES * 2))

    found: list[Passage] = []
    for part in message.walk():
        if part.get_content_maintype() != "text":
            continue
        try:
            payload = part.get_content()
        except (LookupError, ValueError):
            continue  # an encoding this interpreter has no codec for
        if not isinstance(payload, str):
            continue
        if part.get_content_subtype() == "html":
            found.append(Passage("body (html)", _stripped(payload)))
        else:
            # Not cut into lines: a body reaches here decoded, and its lines no
            # longer correspond to the file's - quoted-printable puts soft
            # breaks where the message has none. A line number nobody can find
            # is worse than saying "the body" and meaning it.
            found.append(Passage("body", payload))
    return found


def _outlook(path: Path) -> list[Passage]:
    """The body stream of a compound message, unicode spelling first."""
    from .embedded.ole import read_streams

    streams = read_streams(path, list(_OUTLOOK_BODY))
    for name, encoding in zip(_OUTLOOK_BODY, ("utf-16-le", "utf-8"), strict=True):
        raw = streams.get(name)
        if raw is not None:
            return [Passage("body", raw.decode(encoding, "replace").rstrip("\x00"))]
    return []
