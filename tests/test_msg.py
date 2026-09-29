"""A saved Outlook message, which is a compound document that holds an email.

`.msg` was already opened as a compound document, because its Office-style
summary properties sit where a `.doc`'s do. What was never read is the stream
Outlook keeps the internet headers in - the same RFC 5322 block an `.eml`
starts with, and with it the same `Received:` chain, which is the one part of a
message the sender did not write.

Nothing on this machine writes a `.msg`, so every fixture here is assembled
from [MS-OXMSG] and the reader is spec-only: it has never been run against a
message Outlook actually produced.
"""

from __future__ import annotations

from pathlib import Path

from filegrail.scan import scan
from filegrail.sources.mail import read_mail
from tests.compound import ole

#: [MS-OXMSG] names a property stream `__substg1.0_` then the property tag then
#: its type: 001F for UTF-16 text, 001E for 8-bit. `007D` is
#: PR_TRANSPORT_MESSAGE_HEADERS.
HEADERS_UNICODE = "__substg1.0_007D001F"
HEADERS_ANSI = "__substg1.0_007D001E"
SUBJECT = "__substg1.0_0037001F"
SENDER = "__substg1.0_0C1F001F"
MESSAGE_ID = "__substg1.0_1035001F"
SUBJECT_ANSI = "__substg1.0_0037001E"

TRANSPORT = """\
Received: from mx.example.net (mx.example.net [198.51.100.9])
 by mail.example.org (Postfix) with ESMTPS id 4XyZ12
 for <alice@example.org>; Mon, 31 Aug 2026 10:49:33 +0000
Received: from workstation.example.net (workstation.example.net [203.0.113.4])
 by mx.example.net (Postfix) with ESMTP id 9AbC34
 for <alice@example.org>; Mon, 31 Aug 2026 10:49:30 +0000
From: Bob <bob@example.net>
To: alice@example.org
Subject: The quarterly figures
Date: Mon, 31 Aug 2026 10:49:28 +0000
Message-ID: <c0ffee@example.net>
X-Mailer: Microsoft Outlook 16.0
"""


def _message(tmp_path: Path, streams: dict[str, bytes], name: str = "note.msg") -> Path:
    path = tmp_path / name
    path.write_bytes(ole(streams))
    return path


def _wide(text: str) -> bytes:
    return text.encode("utf-16-le")


def test_the_delivery_chain_is_read_from_the_transport_headers(tmp_path: Path):
    path = _message(tmp_path, {HEADERS_UNICODE: _wide(TRANSPORT)})

    found = read_mail(path)

    assert [origin.source for origin in found] == [
        "email-delivery",
        "email-relay",
        "email-header",
    ]


def test_the_topmost_hop_is_the_one_the_recipient_can_trust(tmp_path: Path):
    """Same rule as an `.eml`: the last server to write is the first to read."""
    path = _message(tmp_path, {HEADERS_UNICODE: _wide(TRANSPORT)})

    delivery = read_mail(path)[0]

    assert delivery.tool == "mail.example.org"
    assert delivery.fields["ConnectingAddress"] == "198.51.100.9"
    assert delivery.at == "2026-08-31T10:49:33Z"


def test_the_eight_bit_spelling_of_the_same_stream_is_read(tmp_path: Path):
    """Older senders write 001E, and the tag is the same property."""
    path = _message(tmp_path, {HEADERS_ANSI: TRANSPORT.encode("latin-1")})

    assert [origin.source for origin in read_mail(path)][0] == "email-delivery"


def test_a_message_with_no_transport_headers_still_names_itself(tmp_path: Path):
    """Exchange delivers internally without ever writing internet headers.

    There is no delivery record to be had in that case and none is invented;
    what the message says about itself is reported as exactly that.
    """
    path = _message(
        tmp_path,
        {
            SUBJECT: _wide("The quarterly figures"),
            SENDER: _wide("bob@example.net"),
            MESSAGE_ID: _wide("<c0ffee@example.net>"),
        },
    )

    found = read_mail(path)

    assert [origin.source for origin in found] == ["email-header"]
    assert found[0].fields["Subject"] == "The quarterly figures"
    assert found[0].fields["From"] == "bob@example.net"


def test_the_self_description_is_not_repeated_when_the_headers_are_there(tmp_path: Path):
    """The header block already carries a From and a Subject of its own."""
    path = _message(
        tmp_path,
        {HEADERS_UNICODE: _wide(TRANSPORT), SUBJECT: _wide("Something else entirely")},
    )

    headers = [origin for origin in read_mail(path) if origin.source == "email-header"]

    assert len(headers) == 1
    assert headers[0].fields["Subject"] == "The quarterly figures"


def test_a_message_that_says_nothing_yields_nothing(tmp_path: Path):
    path = _message(tmp_path, {"\x05SummaryInformation": b"\x00" * 8})

    assert read_mail(path) == []


def test_a_msg_that_is_not_a_compound_document_is_left_alone(tmp_path: Path):
    path = tmp_path / "note.msg"
    path.write_bytes(b"not a compound document at all")

    assert read_mail(path) == []


def test_a_truncated_stream_is_refused_rather_than_half_read(tmp_path: Path):
    """An odd byte count cannot be UTF-16, and guessing would invent a name."""
    path = _message(tmp_path, {SUBJECT: _wide("Quarterly") + b"\x00"})

    assert read_mail(path) == []


def test_a_scan_reaches_the_delivery_chain(tmp_path: Path):
    """Through the scan, beside the summary properties the same file carries."""
    case = tmp_path / "case"
    case.mkdir()
    _message(case, {HEADERS_UNICODE: _wide(TRANSPORT)})

    record = scan(case, home=tmp_path / "empty", use_shell_history=False)[0]

    assert "email-delivery" in {origin.source for origin in record.evidence}


def test_the_unicode_spelling_wins_where_a_message_carries_both(tmp_path: Path):
    """The 8-bit form is a lossy transcription of the same property.

    A message is meant to be one or the other, so both at once is already a
    file worth distrusting - but where it happens, the form that can represent
    the subject is the one that has not already lost part of it.
    """
    path = _message(
        tmp_path,
        {
            SUBJECT: _wide("Zażółć gęślą jaźń"),
            SUBJECT_ANSI: "Zazolc gesla jazn".encode("latin-1"),
        },
    )

    assert read_mail(path)[0].fields["Subject"] == "Zażółć gęślą jaźń"
