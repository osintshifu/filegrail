"""XMP: what a file records about its own editing.

EXIF says which camera made a photograph. XMP says what happened to it
afterwards - which application opened it, when, and what it was derived from -
and it is the only metadata standard in wide use that keeps that as a sequence
rather than a single field.

XMP travels as a literal XML packet inside the container, uncompressed, so that
a reader can find it without understanding the format around it. That is what
lets one module serve every format that embeds one, rather than a reader per
container. PNG is the exception, because it may deflate the packet, and there
the PNG reader hands the bytes over already inflated.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from datetime import datetime, timezone
from pathlib import Path

from ..models import EvidenceRecord
from .embedded import png

_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

#: The conventional prefix for each namespace a field name can carry. An
#: unlisted namespace keeps its URI, because a name a reader cannot look up is
#: worse than a long one.
_PREFIXES = {
    _RDF: "rdf",
    "http://www.w3.org/XML/1998/namespace": "xml",
    "http://purl.org/dc/elements/1.1/": "dc",
    "http://purl.org/dc/terms/": "dcterms",
    "http://ns.adobe.com/xap/1.0/": "xmp",
    "http://ns.adobe.com/xap/1.0/mm/": "xmpMM",
    "http://ns.adobe.com/xap/1.0/rights/": "xmpRights",
    "http://ns.adobe.com/xap/1.0/bj/": "xmpBJ",
    "http://ns.adobe.com/xap/1.0/t/pg/": "xmpTPg",
    "http://ns.adobe.com/xap/1.0/g/": "xmpG",
    "http://ns.adobe.com/xmp/1.0/DynamicMedia/": "xmpDM",
    "http://ns.adobe.com/xmp/note/": "xmpNote",
    "http://ns.adobe.com/xap/1.0/sType/ResourceEvent#": "stEvt",
    "http://ns.adobe.com/xap/1.0/sType/ResourceRef#": "stRef",
    "http://ns.adobe.com/xap/1.0/sType/Dimensions#": "stDim",
    "http://ns.adobe.com/xap/1.0/sType/Version#": "stVer",
    "http://ns.adobe.com/photoshop/1.0/": "photoshop",
    "http://ns.adobe.com/camera-raw-settings/1.0/": "crs",
    "http://ns.adobe.com/lightroom/1.0/": "lr",
    "http://ns.adobe.com/illustrator/1.0/": "illustrator",
    "http://ns.adobe.com/tiff/1.0/": "tiff",
    "http://ns.adobe.com/exif/1.0/": "exif",
    "http://ns.adobe.com/exif/1.0/aux/": "aux",
    "http://cipa.jp/exif/1.0/": "exifEX",
    "http://ns.adobe.com/pdf/1.3/": "pdf",
    "http://ns.adobe.com/pdfx/1.3/": "pdfx",
    "http://www.aiim.org/pdfua/ns/id/": "pdfuaid",
    "http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/": "Iptc4xmpCore",
    "http://iptc.org/std/Iptc4xmpExt/2008-02-29/": "Iptc4xmpExt",
    "http://ns.useplus.org/ldf/xmp/1.0/": "plus",
    "http://ns.microsoft.com/photo/1.0/": "MicrosoftPhoto",
    "http://ns.google.com/photos/1.0/camera/": "GCamera",
    "http://ns.google.com/photos/1.0/container/": "Container",
    "http://www.metadataworkinggroup.com/schemas/regions/": "mwg-rs",
    "http://www.digikam.org/ns/1.0/": "digiKam",
    "http://darktable.sf.net/": "darktable",
    "http://www.gimp.org/xmp/": "GIMP",
    "http://ns.acdsee.com/iptc/1.0/": "acdsee",
}

#: The same table keyed on the namespace with its trailing delimiter removed.
#: Encoders differ on whether they write it, and a field name a reader looks up
#: must not depend on which spelling one of them chose.
_BY_NAMESPACE = {uri.rstrip("/#"): prefix for uri, prefix in _PREFIXES.items()}

_HISTORY = "{http://ns.adobe.com/xap/1.0/mm/}History"

#: Which language a value is in. Beside a value it adds nothing the value does
#: not already carry, and beside an empty one it is all that is left: Acrobat
#: writes `<rdf:li xml:lang="x-default"/>` for a title nobody set, which used to
#: be reported as a field whose entire content was the word `x-default`. It
#: describes the encoding, which is why `rdf:about` is skipped too.
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

#: RDF's three array spellings. A property holding one wraps its real values in
#: rdf:li elements, so the value is a level below where a reader first looks.
_ARRAYS = frozenset(f"{{{_RDF}}}{kind}" for kind in ("Seq", "Bag", "Alt"))

#: The local name of the packet's root element. The `<?xpacket?>` processing
#: instructions around it are optional - PDF and SVG writers routinely omit them
#: - so the root is the only marker present in every file that has XMP at all.
#: Its prefix is not: Adobe writes `x:xmpmeta`, Windows Photo Gallery writes
#: `xmp:xmpmeta`, and a namespace prefix is the encoder's choice either way.
_META = b"xmpmeta"

#: How far back from the local name to look for the opening angle bracket. A
#: namespace prefix is a short name, not a sentence.
_MAX_PREFIX = 32

#: How much of each end of a file to search.
_WINDOW = 4 * 1024 * 1024

#: How large a packet may be before it is left alone. Adobe writes kilobytes;
#: megabytes of XML between the markers is a reason to stop, not to parse on.
_MAX_PACKET = 2 * 1024 * 1024

#: How many edits are reported as claims of their own. A file reworked over
#: years can record hundreds, and one file must not bury a scan. What the bound
#: drops is counted and said aloud rather than quietly discarded.
_MAX_EDITS = 25

#: How far into nested structs to descend. Real XMP nests one or two levels; the
#: bound exists so a crafted file cannot recurse this reader off its stack.
_MAX_DEPTH = 6

#: How many entries of one array are reported in full. Illustrator writes its
#: entire default palette into `xmpTPg:SwatchGroups` - forty-five colorants of
#: seven fields each - and printing all of it buries a file's provenance under
#: its colour picker. The first few are enough to recognise a palette somebody
#: built; how many there were is stated rather than left to be guessed at.
_MAX_ENTRIES = 3


def read_xmp(path: Path) -> list[EvidenceRecord]:
    """Return what the file's XMP packet claims, or an empty list."""
    packet = _packet(path)
    if not packet:
        return []

    try:
        root = ElementTree.fromstring(packet)
    except ElementTree.ParseError:
        return []

    properties = _properties(root)
    history = _history(root)
    if not properties and not history:
        return []

    # An undated step must not become a claim of its own: the timeline falls
    # back to the file's own timestamps for a claim carrying none, which would
    # place an editing action at a moment nothing recorded. It is kept as a
    # field instead, where it states what happened without inventing when.
    dated = []
    for position, step in enumerate(history, 1):
        if _timestamp(_first(step, ("stEvt:when",))):
            dated.append(step)
        elif summary := _summary(step):
            properties.setdefault(f"xmpMM:History[{position}]", summary)

    shown = dated[:_MAX_EDITS]
    return [
        EvidenceRecord(
            source="xmp",
            block="xmp",
            tool=_first(properties, ("xmp:CreatorTool",)),
            at=_timestamp(_first(properties, ("xmp:CreateDate",))),
            note=_note(properties, len(dated) - len(shown), len(dated)),
            fields=properties,
        ),
        *(_edit(step) for step in shown),
    ]


