"""The evidence graph as CASE/UCO JSON-LD.

CASE is the exchange format digital forensic tools use to hand results to one
another, built on the UCO ontology. It is the only format `filegrail` writes
that has a place for the two things this tool is about: **evidence attached to
a relationship**, and **a record of which tool produced what, when**. GraphML
and a CSV edge list can carry both, but only as text no reader is obliged to
understand; here they are the model.

A relationship in UCO is an object with its own identifier rather than a line
between two nodes, and an object takes facets. That is what makes the export
possible without flattening anything: a relationship supported by two
independent grounds stays one relationship carrying two facets, instead of
becoming two relationships or losing the grounds along the way.

Nothing here needs a JSON-LD or RDF library. A document is valid JSON-LD by
construction when it is a map holding `@context` and `@graph`, and a context
written inline is never fetched - which also means this export makes no
network request, like everything else in the tool.

**Identifiers are deterministic, and they claim no more than the evidence
supports.** A file with a SHA-256 is identified by its content, so two scans
anywhere agree on it. A file without one is identified by where it was found,
which is a claim about this target and not about the world. A name alone is
never an identity: two files called `report.pdf` are two files.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from . import __version__
from .graph import DIRECTED, TAXONOMY, Graph, Node, Relationship
from .models import FileRecord

#: The namespaces a reader needs to make sense of this document. They are
#: written into the file because CASE publishes no context to point at, and a
#: context given as a map is never dereferenced - so the export stays offline.
CONTEXT: dict[str, str] = {
    "kb": "urn:uuid:",
    "case-investigation": "https://ontology.caseontology.org/case/investigation/",
    "uco-action": "https://ontology.unifiedcyberontology.org/uco/action/",
    "uco-core": "https://ontology.unifiedcyberontology.org/uco/core/",
    "uco-identity": "https://ontology.unifiedcyberontology.org/uco/identity/",
    "uco-observable": "https://ontology.unifiedcyberontology.org/uco/observable/",
    "uco-tool": "https://ontology.unifiedcyberontology.org/uco/tool/",
    "uco-types": "https://ontology.unifiedcyberontology.org/uco/types/",
    "fg": "https://github.com/osintshifu/filegrail/ns#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
}

#: The seed every identifier in this export is derived from. Version 5 UUIDs
#: are a function of their input, so the same material scanned twice produces
#: the same document, and two scans that met the same address agree on it
#: without having to be told.
NAMESPACE = uuid.UUID("f11e9247-0000-5000-8000-000000000001")

#: What UCO calls the things `filegrail` finds. A type that is not here is
#: still exported, as a plain observable that carries what `filegrail` called
#: it: leaving it out would lose evidence, and guessing a class would state
#: something the tool did not find.
_OBSERVABLE: dict[str, tuple[str, str, str]] = {
    "file": ("File", "", ""),
    "url": ("URL", "URLFacet", "fullValue"),
    "domain": ("DomainName", "DomainNameFacet", "value"),
    "email": ("EmailAddress", "EmailAddressFacet", "addressValue"),
    "ipv4": ("IPv4Address", "IPv4AddressFacet", "addressValue"),
    "ipv6": ("IPv6Address", "IPv6AddressFacet", "addressValue"),
    "mac": ("MACAddress", "MACAddressFacet", "value"),
    "device": ("Device", "DeviceFacet", "serialNumber"),
    "lens": ("Device", "DeviceFacet", "serialNumber"),
    "camera_model": ("Device", "DeviceFacet", "model"),
}

#: The CASE vocabulary word for a relationship `filegrail` names in its own
#: words. Only where the two mean the same thing; the rest keep their own name,
#: which `kindOfRelationship` allows and which is better than a near-synonym.
_KIND: dict[str, str] = {
    "origin URL": "Downloaded_From",
    "referrer": "Downloaded_From",
    "member of archive": "Contained_Within",
    "embedded in": "Contained_Within",
    "listed in torrent": "Contained_Within",
    "derived from": "Derived_From",
}


def render_case_jsonld(
    graph: Graph,
    records: list[FileRecord],
    *,
    root: Path,
    moment: str,
    run: Mapping[str, object] | None = None,
    case: str | None = None,
    examiner: str | None = None,
) -> str:
    """The graph, the files behind it and the run that produced them, as CASE."""
    hashes = {record.path: record.sha256 for record in records if record.sha256}
    sizes = {record.path: record.size for record in records}
    identity = _Identity(root, hashes)
    # Every reference has to reach an object that is in this document, so what
    # each node is called is settled once and then looked up. A file is named
    # by its content where that is known, which is not what its graph key says.
    identity.settle(graph.nodes)

    objects: list[dict[str, Any]] = []
    observable: dict[str, bool] = {}
    for node in graph.nodes:
        objects.extend(_node(node, identity, sizes, hashes))
        observable[node.id] = _is_observable(node)

    for relationship in graph.relationships:
        objects.append(_relationship(relationship, identity, observable))

    objects.extend(_provenance(graph, identity, moment, run, case, examiner))
    return json.dumps({"@context": CONTEXT, "@graph": objects}, ensure_ascii=False, indent=2)


class _Identity:
    """What each thing in the export is called, and how strong that claim is."""

    def __init__(self, root: Path, hashes: Mapping[str, str]) -> None:
        self._root = str(root)
        self._hashes = hashes
        self._settled: dict[str, str] = {}

    def settle(self, nodes: tuple[Node, ...]) -> None:
        self._settled = {node.id: self.of(node) for node in nodes}

    def node(self, key: str) -> str:
        """What the node with this graph key ended up being called."""
        return self._settled.get(key) or self.named(key)

    def of(self, node: Node) -> str:
        """A file by its content where that is known, by where it was found
        otherwise. A path is a claim about this target, not about the world, so
        it is scoped to the target it was read from."""
        if node.type != "file":
            return self.named(node.id)
        digest = self._hashes.get(node.value)
        if digest:
            return self.named(f"sha256:{digest}")
        return self.named(f"path:{self._root}|{node.value}")

    def named(self, key: str) -> str:
        return f"kb:{uuid.uuid5(NAMESPACE, key)}"

    def part(self, owner: str, part: str) -> str:
        """A facet or a record that belongs to one thing and to nothing else."""
        return self.named(f"{owner}#{part}")


def _is_observable(node: Node) -> bool:
    """Whether UCO would call this an observable. A person is not one: an
    identity is something asserted about the world, not something read off a
    disk, and a relationship touching one has to say so."""
    return node.type != "person"


def _node(
    node: Node, identity: _Identity, sizes: Mapping[str, int], hashes: Mapping[str, str]
) -> list[dict[str, Any]]:
    """One thing the graph knows about, with the facets that describe it."""
    at = identity.of(node)
    if node.type == "person":
        return [
            {
                "@id": at,
                "@type": "uco-identity:Identity",
                "uco-core:name": node.value,
                "fg:normalized": node.normalized or node.value,
            }
        ]

    if node.type == "file":
        return _file(node, at, identity, sizes, hashes)

    name, facet, field = _OBSERVABLE.get(node.type, ("ObservableObject", "", ""))
    body: dict[str, Any] = {"@id": at, "@type": f"uco-observable:{name}", "fg:type": node.type}
    if node.normalized:
        body["fg:normalized"] = node.normalized
    if facet:
        body["uco-core:hasFacet"] = {
            "@id": identity.part(node.id, facet),
            "@type": f"uco-observable:{facet}",
            f"uco-observable:{field}": node.value,
        }
    else:
        # Nothing in UCO says what this is, so what it holds is said in the
        # tool's own words rather than fitted into a class that means
        # something else.
        body["fg:value"] = node.value
    return [body]


def _file(
    node: Node,
    at: str,
    identity: _Identity,
    sizes: Mapping[str, int],
    hashes: Mapping[str, str],
) -> list[dict[str, Any]]:
    """A file, its name and path, and its content where a digest was taken."""
    path = node.value
    name = PurePosixPath(PureWindowsPath(path).as_posix()).name or path
    facets: list[dict[str, Any]] = [
        {
            "@id": identity.part(node.id, "FileFacet"),
            "@type": "uco-observable:FileFacet",
            "uco-observable:fileName": name,
            "uco-observable:filePath": path,
        }
    ]
    size = sizes.get(path)
    digest = hashes.get(path)
    if size is not None or digest:
        content: dict[str, Any] = {
            "@id": identity.part(node.id, "ContentDataFacet"),
            "@type": "uco-observable:ContentDataFacet",
        }
        if size is not None:
            content["uco-observable:sizeInBytes"] = size
        if digest:
            content["uco-observable:hash"] = {
                "@id": identity.part(node.id, "Hash"),
                "@type": "uco-types:Hash",
                # A plain string, not the vocabulary type the older examples
                # use: UCO 1.4.0 asked for this and 2.0.0 will refuse anything
                # else.
                "uco-types:hashMethod": "SHA256",
                "uco-types:hashValue": {"@type": "xsd:hexBinary", "@value": digest},
            }
        facets.append(content)
    return [{"@id": at, "@type": "uco-observable:File", "uco-core:hasFacet": facets}]


def _relationship(
    relationship: Relationship, identity: _Identity, observable: Mapping[str, bool]
) -> dict[str, Any]:
    """One relationship, carrying every ground it rests on as its own facet.

    This is the whole reason the export is worth writing. A relationship is an
    object here, so two independent grounds stay two facets of one claim - the
    shape `filegrail` already has, kept rather than flattened.
    """
    both = observable.get(relationship.source, False) and observable.get(relationship.target, False)
    key = f"{relationship.source}|{relationship.kind}|{relationship.target}"
    body: dict[str, Any] = {
        "@id": identity.named(f"relationship:{key}"),
        "@type": "uco-observable:ObservableRelationship" if both else "uco-core:Relationship",
        "uco-core:source": {"@id": identity.node(relationship.source)},
        "uco-core:target": {"@id": identity.node(relationship.target)},
        "uco-core:kindOfRelationship": _KIND.get(relationship.kind, relationship.kind),
        # What the taxonomy says, not a constant. Two of these kinds read the
        # same from either end, and UCO has this field so that a reader is
        # told which - a rendition of a document is not its parent.
        "uco-core:isDirectional": TAXONOMY[relationship.kind].direction == DIRECTED,
        "fg:kind": relationship.kind,
        "fg:occurrences": relationship.count,
        "uco-core:hasFacet": [
            _evidence(relationship, item, position, identity)
            for position, item in enumerate(relationship.evidence)
        ],
    }
    times = sorted(item.at for item in relationship.evidence if item.at)
    if times:
        body["uco-core:startTime"] = {"@type": "xsd:dateTime", "@value": times[0]}
        body["uco-core:endTime"] = {"@type": "xsd:dateTime", "@value": times[-1]}
    return body


def _evidence(
    relationship: Relationship, item: Any, position: int, identity: _Identity
) -> dict[str, Any]:
    """One ground, in the tool's own vocabulary because UCO has none for it.

    UCO shapes are open, so terms of our own sit beside the standard ones and
    the document stays valid CASE. A reader who knows only UCO still gets the
    relationship; a reader who knows `filegrail` also gets why it is there.
    """
    key = f"{relationship.source}|{relationship.kind}|{relationship.target}"
    body: dict[str, Any] = {
        "@id": identity.named(f"evidence:{key}#{position}"),
        # Two types: ours says what it holds, `uco-core:Facet` is what makes it
        # a facet at all. Without the second a validator refuses it.
        "@type": ["fg:EvidenceFacet", "uco-core:Facet"],
        "fg:source": item.source,
        "fg:place": item.place,
        "fg:corpus": item.corpus,
        "fg:occurrences": item.count,
    }
    if item.category is not None:
        body["fg:category"] = item.category
    if item.match is not None:
        body["fg:matchBasis"] = item.match
    if item.at is not None:
        body["fg:at"] = {"@type": "xsd:dateTime", "@value": item.at}
    if item.rule is not None:
        # Not observed anywhere: worked out from the value. The rule and what
        # it was applied to are what let a reader check it.
        body["fg:derivedByRule"] = item.rule
        body["fg:premise"] = item.premise or ""
    return body


def _provenance(
    graph: Graph,
    identity: _Identity,
    moment: str,
    run: Mapping[str, object] | None,
    case: str | None,
    examiner: str | None,
) -> list[dict[str, Any]]:
    """Which tool produced this, from what, and when.

    The part a graph format has nowhere to put. It is also what makes the
    export readable as provenance by anything speaking PROV-O, because the
    published converters build that from exactly these three objects.
    """
    tool = identity.named("tool:filegrail")
    action = identity.named(f"action:scan|{moment}")
    record = identity.named(f"provenance:{moment}")
    examined = [{"@id": identity.of(node)} for node in graph.nodes if node.type == "file"]

    objects: list[dict[str, Any]] = [
        {
            "@id": tool,
            "@type": "uco-tool:AnalyticTool",
            "uco-core:name": "filegrail",
            "uco-tool:version": __version__,
            "uco-tool:toolType": "Analysis",
        },
        {
            "@id": action,
            "@type": "case-investigation:InvestigativeAction",
            "uco-core:name": "scan",
            "uco-action:startTime": {"@type": "xsd:dateTime", "@value": moment},
            "uco-action:instrument": {"@id": tool},
            "uco-action:result": {"@id": record},
            "fg:options": json.dumps(run, ensure_ascii=False, sort_keys=True) if run else "",
        },
        {
            "@id": record,
            "@type": "case-investigation:ProvenanceRecord",
            "uco-core:object": examined,
        },
    ]
    if case:
        objects[2]["case-investigation:exhibitNumber"] = case
    if examiner:
        who = identity.named(f"examiner:{examiner}")
        objects.append(
            {"@id": who, "@type": "case-investigation:Examiner", "uco-core:name": examiner}
        )
        objects[1]["uco-action:performer"] = {"@id": who}
    return objects
