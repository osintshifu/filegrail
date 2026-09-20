from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # a Link is attached by `lineage`, which imports this module
    from .lineage import Link

# --- what a record is about ---------------------------------------------------

#: How or from where the file reached the environment being examined. Another
#: system wrote this down: a browser's download history, an attribute the
#: operating system attached, the sidecar a fetching tool left beside the file.
#:
#: Deliberately not `acquisition`. In digital forensics that word means the
#: examiner taking custody of material - disk imaging, memory capture, a
#: forensic copy - and using it for "a browser downloaded this" would collide
#: with the one meaning every examiner already has for it.
ORIGIN = "origin"

#: What the file itself carries: the author, device, software, timestamps,
#: identifiers, document properties and editing history written into its own
#: structure. It travels with the bytes through copying and renaming.
METADATA = "metadata"

#: A local trace that the file was handled here - opened, listed, moved,
#: synchronized, deleted, named in a shell. It establishes contact and says
#: nothing about where the bytes came from, which is the distinction the old
#: single "origin" collection destroyed by holding both.
ACTIVITY = "activity"

#: Every category there is, so consumers can enumerate them and tests can hold
#: the source table against them.
CATEGORIES = (ORIGIN, METADATA, ACTIVITY)


# --- how a record came to be about this file ----------------------------------

#: Read out of the file's own bytes.
EMBEDDED = "embedded"

#: Read from what the filesystem keeps beside the bytes for this exact file -
#: an extended attribute, an alternate data stream, the inode's own stamps.
FILE_ATTRIBUTE = "file-attribute"

#: A separate file written beside this one and naming it: a `yt-dlp` sidecar,
#: the trash's own `.trashinfo` record.
SIDECAR = "sidecar"

#: An external store recorded this exact path for the file.
RECORDED_PATH = "recorded-path"

#: An external store naming a file by this name, and nothing more. It survives
#: the file being moved, which is why it is tried - and it matches any other
#: file that happens to share the name, which is why it is recorded as what it
#: is rather than presented as a path match.
FILENAME = "filename"

#: The name *and* the exact byte count agree. Two files can still share both,
#: but not nearly as easily as they share a name.
NAME_AND_SIZE = "name+size"

#: The file is a member of a container - an archive, a torrent - or the record
#: was read from one member and restated about the container.
CONTAINER_MEMBER = "container-member"

#: The file lies under a directory a sync client manages. Containment is the
#: whole of the match; it says nothing about which way the bytes travelled.
SYNC_ROOT = "sync-root"

MATCH_BASES = (
    EMBEDDED,
    FILE_ATTRIBUTE,
    SIDECAR,
    RECORDED_PATH,
    FILENAME,
    NAME_AND_SIZE,
    CONTAINER_MEMBER,
    SYNC_ROOT,
)

# --- the sources ---------------------------------------------------------------

