"""The names messaging clients give to the files they save.

The stores themselves are out of reach and it is worth saying why, because the
absence is not an oversight. Telegram Desktop encrypts `tdata` and does not
keep chat history in it at all. Signal Desktop's `db.sqlite` is SQLCipher, with
the key wrapped by DPAPI on Windows and the Keychain on macOS; opening it needs
a crypto library, and this tool has no runtime dependencies. Discord and Slack
keep no local message database to read. So nothing here is a message record,
and none of it names a sender or a conversation.

What is left is the file name. Both clients write a fixed pattern when they
save, and a file carrying one came through that client far more often than not.
That is a much weaker thing than a record and is ranked and worded as one: a
name can be typed by anybody, it survives no scrutiny on its own, and a file
renamed by hand loses it entirely.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from ..models import EvidenceRecord

#: `IMG-20240115-WA0001.jpg`. WhatsApp prefixes by kind, then the day it was
#: sent, then a counter within that day. The prefixes are its own vocabulary.
_WHATSAPP = re.compile(r"^(?P<what>IMG|VID|AUD|PTT|DOC|STK)-(?P<day>\d{8})-WA\d{4}", re.IGNORECASE)

#: What each WhatsApp prefix means, in the words a reader wants rather than the
#: abbreviation. `PTT` is push-to-talk: a voice message, not an audio file.
_WHATSAPP_KINDS = {
    "IMG": "an image",
    "VID": "a video",
    "AUD": "an audio file",
    "PTT": "a voice message",
    "DOC": "a document",
    "STK": "a sticker",
}

#: `photo_2024-01-15_12-30-45.jpg`. Telegram Desktop names what it saves after
#: the kind and the moment, with the clock in local time and no zone on it.
_TELEGRAM = re.compile(
    r"^(?P<what>photo|video|audio|file|document|sticker)_"
    r"(?P<day>\d{4}-\d{2}-\d{2})_(?P<clock>\d{2}-\d{2}-\d{2})",
    re.IGNORECASE,
)


def read_messenger_name(path: Path) -> EvidenceRecord | None:
    """What the file's own name says about the client that saved it."""
    return _whatsapp(path.name) or _telegram(path.name)


def _whatsapp(name: str) -> EvidenceRecord | None:
    found = _WHATSAPP.match(name)
    if not found:
        return None
    day = _day(found.group("day"))
    if day is None:
        return None

    what = _WHATSAPP_KINDS[found.group("what").upper()]
    return _named("WhatsApp", f"the name is WhatsApp's for {what}", day)


def _telegram(name: str) -> EvidenceRecord | None:
    found = _TELEGRAM.match(name)
    if not found:
        return None
    day = _day(found.group("day").replace("-", ""))
    if day is None:
        return None

    what = found.group("what").lower()
    fields = {"clock": found.group("clock").replace("-", ":")}
    return _named("Telegram", f"the name is Telegram Desktop's for a saved {what}", day, fields)


def _named(tool: str, note: str, day: str, extra: dict[str, str] | None = None) -> EvidenceRecord:
    """One claim, deliberately undated.

    The name carries a day, and for Telegram a clock with no zone attached.
    Neither is a moment this tool can put on a timeline without inventing the
    half nobody wrote down, so the day is reported as what it is - something
    the name says - and the claim itself stays undated.
    """
    return EvidenceRecord(
        source="messenger-name",
        tool=tool,
        note=note,
        fields={"dated": day, **(extra or {})},
    )


def _day(digits: str) -> str | None:
    """`20240115` as `2024-01-15`, or None where it is not a date at all.

    A pattern that matches the shape and not the calendar is a coincidence, and
    a file called `IMG-20241315-WA0001.jpg` was not sent in the thirteenth
    month. Reporting it would invent an arrival out of a string.
    """
    try:
        found = date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        return None
    return found.isoformat()
