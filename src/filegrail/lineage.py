"""How the files in one scan say they were made from each other.

XMP carries four identifiers for exactly this - the document a file is a
rendition of, the exact bytes it is, the first document in its chain, and the
resource it was derived from. On their own they are opaque strings that the
report prints and nobody can use. Read across a directory they say which file
came from which, which is often the only account of an edit that survives.

Nothing here is proof. Every one of these values is plain text in a packet
nobody signs, and copying a file copies them along with everything else. A link
is what two files say about each other, on the same footing as any other claim
the tool reads out of a file.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .models import FileRecord

#: A was made from B. The strongest of the four, and the only directed one.
DERIVED_FROM = "derived from"

#: The same edge read backwards, so a master can name its own exports.
SOURCE_OF = "source of"

#: Two renditions of one document - a web JPEG and the TIFF it was flattened
#: from. Undirected: neither came from the other, both came from the document.
SAME_DOCUMENT = "same document"

#: A names B's document as the first in its chain: B is where A started, however
#: many saves ago. Weaker than a derivation - the distance is unknown - and much
#: stronger than merely sharing an ancestor with it.
DESCENDS_FROM = "descends from"

#: The same relation read backwards.
ORIGINAL_OF = "original of"

#: A shared first document, at an unknown distance, with neither file being it.
#: The weakest of them and the one most often meaningless: a template carries
#: its XMP block into every file made from it, and those files share an original
#: and nothing else.
COMMON_ANCESTOR = "common ancestor"

#: Relations in the order they are looked for, so a pair joined more than one
#: way is reported by the strongest of the ways.
KINDS = (
    DERIVED_FROM,
    SOURCE_OF,
    SAME_DOCUMENT,
    DESCENDS_FROM,
    ORIGINAL_OF,
    COMMON_ANCESTOR,
)

DOCUMENT = "xmpMM:DocumentID"
INSTANCE = "xmpMM:InstanceID"
ORIGINAL = "xmpMM:OriginalDocumentID"
FROM_DOCUMENT = "xmpMM:DerivedFrom/stRef:documentID"
FROM_INSTANCE = "xmpMM:DerivedFrom/stRef:instanceID"

_WANTED = (DOCUMENT, INSTANCE, ORIGINAL, FROM_DOCUMENT, FROM_INSTANCE)

#: The relations found by matching one stated value against another, strongest
#: first: which value of this file to look up, and which index to look it up in.
#: `DerivedFrom` is not here because it is directed and produces both halves of
#: its edge at once.
_MATCHES = (
    (SAME_DOCUMENT, DOCUMENT, DOCUMENT),
    (DESCENDS_FROM, ORIGINAL, DOCUMENT),
    (ORIGINAL_OF, DOCUMENT, ORIGINAL),
    (COMMON_ANCESTOR, ORIGINAL, ORIGINAL),
)

#: Above this many files sharing one identifier, they are counted rather than
#: listed against each other. A directory built from one template is the case:
#: pairing all of it is a square number of links about a relation nobody would
#: call a lineage, and the count is the part worth reading anyway.
_CROWD = 8

#: Shorter than this and it is a label, not an identifier.
_MIN_LENGTH = 8


@dataclass(frozen=True, slots=True)
class Link:
    """One relation between a file and others in the same scan."""

    kind: str

    #: The related files, by path, or empty when there were too many to name.
    others: tuple[str, ...]

    #: How many there are. Equal to `len(others)` unless they were a crowd.
    count: int

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "others": list(self.others), "count": self.count}


def attach_lineage(records: list[FileRecord]) -> None:
    """Give every record the relations it has to the others in the same scan."""
    stated = [_identifiers(record) for record in records]
    by_document = _index(stated, DOCUMENT)
    by_instance = _index(stated, INSTANCE)
    by_original = _index(stated, ORIGINAL)

    parents = {
        position: _parents(ids, position, by_document, by_instance)
        for position, ids in enumerate(stated)
    }
    children: dict[int, set[int]] = defaultdict(set)
    for position, found in parents.items():
        for parent in found:
            children[parent].add(position)

    indexes = {DOCUMENT: by_document, ORIGINAL: by_original}
    for position, ids in enumerate(stated):
        records[position].links = _links(position, ids, records, parents, children, indexes)


def _links(
    position: int,
    ids: dict[str, str],
    records: list[FileRecord],
    parents: dict[int, set[int]],
    children: dict[int, set[int]],
    indexes: dict[str, dict[str, list[int]]],
) -> list[Link]:
    found = []
    joined = parents[position] | children[position]
    for kind, group in ((DERIVED_FROM, parents[position]), (SOURCE_OF, children[position])):
        if group:
            found.append(_named(kind, group, records))

    for kind, mine, theirs in _MATCHES:
        sharing = indexes[theirs].get(ids.get(mine, ""), ())
        if len(sharing) - 1 > _CROWD:
            # Counted without being materialised: a whole directory under one
            # template would otherwise cost a set per file of every other file.
            found.append(Link(kind=kind, others=(), count=len(sharing) - 1))
            continue
        group = {other for other in sharing if other != position} - joined
        if group:
            found.append(_named(kind, group, records))
            joined |= group
    return found


def _parents(
    ids: dict[str, str],
    position: int,
    by_document: dict[str, list[int]],
    by_instance: dict[str, list[int]],
) -> set[int]:
    """Which records this one says it was made from.

    The two halves of the reference are looked up in their own indexes and
    never across: a writer that puts one uuid in both the document and the
    instance would otherwise make every file carrying it a parent of the rest.
    """
    found: set[int] = set()
    for name, index in ((FROM_INSTANCE, by_instance), (FROM_DOCUMENT, by_document)):
        sharing = index.get(ids.get(name, ""), ())
        if len(sharing) <= _CROWD:
            found.update(sharing)
    found.discard(position)
    return found


def _named(kind: str, group: set[int], records: list[FileRecord]) -> Link:
    others = tuple(sorted(records[position].path for position in group))
    return Link(kind=kind, others=others, count=len(others))


def _index(stated: list[dict[str, str]], name: str) -> dict[str, list[int]]:
    found: dict[str, list[int]] = defaultdict(list)
    for position, ids in enumerate(stated):
        if value := ids.get(name):
            found[value].append(position)
    return found


def _identifiers(record: FileRecord) -> dict[str, str]:
    """The identifiers one file states, under their canonical spellings.

    Writers disagree about the case of `stRef:documentID`, so the lookup does
    not depend on it.
    """
    for found in record.evidence:
        if found.source != "xmp":
            continue
        stated = {name.lower(): value.strip() for name, value in found.fields.items()}
        return {
            name: value for name in _WANTED if _meaningful(value := stated.get(name.lower(), ""))
        }
    return {}


def _meaningful(value: str) -> bool:
    """Whether a value identifies anything.

    A null uuid is what a writer emits when it has nothing to say, and reading
    it as an identity would make every file carrying one a rendition of every
    other. The scheme in front of it - `uuid:`, `xmp.did:` - is dropped first,
    because it is the same on every value and would hide an empty one.
    """
    body = "".join(c for c in value.rpartition(":")[2] if c.isalnum())
    return len(body) >= _MIN_LENGTH and body.strip("0") != ""
