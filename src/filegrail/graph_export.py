"""GraphML and CSV serialization for an investigation graph."""

from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterable, Mapping
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
    """Serialize one relationship per row, with both endpoints and its evidence.

    An edge list is a table of relationships, so every column has to be a
    property of the relationship in that row. `run` and `coverage` describe the
    scan, not any one edge, and repeating them made them 70% of the file - a
    column identical in every row, which no tool can filter on and every tool
    has to carry. They are written beside the table instead; `--json` has them
    in full. `run` and `coverage` are still accepted so a caller need not know
    which of the two writers it is calling.

    The evidence is given twice on purpose. The flat columns are what a graph
    tool can filter and sort on, and they are exact for the one-evidence edge
    that almost every edge is; `evidence` keeps the whole record, because only
    there does each ground stay joined to its own place, count and time.
    """
    del run, coverage
    nodes = {node.id: node for node in graph.nodes}
    output = io.StringIO(newline="")
    # `source` and `target` are what an importer looks for to find the two ends,
    # and `kind` is what it uses to tell two relationships between one pair
    # apart. Those three names are not free choices.
    fields = (
        "source",
        "source_type",
        "source_label",
        "target",
        "target_type",
        "target_label",
        "kind",
        "label",
        "weight",
        "evidence_count",
        "evidence_source",
        "evidence_place",
        "evidence_category",
        "evidence_match",
        "evidence_rule",
        "evidence_at",
        "evidence",
    )
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for relationship in graph.relationships:
        source = nodes[relationship.source]
        target = nodes[relationship.target]
        found = relationship.evidence
        writer.writerow(
            {
                "source": source.id,
                "source_type": source.type,
                "source_label": _label(source),
                "target": target.id,
                "target_type": target.type,
                "target_label": _label(target),
                "kind": relationship.kind,
                "label": _edge_label(relationship.kind),
                "weight": relationship.count,
                "evidence_count": len(found),
                "evidence_source": _joined(item.source for item in found),
                "evidence_place": _joined(item.place for item in found),
                "evidence_category": _joined(item.category or "" for item in found),
                "evidence_match": _joined(item.match or "" for item in found),
                "evidence_rule": _joined(item.rule or "" for item in found),
                "evidence_at": min((item.at for item in found if item.at), default=""),
                "evidence": json.dumps(
                    [item.to_dict() for item in found],
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            }
        )
    return output.getvalue()


def render_graph_meta(
    run: Mapping[str, object] | None = None,
    coverage: Mapping[str, object] | None = None,
) -> str:
    """What the scan was, for the file written beside an edge list."""
    document: dict[str, object] = {}
    if run is not None:
        document["run"] = run
    if coverage is not None:
        document["coverage"] = coverage
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _joined(values: Iterable[str]) -> str:
    """The distinct values of one evidence field, in the order they were found.

    Almost every edge rests on one ground and this is then that ground. Where
    there are several the column says all of them, because a column that showed
    only the first would read as a complete answer.
    """
    return " | ".join(dict.fromkeys(value for value in values if value))


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
