"""Identifiers pulled out of what a scan read.

The corpus is what files record about themselves - an author line, a company, a
template path, a producing URL, a GPS fix - which is where the identifiers a
document body never mentions actually live. Document text is the second corpus,
off unless asked for, and the tests at the end of this file are about keeping
the two apart.
"""

from __future__ import annotations

import json
from pathlib import Path

from filegrail.identify import (
    PLACE,
    extract,
    find_coordinates,
    normalize_domain,
    normalize_url,
)
from filegrail.models import EvidenceRecord, FileRecord
from filegrail.report import render_json, render_text
from filegrail.theme import Theme

PLAIN = Theme(colour=False, unicode=False, width=88)


def _record(name: str, **origin) -> FileRecord:
    record = FileRecord(path=f"/case/{name}", size=1, mtime="2026-08-24T19:00:00Z")
    record.evidence.append(EvidenceRecord(**origin))
    return record


# --- the ported detectors ----------------------------------------------------


def test_an_unknown_tld_is_not_a_domain():
    assert normalize_domain("example.org") == "example.org"
    assert normalize_domain("report.finaldraft") is None


def test_a_url_normalises_to_scheme_host_path():
    assert normalize_url("https://Example.ORG/a/b/?q=1") == (
        "https://example.org/a/b?q=1",
        "example.org",
    )


def test_a_malformed_port_does_not_raise():
    assert normalize_url("http://localhost:1420$") is None


def test_a_bare_decimal_pair_is_not_a_coordinate():
    """An SVG path and a version tuple look exactly like one."""
    assert find_coordinates("43.467448, 11.885127") == []


def test_a_hemisphere_letter_makes_it_a_coordinate():
    found = find_coordinates("43.467448 N, 11.885127 E")

    assert len(found) == 1
    assert round(found[0][1], 4) == 43.4674


def test_null_island_is_rejected():
    assert find_coordinates("0.0 N, 0.0 E") == []


# --- over a scan's own metadata ---------------------------------------------


def test_an_email_in_a_document_author_is_found():
    records = [_record("report.pdf", source="document-metadata", fields={"Author": "a@b.org"})]

    found = extract(records)

    assert [(i.type, i.normalized) for i in found if i.type == "email"] == [("email", "a@b.org")]


def test_the_field_it_came_from_is_recorded():
    """An identifier without its source is a lead nobody can check."""
    records = [_record("report.pdf", source="document-metadata", fields={"Author": "a@b.org"})]

    email = next(i for i in extract(records) if i.type == "email")

    assert "report.pdf" in email.where[0]
    assert "Author" in email.where[0]


def test_the_same_value_across_files_is_one_identifier():
    records = [
        _record("a.pdf", source="document-metadata", fields={"Author": "a@b.org"}),
        _record("b.pdf", source="document-metadata", fields={"creator": "A@B.ORG"}),
    ]

    email = next(i for i in extract(records) if i.type == "email")

    assert email.files == 2
    assert email.count == 2


def test_a_url_origin_yields_its_domain():
    records = [_record("x.zip", source="browser-download", url="https://portal.example.org/a")]

    kinds = {i.type for i in extract(records)}

    assert "url" in kinds
    assert "domain" in kinds


def test_a_command_is_searched_too():
    records = [
        _record("r.csv", source="shell-history", command="curl -o r.csv https://api.example.org/x")
    ]

    # The full host, not the registrable domain: a subdomain is a pivot in its
    # own right and can always be truncated later.
    assert any(i.normalized == "api.example.org" for i in extract(records))


def test_a_private_address_is_flagged():
    records = [_record("log.txt", source="document-metadata", fields={"Host": "192.168.1.10"})]

    address = next(i for i in extract(records) if i.type == "ipv4")

    assert address.private is True


def test_a_version_string_is_not_an_address():
    records = [_record("a.pdf", source="document-metadata", fields={"Producer": "Tool v1.2.3.4"})]

    assert not [i for i in extract(records) if i.type == "ipv4"]


def test_a_version_in_a_software_field_is_not_an_address():
    """`LibreOffice/24.2.7.2` is the single most common string in this corpus,
    and nothing about its shape distinguishes it from an address - only the
    field it sits in does."""
    records = [
        _record("a.odt", source="document-metadata", tool="LibreOffice/24.2.7.2$Linux_X86_64"),
        _record("b.pdf", source="document-metadata", fields={"Producer": "LibreOffice 25.2.3.2"}),
    ]

    assert not [i for i in extract(records) if i.type == "ipv4"]


def test_a_build_hash_in_a_software_field_is_not_evidence():
    records = [
        _record(
            "a.ods",
            source="document-metadata",
            tool="LibreOffice_project/c838ef25c16710f8838b1faec480ebba495259d0",
        )
    ]

    assert not [i for i in extract(records) if i.type == "sha1"]


def test_an_address_in_an_ordinary_field_is_still_found():
    """The suppression is per field, not global."""
    records = [_record("log.txt", source="document-metadata", fields={"Host": "203.0.113.7"})]

    assert [i.normalized for i in extract(records) if i.type == "ipv4"] == ["203.0.113.7"]


