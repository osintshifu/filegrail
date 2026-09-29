"""What the files in one scan say about being made from each other.

XMP carries four identifiers for this: the document a file is a rendition of,
the exact bytes it is, the first document in its chain, and the resource it was
derived from. On their own they are opaque strings. Read across a directory they
say which file came from which.
"""

from __future__ import annotations

from pathlib import Path

from filegrail.lineage import (
    COMMON_ANCESTOR,
    DERIVED_FROM,
    DESCENDS_FROM,
    ORIGINAL_OF,
    SAME_DOCUMENT,
    SOURCE_OF,
    attach_lineage,
)
from filegrail.models import EvidenceRecord, FileRecord
from filegrail.report import render_text
from filegrail.theme import Theme

PLAIN = Theme(colour=False, unicode=True, width=88)

DOCUMENT = "xmpMM:DocumentID"
INSTANCE = "xmpMM:InstanceID"
ORIGINAL = "xmpMM:OriginalDocumentID"
FROM_DOCUMENT = "xmpMM:DerivedFrom/stRef:documentID"
FROM_INSTANCE = "xmpMM:DerivedFrom/stRef:instanceID"


def _file(name: str, fields: dict[str, str] | None = None) -> FileRecord:
    record = FileRecord(path=f"/case/{name}", size=100, mtime="2026-08-24T19:00:00Z")
    if fields is not None:
        record.evidence.append(EvidenceRecord(source="xmp", fields=dict(fields)))
    return record


def _relations(record: FileRecord) -> list[tuple[str, tuple[str, ...]]]:
    return [(link.kind, link.others) for link in record.links]


# --- the directed edge -------------------------------------------------------


def test_a_file_naming_its_parent_is_linked_to_it():
    parent = _file("master.jpg", {DOCUMENT: "xmp.did:1111AAAA"})
    child = _file("export.jpg", {DOCUMENT: "xmp.did:2222BBBB", FROM_DOCUMENT: "xmp.did:1111AAAA"})

    attach_lineage([parent, child])

    assert _relations(child) == [(DERIVED_FROM, ("/case/master.jpg",))]


def test_the_parent_learns_what_was_made_from_it():
    """The edge is worth as much read backwards. A master that cannot name its
    own exports leaves the reader to search for them by hand."""
    parent = _file("master.jpg", {DOCUMENT: "xmp.did:1111AAAA"})
    child = _file("export.jpg", {DOCUMENT: "xmp.did:2222BBBB", FROM_DOCUMENT: "xmp.did:1111AAAA"})

    attach_lineage([parent, child])

    assert _relations(parent) == [(SOURCE_OF, ("/case/export.jpg",))]


def test_both_halves_of_one_reference_do_not_make_two_links():
    """DerivedFrom names the bytes and the work at once. Two links would say
    one thing twice."""
    parent = _file("master.jpg", {DOCUMENT: "xmp.did:1111AAAA", INSTANCE: "xmp.iid:1111AAAA01"})
    child = _file(
        "export.jpg",
        {
            DOCUMENT: "xmp.did:2222BBBB",
            FROM_DOCUMENT: "xmp.did:1111AAAA",
            FROM_INSTANCE: "xmp.iid:1111AAAA01",
        },
    )

    attach_lineage([parent, child])

    assert _relations(child) == [(DERIVED_FROM, ("/case/master.jpg",))]


def test_an_instance_reference_is_not_matched_against_a_document_id():
    """PowerPoint writes one uuid as both the document and the instance. A
    matcher that compared across the two would make every export of it an
    instance of the others."""
    parent = _file("master.pdf", {DOCUMENT: "uuid:1111AAAA", INSTANCE: "uuid:2222BBBB"})
    child = _file("copy.pdf", {DOCUMENT: "uuid:3333CCCC", FROM_INSTANCE: "uuid:1111AAAA"})

    attach_lineage([parent, child])

    assert child.links == []


# --- the undirected groups ---------------------------------------------------


def test_two_renditions_of_one_document_are_recognised():
    web = _file("web.jpg", {DOCUMENT: "xmp.did:1111AAAA", INSTANCE: "xmp.iid:1111AAAA01"})
    print_ready = _file("print.tif", {DOCUMENT: "xmp.did:1111AAAA", INSTANCE: "xmp.iid:1111AAAA02"})

    attach_lineage([web, print_ready])

    assert _relations(web) == [(SAME_DOCUMENT, ("/case/print.tif",))]


def test_the_first_document_of_a_chain_is_named_as_its_original():
    """`shares an original` is what two descendants have in common. Saying it of
    a pair where one of them *is* the original understates the only thing about
    that pair worth knowing."""
    shoot = _file("shoot-raw.jpg", {DOCUMENT: "xmp.did:1111AAAA", ORIGINAL: "xmp.did:1111AAAA"})
    export = _file("web-export.jpg", {DOCUMENT: "xmp.did:3333CCCC", ORIGINAL: "xmp.did:1111AAAA"})

    attach_lineage([shoot, export])

    assert _relations(export) == [(DESCENDS_FROM, ("/case/shoot-raw.jpg",))]
    assert _relations(shoot) == [(ORIGINAL_OF, ("/case/web-export.jpg",))]


