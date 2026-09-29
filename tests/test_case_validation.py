"""What `--case-jsonld` writes, held against the standard it claims to be.

Reading the JSON back proves only that it is JSON. Whether it is CASE is a
question about shapes in an ontology, and the official validator is the only
thing that can answer it. The failures it catches are exactly the ones a test
of our own would miss: a date written as a bare string, an object without an
identifier, a reference to something that is not in the document. All of those
parse, none of them are valid, and the person who finds out is whoever was
sent the file.

The validator brings rdflib, pySHACL and pandas with it, so it is not a
development dependency and this file is not part of the ordinary test run. It
has a job of its own in CI (`pip install -e ".[dev,case]"`), and it skips where
the validator is absent rather than failing for being unequipped.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from filegrail.caseexport import render_case_jsonld
from filegrail.graph import build_graph
from filegrail.identify import extract
from filegrail.lineage import attach_lineage
from filegrail.models import EvidenceRecord, FileRecord

#: The version the export is written against. Pinned on purpose: the shapes
#: already warn about what 1.6.0 and 2.0.0 will refuse, and a validator that
#: silently moved on would turn a standards change into a mystery failure.
VERSION = "case-1.5.0"

pytestmark = pytest.mark.skipif(
    shutil.which("case_validate") is None,
    reason="the CASE validator is not installed; `pip install -e '.[case]'`",
)


def _corpus() -> list[FileRecord]:
    """One of everything the export has a decision to make about: a file with a
    digest and one without, an origin, a derivable identifier, a person, and a
    pair of renditions, which is the only way to reach a relationship the
    taxonomy calls symmetric and the only way `isDirectional: false` is ever
    written. The shapes that are not exercised are the ones that break."""
    records = [
        FileRecord(
            path="/case/invoice.pdf",
            size=2048,
            mtime="2026-03-30T14:05:00Z",
            sha256="d" * 64,
            evidence=[
                EvidenceRecord(
                    source="browser-download",
                    at="2026-03-29T09:15:00Z",
                    url="https://files.example.org/invoice.pdf",
                    referrer="https://example.org/billing",
                ),
                EvidenceRecord(
                    source="document-metadata",
                    block="pdf-info",
                    fields={"Author": "ann.shaw@example.org"},
                ),
            ],
        ),
        FileRecord(
            path="/case/photo.jpg",
            size=1024,
            mtime="2026-03-30T14:05:00Z",
            evidence=[
                EvidenceRecord(
                    source="device-metadata",
                    block="exif",
                    fields={"Make": "NIKON", "Model": "COOLPIX P6000", "Artist": "Ann Shaw"},
                ),
                EvidenceRecord(source="xmp", fields={"xmpMM:DocumentID": "xmp.did:AAAA1111"}),
            ],
        ),
        FileRecord(
            path="/case/photo.tif",
            size=8192,
            mtime="2026-03-30T14:05:00Z",
            evidence=[
                EvidenceRecord(source="xmp", fields={"xmpMM:DocumentID": "xmp.did:AAAA1111"}),
            ],
        ),
    ]
    attach_lineage(records)
    return records


def test_what_the_export_writes_is_valid_case(tmp_path: Path):
    records = _corpus()
    graph = build_graph(records, extract(records, content=True, metadata=True))
    document = render_case_jsonld(
        graph,
        records,
        root=Path("/case"),
        moment=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        run={"hash": True, "pivots": True},
        case="2026/014",
        examiner="J. Nowak",
    )
    written = tmp_path / "case.json"
    written.write_text(document, encoding="utf-8")

    # Every relationship the corpus can produce has to be in what was checked,
    # or the run proves nothing about the shapes that were not exercised.
    kinds = {edge.kind for edge in graph.relationships}
    assert {
        "has identifier",
        "origin URL",
        "author",
        "email domain",
        "same document",
    } <= kinds

    done = subprocess.run(
        ["case_validate", "--built-version", VERSION, str(written)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert "Conforms: True" in done.stdout, done.stdout or done.stderr


def test_the_document_says_which_tool_made_it_and_from_what(tmp_path: Path):
    """A graph format has nowhere to put this, and it is half of why the export
    is worth writing. It is checked here rather than beside the other export
    tests because what makes it meaningful is that the validator accepts it."""
    records = _corpus()
    graph = build_graph(records, extract(records, content=True, metadata=True))
    document = json.loads(
        render_case_jsonld(
            graph, records, root=Path("/case"), moment="2026-09-23T12:00:00Z", examiner="J. Nowak"
        )
    )

    types = [item["@type"] for item in document["@graph"]]
    assert "uco-tool:AnalyticTool" in types
    assert "case-investigation:InvestigativeAction" in types
    assert "case-investigation:ProvenanceRecord" in types
    assert "case-investigation:Examiner" in types