def _note(properties: dict[str, str], dropped: int, total: int) -> str | None:
    """The one line a reader sees before opening the field tree."""
    notes = []
    author = _first(properties, ("dc:creator", "xmp:Author"))
    if author:
        notes.append(f"author {author}")
    derived = _first(
        properties,
        (
            "xmpMM:DerivedFrom/stRef:documentID",
            "xmpMM:DerivedFrom/stRef:instanceID",
            "xmpMM:DerivedFrom",
        ),
    )
    if derived:
        notes.append(f"derived from document {derived}")
    if dropped:
        notes.append(f"{dropped} of {total} recorded edits not shown separately")
    return "; ".join(notes) or None


def _first(properties: dict[str, str], names: tuple[str, ...]) -> str | None:
    """A named value, in whatever case the encoder chose to write the name.

    XMP names are case-sensitive and encoders disregard that: Windows Photo
    Gallery writes `xmp:creatortool`. The field keeps the spelling it was found
    under, but recognising the property must not depend on it.
    """
    folded = {name.lower(): value for name, value in properties.items()}
    for name in names:
        if folded.get(name.lower()):
            return folded[name.lower()]
    return None


# --- finding the packet ------------------------------------------------------


def _packet(path: Path) -> str | None:
    """The XMP packet embedded anywhere in the container, as text.

    Every container that carries XMP stores it the same way: a literal XML
    packet, uncompressed, so that a reader can find it without understanding the
    format around it. That is what the standard is for, and it means one search
    serves JPEG, TIFF, PNG, PDF, MP4, SVG and every format not enumerated here.

    The search is bounded at both ends of the file rather than run over all of
    it: metadata sits at a container boundary - JPEG writes it after the marker,
    MP4 in a `moov` box that may be first or last - and reading gigabytes of
    video to discover it has none would cost more than the answer is worth. A
    packet in the middle of a file larger than two windows is not found, and a
    packet straddling the boundary of one is not either.
    """
    if path.suffix.lower() in png.SUFFIXES:
        deflated = png.read_xmp_packet(path)
        if deflated:
            return deflated

    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            found = _find(handle.read(_WINDOW))
            if found is None and size > _WINDOW:
                handle.seek(max(0, size - _WINDOW))
                found = _find(handle.read(_WINDOW))
    except OSError:
        return None
    return found


