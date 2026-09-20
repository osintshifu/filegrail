"""What a scan found, before any one file is described.

A report that opens on its first entry has answered the last question an
analyst asks. These are the ones that come first: what is in this directory,
how much of it there is, how many files said anything at all, what they said,
and which of them wants a second look.

Nothing here decides anything. Every count is read back off the records the
scan already produced, through the same family table `--type` filters on and
the same correlation the entries print, so a number in the overview and the
entry it refers to cannot disagree.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .correlate import correlate
from .filters import FAMILIES
from .identify import IN_CONTENT, Identifier
from .models import ACTIVITY, METADATA, ORIGIN, FileRecord, category

#: Which family a file is counted under when more than one claims it. `.msg` is
#: in `document` and in `mail`, because either filter should select it; an
#: inventory has to put it in one place, and a message is the more specific of
#: the two answers.
PRECEDENCE = ("image", "video", "audio", "mail", "document", "archive", "text")

#: Files whose extension no family claims. Counted rather than dropped: the
#: format this tool does not know is exactly the one worth noticing.
OTHER = "other"

#: How a file with no extension is listed. It is a real answer, not a gap.
NO_EXTENSION = "(none)"

#: Spellings of one format, folded to the name the format is usually called by.
#: `JPG 20` beside `JPEG 1` counts one format twice, and an inventory exists to
#: say what is in a directory rather than which of two spellings each file
#: happened to be saved under. Presentation only: `--type`, `--ext` and the
#: record itself keep the extension the filesystem has.
ALIASES = {
    "jpg": "jpeg",
    "jpe": "jpeg",
    "tif": "tiff",
    "yml": "yaml",
    "htm": "html",
}

#: Compressed tarballs, where the last suffix alone says the least useful half
#: of what the file is. `GZ` for `audit.tar.gz` tells a reader nothing the file
#: name did not, and hides that it is an archive of many files.
COMPOUND = (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst")

#: How many files an alert names before it starts saying how many it did not.
#: The whole point of the section is that it is short enough to read.
NAMED = 5

#: Singular and plural, for the one verb every alert but the last one uses.
CONTAIN = ("contains", "contain")

#: Which field each block names a person in. Keyed on the block rather than on
#: the field name, because `Creator` is the application in a PDF Info dictionary
#: and the person in OOXML core properties - one flat list of names would count
#: every PDF's typesetter as its author. `identify._SOFTWARE_FIELDS` is the same
#: kind of table for the same reason.
AUTHOR_FIELDS: dict[str, tuple[str, ...]] = {
    "pdf-info": ("Author",),
    "ooxml-properties": ("creator", "lastModifiedBy"),
    "ole-summary": ("Author", "LastAuthor"),
    "odf-meta": ("creator", "initial-creator"),
    "epub-package": ("creator",),
    "rtf-generator": ("author",),
    "png-text": ("Author",),
    "exif": ("Artist",),
    "riff": ("Artist", "id3:artist"),
    "id3": ("artist",),
    "vorbis-comment": ("ARTIST", "PERFORMER"),
    "aiff": ("Author", "id3:artist"),
    "ape-tag": ("Artist",),
    "matroska": ("ARTIST",),
    "xmp": ("dc:creator",),
    "iptc": ("By-line",),
    #: Not the author of the picture but the owner of the body that took it,
    #: typed into the camera once and stamped on every frame since. As a way of
    #: putting a name to a photograph it frequently outlives the EXIF artist.
    "maker-notes": ("OwnerName",),
    "font-tables": ("Designer",),
    "web-document": (
        "author",
        "article:author",
        "citation_author",
        "dc.creator",
        "dcterms.creator",
        "jsonld:author",
    ),
}

#: Blocks that name no person, listed rather than left out so that adding a
#: reader is a decision somebody made rather than a count that quietly
#: understates itself. A test holds the two lists against the readers.
WITHOUT_AUTHOR = frozenset(
    {
        "isobmff",
        "svg-metadata",
        "notebook-kernel",
        "photoshop-irb",
        "pe-header",
        "c2pa",
        "xmp-history",
    }
)


@dataclass(frozen=True, slots=True)
class Extension:
    """One file type, and how much of the scan it accounts for."""

    name: str
    count: int
    size: int


@dataclass(frozen=True, slots=True)
class Inventory:
    """Everything that was scanned, by type and by family."""

    types: list[Extension]
    families: list[tuple[str, int]]
    files: int
    size: int


@dataclass(frozen=True, slots=True)
class Tally:
    """One row of the summary: what was read, in how many files.

    Not a finding. A finding is what correlation produced - a conflict, a
    corroboration, an impossible order; this counts how many files carried a
    kind of evidence at all, which is a different question and was being asked
    under the same name.
    """

    name: str
    files: int


@dataclass(frozen=True, slots=True)
class Alert:
    """One thing worth a second look, and where to look for it."""

    text: str

    #: Whether this is evidence disagreeing with itself, which is the one state
    #: the palette already has a colour for.
    contested: bool = False

    #: The files behind it, by the path the scan recorded, for the caller to
    #: show the way it shows every other path.
    files: tuple[str, ...] = ()

    #: How many more there were than `files` names. Said aloud rather than
    #: silently dropped: a capped list that does not admit it reads as the
    #: whole list.
    hidden: int = 0


def inventory(records: list[FileRecord]) -> Inventory:
    """Every extension in the scan, with how many files and how many bytes.

    No top ten and no ellipsis. Which types are present is the first thing an
    analyst wants from a directory they did not assemble, and a list that stops
    at the tenth answers it for the part they had already guessed.
    """
    counted: dict[str, list[int]] = {}
    families: dict[str, int] = {}

    for record in records:
        suffix = Path(record.path).suffix.lower()
        entry = counted.setdefault(format_of(record.path, suffix), [0, 0])
        entry[0] += 1
        entry[1] += record.size

        family = _family(suffix)
        families[family] = families.get(family, 0) + 1

    types = sorted(
        (Extension(name, count, size) for name, (count, size) in counted.items()),
        key=lambda entry: (-entry.count, -entry.size, entry.name),
    )
    ordered = [(name, families[name]) for name in (*PRECEDENCE, OTHER) if name in families]
    return Inventory(
        types=types,
        families=ordered,
        files=len(records),
        size=sum(record.size for record in records),
    )


def format_of(path: str, suffix: str) -> str:
    """What an analyst would call this file's format.

    The family is still decided by the extension the file actually has, so a
    name folded here can never move a file out of what `--type` would select.
    """
    lowered = path.lower()
    for compound in COMPOUND:
        if lowered.endswith(compound):
            return compound.lstrip(".").upper()
    if not suffix:
        return NO_EXTENSION
    bare = suffix.lstrip(".")
    return ALIASES.get(bare, bare).upper()


def _family(suffix: str) -> str:
    for name in PRECEDENCE:
        if suffix in FAMILIES[name]:
            return name
    return OTHER


# --- what was found ----------------------------------------------------------


def _has_origin(record: FileRecord) -> bool:
    return any(category(found) == ORIGIN for found in record.evidence)


def _has_activity(record: FileRecord) -> bool:
    return any(category(found) == ACTIVITY for found in record.evidence)


def _tooled(record: FileRecord) -> bool:
    return any(found.tool for found in record.evidence)


def _from_a_device(record: FileRecord) -> bool:
    return any(found.source == "device-metadata" for found in record.evidence)


def _content_credentials(record: FileRecord) -> bool:
    return any(found.source == "c2pa" for found in record.evidence)


def _placed(record: FileRecord) -> bool:
    return any(found.geo for found in record.evidence)


def _named_place(record: FileRecord) -> bool:
    return any(found.location for found in record.evidence)


def _edited(record: FileRecord) -> bool:
    return any(found.source == "xmp-history" for found in record.evidence)


def _dated(record: FileRecord) -> bool:
    return any(found.at for found in record.evidence)


def _related(record: FileRecord) -> bool:
    return bool(record.links)


def _contested(record: FileRecord) -> bool:
    return correlate(record).contested


def _described(record: FileRecord) -> bool:
    return any(category(found) == METADATA for found in record.evidence)


def _authored(record: FileRecord) -> bool:
    return any(
        name in found.fields
        for found in record.evidence
        for name in AUTHOR_FIELDS.get(found.block or "", ())
    )


#: What can be counted off a record without deciding anything new, in the order
#: the report prints it: which of the three questions the evidence answers,
#: then what the metadata turned out to hold, then how the files stand to each
#: other. Named for what was found rather than for the reader that found it -
#: `which parsers returned records` is the last section of the report, not this
#: one.
#:
#: How many files said anything at all, and how many said nothing, are not in
#: here: the masthead already counts both, and a row repeating one of them under
#: a slightly different name is a second number to keep in agreement with the
#: first.
TALLIES: tuple[tuple[str, Callable[[FileRecord], bool]], ...] = (
    ("metadata", _described),
    ("origin evidence", _has_origin),
    ("activity records", _has_activity),
    ("authors / creators", _authored),
    ("creating software", _tooled),
    ("device information", _from_a_device),
    ("Content Credentials", _content_credentials),
    ("coordinates", _placed),
    ("named locations", _named_place),
    ("edit history", _edited),
    ("timestamps", _dated),
    ("related files", _related),
    ("conflicting evidence", _contested),
)

#: Rows printed even at zero. This tool stands on two things - what a file says
#: about itself and what the machine recorded about its arrival - and a scan
#: that read a great deal of the first and none of the second has found that
#: out. Leaving the row off would make the absence look like an omission.
ALWAYS: frozenset[str] = frozenset({"metadata", "origin evidence"})


def summary(records: list[FileRecord]) -> list[Tally]:
    """How many files each kind of evidence was read from.

    A row nothing matched is left out rather than printed as a zero: a column
    of zeroes reads as a list of the things the tool could not do, which is a
    different report from the one this is.
    """
    found = []
    for name, matches in TALLIES:
        count = sum(1 for record in records if matches(record))
        if count or name in ALWAYS:
            found.append(Tally(name=name, files=count))
    return found


# --- what wants a second look ------------------------------------------------


def notable(
    records: list[FileRecord],
    identifiers: list[Identifier],
    *,
    listed: bool = False,
) -> list[Alert]:
    """The handful of things a long report will otherwise bury.

    Only what an analyst would want to be interrupted for, and nothing that
    merely happened: a file naming the software that made it is ordinary, two
    records naming different origins for it is not.
    """
    raised: list[Alert] = []

    conflicting = [record.path for record in records if _contested(record)]
    if conflicting:
        raised.append(
            Alert(
                text=_said(len(conflicting), CONTAIN, "conflicting evidence"),
                contested=True,
                files=tuple(conflicting[:NAMED]),
                hidden=max(0, len(conflicting) - NAMED),
            )
        )

    for matches, verb, what in (
        (_placed, CONTAIN, "coordinates"),
        (_content_credentials, CONTAIN, "Content Credentials"),
        (_related, ("references", "reference"), "other files in this scan"),
    ):
        count = sum(1 for record in records if matches(record))
        if count:
            raised.append(Alert(text=_said(count, verb, what)))

    linked = [entry for entry in identifiers if entry.acquired and IN_CONTENT in entry.corpora]
    if linked:
        # The one thing reading document text is for. A name inside a document
        # is a lead; a name inside a document that the record of the file's
        # arrival also carries was put there twice, by two separate acts, and
        # neither half says that on its own.
        phrase = "identifier is" if len(linked) == 1 else "identifiers are"
        raised.append(
            Alert(text=f"{len(linked)} {phrase} named in a document and in how it arrived")
        )

    if identifiers:
        # Counted in identifiers, not in files: fifteen of these are fifteen
        # leads, and one address across forty files is one of them.
        total = len(identifiers)
        noun = "identifier" if total == 1 else "identifiers"
        tail = "" if listed else " (--pivots to list them)"
        raised.append(Alert(text=f"{total} unique {noun} extracted{tail}"))

    return raised


def _said(count: int, verb: tuple[str, str], what: str) -> str:
    """`1 file carries coordinates`, `7 files carry coordinates`.

    Both forms of the verb are given rather than derived. English does not
    conjugate by rule often enough for a rule to be worth writing, and a report
    that reads as though nobody proof-read it is not what a piece of evidence
    should look like.
    """
    one, many = verb
    return f"1 file {one} {what}" if count == 1 else f"{count} files {many} {what}"
