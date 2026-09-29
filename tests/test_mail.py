"""What a saved message says about how it travelled.

`Received:` headers are the only part of an email written by anyone other than
the sender. Each mail server prepends its own as the message passes through, so
they read from the bottom up - and the topmost was written by the recipient's
own server, which is the one hop nobody but the recipient could have forged.
"""

from __future__ import annotations

from pathlib import Path

from filegrail.identify import extract
from filegrail.models import METADATA, ORIGIN, FileRecord, category
from filegrail.sources.mail import read_mail

DELIVERED = """\
Received: from mail.example.com (mail.example.com [203.0.113.5])
        by mx.recipient.org with ESMTPS id 4bK9x2
        for <analyst@recipient.org>; Mon, 4 Mar 2019 10:22:31 -0800 (PST)
Received: from workstation.example.com (workstation.example.com [198.51.100.9])
        by mail.example.com with SMTP id 7ttQ1a; Mon, 4 Mar 2019 10:22:29 -0800
From: Jan Kowalski <jan@example.com>
To: analyst@recipient.org
Subject: The photographs you asked for
Date: Mon, 4 Mar 2019 10:22:28 -0800
Message-ID: <20190304182228.7ttQ1a@example.com>
X-Mailer: Mozilla Thunderbird 60.5.1

The attachments are in the archive.
"""


def _message(tmp_path: Path, text: str = DELIVERED, name: str = "note.eml") -> Path:
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return path


def _by(origins, source: str):
    return [origin for origin in origins if origin.source == source]


# --- the hops ----------------------------------------------------------------


def test_the_topmost_hop_is_the_delivery_record(tmp_path: Path):
    """It was written by the recipient's own server. Every hop below it was
    written by a machine the sender may well control."""
    origins = read_mail(_message(tmp_path))

    delivery = _by(origins, "email-delivery")
    assert len(delivery) == 1
    assert delivery[0].tool == "mx.recipient.org"
    assert category(delivery[0]) == ORIGIN


def test_every_other_hop_is_a_relay(tmp_path: Path):
    origins = read_mail(_message(tmp_path))

    relays = _by(origins, "email-relay")
    assert [origin.tool for origin in relays] == ["mail.example.com"]
    assert relays[0].priority < _by(origins, "email-delivery")[0].priority


def test_a_hop_carries_the_moment_the_server_stamped_it(tmp_path: Path):
    origins = read_mail(_message(tmp_path))

    assert _by(origins, "email-delivery")[0].at == "2019-03-04T18:22:31Z"
    assert _by(origins, "email-relay")[0].at == "2019-03-04T18:22:29Z"


def test_the_connecting_address_is_kept(tmp_path: Path):
    """The name in `from` is whatever the connecting host claimed. The address
    in brackets is what the receiving server saw, and it is the useful half."""
    fields = _by(read_mail(_message(tmp_path)), "email-delivery")[0].fields

    assert fields["ConnectingAddress"] == "203.0.113.5"
    assert fields["From"] == "mail.example.com"


def test_a_hop_with_no_date_states_no_time(tmp_path: Path):
    """A server that stamped no time is not a server that delivered at
    midnight."""
    origins = read_mail(_message(tmp_path, "Received: by localhost with LMTP\n\nbody\n"))

    assert _by(origins, "email-delivery")[0].at is None


def test_a_sending_address_reaches_identify(tmp_path: Path):
    record = FileRecord(path=str(_message(tmp_path)), size=10, mtime="")
    record.evidence.extend(read_mail(Path(record.path)))

    found = {identifier.value for identifier in extract([record])}

    assert "203.0.113.5" in found
    assert "198.51.100.9" in found


# --- what the sender said ----------------------------------------------------


def test_the_sender_headers_are_the_message_describing_itself(tmp_path: Path):
    """From and Subject are typed by whoever sent it and checked by nobody.
    They belong with what a file says about its own earlier life, not with the
    record of how it arrived."""
    header = _by(read_mail(_message(tmp_path)), "email-header")[0]

    assert category(header) == METADATA
    assert header.fields["From"] == "Jan Kowalski <jan@example.com>"
    assert header.fields["Message-ID"] == "<20190304182228.7ttQ1a@example.com>"


def test_the_composing_client_is_the_tool(tmp_path: Path):
    header = _by(read_mail(_message(tmp_path)), "email-header")[0]

    assert header.tool == "Mozilla Thunderbird 60.5.1"
    assert "The photographs you asked for" in header.note


# --- files with nothing to say -----------------------------------------------


def test_a_file_that_is_not_a_message_is_not_claimed(tmp_path: Path):
    assert read_mail(_message(tmp_path, "just some text with no headers at all\n")) == []


def test_an_empty_file_is_not_claimed(tmp_path: Path):
    assert read_mail(_message(tmp_path, "")) == []


def test_a_flood_of_hops_is_bounded(tmp_path: Path):
    """A mailing list can legitimately add a dozen. Hundreds is a message built
    to make a report unreadable."""
    hops = "".join(f"Received: by hop{n}.example.com with SMTP\n" for n in range(400))
    origins = read_mail(_message(tmp_path, hops + "From: a@b.c\n\nbody\n"))

    assert len(origins) < 100
