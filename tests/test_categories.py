"""Three categories of evidence, and typed findings rather than prose.

`origin` says how or from where the file reached this environment. `activity`
says something here handled it afterwards, which is not the same thing and must
not be presented as though it were. `metadata` says what the file records about
its own earlier life.

Findings carry a kind as well as a sentence, because a consumer reading the JSON
should not have to pattern-match English to tell a source conflict from a
timeline conflict.
"""

from __future__ import annotations

import ast
from pathlib import Path

from filegrail.correlate import (
    CORROBORATION,
    SIZE_MISMATCH,
    SOURCE_CONFLICT,
    TIMELINE_CONFLICT,
    WEAK_MATCH,
    correlate,
)
from filegrail.models import (
    ACTIVITY,
    BLOCK_LABELS,
    FILENAME,
    METADATA,
    ORIGIN,
    SOURCE_PRIORITY,
    EvidenceRecord,
    FileRecord,
    category,
)
from filegrail.sources import embedded


def _record(*origins: EvidenceRecord) -> FileRecord:
    record = FileRecord(path="/case/a.pdf", size=4096, mtime="2026-08-24T19:00:00Z")
    record.evidence.extend(origins)
    return record


# --- the three kinds ---------------------------------------------------------


def test_a_download_is_an_origin_record():
    assert category(EvidenceRecord(source="browser-download", url="https://x.org/a")) == ORIGIN


def test_exif_is_metadata():
    assert category(EvidenceRecord(source="device-metadata", tool="Canon")) == METADATA


def test_the_recent_documents_list_is_activity_not_origin():
    """An application opening a file did not put it there."""
    assert category(EvidenceRecord(source="recent-documents", tool="GIMP")) == ACTIVITY


def test_a_fetch_command_is_an_origin_record():
    origin = EvidenceRecord(
        source="shell-history", tool="curl", command="curl -o a.pdf https://x.org/"
    )

    assert category(origin) == ORIGIN


def test_a_command_that_merely_names_the_file_is_activity():
    """`cat a.pdf` proves contact. It does not say where the bytes came from."""
    origin = EvidenceRecord(source="shell-history", tool="cat", command="cat a.pdf")

    assert category(origin) == ACTIVITY


def test_every_source_has_a_kind():
    for source in SOURCE_PRIORITY:
        assert category(EvidenceRecord(source=source)) in (ORIGIN, ACTIVITY, METADATA)


# --- typed findings ----------------------------------------------------------


def _download(url: str, **extra) -> EvidenceRecord:
    return EvidenceRecord(source="browser-download", url=url, tool="firefox", **extra)


def _kinds(verdict) -> set[str]:
    return {finding.kind for finding in verdict.findings}


def test_different_hosts_are_a_source_conflict():
    verdict = correlate(
        _record(
            _download("https://example.com/a.pdf"),
            EvidenceRecord(
                source="windows-zone-identifier", url="https://mirror.example.net/a.pdf"
            ),
        )
    )

    assert SOURCE_CONFLICT in _kinds(verdict)
    assert TIMELINE_CONFLICT not in _kinds(verdict)


def test_creation_after_arrival_is_a_timeline_conflict():
    verdict = correlate(
        _record(
            _download("https://example.org/a.pdf", at="2026-08-01T10:00:00Z"),
            EvidenceRecord(source="document-metadata", tool="Word", at="2026-08-24T19:02:11Z"),
        )
    )

    assert TIMELINE_CONFLICT in _kinds(verdict)
    assert SOURCE_CONFLICT not in _kinds(verdict)


def test_the_two_conflicts_are_independent():
    """A file can have both, and they are different problems."""
    verdict = correlate(
        _record(
            _download("https://example.com/a.pdf", at="2026-08-01T10:00:00Z"),
            EvidenceRecord(
                source="windows-zone-identifier", url="https://mirror.example.net/a.pdf"
            ),
            EvidenceRecord(source="document-metadata", tool="Word", at="2026-08-24T19:02:11Z"),
        )
    )

    assert {SOURCE_CONFLICT, TIMELINE_CONFLICT} <= _kinds(verdict)


def test_agreement_is_typed_too():
    verdict = correlate(
        _record(
            _download("https://example.org/a.pdf"),
            EvidenceRecord(source="windows-zone-identifier", url="https://example.org/a.pdf"),
        )
    )

    assert CORROBORATION in _kinds(verdict)


def test_a_name_match_with_a_wrong_size_is_typed():
    origin = _download("https://example.org/a.pdf", bytes=9999)
    origin.match = FILENAME
    origin.bytes = 9999

    assert SIZE_MISMATCH in _kinds(correlate(_record(origin)))


def test_a_bare_name_match_is_typed_as_weak():
    origin = _download("https://example.org/a.pdf")
    origin.match = FILENAME

    assert WEAK_MATCH in _kinds(correlate(_record(origin)))


def test_activity_records_never_create_a_source_conflict():
    """Two applications opening a file is not a disagreement about anything."""
    verdict = correlate(
        _record(
            EvidenceRecord(source="recent-documents", tool="GIMP", note="opened by GIMP"),
            EvidenceRecord(
                source="recent-documents", tool="Eye of GNOME", note="opened by Eye of GNOME"
            ),
        )
    )

    assert SOURCE_CONFLICT not in _kinds(verdict)


def test_json_carries_the_kind_and_the_sentence():
    verdict = correlate(
        _record(
            _download("https://example.com/a.pdf"),
            EvidenceRecord(
                source="windows-zone-identifier", url="https://mirror.example.net/a.pdf"
            ),
        )
    )

    payload = verdict.to_dict()
    assert payload["state"]
    assert all({"kind", "text"} <= set(finding) for finding in payload["findings"])


def test_every_block_a_reader_declares_has_a_label():
    """A block with no label reads as `document metadata`, which is the very
    thing naming the block was for. The dispatcher is read rather than a list
    kept beside it, because a list beside it is the thing that goes stale."""
    source = Path(embedded.__file__).read_text(encoding="utf-8")
    declared = {
        keyword.value.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "block" and isinstance(keyword.value, ast.Constant)
    }

    assert declared, "no reader declares a block; the walk found nothing to check"
    assert declared <= set(BLOCK_LABELS), sorted(declared - set(BLOCK_LABELS))
