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
    """Why one relationship is present in the graph."""

    source: str
    place: str
    corpus: str
    count: int
    category: str | None = None
    match: str | None = None
    at: str | None = None

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
    return f"file:{path}"


def identifier_node_id(identifier: Identifier) -> str:
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
        key = (edge.source, edge.target, edge.kind)
        standing = merged.get(key)
        if standing is None:
            merged[key] = edge
            continue
        merged[key] = replace(
            standing,
            count=standing.count + edge.count,
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
                relationships.append(_derived(source, target, DIGEST_OF, "digest equality"))

        if identifier.type == "email":
            host = identifier.normalized.rpartition("@")[2]
            target = by_value.get(("domain", host))
            if target is not None:
                relationships.append(_derived(source, target, EMAIL_DOMAIN, "email host"))

        if identifier.type == "url":
            parsed = normalize_url(identifier.normalized)
            url_host = parsed[1] if parsed else None
            target = by_value.get(("domain", url_host)) if url_host else None
            if target is not None:
                relationships.append(_derived(source, target, URL_HOST, "URL host"))
    return relationships


def _derived(source: str, target: str, kind: str, place: str) -> Relationship:
    evidence = RelationshipEvidence(
        source="derived",
        place=place,
        corpus="derived",
        count=1,
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