#: Which of the three questions each source speaks to. Every source is listed;
#: a source missing from here is a source nobody classified, and `category()`
#: raises rather than guessing, because guessing is how EXIF ended up in a
#: collection named `origins`.
SOURCE_CATEGORIES: dict[str, str] = {
    "browser-download": ORIGIN,
    "windows-zone-identifier": ORIGIN,
    "macos-wherefroms": ORIGIN,
    "macos-quarantine": ORIGIN,
    "xdg-xattr": ORIGIN,
    "ytdlp-sidecar": ORIGIN,
    # The hop the recipient's own mail server wrote as the message arrived.
    # That is how this file reached the machine.
    "email-delivery": ORIGIN,
    # The archive's own origin, inherited by a file that came out of it.
    "archive-member": ORIGIN,
    # A file carried inside a document or a message: an attachment, an
    # embedded file, a packaged object. Its origin is the carrier's.
    "embedded-file": ORIGIN,
    "torrent": ORIGIN,
    # A file name in the shape a messenger writes. It is an association with a
    # naming convention, and the match basis on every one of these records says
    # so: nothing here was matched by anything but a name.
    "messenger-name": ORIGIN,
    # Decided per record rather than per source: `curl -o` fetched the bytes,
    # `cat` merely read them. See `category`.
    "shell-history": ORIGIN,
    "c2pa": METADATA,
    "device-metadata": METADATA,
    "xmp": METADATA,
    "xmp-history": METADATA,
    "iptc": METADATA,
    "document-metadata": METADATA,
    # Which format the leading bytes are written in, said only where the name
    # says another one. It is read out of the file and travels with the bytes,
    # which is what makes it metadata rather than a statement about arrival.
    "file-signature": METADATA,
    # Metadata read from a member and restated as a fact about the container.
    "email-header": METADATA,
    # A hop some machine wrote into the message before it was sent. It is a
    # header the file carries - transport of the message, not the origin of the
    # file - so it is read as metadata and never as an origin record.
    "email-relay": METADATA,
    "recent-documents": ACTIVITY,
    "windows-recent": ACTIVITY,
    "sync-folder": ACTIVITY,
    "freedesktop-trash": ACTIVITY,
    # Times and paths the filesystem keeps. They say what happened to the file
    # here; they do not say where it came from, and classifying them as origin
    # made every unexplained file look as though something had explained it.
    "filesystem": ACTIVITY,
}

#: The ordinary way each source is tied to the file it describes. A reader that
#: knows better for a particular record overrides it on the record itself.
SOURCE_MATCH: dict[str, str] = {
    "browser-download": RECORDED_PATH,
    "windows-zone-identifier": FILE_ATTRIBUTE,
    "macos-wherefroms": FILE_ATTRIBUTE,
    "macos-quarantine": FILENAME,
    "xdg-xattr": FILE_ATTRIBUTE,
    "ytdlp-sidecar": SIDECAR,
    "email-delivery": EMBEDDED,
    "email-relay": EMBEDDED,
    "email-header": EMBEDDED,
    "archive-member": CONTAINER_MEMBER,
    "embedded-file": CONTAINER_MEMBER,
    "torrent": NAME_AND_SIZE,
    "messenger-name": FILENAME,
    "shell-history": FILENAME,
    "c2pa": EMBEDDED,
    "device-metadata": EMBEDDED,
    "xmp": EMBEDDED,
    "xmp-history": EMBEDDED,
    "iptc": EMBEDDED,
    "document-metadata": EMBEDDED,
    "file-signature": EMBEDDED,
    "recent-documents": RECORDED_PATH,
    "windows-recent": NAME_AND_SIZE,
    "sync-folder": SYNC_ROOT,
    "freedesktop-trash": SIDECAR,
    "filesystem": FILE_ATTRIBUTE,
}

#: Which source is shown first where several describe the same thing, and which
#: one a summary counts when a file needs one row. Presentation order and
#: nothing else: these are not probabilities, they are not scores, and they are
#: never printed or exported. A source that records the arrival as it happens
#: sorts above one matched to the file afterwards; a file describing itself
#: sorts below both, because it is the one account with no independent witness.
SOURCE_PRIORITY: dict[str, int] = {
    "browser-download": 90,
    "windows-zone-identifier": 85,
    "macos-wherefroms": 85,
    "macos-quarantine": 85,
    "xdg-xattr": 80,
    "email-delivery": 78,
    "ytdlp-sidecar": 75,
    "archive-member": 70,
    "embedded-file": 70,
    "torrent": 70,
    "c2pa": 60,
    "device-metadata": 55,
    "xmp": 52,
    "xmp-history": 52,
    "iptc": 51,
    "document-metadata": 50,
    "email-relay": 45,
    "freedesktop-trash": 45,
    "shell-history": 40,
    "sync-folder": 38,
    "windows-recent": 36,
    "recent-documents": 35,
    "email-header": 30,
    "messenger-name": 25,
    "file-signature": 20,
    "filesystem": 10,
}


