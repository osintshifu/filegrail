"""Evidence-backed relationships between files and investigative pivots."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .cluster import AUTHOR, DEVICE, LENS, MODEL, attributes
from .identify import (
    IN_METADATA,
    PLACE,
    Identifier,
    IdentifierEvidence,
    normalize_name,
    normalize_url,
)
from .lineage import (
    COMMON_ANCESTOR,
    DERIVED_FROM,
    DESCENDS_FROM,
    DOCUMENT,
    FROM_DOCUMENT,
    FROM_INSTANCE,
    INSTANCE,
    ORIGINAL,
    ORIGINAL_OF,
    SAME_DOCUMENT,
    SOURCE_OF,
)
from .models import ORIGIN, EvidenceRecord, FileRecord, category, label

HAS_IDENTIFIER = "has identifier"
ORIGIN_URL = "origin URL"
REFERRER = "referrer"
DIGEST_OF = "digest of"
EMAIL_DOMAIN = "email domain"
URL_HOST = "URL host"
CONTENT_HASH = "content hash"
CAMERA_BODY = "camera body"
CAMERA_LENS = "camera lens"
CAMERA_MODEL = "camera model"
AUTHORSHIP = "author"
ARCHIVE_MEMBER = "member of archive"
EMBEDDED_IN = "embedded in"
TORRENT_MEMBER = "listed in torrent"

#: How the two ends of a relationship stand to each other.
#:
#: Directed is the ordinary case: a file has an identifier and the identifier
#: does not have the file. Symmetric means the claim reads the same from either
#: end, so it is one edge - a scan reaches such a claim from both files, and
#: keeping both halves would report one finding twice and count it twice.
DIRECTED = "directed"
SYMMETRIC = "symmetric"


@dataclass(frozen=True, slots=True)
class Kind:
    """What one relationship is allowed to mean."""

    #: `DIRECTED` or `SYMMETRIC`, read by `relationship_key`. So it is this
    #: table that decides what counts as one edge, rather than the order a scan
    #: happened to visit two files in.
    direction: str

    #: What an edge of this kind asserts.
    claim: str

    #: Where the assertion stops - the half a reader is most likely to supply
    #: for themselves, and the half this tool exists to refuse to supply.
    limits: str

    #: The kind that is this one read backwards, where the graph carries both.
    #: Two named edges rather than one symmetric edge, because each end names
    #: the other in its own words and either may be where a reader starts.
    inverse: str | None = None


#: Every relationship the graph can hold, and what it is allowed to mean.
#:
#: This table is the taxonomy rather than a description of one: `direction` is
#: read at build time, and `tests/test_graph.py` holds the keys against the
#: kinds the code can emit, so a kind that reaches an export undeclared is a
#: failing test rather than an edge nobody defined.
TAXONOMY: dict[str, Kind] = {
    HAS_IDENTIFIER: Kind(
        DIRECTED,
        "the file carries this value, in the place the evidence names",
        "not that the file is about it, nor that whoever holds it touched the file",
    ),
    ORIGIN_URL: Kind(
        DIRECTED,
        "a download record names this URL as where the bytes came from",
        "the record was written by the downloading program and travels with the file",
    ),
    REFERRER: Kind(
        DIRECTED,
        "the download record names this page as where the download was started",
        "not that anybody in particular was on that page",
    ),
    DIGEST_OF: Kind(
        DIRECTED,
        "this digest is the digest of that address",
        "the address was recovered by matching, so the file names the digest, not the address",
    ),
    EMAIL_DOMAIN: Kind(
        DIRECTED,
        "the address is at that domain",
        "read out of the address itself; the domain need not exist or be controlled by anyone",
    ),
    URL_HOST: Kind(
        DIRECTED,
        "the URL names that host",
        "read out of the URL itself, which anybody can write",
    ),
    CONTENT_HASH: Kind(
        DIRECTED,
        "these bytes hash to that value",
        "identifies the content and nothing else - not the name, the place or the time",
    ),
    CAMERA_BODY: Kind(
        DIRECTED,
        "the file carries that body serial, which is assigned per unit",
        "the serial is text in metadata and is copied wherever the metadata is copied",
    ),
    CAMERA_LENS: Kind(
        DIRECTED,
        "the file carries that lens serial",
        "a lens is lent, kept across an upgrade and sold on; it does not name a photographer",
    ),
    CAMERA_MODEL: Kind(
        DIRECTED,
        "the file names that make and model",
        "a product thousands of people own, never which camera",
    ),
    AUTHORSHIP: Kind(
        DIRECTED,
        "the file names this person in a field meant to name a person",
        "not that they wrote, edited or own it; which field it was is in the evidence",
    ),
    ARCHIVE_MEMBER: Kind(
        DIRECTED,
        "the archive lists this file among its entries",
        "not that the copy on disk is the copy the archive holds",
    ),
    EMBEDDED_IN: Kind(
        DIRECTED,
        "the container carries this file inside it",
        "not that the container is where the file was first written",
    ),
    TORRENT_MEMBER: Kind(
        DIRECTED,
        "the torrent lists a file of this name and size",
        "a name and a size, not the bytes: the tie is an association, not an identity",
    ),
    DERIVED_FROM: Kind(
        DIRECTED,
        "this file states it was made from that one",
        "plain text in a packet nobody signs, copied along with everything else",
        inverse=SOURCE_OF,
    ),
    SOURCE_OF: Kind(
        DIRECTED,
        "that file states it was made from this one",
        "the same unsigned statement, read from the end that did not make it",
        inverse=DERIVED_FROM,
    ),
    SAME_DOCUMENT: Kind(
        SYMMETRIC,
        "both files state the same document identifier: two renditions of one document",
        "neither came from the other, and both statements are copyable text",
    ),
    DESCENDS_FROM: Kind(
        DIRECTED,
        "this file names that one as the first document in its chain",
        "the distance is unknown: one save or fifty",
        inverse=ORIGINAL_OF,
    ),
    ORIGINAL_OF: Kind(
        DIRECTED,
        "that file names this one as the first document in its chain",
        "the same claim from the other end, at the same unknown distance",
        inverse=DESCENDS_FROM,
    ),
    COMMON_ANCESTOR: Kind(
        SYMMETRIC,
        "both files name the same first document, which is neither of them",
        "the weakest of these: a template carries its XMP into every file made from it",
    ),
}


def relationship_key(source: str, target: str, kind: str) -> tuple[str, str, str]:
    """What makes one relationship one relationship: its two ends and its kind.

    Direction is part of the key, because for most kinds the ends are not
    interchangeable - a file has an identifier, and the identifier does not
    have the file. Where `TAXONOMY` says the ends *are* interchangeable the
    pair is ordered first, so one claim has one key however the scan reached
    it, and a mirrored half cannot arrive as a second finding.
    """
    if TAXONOMY[kind].direction == SYMMETRIC and target < source:
        source, target = target, source
    return (source, target, kind)


@dataclass(frozen=True, slots=True)
class Node:
    """One file or normalized identifier in an investigation graph."""

    id: str
    type: str
    value: str
    normalized: str | None = None
    private: bool | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {"id": self.id, "type": self.type, "value": self.value}
        if self.normalized is not None:
            data["normalized"] = self.normalized
        if self.private is not None:
            data["private"] = self.private
        return data


@dataclass(frozen=True, slots=True)
class RelationshipEvidence:
    """Why one relationship is present in the graph.

    Most of these are observations: a reader found a value in a place inside a
    file. A few are not. A relationship between an address and its domain was
    never written anywhere - it follows from the value itself. Saying only
    `derived` leaves a reader unable to check it, so a derived record names the
    rule that was applied and the value it was applied to. The two kinds must
    not be told apart by eye, and here they are told apart by a field.
    """

    source: str
    place: str
    corpus: str
    count: int
    category: str | None = None
    match: str | None = None
    at: str | None = None
    rule: str | None = None
    premise: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "source": self.source,
            "place": self.place,
            "corpus": self.corpus,
            "count": self.count,
        }
        if self.category is not None:
            data["category"] = self.category
        if self.match is not None:
            data["match"] = {"method": self.match}
        if self.at is not None:
            data["at"] = self.at
        if self.rule is not None:
            data["derived"] = {"rule": self.rule, "premise": self.premise}
        return data


@dataclass(frozen=True, slots=True)
class Relationship:
    """A directed edge whose evidence can be checked in the source file."""

    source: str
    target: str
    kind: str
    count: int
    evidence: tuple[RelationshipEvidence, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "target": self.target,
            "kind": self.kind,
            "count": self.count,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class Graph:
    """The graph section added to scan JSON."""

    nodes: tuple[Node, ...]
    relationships: tuple[Relationship, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "relationships": [relationship.to_dict() for relationship in self.relationships],
        }


def file_node_id(path: str) -> str:
    """A file's identity inside one scan: the path it was found at.

    Deliberately not its name, which identifies nothing - two directories each
    holding a `report.pdf` hold two files. Deliberately not its hash either,
    because the graph has to carry files that were never hashed, and a node
    whose key changed with `--hash` would not be the same node between two
    runs of one scan. This key therefore means nothing outside the scan that
    produced it, which is why the CASE export replaces it with one that does.
    """
    return f"file:{path}"


def identifier_node_id(identifier: Identifier) -> str:
    """An identifier's identity: its type and its normalized value.

    Normalized rather than as written, so one address in two spellings is one
    node. Typed as well as valued, because the same text is not always the
    same thing - `example.org` is a domain in one file and the tail of an
    address in another, and merging them would invent a pivot.
    """
    return f"{identifier.type}:{identifier.normalized}"


def build_graph(records: list[FileRecord], identifiers: list[Identifier]) -> Graph:
    """Build file and identifier nodes plus their evidence-backed edges."""
    nodes = {
        file_node_id(record.path): Node(file_node_id(record.path), "file", record.path)
        for record in records
    }
    nodes.update(
        (
            identifier_node_id(identifier),
            Node(
                identifier_node_id(identifier),
                identifier.type,
                identifier.value,
                identifier.normalized,
                identifier.private,
            ),
        )
        for identifier in identifiers
    )

    relationships: list[Relationship] = []
    for identifier in identifiers:
        target = identifier_node_id(identifier)
        for path, count in identifier.holders.items():
            found = identifier.evidence.get(path, {})
            evidence = tuple(
                _relationship_evidence(place, occurrences)
                for place, occurrences in sorted(found.items(), key=_evidence_sort_key)
            )
            relationships.append(
                Relationship(file_node_id(path), target, HAS_IDENTIFIER, count, evidence)
            )

    by_value = {
        (identifier.type, identifier.normalized): identifier_node_id(identifier)
        for identifier in identifiers
    }
    relationships.extend(_origin_urls(records, by_value))
    relationships.extend(_derived_values(identifiers, by_value))
    relationships.extend(_content_hashes(records, nodes))
    relationships.extend(_file_attributes(records, nodes))
    relationships.extend(_container_memberships(records, nodes))
    relationships.extend(_lineage_relationships(records))

    return Graph(
        tuple(sorted(nodes.values(), key=lambda node: node.id)),
        _one_edge_per_claim(relationships),
    )


def _one_edge_per_claim(relationships: list[Relationship]) -> tuple[Relationship, ...]:
    """One edge for one claim, however many places support it.

    A document naming the same person in `creator` and in `lastModifiedBy`
    produced two identical edges, which reads as two findings where there is
    one. Both grounds belong on the same edge: the edge says the relationship
    holds, and its evidence says on how many independent grounds. Keeping them
    apart also loses the thing the evidence is for, because neither copy knows
    about the other.
    """
    merged: dict[tuple[str, str, str], Relationship] = {}
    for edge in relationships:
        key = relationship_key(edge.source, edge.target, edge.kind)
        symmetric = TAXONOMY[edge.kind].direction == SYMMETRIC
        standing = merged.get(key)
        if standing is None:
            # Stored the way the key spells it, so a symmetric claim lies in
            # one direction whichever end the scan reached it from.
            merged[key] = replace(edge, source=key[0], target=key[1])
            continue
        merged[key] = replace(
            standing,
            # A second ground for a directed claim is a second occurrence. A
            # symmetric claim met from its other end is the same occurrence
            # seen twice, and adding it up would inflate every weight in the
            # export by exactly the number of files that can see it.
            count=max(standing.count, edge.count) if symmetric else standing.count + edge.count,
            evidence=tuple(dict.fromkeys(standing.evidence + edge.evidence)),
        )
    return tuple(sorted(merged.values(), key=lambda edge: (edge.source, edge.target, edge.kind)))


def _lineage_relationships(records: list[FileRecord]) -> list[Relationship]:
    """Restate resolved XMP links with the exact fields that matched."""
    by_path = {record.path: record for record in records}
    relationships = []
    for record in records:
        for link in record.links:
            for other_path in link.others:
                other = by_path.get(other_path)
                if other is None:  # pragma: no cover - links are made from this list
                    continue
                evidence = _lineage_evidence(record, other, link.kind)
                relationships.append(
                    Relationship(
                        file_node_id(record.path),
                        file_node_id(other.path),
                        link.kind,
                        1,
                        evidence,
                    )
                )
    return relationships


_LINEAGE_PAIRS = {
    DERIVED_FROM: ((FROM_INSTANCE, INSTANCE), (FROM_DOCUMENT, DOCUMENT)),
    SOURCE_OF: ((INSTANCE, FROM_INSTANCE), (DOCUMENT, FROM_DOCUMENT)),
    SAME_DOCUMENT: ((DOCUMENT, DOCUMENT),),
    DESCENDS_FROM: ((ORIGINAL, DOCUMENT),),
    ORIGINAL_OF: ((DOCUMENT, ORIGINAL),),
    COMMON_ANCESTOR: ((ORIGINAL, ORIGINAL),),
}


def _lineage_evidence(
    source: FileRecord, target: FileRecord, kind: str
) -> tuple[RelationshipEvidence, ...]:
    source_record, source_fields = _xmp_fields(source)
    target_record, target_fields = _xmp_fields(target)
    if source_record is None or target_record is None:
        return ()  # pragma: no cover - lineage only links two XMP records

    evidence = []
    for source_name, target_name in _LINEAGE_PAIRS[kind]:
        left = source_fields.get(source_name.lower())
        right = target_fields.get(target_name.lower())
        if left is None or right is None or left[1].strip() != right[1].strip():
            continue
        evidence.append(_xmp_evidence(source_record, left[0]))
        evidence.append(_xmp_evidence(target_record, right[0]))
    return tuple(evidence)


def _xmp_fields(
    record: FileRecord,
) -> tuple[EvidenceRecord | None, dict[str, tuple[str, str]]]:
    for found in record.evidence:
        if found.source == "xmp":
            return found, {name.lower(): (name, value) for name, value in found.fields.items()}
    return None, {}


def _xmp_evidence(found: EvidenceRecord, field: str) -> RelationshipEvidence:
    return RelationshipEvidence(
        source=found.source,
        category=category(found),
        match=found.matched_by,
        place=f"{label(found)}{PLACE}{field}",
        corpus=IN_METADATA,
        count=1,
        at=found.at,
    )


def _container_memberships(records: list[FileRecord], nodes: dict[str, Node]) -> list[Relationship]:
    """Connect matched members to an explicitly recorded archive or torrent."""
    relationships = []
    kinds = {
        "archive-member": ARCHIVE_MEMBER,
        "embedded-file": EMBEDDED_IN,
        "torrent": TORRENT_MEMBER,
    }
    for record in records:
        for found in record.evidence:
            kind = kinds.get(found.source)
            if kind is None or found.container is None:
                continue
            target = file_node_id(found.container)
            nodes.setdefault(target, Node(target, "file", found.container))
            evidence = RelationshipEvidence(
                source=found.source,
                category=category(found),
                match=found.matched_by,
                place=f"{label(found)}{PLACE}{Path(record.path).name}",
                corpus=IN_METADATA,
                count=1,
                at=found.at,
            )
            relationships.append(
                Relationship(file_node_id(record.path), target, kind, 1, (evidence,))
            )
    return relationships


def _file_attributes(records: list[FileRecord], nodes: dict[str, Node]) -> list[Relationship]:
    """Connect files to author and camera values already used by clustering."""
    relationships = []
    for record in records:
        for attribute in attributes(record):
            node_type, kind, normalized = _attribute_identity(attribute.axis, attribute.name)
            target = f"{node_type}:{normalized}"
            nodes.setdefault(target, Node(target, node_type, attribute.name, normalized))
            found = attribute.evidence
            evidence = RelationshipEvidence(
                source=found.source,
                category=category(found),
                match=found.matched_by,
                place=attribute.basis,
                corpus=IN_METADATA,
                count=1,
                at=found.at,
            )
            relationships.append(
                Relationship(file_node_id(record.path), target, kind, 1, (evidence,))
            )
    return relationships


def _attribute_identity(axis: str, value: str) -> tuple[str, str, str]:
    if axis == AUTHOR:
        return "person", AUTHORSHIP, normalize_name(value)
    normalized = " ".join(value.split()).casefold()
    if axis == DEVICE:
        return "device", CAMERA_BODY, normalized
    if axis == LENS:
        return "lens", CAMERA_LENS, normalized
    if axis == MODEL:
        return "camera_model", CAMERA_MODEL, normalized
    raise ValueError(f"unknown shared attribute axis: {axis}")  # pragma: no cover


def _content_hashes(records: list[FileRecord], nodes: dict[str, Node]) -> list[Relationship]:
    """Connect hashed files through a shared SHA-256 node without pairwise edges."""
    relationships = []
    for record in records:
        if record.sha256 is None:
            continue
        target = f"sha256:{record.sha256}"
        nodes.setdefault(target, Node(target, "sha256", record.sha256, record.sha256))
        evidence = RelationshipEvidence(
            source="computed-hash",
            place="whole file",
            corpus="derived",
            count=1,
        )
        relationships.append(
            Relationship(file_node_id(record.path), target, CONTENT_HASH, 1, (evidence,))
        )
    return relationships


def _origin_urls(
    records: list[FileRecord], by_value: dict[tuple[str, str], str]
) -> list[Relationship]:
    """Specific origin and referrer edges, in addition to generic pivots."""
    grouped: dict[tuple[str, str, str], list[tuple[RelationshipEvidence, int]]] = {}
    for record in records:
        source = file_node_id(record.path)
        for found in record.evidence:
            if category(found) != ORIGIN:
                continue
            for field, kind, value in (
                ("url", ORIGIN_URL, found.url),
                ("referrer", REFERRER, found.referrer),
            ):
                parsed = normalize_url(value) if value else None
                target = by_value.get(("url", parsed[0])) if parsed else None
                if target is None:
                    continue
                evidence = RelationshipEvidence(
                    source=found.source,
                    category=ORIGIN,
                    match=found.matched_by,
                    place=f"{label(found)}{PLACE}{field}",
                    corpus=IN_METADATA,
                    count=1,
                    at=found.at,
                )
                grouped.setdefault((source, target, kind), []).append((evidence, 1))
    return _grouped(grouped)


def _derived_values(
    identifiers: list[Identifier], by_value: dict[tuple[str, str], str]
) -> list[Relationship]:
    """Relations proven by the normalized values themselves."""
    relationships: list[Relationship] = []
    for identifier in identifiers:
        source = identifier_node_id(identifier)
        if identifier.of is not None:
            target = by_value.get(("email", identifier.of))
            if target is not None:
                relationships.append(
                    _derived(
                        source,
                        target,
                        DIGEST_OF,
                        "digest equality",
                        DIGEST_EQUALITY,
                        identifier.normalized,
                    )
                )

        if identifier.type == "email":
            host = identifier.normalized.rpartition("@")[2]
            target = by_value.get(("domain", host))
            if target is not None:
                relationships.append(
                    _derived(
                        source,
                        target,
                        EMAIL_DOMAIN,
                        "email host",
                        EMAIL_HOST,
                        identifier.normalized,
                    )
                )

        if identifier.type == "url":
            parsed = normalize_url(identifier.normalized)
            url_host = parsed[1] if parsed else None
            target = by_value.get(("domain", url_host)) if url_host else None
            if target is not None:
                relationships.append(
                    _derived(
                        source, target, URL_HOST, "URL host", URL_HOSTNAME, identifier.normalized
                    )
                )
    return relationships


#: The rules that read a relationship out of a value rather than out of a file.
#: Each is named so a reader can check it, and so two runs name it the same way.
DIGEST_EQUALITY = "digest-equality"
EMAIL_HOST = "email-host"
URL_HOSTNAME = "url-hostname"


def _derived(
    source: str, target: str, kind: str, place: str, rule: str, premise: str
) -> Relationship:
    """A relationship the values themselves carry, with the working shown."""
    evidence = RelationshipEvidence(
        source="derived",
        place=place,
        corpus="derived",
        count=1,
        rule=rule,
        premise=premise,
    )
    return Relationship(source, target, kind, 1, (evidence,))


def _grouped(
    grouped: dict[tuple[str, str, str], list[tuple[RelationshipEvidence, int]]],
) -> list[Relationship]:
    relationships = []
    for (source, target, kind), found in grouped.items():
        count = sum(occurrences for _evidence, occurrences in found)
        evidence = tuple(item for item, _occurrences in found)
        relationships.append(Relationship(source, target, kind, count, evidence))
    return relationships


def _evidence_sort_key(item: tuple[IdentifierEvidence, int]) -> tuple[str, ...]:
    place, _count = item
    return (
        place.source,
        place.category or "",
        place.match or "",
        place.place,
        place.corpus,
        place.at or "",
    )


def _relationship_evidence(place: IdentifierEvidence, occurrences: int) -> RelationshipEvidence:
    return RelationshipEvidence(
        source=place.source,
        category=place.category,
        match=place.match,
        place=place.place,
        corpus=place.corpus,
        count=occurrences,
        at=place.at,
    )
