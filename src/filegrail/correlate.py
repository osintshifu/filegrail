"""Whether the origin records for a file agree with each other.

One record is an observation. Two that agree are corroboration, and worth more
than either alone. Two that disagree are a finding in their own right - a file
downloaded twice, a file copied after it arrived, or origin metadata that was
replaced afterwards - and a report that quietly prints the higher-ranked one
has destroyed that finding rather than reported it.

Nothing here decides which record is true. Correlation says what the records
do; a reader does the deciding, which is why the result is a
`CorrelationResult` and not a verdict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import NamedTuple

from .identify import normalize_url
from .models import (
    FILENAME,
    METADATA,
    NAME_AND_SIZE,
    ORIGIN,
    EvidenceRecord,
    FileRecord,
    category,
    label,
)

#: No origin record at all: nothing said how the file got here.
NONE = "no origin record"

#: Exactly one. The ordinary case, and not a finding either way.
SINGLE = "single source"

#: Two or more independent records naming the same address.
AGREEMENT = "agreement"

#: Same host, different path. Often one record kept a redirect and another the
#: landing page, which is agreement about where but not about what.
PARTIAL = "partial agreement"

#: Different hosts. Something happened that the records do not jointly explain.
CONFLICT = "conflict"

#: Not an origin state at all: the file's two accounts of its own origin
#: contradict each other. It headlines the block when nothing about the
#: origin records is worth headlining instead.
CONTESTED = "contested attribution"

#: Not an origin state either: the file's own account of itself puts a
#: change before the making of the thing changed. It headlines for the same
#: reason `contested attribution` does - the origin state describes
#: records this finding never consulted.
SELF_CONTRADICTORY = "contradicts itself"

#: What a single finding is about. Typed, so a consumer reading the JSON does
#: not have to pattern-match English to tell one problem from another - and so
#: the two conflicts, which are genuinely different classes of problem, stay
#: distinguishable after the sentence has been translated or reworded.
CORROBORATION = "corroboration"
SOURCE_CONFLICT = "source_conflict"
PATH_DISAGREEMENT = "path_disagreement"
TIMELINE_CONFLICT = "timeline_conflict"
WEAK_MATCH = "weak_match"
SIZE_MISMATCH = "size_mismatch"
SIZE_CORROBORATION = "size_corroboration"
ATTRIBUTION_CONFLICT = "attribution_conflict"

#: One block's own two timestamps in an order that cannot have happened. Kept
#: apart from `timeline_conflict`, which is a disagreement between the file and
#: the machine it arrived on; this one needs no second source to be wrong, and
#: a reader chasing tampering wants to tell the two apart.
IMPOSSIBLE_ORDER = "impossible_order"

#: Every kind there is, so a consumer can enumerate them and the report can size
#: its column to the longest of them rather than guess at a width.
KINDS = (
    CORROBORATION,
    SOURCE_CONFLICT,
    PATH_DISAGREEMENT,
    TIMELINE_CONFLICT,
    WEAK_MATCH,
    SIZE_MISMATCH,
    SIZE_CORROBORATION,
    ATTRIBUTION_CONFLICT,
    IMPOSSIBLE_ORDER,
)

#: Findings that say something is wrong, as against something corroborated. The
#: report colours by this rather than by the state, because a finding can now
#: arrive from somewhere the state knows nothing about.
CONFLICTS = frozenset(
    {
        SOURCE_CONFLICT,
        PATH_DISAGREEMENT,
        TIMELINE_CONFLICT,
        SIZE_MISMATCH,
        ATTRIBUTION_CONFLICT,
        IMPOSSIBLE_ORDER,
    }
)

#: Where one block records both when a thing was made and when it was last
#: changed, under the names its own standard fixes. Only pairs a reader
#: actually emits are here: a pair invented for a block that writes neither
#: field would be a rule that can never fire, and so never be found wrong.
_MADE_AND_CHANGED = {
    "pdf-info": ("CreationDate", "ModDate"),
    "ooxml-properties": ("created", "modified"),
    "xmp": ("xmp:CreateDate", "xmp:ModifyDate"),
}

#: The same fact under two names, for IIM and XMP. Adobe published this pairing
#: when it moved IIM into XMP, which is what makes the two standards comparable
#: at all: the correspondence is documented, not inferred from whatever the
#: values happen to look like.
_IIM_IN_XMP = (
    ("By-line", "dc:creator"),
    ("By-lineTitle", "photoshop:AuthorsPosition"),
    ("Credit", "photoshop:Credit"),
    ("Source", "photoshop:Source"),
    ("CopyrightNotice", "dc:rights"),
    ("Headline", "photoshop:Headline"),
    ("Caption-Abstract", "dc:description"),
    ("ObjectName", "dc:title"),
    ("Keywords", "dc:subject"),
    ("City", "photoshop:City"),
    ("Province-State", "photoshop:State"),
    ("Country-PrimaryLocationName", "photoshop:Country"),
    ("SpecialInstructions", "photoshop:Instructions"),
    ("OriginalTransmissionReference", "photoshop:TransmissionReference"),
    ("Writer-Editor", "photoshop:CaptionWriter"),
    ("Urgency", "photoshop:Urgency"),
    ("Category", "photoshop:Category"),
)

#: And for EXIF and XMP, where the pairing is the XMP specification's own: the
#: `tiff:` and `exif:` properties are defined as the serialisation of those
#: tags, so a difference is one of the two blocks having been rewritten.
#:
#: Only what the camera said about the act of taking the picture is here.
#: Exposure settings are left out on purpose: XMP writers put units, rationals
#: and comma decimals in them - "f/5,6" against 5.6, "1/500 sec." against 0.002
#: - and a comparison that cannot read those would report a conflict on almost
#: every photograph ever taken. The file's later handling is left out for the
#: opposite reason: `xmp:ModifyDate` is maintained by tools that leave EXIF
#: `DateTime` alone, so the two drift apart in ordinary use and a finding there
#: would say nothing while diluting the ones that do.
_EXIF_IN_XMP = (
    ("Make", "tiff:Make"),
    ("Model", "tiff:Model"),
    ("Software", "tiff:Software"),
    ("Artist", "tiff:Artist"),
    ("Artist", "dc:creator"),
    ("Copyright", "tiff:Copyright"),
    ("ImageDescription", "dc:description"),
    ("LensModel", "aux:Lens"),
    ("BodySerialNumber", "aux:SerialNumber"),
)

#: And for a PDF's Info dictionary and its XMP, where the pairing is again the
#: XMP specification's own - Part 3 defines the Info entries as the legacy form
#: of these properties, and PDF/A requires the two to agree.
#:
#: `/Creator` is the application that made the document; XMP keeps it under
#: `xmp:CreatorTool`. An exporter that stamps a fresh Info dictionary over XMP
#: carried through from the source document leaves the two naming different
#: applications, which is the trace worth reporting.
#:
#: `/Producer` is left out. It names the library that wrote the PDF, and that
#: library writes both blocks at one save - so it disagrees with itself rather
#: than with anything: Adobe PDF Library 15 puts `Adobe PDF Library 15.0` in the
#: Info dictionary and `Adobe PDF library 15.00` in the XMP. Case and spacing
#: are already forgiven, the trailing zero is not, and the pair would put a line
#: on Adobe exports at large while catching a rewrite the other pairs also see.
#:
#: `/Trapped` is left out for a duller reason: it is a PDF name object, `/False`
#: rather than `(False)`, and the reader takes only string values - so the pair
#: could never fire.
_PDF_IN_XMP = (
    ("Title", "dc:title"),
    ("Author", "dc:creator"),
    ("Subject", "dc:description"),
    ("Keywords", "pdf:Keywords"),
    ("Creator", "xmp:CreatorTool"),
)

#: And for a PNG's text chunks and its XMP, published in the same part of the
#: specification. `Software` is the pair worth naming: in a PNG it is the
#: application that made the image, which is what `xmp:CreatorTool` holds. The
#: EXIF tag of the same spelling is not that fact - it is whatever processed the
#: file last, and its mirror is `tiff:Software` - so the two blocks take the
#: word in opposite directions and only a pairing keyed on the block can tell
#: them apart.
#:
#: This one is spec-only. The local corpus has no PNG carrying both a text chunk
#: and an XMP packet, so nothing here has been read against a real file.
_PNG_IN_XMP = (
    ("Title", "dc:title"),
    ("Author", "dc:creator"),
    ("Description", "dc:description"),
    ("Copyright", "dc:rights"),
    ("Software", "xmp:CreatorTool"),
)

#: Pairs holding a timestamp, compared as moments rather than as text. IIM
#: writes a bare eight-digit day, EXIF writes a zoneless local reading, XMP
#: writes the same reading with an offset attached - three spellings of one
#: fact, and comparing their characters would find three conflicts in a file
#: that has none.
_IIM_MOMENTS = (("DateCreated", "photoshop:DateCreated"),)
_EXIF_MOMENTS = (
    ("DateTimeOriginal", "exif:DateTimeOriginal"),
    ("DateTimeDigitized", "exif:DateTimeDigitized"),
)

#: A PDF's two dates. `ModDate` is here where EXIF's `DateTime` is not: an XMP
#: writer maintains `xmp:ModifyDate` while leaving the EXIF tag as it found it,
#: so the two drift apart in ordinary use, but a PDF producer writes both of its
#: blocks at the same save and a gap between them is one of them being stale.
_PDF_MOMENTS = (
    ("CreationDate", "xmp:CreateDate"),
    ("ModDate", "xmp:ModifyDate"),
)

#: And a PNG's. The specification asks for RFC 1123 here - `Sun, 30 Jul 2023
#: 14:22:01 +0000` - which nothing in this module can read, though the writers
#: that fill the chunk in mostly write ISO. An unreadable stamp is skipped
#: rather than reported, so the pair is silent on the spelling it cannot take
#: and useful on the one it meets.
_PNG_MOMENTS = (("Creation Time", "xmp:CreateDate"),)

#: A day, however the writer punctuated it, and a clock reading if one is there.
_DAY = re.compile(r"(\d{4})\D?(\d{2})\D?(\d{2})")
_CLOCK = re.compile(r"[T ](\d{2}):?(\d{2}):?(\d{2})")

#: A PDF date, which is neither: `D:20180511143720-04'00'` opens with two
#: letters `_DAY` will not match past and runs the clock straight into the day
#: with none of the separators `_CLOCK` looks for. Read by the general pattern
#: it comes back unreadable, and an unreadable stamp is never compared - so
#: every PDF timestamp would be skipped in silence rather than checked.
_PDF_STAMP = re.compile(r"D:(\d{4})(\d{2})(\d{2})(?:(\d{2})(\d{2})(\d{2}))?")

#: What a writer said about its own zone, in either punctuation: ISO writes
#: `+02:00` or `Z`, a PDF writes `+02'00'`. Anchored at the end, where a zone
#: is, so the hyphens inside a date cannot be read as one.
_ZONE = re.compile(r"(?:(Z)|([+-])(\d{2})'?:?(\d{2}))'?\s*$")


@dataclass(frozen=True, slots=True)
class Mirror:
    """Two self-descriptions a file is supposed to keep saying the same thing.

    Both sides name a metadata block rather than a source, because the pairing
    is between two standards. The source says what a reader found - a camera or
    a bare document - and one block arrives under either name, while nine
    different blocks arrive under `document-metadata` alone. Keyed on that, a
    mirror would read a WAV's INFO list with the field names of a TIFF tag.
    """

    left: str
    right: str
    text: tuple[tuple[str, str], ...]
    moments: tuple[tuple[str, str], ...]

    #: Which of the two an editor ordinarily keeps current, where the pairing
    #: has a direction at all. Modern tools maintain XMP and copy the IIM block
    #: and a camera's EXIF tags through as they found them, so for those the
    #: other side is the likelier to describe an earlier state.
    #:
    #: A PDF has no such direction. One producer writes both blocks, and an
    #: exporter stamps a fresh Info dictionary at export while carrying the XMP
    #: through from the source document - which is what the corpus shows, XMP
    #: from February beside an Info dictionary from May. Naming the Info as the
    #: stale one would state the opposite of what happened. None says so, so a
    #: correlation does not rank two blocks it has no basis to rank.
    maintained: str | None


#: Every pairing there is, so a consumer can enumerate them and a test can
#: check the comparison against a corpus without restating which fields mirror
#: which.
MIRRORS = (
    Mirror("iptc", "xmp", _IIM_IN_XMP, _IIM_MOMENTS, maintained="xmp"),
    Mirror("exif", "xmp", _EXIF_IN_XMP, _EXIF_MOMENTS, maintained="xmp"),
    Mirror("pdf-info", "xmp", _PDF_IN_XMP, _PDF_MOMENTS, maintained=None),
    Mirror("png-text", "xmp", _PNG_IN_XMP, _PNG_MOMENTS, maintained=None),
)


@dataclass(slots=True)
class Finding:
    kind: str
    text: str

    #: The two blocks a contested attribution is between, already in the words
    #: the report uses for them. Carried rather than left to be read back out of
    #: the sentence, for the reason `kind` is: a consumer should not have to
    #: parse English to learn which two pieces of evidence disagree.
    sources: tuple[str, str] | None = None

    #: Which of `sources` an editor ordinarily keeps current, where the pairing
    #: has a direction. None where it does not, and the two are then not ranked.
    maintained: str | None = None

    #: What the finding is about, named the way the evidence names it: an
    #: origin URL, `DateTimeOriginal`, a recorded size. A table can put it in a
    #: column; a reader scanning for one field can find it.
    field: str | None = None

    #: The two values that differ, in the order `sources` names them. Carried
    #: apart from the sentence so a report can lay them out, and so nothing has
    #: to split English on a comma to get them back.
    values: tuple[str, str] | None = None

    #: What each side is called, where both values come from one block and it
    #: is the field that differs rather than the source. `sources` then names
    #: that block twice and tells the two apart not at all; this does.
    fields: tuple[str, str] | None = None

    def to_dict(self) -> dict[str, object]:
        found: dict[str, object] = {"kind": self.kind, "text": self.text}
        if self.field:
            found["field"] = self.field
        if self.sources:
            found["sources"] = list(self.sources)
        if self.values:
            found["values"] = list(self.values)
        if self.fields:
            found["fields"] = list(self.fields)
        if self.maintained:
            found["maintained"] = self.maintained
        return found


@dataclass(slots=True)
class CorrelationResult:
    state: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def reasons(self) -> list[str]:
        return [finding.text for finding in self.findings]

    @property
    def headline(self) -> str:
        """What the block of findings is about.

        `state` describes the origin records and nothing else. Once a finding
        can come from the file's own self-description, printing the origin
        state above it labels one thing with the name of another.
        """
        if self.state in (AGREEMENT, PARTIAL, CONFLICT):
            return self.state
        if any(finding.kind == ATTRIBUTION_CONFLICT for finding in self.findings):
            return CONTESTED
        if any(finding.kind == IMPOSSIBLE_ORDER for finding in self.findings):
            return SELF_CONTRADICTORY
        return self.state

    @property
    def contested(self) -> bool:
        """Whether anything here says something is wrong."""
        return self.state in (PARTIAL, CONFLICT) or any(
            finding.kind in CONFLICTS for finding in self.findings
        )

    @property
    def notable(self) -> bool:
        """Whether this is worth a line in the report.

        A single uncorroborated record is the common case. Annotating it would
        put a label on almost every entry, and a label on everything says
        nothing.
        """
        return self.state in (AGREEMENT, PARTIAL, CONFLICT) or bool(self.findings)

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "findings": [finding.to_dict() for finding in self.findings],
        }


def correlate(record: FileRecord) -> CorrelationResult:
    """Compare everything that says how `record` reached this machine."""
    origins = [found for found in record.evidence if category(found) == ORIGIN]
    addressed = [found for found in origins if found.url]

    result = CorrelationResult(state=_state(addressed))
    result.findings.extend(_address_findings(addressed, result.state))
    result.findings.extend(_time_findings(record))
    result.findings.extend(_order_findings(record))
    result.findings.extend(_history_findings(record))
    result.findings.extend(_match_findings(record, origins))
    result.findings.extend(_attribution_findings(record))
    return result


def _state(addressed: list[EvidenceRecord]) -> str:
    if not addressed:
        return NONE
    if len(addressed) == 1:
        return SINGLE

    normalised = {_address(found) for found in addressed}
    if len(normalised) == 1:
        return AGREEMENT
    if len({host for _, host in normalised if host}) == 1:
        return PARTIAL
    return CONFLICT


def _address(found: EvidenceRecord) -> tuple[str, str | None]:
    """The URL reduced to what two records have to share to be the same."""
    parsed = normalize_url(found.url or "")
    if parsed is None:
        return (found.url or "").rstrip("/").lower(), None
    normalized, host = parsed
    return normalized.rstrip("/"), host


def _address_findings(addressed: list[EvidenceRecord], state: str) -> list[Finding]:
    if state == AGREEMENT:
        names = ", ".join(_label(found) for found in addressed)
        return [
            Finding(
                CORROBORATION,
                f"{len(addressed)} records name the same address: {names}",
                field="origin URL",
                sources=(_label(addressed[0]), _label(addressed[1])),
            )
        ]

    if state in (PARTIAL, CONFLICT):
        which = PATH_DISAGREEMENT if state == PARTIAL else SOURCE_CONFLICT
        return [
            Finding(which, f"{_label(found)} says {found.url}", field="origin URL")
            for found in addressed
        ]
    return []


def _time_findings(record: FileRecord) -> list[Finding]:
    """Flag a file that claims to have been authored after it arrived.

    The reverse - created long before it was downloaded - is the normal order of
    events and says nothing, so it is not reported.
    """
    arrived = min(
        (o.at for o in record.evidence if category(o) == ORIGIN and o.at),
        default=None,
    )
    authored = max(
        (o.at for o in record.evidence if category(o) == METADATA and o.at), default=None
    )

    if arrived and authored and _created_after(authored, arrived):
        return [
            Finding(
                TIMELINE_CONFLICT,
                f"the file reports being created at {authored}, after it arrived at {arrived}",
            )
        ]
    return []


#: Two clocks wrote the two moments. A file that reports being created this
#: much after it was downloaded is skew between them, not a file made after it
#: arrived.
_CLOCK_SKEW = timedelta(minutes=5)


def _created_after(authored: str, arrived: str) -> bool:
    first, second = instant(authored), instant(arrived)
    if first is None or second is None:
        return authored > arrived
    return first[0] - second[0] > _CLOCK_SKEW


def _order_findings(record: FileRecord) -> list[Finding]:
    """Flag a block whose own two timestamps put the change before the making.

    Nothing can be modified before it exists, so this needs no second source to
    contradict: the block disagrees with itself. It is worth more than either
    timestamp alone, because a document whose own dates run backwards has been
    through something - a clock set wrong, a template reused, or a field edited
    by hand - and which of those it was is a question the report cannot answer
    but the reader can now ask.
    """
    findings: list[Finding] = []
    for found in record.evidence:
        pair = _MADE_AND_CHANGED.get(found.block or "")
        if pair is None:
            continue
        made, changed = found.fields.get(pair[0]), found.fields.get(pair[1])
        if not made or not changed:
            continue
        if _after(made, changed):
            findings.append(
                Finding(
                    IMPOSSIBLE_ORDER,
                    f"{label(found)} says it was modified at {changed}, "
                    f"before it was created at {made}",
                    field=f"{pair[0]} / {pair[1]}",
                    sources=(label(found), label(found)),
                    values=(made, changed),
                    fields=(pair[0], pair[1]),
                )
            )
    return findings


def _history_findings(record: FileRecord) -> list[Finding]:
    """Flag an editing history whose steps are not in the order it lists them.

    `xmpMM:History` is a sequence, and the reader keeps the order the encoder
    wrote. A step dated before the one it follows therefore contradicts the
    list it is in - a clock moved, a zone was got wrong, or the history was
    written by something other than the sequence of events it describes.

    Only the first inversion is reported. One is enough to say the account is
    unreliable, and a history that goes backwards usually does so repeatedly,
    which would bury every other finding about the file.
    """
    steps = [found.at for found in record.evidence if found.source == "xmp-history" and found.at]
    for earlier, later in zip(steps, steps[1:], strict=False):
        if _after(earlier, later):
            return [
                Finding(
                    IMPOSSIBLE_ORDER,
                    f"the recorded editing history runs backwards: a step dated {later} "
                    f"follows one dated {earlier}",
                )
            ]
    return []


def _after(left: str, right: str) -> bool | None:
    """Whether `left` names a later moment than `right`, or None if unrankable.

    Ranking is refused rather than guessed at wherever the two were not written
    to the same standard of precision: one writer naming its zone and the other
    staying silent about it can differ by most of a day, and calling that an
    impossible order would be inventing the half nobody wrote down.
    """
    first, second = _instant(left), _instant(right)
    if first is None or second is None:
        return None

    here, there = _utc(first), _utc(second)
    if here is not None and there is not None:
        return here > there
    if first.offset != second.offset:
        return None
    if first.day != second.day:
        return first.day > second.day
    if first.clock and second.clock:
        return first.clock > second.clock
    return None


def _match_findings(record: FileRecord, origins: list[EvidenceRecord]) -> list[Finding]:
    """Say how firmly each record was tied to this file, where it matters.

    A name match survives the file being moved, which is why it is made, but it
    also matches a different file that happens to share the name. The basis is
    on the record itself, so this reads the model rather than the prose: the
    size comparison is made here, against the file actually on disk, instead of
    being inferred from a sentence somebody wrote earlier.
    """
    findings = []
    for found in origins:
        basis = found.matched_by
        if basis not in (FILENAME, NAME_AND_SIZE):
            continue
        if found.bytes and found.bytes != record.size:
            findings.append(
                Finding(
                    SIZE_MISMATCH,
                    f"{_label(found)} matched by name, but its recorded size differs",
                    field="size",
                    sources=(_label(found), "the file"),
                    values=(str(found.bytes), str(record.size)),
                )
            )
        elif basis == NAME_AND_SIZE:
            findings.append(
                Finding(
                    SIZE_CORROBORATION,
                    f"{_label(found)} matched by name, and its recorded size agrees",
                    field="size",
                    sources=(_label(found), "the file"),
                )
            )
        else:
            findings.append(
                Finding(
                    WEAK_MATCH,
                    f"{_label(found)} was matched by file name, not by path",
                    field="match",
                    sources=(_label(found), ""),
                )
            )
    return findings


def _attribution_findings(record: FileRecord) -> list[Finding]:
    """Say when the file's own accounts of itself contradict each other.

    A file can describe itself more than once - IIM beside XMP, a camera's tags
    beside their XMP mirror - and each pairing is documented, so the two are
    meant to say the same thing. An editor maintains one and leaves the other as
    it found it, so agreement is the ordinary case and worth no line at all,
    while a difference is the trace of one of them having been changed. Which of
    the two is stale is exactly the question the reader has to answer.
    """
    findings: list[Finding] = []
    for mirror in MIRRORS:
        findings.extend(_disagreements(record, mirror))
    return findings


def _disagreements(record: FileRecord, mirror: Mirror) -> list[Finding]:
    left = _describing(record, mirror.left)
    right = _describing(record, mirror.right)
    if left is None or right is None:
        return []

    theirs = _named(left)
    ours = _named(right)
    kept = {mirror.left: left, mirror.right: right}.get(mirror.maintained or "")
    findings = []
    for name, other, agree in (
        *((a, b, _same_text) for a, b in mirror.text),
        *((a, b, _same_moment) for a, b in mirror.moments),
    ):
        said, also = theirs.get(name.lower()), ours.get(other.lower())
        # `agree` returns None when it cannot read one of the two. Unreadable is
        # not disagreement, and reporting it as such would be a fabrication.
        if said and also and agree(said, also) is False:
            findings.append(
                Finding(
                    ATTRIBUTION_CONFLICT,
                    f"{name}: {_label(left)} says {said}, {_label(right)} says {also}",
                    sources=(_label(left), _label(right)),
                    maintained=_label(kept) if kept else None,
                    field=name,
                    values=(said, also),
                )
            )
    return findings


def _describing(record: FileRecord, block: str) -> EvidenceRecord | None:
    for found in record.evidence:
        if found.block == block:
            return found
    return None


def _named(found: EvidenceRecord) -> dict[str, str]:
    return {name.lower(): value for name, value in found.fields.items()}


def _same_text(left: str, right: str) -> bool:
    """Case and spacing are how two tools write one name, not two facts."""
    return _plain(left) == _plain(right)


def _same_moment(left: str, right: str) -> bool | None:
    """Whether two timestamps say the same thing, or None if one cannot be read.

    Where both writers said what zone they were in, the two are compared as
    instants. A PDF's Info dictionary and its XMP both carry an offset, and one
    machine varies it across the year - the same export can write -04'00' into
    one block and -05:00 into the other - so comparing the readings would call a
    single moment a contested attribution.

    Where either did not, the reading is compared instead. EXIF writes no zone
    at all and its XMP mirror writes the same clock with one attached, so
    reading the tag as UTC and the mirror as an instant would make every
    photograph taken outside Greenwich contradict itself. The clock is optional
    for the same reason: IIM records a bare day, and a day that agrees is no
    conflict merely because the other writer also wrote down a time.
    """
    first, second = _instant(left), _instant(right)
    if first is None or second is None:
        return None

    here, there = _utc(first), _utc(second)
    if here is not None and there is not None:
        return here == there

    if first.day != second.day:
        return False
    return not (first.clock and second.clock) or first.clock == second.clock


class _Stamp(NamedTuple):
    """A timestamp as its writer spelled it: a day, a reading, and a zone."""

    day: str
    clock: str | None

    #: Minutes east of UTC, or None where the writer said nothing about it.
    offset: int | None


def _utc(stamp: _Stamp) -> datetime | None:
    """The moment this stamp names, or None if it does not name one.

    A stamp without a clock or without a zone is a reading rather than an
    instant, and an impossible date - month 13, day 32 - is neither.
    """
    if stamp.clock is None or stamp.offset is None:
        return None
    try:
        moment = datetime.strptime(stamp.day + stamp.clock, "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return moment - timedelta(minutes=stamp.offset)


def instant(value: str) -> tuple[datetime, bool] | None:
    """The moment a timestamp names, and whether its writer said which zone.

    In UTC where it did; as the clock reading where it did not, which is the
    most that can be said of it. None where it names no time of day at all, so
    two readings are never set a distance apart that neither writer stated.
    """
    stamp = _instant(value)
    if stamp is None or stamp.clock is None:
        return None
    moment = _utc(stamp)
    if moment is not None:
        return moment, True
    try:
        return datetime.strptime(stamp.day + stamp.clock, "%Y%m%d%H%M%S"), False
    except ValueError:
        return None


def _instant(value: str) -> _Stamp | None:
    text = value.strip()
    offset = _offset(text)

    stamp = _PDF_STAMP.match(text)
    if stamp:
        parts = stamp.group(4, 5, 6)
        return _Stamp("".join(stamp.group(1, 2, 3)), "".join(parts) if all(parts) else None, offset)

    day = _DAY.match(text)
    if not day:
        return None
    clock = _CLOCK.search(text)
    return _Stamp("".join(day.groups()), "".join(clock.groups()) if clock else None, offset)


def _offset(text: str) -> int | None:
    zone = _ZONE.search(text)
    if not zone:
        return None
    if zone.group(1):
        return 0
    sign = -1 if zone.group(2) == "-" else 1
    return sign * (int(zone.group(3)) * 60 + int(zone.group(4)))


def _plain(value: str) -> str:
    return " ".join(value.split()).casefold()


def _label(found: EvidenceRecord) -> str:
    return label(found)