#: How each source reads in prose. Data about sources, so it lives beside the
#: tables above rather than in the renderer - correlation needs to name a
#: source too, and importing the renderer to do it would be a cycle.
SOURCE_LABELS: dict[str, str] = {
    "browser-download": "browser download",
    "email-delivery": "mail delivery",
    "email-relay": "mail relay",
    "email-header": "mail headers",
    "windows-zone-identifier": "Windows zone",
    "macos-wherefroms": "macOS where-from",
    "macos-quarantine": "macOS quarantine",
    "xdg-xattr": "XDG attribute",
    "ytdlp-sidecar": "yt-dlp sidecar",
    "archive-member": "archive member",
    "embedded-file": "embedded file",
    "torrent": "torrent",
    "c2pa": "Content Credentials",
    "device-metadata": "device metadata",
    "xmp": "XMP",
    "xmp-history": "XMP history",
    "iptc": "IPTC",
    "document-metadata": "document metadata",
    "file-signature": "file signature",
    "shell-history": "shell history",
    "messenger-name": "messenger file name",
    "recent-documents": "Recent Documents",
    "sync-folder": "sync folder",
    "freedesktop-trash": "trash record",
    "windows-recent": "Windows shortcut",
    "filesystem": "filesystem",
}

#: What each source's records read as on a timeline. The verb is what happened
#: to the file, not what the tool did: `downloaded` is an event in the file's
#: life and `read the history` is not. A source with no verb here reads by its
#: category, from `CATEGORY_VERBS`.
EVENT_VERBS: dict[str, str] = {
    "browser-download": "downloaded",
    "windows-zone-identifier": "downloaded",
    "macos-wherefroms": "downloaded",
    "macos-quarantine": "downloaded",
    "xdg-xattr": "downloaded",
    "ytdlp-sidecar": "downloaded",
    "email-delivery": "delivered",
    "archive-member": "extracted",
    "embedded-file": "embedded",
    "torrent": "downloaded",
    "shell-history": "handled",
    "device-metadata": "captured",
    "c2pa": "produced",
    "xmp-history": "edited",
    "recent-documents": "opened",
    "windows-recent": "opened",
    "freedesktop-trash": "deleted",
    "sync-folder": "synchronized",
}

CATEGORY_VERBS: dict[str, str] = {ORIGIN: "recorded", METADATA: "written", ACTIVITY: "handled"}

#: How each metadata block reads in prose, where naming it says more than the
#: source does. Only a `document-metadata` record is renamed by it: that source
#: names a category rather than a thing - nine parsers answer to it - so a
#: reader told only that has been told nothing about which standard applies.
#: Every other source already names something specific, and a camera naming its
#: own model is `device metadata`, which says more than `EXIF`.
BLOCK_LABELS: dict[str, str] = {
    "pdf-info": "PDF Info",
    "ooxml-properties": "OOXML properties",
    "odf-meta": "ODF meta",
    "epub-package": "EPUB package",
    "rtf-generator": "RTF generator",
    "svg-metadata": "SVG metadata",
    "notebook-kernel": "notebook kernel",
    "web-document": "web document",
    "exif": "EXIF",
    "maker-notes": "Maker notes",
    "photoshop-irb": "Photoshop resources",
    "isobmff": "movie metadata",
    "png-text": "PNG text",
    "ole-summary": "OLE metadata",
    "pe-header": "PE header",
    "font-tables": "font tables",
    "riff": "RIFF",
    "id3": "ID3",
    "matroska": "Matroska",
    "vorbis-comment": "Vorbis comment",
    "aiff": "AIFF",
    "ape-tag": "APE tag",
}


def label(record: EvidenceRecord) -> str:
    """What to call the source of this record, in the words the report uses."""
    if record.source == "document-metadata" and record.block in BLOCK_LABELS:
        return BLOCK_LABELS[record.block]
    return SOURCE_LABELS.get(record.source, record.source)