def test_nothing_found_is_an_empty_list():
    assert extract([_record("a.txt", source="filesystem")]) == []


# --- through the report ------------------------------------------------------


def test_the_identifier_section_is_absent_unless_asked_for():
    """The field itself is on screen by default; the cross-file roll-up is not."""
    records = [_record("report.pdf", source="document-metadata", fields={"Author": "a@b.org"})]

    assert "identifiers" not in render_text(records, Path("/case"), theme=PLAIN)


def test_the_report_lists_them_on_request():
    records = [_record("report.pdf", source="document-metadata", fields={"Author": "a@b.org"})]

    output = render_text(records, Path("/case"), theme=PLAIN, identify=True)

    assert "a@b.org" in output
    assert "EMAILS" in output


def test_json_carries_them_on_request():
    records = [_record("report.pdf", source="document-metadata", fields={"Author": "a@b.org"})]

    payload = json.loads(render_json(records, Path("/case"), identify=True))

    emails = [i for i in payload["identifiers"] if i["type"] == "email"]
    assert emails[0]["normalized"] == "a@b.org"
    assert emails[0]["where"] == ["report.pdf · document metadata · Author"]


def test_json_omits_them_otherwise():
    records = [_record("report.pdf", source="document-metadata", fields={"Author": "a@b.org"})]

    assert "identifiers" not in json.loads(render_json(records, Path("/case")))


def test_a_namespaced_software_field_is_still_a_software_field():
    """XMP names the same property `pdf:Producer`, and adds version fields of
    its own. A dotted quad is no more an address for having a namespace in front
    of the field it sits in."""
    records = [
        _record("a.pdf", source="xmp", fields={"pdf:Producer": "LibreOffice 25.2.3.2"}),
        _record("b.jpg", source="xmp", fields={"exif:GPSVersionID": "2.2.0.0"}),
    ]

    assert not [entry for entry in extract(records) if entry.type == "ipv4"]


def test_a_message_id_is_not_offered_as_an_address():
    """RFC 5322 builds a message id the same shape as a mailbox, so it matches
    every test for one. Nobody can write to it, and a lead nobody can follow is
    worse than no lead - the field name is known here, so it can be told."""
    record = FileRecord(path="/case/note.eml", size=10, mtime="")
    record.evidence.append(
        EvidenceRecord(
            source="email-header",
            fields={
                "Message-ID": "<20190304182228.7ttQ1a@example.com>",
                "From": "Jan Kowalski <jan@example.com>",
            },
        )
    )

    found = {(identifier.type, identifier.normalized) for identifier in extract([record])}

    assert ("email", "jan@example.com") in found
    assert not [value for kind, value in found if kind == "email" and "7ttq1a" in value]


# --- the second corpus --------------------------------------------------------
#
# `--content` widens what is searched from what files record about themselves to
# what they say. The two are kept apart on every entry: prose is an order of
# magnitude noisier than a property field, and a reader has to be able to tell a
# name somebody typed into a letter from a name a download record carried.


def _document(tmp_path: Path, text: str, name: str = "letter.txt", **origin: object) -> FileRecord:
    """A real file on disk, because reading content means opening it."""
    written = tmp_path / name
    written.write_text(text, encoding="utf-8")
    record = FileRecord(
        path=str(written), size=written.stat().st_size, mtime="2026-08-24T19:00:00Z"
    )
    if origin:
        record.evidence.append(EvidenceRecord(**origin))
    return record


def test_the_corpus_is_still_only_metadata_unless_asked(tmp_path: Path):
    """Every existing scan pays nothing for this and reports nothing from it."""
    record = _document(tmp_path, "write to ann.shaw@acme-legal.example", source="document-metadata")

    assert extract([record]) == []


def test_content_widens_the_corpus_to_what_the_document_says(tmp_path: Path):
    record = _document(tmp_path, "write to ann.shaw@acme-legal.example", source="document-metadata")

    found = extract([record], content=True)

    assert [entry.normalized for entry in found if entry.type == "email"] == [
        "ann.shaw@acme-legal.example"
    ]
    assert [entry.corpora for entry in found if entry.type == "email"] == [{"content"}]


def test_a_value_from_a_document_says_where_in_the_document_it_was(tmp_path: Path):
    """An identifier reported as `notes.txt` sends somebody back to search the
    file. One reported as `notes.txt - content - line 3` does not: it names the
    file, what read it, and where inside it the value was."""
    record = _document(
        tmp_path,
        "nothing here\nnor here\nwrite to ann.shaw@acme-legal.example\n",
        name="notes.txt",
        source="document-metadata",
    )

    email = next(e for e in extract([record], content=True) if e.type == "email")

    assert email.where == [f"notes.txt{PLACE}content{PLACE}line 3"]