def _find(data: bytes) -> str | None:
    cursor = 0
    while (at := data.find(_META, cursor)) >= 0:
        cursor = at + len(_META)
        opening = data.rfind(b"<", max(0, at - _MAX_PREFIX), at)
        if opening < 0:
            continue  # the name appeared in text, not as an element
        name = data[opening + 1 : cursor]
        closing = data.find(b"</" + name + b">", cursor)
        if closing < 0 or closing - opening > _MAX_PACKET:
            continue
        return data[opening : closing + len(name) + 3].decode("utf-8", "replace")
    return None


# --- reading the packet ------------------------------------------------------


def _properties(root: ElementTree.Element) -> dict[str, str]:
    found: dict[str, str] = {}
    for description in root.iter(f"{{{_RDF}}}Description"):
        found.update(
            {name: value for name, value in _fields(description).items() if name not in found}
        )
    return found


def _history(root: ElementTree.Element) -> list[dict[str, str]]:
    """Every step of xmpMM:History, in the order the encoder wrote them.

    The history is a sequence, not a field: one file can record being created,
    edited four times and exported, each by a different application at a
    different moment. Collapsing that into one claim would throw away the only
    account of the file's editing most files ever carry.
    """
    steps = []
    for history in root.iter(_HISTORY):
        for container in history:  # rdf:Seq, occasionally rdf:Bag
            for item in container:
                step = _fields(item)
                if step:
                    steps.append(step)
    return steps


def _edit(step: dict[str, str]) -> EvidenceRecord:
    return EvidenceRecord(
        source="xmp-history",
        block="xmp-history",
        tool=_first(step, ("stEvt:softwareAgent",)),
        at=_timestamp(_first(step, ("stEvt:when",))),
        note=_summary(step) or None,
        fields=step,
    )


def _summary(step: dict[str, str]) -> str:
    """What the step says happened, in the words the encoder used."""
    said = (_first(step, ("stEvt:action",)), _first(step, ("stEvt:parameters",)))
    return " ".join(part for part in said if part) or _first(step, ("stEvt:softwareAgent",)) or ""


def _fields(element: ElementTree.Element, depth: int = 0) -> dict[str, str]:
    """The named values on an element and directly beneath it.

    XMP has two spellings for the same property - an attribute on the
    description or a child element - and encoders mix them freely within one
    packet, so a reader that knows only one form silently loses half of what a
    file records.
    """
    found: dict[str, str] = {}
    for name, value in element.attrib.items():
        # rdf:about, rdf:parseType and xml:lang describe the encoding, not the
        # file.
        if name.startswith(f"{{{_RDF}}}") or name == _XML_LANG:
            continue
        if value.strip():
            found.setdefault(_prefixed(name), value.strip())

    for child in element:
        # The edit history is a sequence of events, not a struct, and it has a
        # reader of its own that reports each step as a dated claim. Walking it
        # here as well printed every step twice.
        if depth == 0 and child.tag == _HISTORY:
            continue

        name = _prefixed(child.tag)
        value = _value(child)
        if value:
            found.setdefault(name, value)
        elif depth < _MAX_DEPTH:
            # A struct - DerivedFrom, ManagedFrom, a swatch group - carries its
            # meaning a level down. The path keeps two structs from colliding on
            # the shared name of a field inside them; the array wrapper around
            # them does not go into it, because `rdf:Seq` and `rdf:li` are how
            # RDF spells "several of these" and say nothing about the property.
            entries = _entries(child)
            if len(entries) > _MAX_ENTRIES:
                found.setdefault(name, f"{len(entries)} entries, {_MAX_ENTRIES} shown")
            for index, entry in enumerate(entries[:_MAX_ENTRIES], start=1):
                label = name if len(entries) == 1 else f"{name}[{index}]"
                for inner, text in _fields(entry, depth + 1).items():
                    found.setdefault(f"{label}/{inner}", text)
    return found


def _entries(element: ElementTree.Element) -> list[ElementTree.Element]:
    """The elements carrying a property's fields, past RDF's array wrappers.

    Several of them where the property holds an array of structs, so the second
    swatch group is reported rather than dropped on the first one's name.
    """
    items = [item for child in element if child.tag in _ARRAYS for item in child]
    return items or [element]


def _value(element: ElementTree.Element) -> str:
    """The element's text, or the joined items of the array it wraps."""
    text = (element.text or "").strip()
    if text:
        return text
    return ", ".join(
        item
        for child in element
        if child.tag in _ARRAYS
        for item in ((entry.text or "").strip() for entry in child)
        if item
    )


def _prefixed(tag: str) -> str:
    if not tag.startswith("{"):
        return tag
    uri, _, local = tag[1:].partition("}")
    return f"{_BY_NAMESPACE.get(uri.rstrip('/#'), uri)}:{local}"


def _timestamp(value: str | None) -> str | None:
    """XMP writes ISO-8601 with an offset; the report compares times in UTC."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