#: Commands that plausibly fetch a file. Kept here rather than in the shell
#: reader because deciding what a record is about is a question about sources,
#: and the reader imports this module rather than the reverse.
FETCH_TOOLS = frozenset(
    {
        "curl",
        "wget",
        "aria2c",
        "yt-dlp",
        "youtube-dl",
        "git",
        "scp",
        "rsync",
        "s3cmd",
        "aws",
        "gh",
        "gallery-dl",
        "wpull",
        "httrack",
        "monolith",
    }
)


def category(record: EvidenceRecord) -> str:
    """Which of the three questions this record speaks to.

    Shell history is the one source that answers either, and which one is
    already in the record: `curl -o` fetched the bytes, `cat` merely read them.
    Deciding per record rather than per source keeps a `cat` from being
    reported as though it explained where a file came from.
    """
    if record.source == "shell-history":
        return ORIGIN if (record.tool or "") in FETCH_TOOLS else ACTIVITY
    try:
        return SOURCE_CATEGORIES[record.source]
    except KeyError:  # pragma: no cover - a test enumerates every source
        raise KeyError(
            f"{record.source!r} has no evidence category; add it to SOURCE_CATEGORIES"
        ) from None


@dataclass(slots=True)
class EvidenceRecord:
    """One observation about a file, from one source.

    Deliberately neutral about what it observes: the same shape carries a
    download row, an EXIF block and a trash record, and `category` says which
    of the three it is. The predecessor was called `Origin`, which made a
    camera's own tags a statement about where the file came from every time
    anybody read the collection's name.
    """

    source: str

    #: The metadata block these values were decoded from: `pdf-info`, `exif`,
    #: `png-text`. `source` names what the parser *found* - a camera, a bare
    #: document - and one parser answers that two ways depending on what the
    #: file happened to hold. This names what it *read*, which is the axis a
    #: mirrored self-description turns on: whether IIM or a PDF Info dictionary
    #: applies is a question about the standard. A record that decoded no
    #: metadata block leaves it unset rather than naming one nobody read.
    block: str | None = None

    #: How this record came to be about this file, where the source's ordinary
    #: basis is not what happened - a download row found by name after the file
    #: moved, an archive member. Unset means the basis in `SOURCE_MATCH`.
    match: str | None = None

    #: What else is worth saying about the match, in prose: why a name was all
    #: there was, or that a recorded size disagrees with the file on disk.
    match_note: str | None = None

    url: str | None = None
    referrer: str | None = None
    tool: str | None = None
    command: str | None = None
    at: str | None = None

    #: Where the file says it comes from, written as a place: "Firenze, Italy".
    #: A newsroom types this by hand, so it is as much a statement by whoever
    #: wrote it as any other text.
    location: str | None = None

    #: A latitude/longitude pair this tool decoded itself, from EXIF or an ISO
    #: 6709 atom. Kept apart from `location` because a decoded fix and a typed
    #: place name are not the same kind of fact, and only one of them can be
    #: put on a map without believing anybody.
    geo: str | None = None
    bytes: int | None = None
    mime: str | None = None
    sha256: str | None = None
    note: str | None = None

    #: Everything the parser decoded, named rather than numbered, beyond the
    #: handful of fields the report summarises. An investigation cannot know in
    #: advance which one matters, so nothing decoded is thrown away.
    fields: dict[str, str] = field(default_factory=dict)

    #: The archive or torrent whose member this file matched. Kept as a path,
    #: not recovered later from a prose note, so graph consumers can connect
    #: the two without guessing which same-named container was meant.
    container: str | None = None

    #: Where inside the file the record was read from, where the reader knows:
    #: `member` for a part of a package or an archive, `object` for a stream or
    #: an object inside a document, `path` for a metadata path. The `note` a
    #: person reads stays; this is the same place, for a consumer.
    where: dict[str, str] = field(default_factory=dict)

    @property
    def category(self) -> str:
        return category(self)

    @property
    def matched_by(self) -> str:
        """How this record was tied to this file."""
        return self.match or SOURCE_MATCH.get(self.source, RECORDED_PATH)

    @property
    def priority(self) -> int:
        """Presentation order only. Never printed, never exported."""
        return SOURCE_PRIORITY.get(self.source, 0)

    def redacted(self) -> EvidenceRecord:
        """Return a copy with credentials removed from every free-text field."""
        from .redact import redact_text, redact_url

        def clean(value: str) -> str:
            # A tag like UserComment is free text: it can hold a URL, a command
            # or a bare token, so it goes through both sweeps.
            return redact_url(redact_text(value))

        return replace(
            self,
            url=clean(self.url) if self.url else None,
            referrer=clean(self.referrer) if self.referrer else None,
            command=redact_text(self.command) if self.command else None,
            location=clean(self.location) if self.location else None,
            note=clean(self.note) if self.note else None,
            fields={name: clean(value) for name, value in self.fields.items()},
        )

    def to_dict(self) -> dict[str, Any]:
        data = {k: v for k, v in asdict(self).items() if v and k not in ("match", "match_note")}
        data["category"] = self.category
        match: dict[str, Any] = {"method": self.matched_by}
        if self.match_note:
            match["note"] = self.match_note
        data["match"] = match
        return data


