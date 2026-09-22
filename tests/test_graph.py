import hashlib
import json
from pathlib import Path

from filegrail.identify import MAX_RELATION_PLACES
from filegrail.lineage import attach_lineage
from filegrail.models import EvidenceRecord, FileRecord
from filegrail.report import render_json


def _record(path: str, *evidence: EvidenceRecord) -> FileRecord:
    return FileRecord(path=path, size=10, mtime="2026-09-17T12:00:00Z", evidence=list(evidence))


def test_graph_is_emitted_with_pivots_and_keeps_structured_evidence():
    path = "/case/report.pdf"
    record = _record(
        path,
        EvidenceRecord(
            source="document-metadata",
            at="2026-09-17T11:00:00Z",
            fields={"Author": "analyst@example.org"},
        ),
    )

    payload = json.loads(render_json([record], Path("/case"), identify=True))

    nodes = {node["id"]: node for node in payload["graph"]["nodes"]}
    assert nodes["email:analyst@example.org"] == {
        "id": "email:analyst@example.org",
        "type": "email",
        "value": "analyst@example.org",
        "normalized": "analyst@example.org",
    }
    assert nodes[f"file:{path}"] == {"id": f"file:{path}", "type": "file", "value": path}

    relationship = next(
        edge
        for edge in payload["graph"]["relationships"]
        if edge["target"] == "email:analyst@example.org"
    )
    assert relationship == {
        "source": f"file:{path}",
        "target": "email:analyst@example.org",
        "kind": "has identifier",
        "count": 1,
        "evidence": [
            {
                "source": "document-metadata",
                "place": "document metadata · Author",
                "corpus": "metadata",
                "count": 1,
                "category": "metadata",
                "match": {"method": "embedded"},
                "at": "2026-09-17T11:00:00Z",
            }
        ],
    }


def test_one_file_to_identifier_edge_groups_independent_evidence():
    path = "/case/report.pdf"
    record = _record(
        path,
        EvidenceRecord(source="browser-download", url="https://example.org/report.pdf"),
        EvidenceRecord(source="document-metadata", fields={"Company": "example.org"}),
    )

    graph = json.loads(render_json([record], Path("/case"), identify=True))["graph"]
    relationship = next(
        edge for edge in graph["relationships"] if edge["target"] == "domain:example.org"
    )

    assert relationship["count"] == 2
    assert [item["source"] for item in relationship["evidence"]] == [
        "browser-download",
        "document-metadata",
    ]
    assert [item["category"] for item in relationship["evidence"]] == [
        "origin",
        "metadata",
    ]


def test_relationship_count_survives_a_shortened_place_list():
    path = "/case/list.txt"
    fields = {f"field-{number}": "ops@example.org" for number in range(MAX_RELATION_PLACES + 1)}
    record = _record(path, EvidenceRecord(source="document-metadata", fields=fields))

    graph = json.loads(render_json([record], Path("/case"), identify=True))["graph"]
    relationship = next(
        edge for edge in graph["relationships"] if edge["target"] == "email:ops@example.org"
    )

    assert relationship["count"] == MAX_RELATION_PLACES + 1
    assert len(relationship["evidence"]) == MAX_RELATION_PLACES


def test_graph_is_absent_without_pivots():
    payload = json.loads(render_json([_record("/case/a.txt")], Path("/case")))

    assert "graph" not in payload


def test_identical_files_share_one_content_hash_node_without_pairwise_edges():
    digest = "a" * 64
    first = _record("/case/a.bin")
    second = _record("/case/b.bin")
    first.sha256 = digest
    second.sha256 = digest

    graph = json.loads(render_json([first, second], Path("/case")))["graph"]

    assert [node for node in graph["nodes"] if node["type"] == "sha256"] == [
        {
            "id": f"sha256:{digest}",
            "type": "sha256",
            "value": digest,
            "normalized": digest,
        }
    ]
    edges = [edge for edge in graph["relationships"] if edge["kind"] == "content hash"]
    assert {edge["source"] for edge in edges} == {"file:/case/a.bin", "file:/case/b.bin"}
    assert {edge["target"] for edge in edges} == {f"sha256:{digest}"}
    assert all(edge["evidence"][0]["source"] == "computed-hash" for edge in edges)


