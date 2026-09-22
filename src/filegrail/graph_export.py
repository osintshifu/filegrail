"""GraphML and CSV serialization for an investigation graph."""

from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ElementTree
from collections.abc import Mapping
from pathlib import PurePosixPath, PureWindowsPath

from .graph import Graph, Node

_GRAPHML = "http://graphml.graphdrawing.org/xmlns"
ElementTree.register_namespace("", _GRAPHML)


def render_graphml(
    graph: Graph,
    *,
    run: Mapping[str, object] | None = None,
    coverage: Mapping[str, object] | None = None,
) -> str:
    """Serialize ``graph`` as dependency-free, interoperable GraphML."""
    root = ElementTree.Element(f"{{{_GRAPHML}}}graphml")
    for key, scope, name, value_type in (
        # Three keys every importer already looks for. Without them Gephi, yEd
        # and Cytoscape label each node `n0`, `n1`, `n2` - the export identifier,
        # which carries nothing - and Neo4j types every relationship `UNKNOWN`.
        # The names and the key ids are what those importers match on, so they
        # are not free choices: an importer looks up the edge type by the key's
        # id and the node label by its name.
        ("label_n", "node", "label", "string"),
        ("labels", "node", "labels", "string"),
        ("label", "edge", "label", "string"),
        ("weight", "edge", "weight", "double"),
        ("node_id", "node", "id", "string"),
        ("node_type", "node", "type", "string"),
        ("node_value", "node", "value", "string"),
        ("node_normalized", "node", "normalized", "string"),
        ("node_private", "node", "private", "boolean"),
        ("edge_kind", "edge", "kind", "string"),
        ("edge_count", "edge", "count", "int"),
        ("edge_evidence", "edge", "evidence", "string"),
        ("graph_run", "graph", "run", "string"),
        ("graph_coverage", "graph", "coverage", "string"),
    ):
        ElementTree.SubElement(
            root,
            f"{{{_GRAPHML}}}key",
            {"id": key, "for": scope, "attr.name": name, "attr.type": value_type},
        )

    document = ElementTree.SubElement(
        root, f"{{{_GRAPHML}}}graph", {"id": "filegrail", "edgedefault": "directed"}
    )
    if run is not None:
        _data(document, "graph_run", _json(run))
    if coverage is not None:
        _data(document, "graph_coverage", _json(coverage))
    exported_ids = {node.id: f"n{position}" for position, node in enumerate(graph.nodes)}
    for node in graph.nodes:
        element = ElementTree.SubElement(
            document, f"{{{_GRAPHML}}}node", {"id": exported_ids[node.id]}
        )
        _data(element, "label_n", _label(node))
        _data(element, "labels", _node_labels(node))
        _data(element, "node_id", node.id)
        _data(element, "node_type", node.type)
        _data(element, "node_value", node.value)
        if node.normalized is not None:
            _data(element, "node_normalized", node.normalized)
        if node.private is not None:
            _data(element, "node_private", str(node.private).lower())

    for position, relationship in enumerate(graph.relationships):
        edge = ElementTree.SubElement(
            document,
            f"{{{_GRAPHML}}}edge",
            {
                "id": f"e{position}",
                "source": exported_ids[relationship.source],
                "target": exported_ids[relationship.target],
            },
        )
        _data(edge, "label", _edge_label(relationship.kind))
        _data(edge, "weight", str(float(relationship.count)))
        _data(edge, "edge_kind", relationship.kind)
        _data(edge, "edge_count", str(relationship.count))
        _data(
            edge,
            "edge_evidence",
            json.dumps(
                [item.to_dict() for item in relationship.evidence],
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )

    ElementTree.indent(root, space="  ")
    return ElementTree.tostring(root, encoding="unicode", xml_declaration=True)


def render_graph_csv(
    graph: Graph,
    *,
    run: Mapping[str, object] | None = None,
    coverage: Mapping[str, object] | None = None,
) -> str:
    """Serialize one relationship per CSV row, including both endpoint nodes."""
    nodes = {node.id: node for node in graph.nodes}
    output = io.StringIO(newline="")
    fields = (
        "source_id",
        "source_type",
        "source_value",
        "target_id",
        "target_type",
        "target_value",
        "kind",
        "count",
        "evidence",
        "run",
        "coverage",
    )
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for relationship in graph.relationships:
        source = nodes[relationship.source]
        target = nodes[relationship.target]
        writer.writerow(
            {
                "source_id": source.id,
                "source_type": source.type,
                "source_value": source.value,
                "target_id": target.id,
                "target_type": target.type,
                "target_value": target.value,
                "kind": relationship.kind,
                "count": relationship.count,
                "evidence": json.dumps(
                    [item.to_dict() for item in relationship.evidence],
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "run": _json(run) if run is not None else "",
                "coverage": _json(coverage) if coverage is not None else "",
            }
        )
    return output.getvalue()


#: What XML 1.0 allows a document to hold: tab, newline, carriage return and
#: the printable ranges. A name on ext4 or NTFS may hold any byte but `/` and
#: NUL, and one whose bytes are not valid UTF-8 reaches Python as a lone
#: surrogate. ElementTree writes all of them without complaint and the result
#: is a document no parser will open - a worse answer than refusing. They are
#: escaped instead: the name stays readable and the file stays a file.
_OUTSIDE_XML = re.compile("[^\u0009\u000a\u000d\u0020-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


def _label(node: Node) -> str:
    """What a person should see on the node.

    A file is its name. The full path stays in `id` and `value`, because a
    graph drawn with absolute paths for labels is a wall of text in which the
    one part that differs sits at the end of every line.
    """
    if node.type == "file":
        return PurePosixPath(PureWindowsPath(node.value).as_posix()).name or node.value
    return node.value


def _node_labels(node: Node) -> str:
    """The node's type as a graph database spells its labels."""
    return ":" + "".join(part.capitalize() for part in node.type.split("_"))


def _edge_label(kind: str) -> str:
    """The kind as a relationship type: one token, the way a query writes it."""
    return kind.replace(" ", "_").replace("-", "_").upper()


def _data(parent: ElementTree.Element, key: str, value: str) -> None:
    text = _OUTSIDE_XML.sub(lambda found: f"\\u{ord(found.group()):04x}", value)
    ElementTree.SubElement(parent, f"{{{_GRAPHML}}}data", {"key": key}).text = text


def _json(value: Mapping[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