@dataclass(slots=True)
class FileRecord:
    """Everything known about one file on disk."""

    path: str
    size: int
    mtime: str
    btime: str | None = None
    sha256: str | None = None
    evidence: list[EvidenceRecord] = field(default_factory=list)

    #: How this file relates to the others in the same scan, from the
    #: identifiers XMP carries for it. Not an evidence record: a record is one
    #: source's observation about this file, and a link is a relation between
    #: two files that only exists because both were scanned together.
    links: list[Link] = field(default_factory=list)

    #: For a file read inside a container: the container's path on disk, and
    #: the file's own path inside it. Unset for a file on disk.
    parent: str | None = None
    member: str | None = None

    @property
    def primary(self) -> EvidenceRecord | None:
        """One record for a file that needs one row, by presentation order.

        Used for grouping and counting. It is not a statement about which
        record is true, and it is not what an entry prints: see `origin`,
        `metadata` and `activity`, which are kept apart on purpose.
        """
        if not self.evidence:
            return None
        return max(self.evidence, key=lambda r: (r.priority, r.at or ""))

    @property
    def origin(self) -> EvidenceRecord | None:
        """The leading record of how the file reached this environment."""
        return self._leading(ORIGIN)

    @property
    def activity(self) -> EvidenceRecord | None:
        """The leading record that something here handled the file."""
        return self._leading(ACTIVITY)

    @property
    def metadata(self) -> EvidenceRecord | None:
        """The leading record of what the file says about itself.

        Kept apart from `origin` because they answer different questions.
        Ranking them against each other lets a download row displace a camera's
        GPS fix, which is the more valuable of the two far more often than not.
        """
        return self._leading(METADATA)

    def _leading(self, wanted: str) -> EvidenceRecord | None:
        candidates = [record for record in self.evidence if record.category == wanted]
        if not candidates:
            return None
        return max(candidates, key=lambda r: (r.priority, r.at or ""))

    def redacted(self) -> FileRecord:
        return replace(self, evidence=[record.redacted() for record in self.evidence])

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "path": self.path,
            "size": self.size,
            "mtime": self.mtime,
            "btime": self.btime,
            "sha256": self.sha256,
        }
        if self.parent is not None:
            data["parent"] = self.parent
            data["member"] = self.member
        data["evidence"] = [record.to_dict() for record in self.evidence]
        data["links"] = [link.to_dict() for link in self.links]
        return data