def test_a_value_written_in_a_document_and_recorded_about_it_says_both(tmp_path: Path):
    """Two separate acts put it there, and neither half says that alone."""
    record = _document(
        tmp_path,
        "write to ann.shaw@acme-legal.example",
        source="document-metadata",
        fields={"Author": "ann.shaw@acme-legal.example"},
    )

    email = next(e for e in extract([record], content=True) if e.type == "email")

    assert email.corpora == {"metadata", "content"}
    assert email.count == 2


def test_a_value_the_document_names_and_the_arrival_record_names_is_marked(tmp_path: Path):
    """The whole reason for reading content: the body and the download agree."""
    record = _document(
        tmp_path,
        "invoice from acme-legal.example",
        source="browser-download",
        url="https://acme-legal.example/invoice.pdf",
    )

    found = extract([record], content=True)
    domain = next(entry for entry in found if entry.normalized == "acme-legal.example")

    assert domain.acquired is True
    assert domain.corpora == {"metadata", "content"}


def test_a_value_only_a_document_claims_about_itself_is_not_an_arrival(tmp_path: Path):
    """A metadata field travelled with the bytes; it does not say they arrived."""
    record = _document(
        tmp_path,
        "invoice from acme-legal.example",
        source="document-metadata",
        fields={"Company": "acme-legal.example"},
    )

    found = extract([record], content=True)
    domain = next(entry for entry in found if entry.normalized == "acme-legal.example")

    assert domain.acquired is False


def test_the_document_carries_the_corpus_of_every_identifier(tmp_path: Path):
    record = _document(
        tmp_path,
        "invoice from acme-legal.example",
        source="browser-download",
        url="https://acme-legal.example/invoice.pdf",
    )

    payload = json.loads(render_json([record], tmp_path, identify=True, content=True))
    domain = next(e for e in payload["identifiers"] if e["normalized"] == "acme-legal.example")

    assert domain["corpora"] == ["content", "metadata"]
    assert domain["acquired"] is True


def test_the_report_says_which_side_of_the_file_a_value_came_from(tmp_path: Path):
    # Two files, because the section that raises this only runs for a directory:
    # a report about one file has nothing to bury it under.
    records = [
        _document(
            tmp_path,
            "invoice from acme-legal.example",
            name="invoice.txt",
            source="browser-download",
            url="https://acme-legal.example/invoice.pdf",
        ),
        _document(
            tmp_path,
            "write to ann.shaw@other.example",
            name="notes.txt",
            source="document-metadata",
        ),
        _document(
            tmp_path,
            "not read, this is not a text format",
            name="holiday.jpg",
            source="device-metadata",
            fields={"Company": "third.example"},
        ),
    ]

    report = render_text(records, tmp_path, identify=True, content=True, theme=PLAIN)

    assert "CROSS-SOURCE MATCHES" in " ".join(report.split())
    # A value in the document *and* in how the file arrived is the pairing this
    # exists to find, and it gets a section of its own rather than a word at the
    # end of a row: a reader scanning for it should not have to compare two
    # tables by eye.
    crossed = report[report.index("CROSS-SOURCE MATCHES") :]
    assert "acme-legal.example" in crossed
    assert "other.example" not in crossed
    assert "third.example" not in crossed


# --- self-checking identifiers ------------------------------------------------
#
# A wallet address, a bank account and a tax number carry their own checksum,
# so a match can be believed without a region hint or a surrounding label. The
# tax numbers are the exception: their checksum passes about one random number
# in eleven, so they are taken only beside the label that names them.


