"""File names the messaging clients give to what they save.

The stores themselves are out of reach: Telegram Desktop encrypts `tdata` and
keeps no chat history in it, and Signal Desktop's database is SQLCipher behind
an operating-system-wrapped key. Reading either needs a crypto dependency this
project does not have, so no claim here is about a message record.

What is left is the name. Both clients write a fixed pattern, and a file
carrying one arrived through that client far more often than not. It is a much
weaker thing than a record and is ranked and worded as one: a name can be typed
by anybody, and a coincidence is a coincidence.
"""

from __future__ import annotations

from pathlib import Path

from filegrail.models import ORIGIN, category
from filegrail.scan import scan
from filegrail.sources.messenger import read_messenger_name


def test_a_whatsapp_image_is_recognised(tmp_path: Path):
    origin = read_messenger_name(tmp_path / "IMG-20240115-WA0001.jpg")

    assert origin is not None
    assert origin.tool == "WhatsApp"
    assert origin.fields["dated"] == "2024-01-15"


def test_a_telegram_photo_is_recognised(tmp_path: Path):
    origin = read_messenger_name(tmp_path / "photo_2024-01-15_12-30-45.jpg")

    assert origin is not None
    assert origin.tool == "Telegram"


def test_an_ordinary_name_is_not_claimed(tmp_path: Path):
    assert read_messenger_name(tmp_path / "holiday.jpg") is None


def test_a_name_shaped_like_one_but_dated_impossibly_is_not_claimed(tmp_path: Path):
    """`20241315` is not a date. A pattern that matches the shape and not the
    calendar is a coincidence, and reporting it would invent an arrival."""
    assert read_messenger_name(tmp_path / "IMG-20241315-WA0001.jpg") is None


def test_the_claim_is_never_dated(tmp_path: Path):
    """The name carries a day, and for Telegram a clock with no zone. Putting
    either on the timeline would place the file at a moment nothing recorded."""
    origin = read_messenger_name(tmp_path / "IMG-20240115-WA0001.jpg")

    assert origin.at is None


def test_it_says_how_the_file_arrived_and_says_so_weakly(tmp_path: Path):
    origin = read_messenger_name(tmp_path / "IMG-20240115-WA0001.jpg")

    assert category(origin) == ORIGIN
    assert origin.priority < 35  # below an application having opened the file


def test_a_scan_attaches_it(tmp_path: Path):
    (tmp_path / "IMG-20240115-WA0001.jpg").write_bytes(b"\x00")

    record = next(iter(scan(tmp_path, use_shell_history=False)))

    assert [o.tool for o in record.evidence if o.source == "messenger-name"] == ["WhatsApp"]