def test_origin_url_and_referrer_have_semantic_relationships():
    path = "/case/report.pdf"
    record = _record(
        path,
        EvidenceRecord(
            source="browser-download",
            url="https://files.example.org/report.pdf",
            referrer="https://portal.example.org/case/42",
            at="2026-09-17T10:00:00Z",
        ),
    )

    graph = json.loads(render_json([record], Path("/case"), identify=True))["graph"]
    semantic = {
        edge["kind"]: edge
        for edge in graph["relationships"]
        if edge["kind"] in {"origin URL", "referrer"}
    }

    assert semantic["origin URL"]["target"] == "url:https://files.example.org/report.pdf"
    assert semantic["referrer"]["target"] == "url:https://portal.example.org/case/42"
    assert semantic["origin URL"]["evidence"] == [
        {
            "source": "browser-download",
            "place": "browser download · url",
            "corpus": "metadata",
            "count": 1,
            "category": "origin",
            "match": {"method": "recorded-path"},
            "at": "2026-09-17T10:00:00Z",
        }
    ]


def test_normalized_values_create_derived_relationships():
    address = "analyst@example.org"
    digest = hashlib.sha256(address.encode()).hexdigest()
    record = _record(
        "/case/notes.txt",
        EvidenceRecord(
            source="document-metadata",
            fields={
                "Author": address,
                "Homepage": "https://portal.example.org/team",
                "Digest": digest,
            },
        ),
    )

    graph = json.loads(render_json([record], Path("/case"), identify=True))["graph"]
    relationships = {
        (edge["source"], edge["target"], edge["kind"]) for edge in graph["relationships"]
    }

    assert (
        f"sha256:{digest}",
        "email:analyst@example.org",
        "digest of",
    ) in relationships
    assert (
        "email:analyst@example.org",
        "domain:example.org",
        "email domain",
    ) in relationships
    assert (
        "url:https://portal.example.org/team",
        "domain:portal.example.org",
        "URL host",
    ) in relationships


def test_author_and_camera_relationships_reuse_cluster_attributes():
    path = "/case/photo.jpg"
    record = _record(
        path,
        EvidenceRecord(
            source="device-metadata",
            block="exif",
            at="2026-09-17T09:00:00Z",
            fields={
                "Artist": "Jan Kowalski",
                "Make": "Canon",
                "Model": "EOS R5",
                "BodySerialNumber": "ABC123",
            },
        ),
    )

    graph = json.loads(render_json([record], Path("/case"), identify=True))["graph"]
    nodes = {node["id"]: node for node in graph["nodes"]}
    edges = {(edge["target"], edge["kind"]): edge for edge in graph["relationships"]}

    assert nodes["person:jan kowalski"]["value"] == "Jan Kowalski"
    assert nodes["device:abc123"]["value"] == "ABC123"
    assert nodes["camera_model:canon eos r5"]["value"] == "Canon EOS R5"
    assert ("person:jan kowalski", "author") in edges
    assert ("device:abc123", "camera body") in edges
    assert ("camera_model:canon eos r5", "camera model") in edges
    assert edges[("device:abc123", "camera body")]["evidence"] == [
        {
            "source": "device-metadata",
            "place": "EXIF · BodySerialNumber",
            "corpus": "metadata",
            "count": 1,
            "category": "metadata",
            "match": {"method": "embedded"},
            "at": "2026-09-17T09:00:00Z",
        }
    ]


def test_container_paths_create_membership_relationships_without_parsing_notes():
    archive = "/downloads/pack.zip"
    torrent = "/profile/BT_backup/release.torrent"
    records = [
        _record(
            "/case/report.pdf",
            EvidenceRecord(
                source="archive-member",
                match="container-member",
                note="wording may change",
                container=archive,
            ),
        ),
        _record(
            "/case/film.mkv",
            EvidenceRecord(
                source="torrent",
                match="name+size",
                container=torrent,
            ),
        ),
    ]

    graph = json.loads(render_json(records, Path("/case")))["graph"]
    relationships = {
        (edge["source"], edge["target"], edge["kind"]): edge for edge in graph["relationships"]
    }

    archive_edge = relationships[("file:/case/report.pdf", f"file:{archive}", "member of archive")]
    torrent_edge = relationships[("file:/case/film.mkv", f"file:{torrent}", "listed in torrent")]
    assert archive_edge["evidence"][0]["match"] == {"method": "container-member"}
    assert torrent_edge["evidence"][0]["match"] == {"method": "name+size"}


