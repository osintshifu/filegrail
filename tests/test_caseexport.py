"""The evidence graph as CASE/UCO JSON-LD.

What makes this export worth writing is that CASE has somewhere to put the two
things the tool is about: the evidence behind a relationship, and a record of
which tool produced it. These check that neither is lost on the way out, and
that an identifier never claims more than the evidence supports.
"""

from __future__ import annotations

import json
from pathlib import Path

from filegrail.caseexport import render_case_jsonld
from filegrail.graph import Graph, Node, Relationship, RelationshipEvidence
from filegrail.models import FileRecord

NOW = "2026-09-23T12:00:00Z"


def _document(graph: Graph, records: list[FileRecord], root: str = "/case") -> dict:
    return json.loads(
        render_case_jsonld(graph, records, root=Path(root), moment=NOW, case="2026/014")
    )


def _typed(document: dict, name: str) -> list[dict]:
    return [
        item
        for item in document["@graph"]
        if name in (item["@type"] if isinstance(item["@type"], list) else [item["@type"]])
    ]


def test_a_relationship_keeps_every_ground_as_its_own_facet():
    """A document naming one person in two fields is one claim resting on two
    grounds. A format that could not say that would force it to become two
    relationships, or to lose where each came from - and that is the whole
    reason this export exists."""
    nodes = (
        Node("file:/case/report.docx", "file", "/case/report.docx"),
        Node("person:stephen richard", "person", "Stephen Richard", "stephen richard"),
    )
    grounds = tuple(
        RelationshipEvidence(
            source="document-metadata",
            place=f"OOXML properties · {field}",
            corpus="metadata",
            count=1,
        )
        for field in ("creator", "lastModifiedBy")
    )
    graph = Graph(nodes, (Relationship(nodes[0].id, nodes[1].id, "author", 2, grounds),))

    document = _document(graph, [FileRecord(path="/case/report.docx", size=10, mtime=NOW)])

    edge = _typed(document, "uco-core:Relationship")[0]
    facets = edge["uco-core:hasFacet"]
    assert len(facets) == 2
    assert {facet["fg:place"] for facet in facets} == {
        "OOXML properties · creator",
        "OOXML properties · lastModifiedBy",
    }
    # Its own type says what it holds; the second makes it a facet at all, and
    # without it a validator refuses the document.
    assert facets[0]["@type"] == ["fg:EvidenceFacet", "uco-core:Facet"]


def test_a_file_is_identified_by_its_content_only_where_that_is_known():
    """A SHA-256 identifies a file anywhere. A path identifies it in this
    target and nowhere else, and a name identifies nothing: two files called
    `report.pdf` are two files. The identifier has to say which of those the
    evidence supports."""
    node = Node("file:/case/report.pdf", "file", "/case/report.pdf")
    graph = Graph((node,), ())
    digest = "a" * 64

    hashed = _document(graph, [FileRecord(path=node.value, size=10, mtime=NOW, sha256=digest)])
    unhashed = _document(graph, [FileRecord(path=node.value, size=10, mtime=NOW)])
    elsewhere = _document(
        graph, [FileRecord(path=node.value, size=10, mtime=NOW)], root="/other-case"
    )

    assert (
        _typed(hashed, "uco-observable:File")[0]["@id"]
        != (_typed(unhashed, "uco-observable:File")[0]["@id"])
    )
    # The same bytes anywhere are one file; the same path in another target is not.
    same = _document(graph, [FileRecord(path=node.value, size=99, mtime="x", sha256=digest)], "/z")
    assert (
        _typed(same, "uco-observable:File")[0]["@id"]
        == (_typed(hashed, "uco-observable:File")[0]["@id"])
    )
    assert (
        _typed(elsewhere, "uco-observable:File")[0]["@id"]
        != (_typed(unhashed, "uco-observable:File")[0]["@id"])
    )


def test_nothing_in_the_document_points_at_something_missing_from_it():
    """A reference to an object that is not in the document is a validation
    error in CASE, and the file a person receives is then not CASE at all. It
    is the failure a test that only reads the JSON back would not notice."""
    nodes = (
        Node("file:/case/photo.jpg", "file", "/case/photo.jpg"),
        Node("domain:example.org", "domain", "example.org", "example.org"),
    )
    evidence = RelationshipEvidence(
        source="derived",
        place="email host",
        corpus="derived",
        count=1,
        rule="email-host",
        premise="ann@example.org",
    )
    graph = Graph(nodes, (Relationship(nodes[0].id, nodes[1].id, "email domain", 1, (evidence,)),))

    document = _document(
        graph, [FileRecord(path="/case/photo.jpg", size=10, mtime=NOW, sha256="b" * 64)]
    )

    known: set[str] = set()
    referenced: set[str] = set()

    def walk(value: object) -> None:
        if isinstance(value, dict):
            if "@type" in value and "@id" in value:
                known.add(str(value["@id"]))
            elif set(value) == {"@id"}:
                referenced.add(str(value["@id"]))
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(document["@graph"])
    assert referenced - known == set()
    assert (
        _typed(document, "case-investigation:ProvenanceRecord")[0][
            "case-investigation:exhibitNumber"
        ]
        == "2026/014"
    )


def test_a_symmetric_relationship_is_not_exported_as_directional():
    """UCO carries `isDirectional` so a reader is told which relationships have
    a direction worth reading. Writing `true` on every one of them tells a
    recipient that a rendition of a document is its parent."""
    nodes = (
        Node("file:/case/web.jpg", "file", "/case/web.jpg"),
        Node("file:/case/print.tif", "file", "/case/print.tif"),
    )
    ground = RelationshipEvidence(
        source="xmp", place="XMP · xmpMM:DocumentID", corpus="metadata", count=1
    )
    graph = Graph(
        nodes,
        (
            Relationship(nodes[0].id, nodes[1].id, "same document", 1, (ground,)),
            Relationship(nodes[0].id, nodes[1].id, "derived from", 1, (ground,)),
        ),
    )

    document = _document(
        graph,
        [
            FileRecord(path=node.value, size=10, mtime=NOW, sha256=digest * 64)
            for node, digest in zip(nodes, "ab", strict=True)
        ],
    )

    stated = {
        edge["fg:kind"]: edge["uco-core:isDirectional"]
        for edge in _typed(document, "uco-observable:ObservableRelationship")
    }
    assert stated == {"same document": False, "derived from": True}


def test_the_case_vocabulary_names_only_relationships_that_exist():
    """A mapping keyed on a kind nothing emits is silently never applied. This
    export carried `derived-from` for a relationship spelled `derived from`, so
    the one lineage relation with a word of its own in the CASE vocabulary went
    out under ours instead, and every test still passed."""
    from filegrail.caseexport import _KIND
    from filegrail.graph import TAXONOMY

    assert set(_KIND) <= set(TAXONOMY), sorted(set(_KIND) - set(TAXONOMY))