def test_a_shared_original_is_not_called_a_derivation():
    """A LibreOffice template drags its whole XMP block into every document made
    from it, so two files can share an original and share nothing else. Wording
    that as `made from` would assert a lineage that never happened."""
    offer = _file("offer.pdf", {DOCUMENT: "xmp.did:1111AAAA", ORIGINAL: "xmp.did:9999ZZZZ"})
    invoice = _file("invoice.pdf", {DOCUMENT: "xmp.did:2222BBBB", ORIGINAL: "xmp.did:9999ZZZZ"})

    attach_lineage([offer, invoice])

    assert _relations(offer) == [(COMMON_ANCESTOR, ("/case/invoice.pdf",))]


def test_the_strongest_relation_is_the_only_one_reported():
    """Two files can be joined more than one way. Printing `shares an original`
    beside `was made from` says the weaker of the two for no reason."""
    parent = _file("master.jpg", {DOCUMENT: "xmp.did:1111AAAA", ORIGINAL: "xmp.did:9999ZZZZ"})
    child = _file(
        "export.jpg",
        {
            DOCUMENT: "xmp.did:2222BBBB",
            ORIGINAL: "xmp.did:9999ZZZZ",
            FROM_DOCUMENT: "xmp.did:1111AAAA",
        },
    )

    attach_lineage([parent, child])

    assert [category for category, _ in _relations(child)] == [DERIVED_FROM]


def test_a_crowd_is_counted_rather_than_named():
    """One template can sit under a whole directory. Pairing every file with
    every other is a square number of links about a relation nobody would call
    a lineage - and the count is the part worth reading anyway."""
    records = [
        _file(f"doc{n}.pdf", {DOCUMENT: f"xmp.did:document{n:04}", ORIGINAL: "xmp.did:9999ZZZZ"})
        for n in range(20)
    ]

    attach_lineage(records)

    link = records[0].links[0]
    assert link.kind == COMMON_ANCESTOR
    assert link.count == 19
    assert link.others == ()


# --- files with nothing to relate --------------------------------------------


def test_a_file_is_not_linked_to_itself():
    """Writers do point DerivedFrom at the file's own document. Whatever that
    means, it is not a second file."""
    only = _file(
        "solo.jpg",
        {
            DOCUMENT: "xmp.did:1111AAAA",
            ORIGINAL: "xmp.did:1111AAAA",
            FROM_DOCUMENT: "xmp.did:1111AAAA",
        },
    )

    attach_lineage([only])

    assert only.links == []


def test_a_file_without_an_xmp_packet_is_left_alone():
    plain = _file("scan.tif")
    other = _file("master.jpg", {DOCUMENT: "xmp.did:1111AAAA"})

    attach_lineage([plain, other])

    assert plain.links == []


def test_a_placeholder_identifier_joins_nothing():
    """A null uuid is what a writer emits when it has nothing to say. Treating
    it as an identity would make every such file a rendition of every other."""
    a = _file("a.pdf", {DOCUMENT: "uuid:00000000-0000-0000-0000-000000000000"})
    b = _file("b.pdf", {DOCUMENT: "uuid:00000000-0000-0000-0000-000000000000"})

    attach_lineage([a, b])

    assert a.links == []
    assert b.links == []


# --- reaching the reader -----------------------------------------------------


def test_a_link_reaches_the_report():
    """A relation the tool worked out and did not print is a relation nobody
    has. It goes in the entry, beside the claims it came from."""
    parent = _file("master.jpg", {DOCUMENT: "xmp.did:1111AAAA"})
    child = _file("export.jpg", {DOCUMENT: "xmp.did:2222BBBB", FROM_DOCUMENT: "xmp.did:1111AAAA"})
    attach_lineage([parent, child])

    output = render_text([parent, child], Path("/case"), theme=PLAIN)

    assert "derived from" in output
    assert "source of" in output


def test_a_crowded_link_says_how_many_rather_than_nothing():
    records = [
        _file(f"doc{n}.pdf", {DOCUMENT: f"xmp.did:document{n:04}", ORIGINAL: "xmp.did:9999ZZZZ"})
        for n in range(20)
    ]
    attach_lineage(records)

    output = render_text(records, Path("/case"), theme=PLAIN)

    assert "common ancestor" in output
    assert "19 files" in output


def test_a_link_reaches_the_json():
    parent = _file("master.jpg", {DOCUMENT: "xmp.did:1111AAAA"})
    child = _file("export.jpg", {DOCUMENT: "xmp.did:2222BBBB", FROM_DOCUMENT: "xmp.did:1111AAAA"})
    attach_lineage([parent, child])

    assert child.to_dict()["links"] == [
        {"kind": DERIVED_FROM, "others": ["/case/master.jpg"], "count": 1}
    ]