def test_xmp_lineage_uses_only_the_fields_that_created_the_link():
    parent = _record(
        "/case/master.jpg",
        EvidenceRecord(
            source="xmp",
            block="xmp",
            fields={
                "xmpMM:DocumentID": "xmp.did:1111AAAA",
                "xmpMM:OriginalDocumentID": "xmp.did:unrelated",
            },
        ),
    )
    child = _record(
        "/case/export.jpg",
        EvidenceRecord(
            source="xmp",
            block="xmp",
            fields={
                "xmpMM:DocumentID": "xmp.did:2222BBBB",
                "xmpMM:DerivedFrom/stRef:documentID": "xmp.did:1111AAAA",
                "xmpMM:OriginalDocumentID": "xmp.did:another-value",
            },
        ),
    )
    attach_lineage([parent, child])

    graph = json.loads(render_json([parent, child], Path("/case")))["graph"]
    edge = next(
        edge
        for edge in graph["relationships"]
        if edge["source"] == "file:/case/export.jpg"
        and edge["target"] == "file:/case/master.jpg"
        and edge["kind"] == "derived from"
    )

    assert [item["place"] for item in edge["evidence"]] == [
        "XMP · xmpMM:DerivedFrom/stRef:documentID",
        "XMP · xmpMM:DocumentID",
    ]
    assert all("OriginalDocumentID" not in item["place"] for item in edge["evidence"])


def test_one_claim_is_one_edge_however_many_places_support_it():
    """A document naming the same person in `creator` and in `lastModifiedBy`
    used to produce two identical edges, which reads as two findings where
    there is one. Both grounds belong to the same claim."""
    from filegrail.graph import build_graph

    record = _record(
        "/case/report.docx",
        EvidenceRecord(
            source="document-metadata",
            block="ooxml-properties",
            fields={"creator": "Stephen Richard", "lastModifiedBy": "Stephen Richard"},
        ),
    )

    graph = build_graph([record], [])

    authored = [edge for edge in graph.relationships if edge.kind == "author"]
    assert len(authored) == 1
    assert authored[0].count == 2
    assert len(authored[0].evidence) == 2
    assert {found.place for found in authored[0].evidence} == {
        "OOXML properties \u00b7 creator",
        "OOXML properties \u00b7 lastModifiedBy",
    }


def test_graphml_keeps_a_name_that_xml_cannot_hold():
    """A name on ext4 or NTFS may hold a control character, and ElementTree
    writes it out as a document no parser will open."""
    import xml.etree.ElementTree as ElementTree

    from filegrail.graph import Graph, Node
    from filegrail.graph_export import render_graphml

    named = Node("file:/case/we\x07ird.txt", "file", "/case/we\x07ird.txt")
    page = render_graphml(Graph((named,), ()))

    ElementTree.fromstring(page)
    assert "\\u0007" in page


def test_graphml_names_its_nodes_and_types_its_edges():
    """Without these an importer labels every node by its export id and gives
    every relationship the same nameless type."""
    from filegrail.graph import Graph, Node, Relationship
    from filegrail.graph_export import render_graphml

    nodes = (
        Node("file:/case/holiday.jpg", "file", "/case/holiday.jpg"),
        Node("camera_model:nikon d70", "camera_model", "NIKON D70", "nikon d70"),
    )
    page = render_graphml(
        Graph(nodes, (Relationship(nodes[0].id, nodes[1].id, "camera model", 3, ()),))
    )

    assert '<key id="label" for="edge" attr.name="label" attr.type="string" />' in page
    assert '<data key="label_n">holiday.jpg</data>' in page
    assert '<data key="labels">:CameraModel</data>' in page
    assert '<data key="label">CAMERA_MODEL</data>' in page
    assert '<data key="weight">3.0</data>' in page