def test_a_bitcoin_address_with_a_valid_checksum_is_found(tmp_path: Path):
    record = _document(
        tmp_path, "pay 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa by friday", source="document-metadata"
    )

    found = {(e.type, e.normalized) for e in extract([record], content=True)}

    assert ("btc", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa") in found


def test_a_bech32_address_is_found_and_lowercased(tmp_path: Path):
    """The spec allows an all-uppercase spelling; one wallet must be one entry."""
    record = _document(
        tmp_path, "BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4", source="document-metadata"
    )

    found = [e for e in extract([record], content=True) if e.type == "btc"]

    assert [e.normalized for e in found] == ["bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"]


def test_a_bitcoin_address_with_a_broken_checksum_is_not(tmp_path: Path):
    record = _document(
        tmp_path, "pay 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb", source="document-metadata"
    )

    assert [e for e in extract([record], content=True) if e.type == "btc"] == []


def test_the_other_chains_are_each_their_own_type_by_their_own_checksum(tmp_path: Path):
    """A `3` address was pay-to-script on Litecoin too, once; it stays a `btc`."""
    monero = (
        "44AFFq5kSiGBoZ4NMDwYtN18obc8AemS33DBLWs3H7otXft3XjrpDtQG"
        "v7SqSsaBYBb98uNbr2VBBEt7f2wfn3RVGQBEP3A"
    )
    record = _document(
        tmp_path,
        "ltc LUEweDxDA4WhvWiNXXSxjM9CYzHPJv4QQF and ltc1qw508d6qejxtdg4y5r3zarvary0c5xw7kgmn4n9, "
        "doge DEA5vGb2NpAwCiCp5yTE16F3DueQUVivQp, bch qpm2qsznhks23z7629mms6s4cwef74vcwvy22gdx6a, "
        f"xmr {monero}, "
        "p2sh 3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy, broken DEA5vGb2NpAwCiCp5yTE16F3DueQUVivQq",
        source="document-metadata",
    )

    wallets = {"btc", "ltc", "doge", "bch", "xmr"}
    found = sorted(
        (e.type, e.normalized) for e in extract([record], content=True) if e.type in wallets
    )

    assert found == [
        ("bch", "bitcoincash:qpm2qsznhks23z7629mms6s4cwef74vcwvy22gdx6a"),
        ("btc", "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"),
        ("doge", "DEA5vGb2NpAwCiCp5yTE16F3DueQUVivQp"),
        ("ltc", "LUEweDxDA4WhvWiNXXSxjM9CYzHPJv4QQF"),
        ("ltc", "ltc1qw508d6qejxtdg4y5r3zarvary0c5xw7kgmn4n9"),
        ("xmr", monero),
    ]


def test_an_iban_is_found_without_its_spaces(tmp_path: Path):
    record = _document(
        tmp_path, "account GB82 WEST 1234 5698 7654 32 please", source="document-metadata"
    )

    found = [e for e in extract([record], content=True) if e.type == "iban"]

    assert [e.normalized for e in found] == ["GB82WEST12345698765432"]
    assert found[0].value == "GB82 WEST 1234 5698 7654 32"


def test_an_iban_that_fails_mod_97_is_not(tmp_path: Path):
    record = _document(tmp_path, "account GB82WEST12345698765433", source="document-metadata")

    assert [e for e in extract([record], content=True) if e.type == "iban"] == []


def test_a_nip_is_found_only_beside_its_label(tmp_path: Path):
    labelled = _document(tmp_path, "NIP: 526-025-02-74", name="a.txt", source="document-metadata")
    bare = _document(tmp_path, "call 5260250274 today", name="b.txt", source="document-metadata")

    found = {(e.type, e.normalized) for e in extract([labelled, bare], content=True)}

    assert ("nip", "5260250274") in found
    nip = next(e for e in extract([labelled, bare], content=True) if e.type == "nip")
    assert nip.files == 1


def test_a_nip_behind_its_country_prefix_is_found(tmp_path: Path):
    """The EU VAT spelling is the label: `PL` and ten digits."""
    record = _document(tmp_path, "vat id PL5260250274", source="document-metadata")

    found = {(e.type, e.normalized) for e in extract([record], content=True)}

    assert ("nip", "5260250274") in found


def test_a_nip_with_a_broken_check_digit_is_not(tmp_path: Path):
    record = _document(tmp_path, "NIP 5260250275", source="document-metadata")

    assert [e for e in extract([record], content=True) if e.type == "nip"] == []


def test_a_regon_is_found_beside_its_label(tmp_path: Path):
    record = _document(
        tmp_path, "REGON: 123456785, and REGON 12345678500010", source="document-metadata"
    )

    found = sorted(e.normalized for e in extract([record], content=True) if e.type == "regon")

    assert found == ["123456785", "12345678500010"]


def test_a_self_checking_value_in_metadata_is_found_too():
    """The detectors run over both corpora; a note can carry a wallet."""
    record = _record("x", source="document-metadata", note="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")

    assert [e.type for e in extract([record])] == ["btc"]


# --- addresses and accounts with a shape of their own ---------------------------


def test_an_onion_address_with_a_valid_checksum_is_found_lowercased(tmp_path: Path):
    record = _document(
        tmp_path,
        "mirror at DUCKDUCKGOGG42XJOC72X3SJASOWOARFBGCMVFIMAFTT6TWAGSWZCZAD.onion tonight",
        source="document-metadata",
    )

    found = [e.normalized for e in extract([record], content=True) if e.type == "onion"]

    assert found == ["duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion"]


def test_a_mac_address_is_found_in_either_spelling_as_one_value(tmp_path: Path):
    record = _document(
        tmp_path, "nic AA-BB-CC-DD-EE-01 also seen as aa:bb:cc:dd:ee:01", source="document-metadata"
    )

    found = [e for e in extract([record], content=True) if e.type == "mac"]

    assert [(e.normalized, e.count) for e in found] == [("aa:bb:cc:dd:ee:01", 2)]


def test_a_windows_account_sid_is_found(tmp_path: Path):
    record = _document(
        tmp_path, "owner S-1-5-21-3623811015-3361044348-30300820-1013", source="document-metadata"
    )

    found = {(e.type, e.normalized) for e in extract([record], content=True)}

    assert ("sid", "S-1-5-21-3623811015-3361044348-30300820-1013") in found


def test_a_bic_is_found_beside_its_label_in_both_lengths(tmp_path: Path):
    record = _document(
        tmp_path, "SWIFT: deutdeff and BIC code DEUTDEFF500", source="document-metadata"
    )

    found = sorted(e.normalized for e in extract([record], content=True) if e.type == "bic")

    assert found == ["DEUTDEFF", "DEUTDEFF500"]


def test_the_shapes_that_look_right_and_are_not_are_left_alone(tmp_path: Path):
    """A broken onion checksum, a broadcast address, a well-known SID and a
    bare BIC are each the sort of thing a looser sweep would report."""
    record = _document(
        tmp_path,
        "duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczae.onion "
        "ff:ff:ff:ff:ff:ff 00:00:00:00:00:00 S-1-5-18 pay via DEUTDEFF today "
        "BIC: ABCDXXFF",
        source="document-metadata",
    )

    assert [e.type for e in extract([record], content=True)] == []


# --- credentials --------------------------------------------------------------
#
# A key or a token in a document is a finding, and printing it into a report
# that leaves the machine is the one mistake here that cannot be undone. So a
# credential is reported as what it is and a fingerprint of it, the same one
# `--redact` writes, and never as the value.


def test_a_credential_is_reported_as_a_fingerprint_never_the_value(tmp_path: Path):
    from filegrail.redact import fingerprint

    key = "AKIAIOSFODNN7EXAMPLE"
    token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop"
    record = _document(tmp_path, f"aws {key}\nbearer {token}\n", source="document-metadata")

    found = [e for e in extract([record], content=True) if e.type == "secret"]

    assert sorted(e.value for e in found) == [
        f"aws_access_key {fingerprint(key)}",
        f"jwt {fingerprint(token)}",
    ]
    assert not [e for e in found if key in e.value or token in e.normalized]


def test_private_key_blocks_are_one_fact_wherever_they_sit(tmp_path: Path):
    """Every key opens with the same line and a per-line scan never sees the
    rest, so the identity of a key block is where it is, not what it holds."""
    a = _document(
        tmp_path,
        "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n",
        name="a.txt",
        source="document-metadata",
    )
    b = _document(
        tmp_path, "-----BEGIN PRIVATE KEY-----\nMIIE...\n", name="b.txt", source="document-metadata"
    )

    found = [e for e in extract([a, b], content=True) if e.type == "secret"]

    assert [(e.value, e.files) for e in found] == [("private key block", 2)]


# --- who a file says made it ---------------------------------------------------
#
# A person or a company is never read out of prose - a capitalised pair of
# words is a name, a town and a sign-off in equal measure. It is read from the
# fields whose *name* says who: an author line, a by-line, the display name on
# a mail header. That is a fact the format declared, and the corpus it lives
# in is metadata, so a document body cannot produce one by construction.


def test_a_vocabulary_term_is_not_a_pivot():
    """A Content Credentials source type is a URI into the IPTC vocabulary: it
    says what kind of picture this is and names no host anybody in a case runs."""
    record = _record(
        "generated.png",
        source="c2pa",
        block="c2pa",
        fields={
            "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
        },
    )

    assert extract([record]) == []


def test_a_person_is_read_from_a_field_that_names_one():
    docx = _record("letter.docx", source="document-metadata", fields={"Author": "Jan Kowalski"})
    mail = _record(
        "note.eml", source="email-header", fields={"From": "Ann Shaw <ann.shaw@acme.example>"}
    )
    placeholder = _record(
        "form.docx", source="document-metadata", fields={"Author": "Microsoft Office User"}
    )
    # An OLE document's summary names its last editor under its own spelling.
    sheet = _record("sheet.xls", source="document-metadata", fields={"LastAuthor": "Ann Shaw"})
    # Seen in the wild: an application writing its device id where the
    # photographer's name goes.
    blob = _record(
        "image.jpg",
        source="document-metadata",
        fields={"Artist": "7a3c0114-90a5-43cf-af74-75f091770f13"},
    )

    found = extract([docx, mail, placeholder, blob, sheet])

    people = {e.normalized: e.files for e in found if e.type == "person"}
    assert people == {"ann shaw": 2, "jan kowalski": 1}
    assert [e.normalized for e in found if e.type == "email"] == ["ann.shaw@acme.example"]


def test_a_value_counts_every_file_it_is_in_not_only_the_sampled_places():
    """The places are a sample; the file count is not. Two files of one name in
    two folders are two files."""
    records = [
        _record(f"d{i}/letter.docx", source="document-metadata", fields={"Author": "Jan Kowalski"})
        for i in range(25)
    ]

    entry = next(e for e in extract(records) if e.type == "person")

    assert (entry.count, entry.files) == (25, 25)


def test_a_name_in_prose_is_not_a_person(tmp_path: Path):
    record = _document(
        tmp_path, "Author: Jan Kowalski\nSigned, Ann Shaw", source="document-metadata"
    )

    assert [e for e in extract([record], content=True) if e.type == "person"] == []


def test_a_company_and_the_accounts_a_file_points_at_are_read():
    record = _record(
        "report.docx",
        source="document-metadata",
        fields={
            "Company": "Acme Ltd",
            "Template": r"C:\Users\jkowalski\AppData\Roaming\Microsoft\Templates\Normal.dotm",
        },
        note="see https://github.com/jkowalski and https://x.com/home for more",
    )

    found = {(e.type, e.normalized) for e in extract([record])}

    assert ("org", "acme ltd") in found
    assert ("handle", "github:jkowalski") in found
    assert ("handle", "home:jkowalski") in found
    assert not [h for kind, h in found if kind == "handle" and h.startswith("x:")]


def test_a_message_id_links_a_message_to_the_reply_that_quotes_it():
    sent = _record(
        "sent.eml", source="email-header", fields={"Message-ID": "<CAF1x9@mail.gmail.com>"}
    )
    reply = _record(
        "reply.eml",
        source="email-header",
        fields={
            "In-Reply-To": "<CAF1x9@MAIL.GMAIL.COM>",
            "References": "<a1.b2@lists.example> <CAF1x9@mail.gmail.com>",
            "Content-ID": "<image001.png@01DA>",
        },
    )

    found = {e.normalized: e.files for e in extract([sent, reply]) if e.type == "message_id"}

    assert found == {"<CAF1x9@mail.gmail.com>": 2, "<a1.b2@lists.example>": 1}


def test_the_owner_of_a_github_repository_is_an_account(tmp_path: Path):
    record = _document(
        tmp_path,
        "clone https://github.com/osintshifu/filegrail/commit/abc, payload at "
        "https://raw.githubusercontent.com/evil-dev/tools/main/x.ps1; see "
        "https://github.com/features/actions and https://github.com/user-attachments/assets/1",
        source="document-metadata",
    )

    found = sorted(e.normalized for e in extract([record], content=True) if e.type == "handle")

    assert found == ["github:evil-dev", "github:osintshifu"]


# --- names that carry their own label ------------------------------------------
#
# The one way a name is read out of prose: when the text itself labels it. A
# legal suffix says a company, an honorific says a person, a postcode with the
# town after it says an address. Recall is low by design; a capitalised pair
# of words on its own is still never believed.


def test_a_company_is_read_by_its_legal_suffix(tmp_path: Path):
    record = _document(
        tmp_path,
        "we paid Acme Systems Ltd. and Zakłady Nowak Sp. z o.o. last year",
        source="document-metadata",
    )

    found = sorted(e.normalized for e in extract([record], content=True) if e.type == "org")

    assert found == ["acme systems ltd", "zakłady nowak sp. z o.o"]


def test_a_person_is_read_after_an_honorific_and_not_without(tmp_path: Path):
    record = _document(
        tmp_path, "met Pani Anna Nowak and Ann Shaw at Mr J. Smith's", source="document-metadata"
    )

    found = sorted(e.normalized for e in extract([record], content=True) if e.type == "person")

    assert found == ["anna nowak"]


def test_a_postcode_is_read_with_the_town_it_belongs_to(tmp_path: Path):
    record = _document(
        tmp_path,
        "ul. Prosta 1, 00-950 Warszawa and 12-345 in stock, or SW1A 1AA London",
        source="document-metadata",
    )

    found = sorted(e.normalized for e in extract([record], content=True) if e.type == "postcode")

    assert found == ["00-950 warszawa", "sw1a 1aa"]


# --- united states ------------------------------------------------------------
#
# None of these carries a checksum a document can be trusted on alone - the
# routing number has one, and it passes one random number in ten - so all
# three are taken only beside the label that names them. A social security
# number is the key to somebody's identity, and is reported the way a
# credential is: as a fingerprint, never as the number.


def test_a_social_security_number_is_a_fingerprint_beside_its_label(tmp_path: Path):
    from filegrail.redact import fingerprint

    record = _document(
        tmp_path,
        "SSN: 123-45-6789 on file; call 987-65-4321; SSN 000-12-3456 is a placeholder",
        source="document-metadata",
    )

    found = [e for e in extract([record], content=True) if e.type == "ssn"]

    assert [e.value for e in found] == [fingerprint("123456789")]
    assert not [e for e in found if "123-45" in e.where[0] or "6789" in e.normalized]


def test_an_employer_id_is_taken_beside_its_label_with_a_real_prefix(tmp_path: Path):
    record = _document(
        tmp_path,
        "EIN 12-3456789 for Acme; invoice 12-3456789 again; Tax ID: 07-1234567 is not one",
        source="document-metadata",
    )

    found = [(e.normalized, e.count) for e in extract([record], content=True) if e.type == "ein"]

    assert found == [("12-3456789", 1)]


def test_a_routing_number_needs_its_label_and_its_checksum(tmp_path: Path):
    record = _document(
        tmp_path,
        "ABA routing 021000021 for wires; account 021000021; routing number 021000022 no",
        source="document-metadata",
    )

    found = [(e.normalized, e.count) for e in extract([record], content=True) if e.type == "aba"]

    assert found == [("021000021", 1)]


# --- trackers -----------------------------------------------------------------
#
# An analytics or advertising id is an account, and the same one on two sites
# is one owner. The ones with a prefix are taken wherever they stand; a bare
# number is taken only beside the service that issued it.


def test_a_tracker_id_is_read_by_its_prefix_and_one_publisher_is_one_value(tmp_path: Path):
    record = _document(
        tmp_path,
        "UA-12345-1 GTM-ABC123 G-1A2B3C4D G-SHOCK ca-pub-1234567890123456 pub-1234567890123456",
        source="document-metadata",
    )

    found = sorted(
        (e.normalized, e.count) for e in extract([record], content=True) if e.type == "tracker"
    )

    assert found == [
        ("G-1A2B3C4D", 1),
        ("GTM-ABC123", 1),
        ("UA-12345-1", 1),
        ("pub-1234567890123456", 2),
    ]


def test_a_numeric_tracker_id_needs_its_service_beside_it(tmp_path: Path):
    """The snippets live in `<script>`, which the reader leaves out; the ids
    survive in the `src` of the noscript image and the loader, which it keeps."""
    record = _document(
        tmp_path,
        "<p>order 123456789012345</p>"
        '<img src="https://www.facebook.com/tr?id=123456789012345&ev=PageView">'
        '<img src="https://mc.yandex.ru/watch/12345678">'
        '<a href="https://www.amazon.com/dp/B0X/?tag=mysite-20">buy</a>',
        name="page.html",
        source="document-metadata",
    )

    found = sorted(e.normalized for e in extract([record], content=True) if e.type == "tracker")

    assert found == ["amazon:mysite-20", "facebook:123456789012345", "yandex:12345678"]


# --- indicators -----------------------------------------------------------------


def test_a_cve_id_is_found_in_either_case(tmp_path: Path):
    record = _document(
        tmp_path, "patched cve-2021-44228 and CVE-2021-44228", source="document-metadata"
    )

    found = [(e.normalized, e.count) for e in extract([record], content=True) if e.type == "cve"]

    assert found == [("CVE-2021-44228", 2)]


def test_a_sha512_digest_and_weakness_and_advisory_ids_are_found(tmp_path: Path):
    record = _document(
        tmp_path, f"sum {'AB' * 64}, cwe-79 and GHSA-JFH8-C2JP-5V3Q", source="document-metadata"
    )

    found = {(e.type, e.normalized) for e in extract([record], content=True)}

    assert {("sha512", "ab" * 64), ("cwe", "CWE-79"), ("ghsa", "GHSA-jfh8-c2jp-5v3q")} <= found
    assert not [value for kind, value in found if kind in {"md5", "sha1", "sha256"}]


def test_a_registry_key_is_one_value_under_either_hive_spelling(tmp_path: Path):
    record = _document(
        tmp_path,
        r"HKEY_LOCAL_MACHINE\Software\Microsoft\Windows\CurrentVersion\Run and "
        r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run again",
        source="document-metadata",
    )

    found = [
        (e.normalized, e.count) for e in extract([record], content=True) if e.type == "registry"
    ]

    assert found == [(r"hklm\software\microsoft\windows\currentversion\run", 2)]


def test_a_fingerprint_written_with_colons_is_the_same_digest(tmp_path: Path):
    bare = "2fd4e1c67a2d28fced849ee1bb76e7391b93eb12"
    colons = ":".join(bare[i : i + 2] for i in range(0, 40, 2)).upper()
    record = _document(tmp_path, f"sha1 {bare}\nfingerprint {colons}\n", source="document-metadata")

    found = [(e.normalized, e.count) for e in extract([record], content=True) if e.type == "sha1"]

    assert found == [(bare, 2)]


def test_an_ipv6_address_is_believed_written_out_or_in_brackets_and_not_bare(tmp_path: Path):
    record = _document(
        tmp_path,
        "host 2001:0db8:85a3:0000:0000:8a2e:0370:7334 and http://[2001:db8::1]/x and ::1 and a::b",
        source="document-metadata",
    )

    found = sorted(e.normalized for e in extract([record], content=True) if e.type == "ipv6")

    assert found == ["2001:db8:85a3::8a2e:370:7334", "2001:db8::1"]


def test_a_digest_of_an_address_in_the_corpus_is_named_for_it(tmp_path: Path):
    """A list of hashed addresses beside one address in the clear is that
    address, named twice; the hash says which one it is."""
    import hashlib

    address = "ann.shaw@acme.example"
    digest = hashlib.md5(address.encode()).hexdigest()
    other = hashlib.md5(b"nothing").hexdigest()
    record = _document(
        tmp_path,
        f"list: {digest} {other}\ncontact Ann.Shaw@acme.example\n",
        source="document-metadata",
    )

    found = {(e.type, e.normalized): e for e in extract([record], content=True)}

    assert found[("md5", digest)].of == address
    assert found[("md5", other)].of is None
    assert found[("md5", digest)].to_dict()["of"] == address


def test_the_text_report_shows_every_type_the_extractor_knows():
    """A type the report's own table has not heard of must still be printed:
    a value that reaches `--json` and not the report is a lead nobody sees."""
    record = _record("x", source="document-metadata", note="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")

    text = render_text([record], Path("/case"), theme=PLAIN, identify=True)

    assert "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa" in text


# --- what an incident report is made of ------------------------------------------


def test_a_windows_path_is_one_value_however_it_is_cased(tmp_path: Path):
    record = _document(
        tmp_path,
        r"dropped to C:\Users\Public\update.exe then c:\users\public\UPDATE.EXE; "
        r"config in %APPDATA%\Roaming\svc\run.bat; share \\FS01\tools\rat.dll; "
        r"key HKLM\Software\x is not a path; /usr/bin/env neither",
        source="document-metadata",
    )

    found = sorted(
        (e.normalized, e.count) for e in extract([record], content=True) if e.type == "path"
    )

    assert found == [
        (r"%appdata%\roaming\svc\run.bat", 1),
        (r"\\fs01\tools\rat.dll", 1),
        (r"c:\users\public\update.exe", 2),
    ]


def test_a_machine_name_is_read_where_a_shortcut_a_share_or_a_mail_hop_records_one():
    shortcut = _record(
        "report.lnk",
        source="windows-recent",
        fields={"MachineID": "DESKTOP-7QK2", "NetworkShare": r"\\FILESRV01\share"},
    )
    hop = _record("note.eml", source="email-delivery", fields={"From": "WS-ANNA", "By": "EXCH01"})
    lookalikes = _record(
        "note2.eml",
        source="email-header",
        fields={"From": "Ann Shaw <ann@acme.example>"},
        note=r"see \\server\share, \\localhost\c$, \\192.168.1.5\c$ and \\fs.example.com\x",
    )

    found = extract([shortcut, hop, lookalikes])

    assert sorted(e.normalized for e in found if e.type == "hostname") == [
        "desktop-7qk2",
        "exch01",
        "filesrv01",
        "ws-anna",
    ]
    assert "fs.example.com" in [e.normalized for e in found if e.type == "domain"]


def test_an_executable_name_is_found_bare_or_inside_a_path_and_a_source_file_is_not(tmp_path: Path):
    record = _document(
        tmp_path,
        r"see evil.exe and C:\tmp\Evil.EXE and http://x.example/dl/evil.exe; "
        r"edit main.py and readme.md",
        source="document-metadata",
    )

    found = [
        (e.normalized, e.count) for e in extract([record], content=True) if e.type == "executable"
    ]

    assert found == [("evil.exe", 3)]


# --- ethereum and vehicles ----------------------------------------------------------


def test_an_ethereum_address_is_taken_by_its_checksum_or_written_lowercase(tmp_path: Path):
    """Mixed case carries a checksum and has to pass it; all-lowercase carries
    none and is taken by its shape. A transaction hash is longer and is not."""
    record = _document(
        tmp_path,
        "pay 0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed "
        "or 0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed; "
        "not 0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAeD; tx 0x" + "ab" * 32,
        source="document-metadata",
    )

    found = [(e.normalized, e.count) for e in extract([record], content=True) if e.type == "eth"]

    assert found == [("0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed", 2)]


def test_a_vin_is_taken_by_its_check_digit_or_beside_its_label(tmp_path: Path):
    """North America requires the check digit and Europe does not: a bare VIN
    has to pass it, a labelled one need not."""
    record = _document(
        tmp_path,
        "car 1HGCM82633A004352, not 1HGCM82633A004353, not WVWZZZ3CZWE000001 bare, "
        "VIN: WVWZZZ3CZWE000001 labelled",
        source="document-metadata",
    )

    found = sorted(e.normalized for e in extract([record], content=True) if e.type == "vin")

    assert found == ["1HGCM82633A004352", "WVWZZZ3CZWE000001"]


# --- registries and networks ---------------------------------------------------------


def test_a_company_registry_number_is_taken_beside_its_label(tmp_path: Path):
    """None of these carries a checksum, so the label is the whole warrant. A
    SEC filer number is one number however many zeros the filing pads it with."""
    record = _document(
        tmp_path,
        "Company No. 09876543, Companies House SC123456, bare 12345678; "
        "CIK 0000320193 and CIK: 320193; VAT: DE123456789, VAT ID GB123456789, VAT PL5260250274",
        source="document-metadata",
    )

    found = extract([record], content=True)
    by_type = {
        kind: sorted((e.normalized, e.count) for e in found if e.type == kind)
        for kind in ("crn", "cik", "vat", "nip")
    }

    assert by_type["crn"] == [("09876543", 1), ("SC123456", 1)]
    assert by_type["cik"] == [("320193", 2)]
    assert by_type["vat"] == [("DE123456789", 1), ("GB123456789", 1)]
    assert by_type["nip"] == [("5260250274", 1)]


def test_an_autonomous_system_number_is_taken_and_a_product_name_is_not(tmp_path: Path):
    record = _document(
        tmp_path,
        "peers with AS15169 and ASN 3356, ASN: 174; runs on an AS400 to AS9100",
        source="document-metadata",
    )

    found = sorted(e.normalized for e in extract([record], content=True) if e.type == "asn")

    assert found == ["AS15169", "AS174", "AS3356"]
