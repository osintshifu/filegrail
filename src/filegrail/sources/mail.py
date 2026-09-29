"""What a saved message says about how it travelled.

`Received:` headers are the only part of an email not written by the sender.
Each mail server prepends its own as the message passes through, so they read
from the bottom up, and the topmost was written by the recipient's own server -
the one hop nobody but the recipient could have forged. Every hop below it was
written by a machine the sender may control, which is why they are not ranked
alike: the chain is evidence, and how much of it to believe depends on where in
the chain you are reading.

Everything else - who it says it is from, what it says the subject was, which
client it says composed it - is the message describing itself, checked by
nobody, and it is kept apart from the delivery record for that reason.
"""

from __future__ import annotations

import re
from datetime import timezone
from email.message import Message
from email.parser import BytesHeaderParser
from email.utils import parsedate_to_datetime
from pathlib import Path

from ..models import EvidenceRecord

SUFFIXES = {".eml"}

#: A saved Outlook message is a compound document rather than a file of
#: headers, but it keeps the same RFC 5322 block in a stream of its own - and
#: with it the same `Received:` chain, reached by a different door.
OUTLOOK_SUFFIXES = {".msg"}

#: [MS-OXMSG] names a property stream `__substg1.0_` then the property tag then
#: its type, `001F` for UTF-16 text and `001E` for 8-bit. Both spellings of a
#: tag are asked for, because which one a message carries depends on the
#: sender's Outlook and not on anything in the message.
_TRANSPORT_HEADERS = ("__substg1.0_007D001F", "__substg1.0_007D001E")

#: What a message says about itself when it never crossed the internet and so
#: has no headers to say it with. An Exchange delivery between two mailboxes on
#: one server is the ordinary case, not an edge one.
_MAPI_HEADERS = {
    "Subject": ("__substg1.0_0037001F", "__substg1.0_0037001E"),
    "From": ("__substg1.0_0C1F001F", "__substg1.0_0C1F001E"),
    "Sender": ("__substg1.0_0C1A001F", "__substg1.0_0C1A001E"),
    "To": ("__substg1.0_0E04001F", "__substg1.0_0E04001E"),
    "Message-ID": ("__substg1.0_1035001F", "__substg1.0_1035001E"),
}

#: Headers sit at the front. A message with more than this before its body is
#: not a message anybody sent.
_WINDOW = 512 * 1024

#: A mailing list legitimately adds a dozen hops. Hundreds is a message built to
#: make a report unreadable.
_MAX_HOPS = 40

_MAX_VALUE = 1024

#: What the sender says about the message, worth naming rather than dumping.
_HEADERS = (
    "From",
    "To",
    "Cc",
    "Reply-To",
    "Return-Path",
    "Sender",
    "Subject",
    "Date",
    "Message-ID",
    "In-Reply-To",
    "References",
    "X-Mailer",
    "User-Agent",
    "X-Originating-IP",
    "Content-Type",
    "List-Id",
)

#: The client that composed the message, under the two names clients use.
_COMPOSER = ("X-Mailer", "User-Agent")

_FROM = re.compile(r"\bfrom\s+([^\s(;]+)", re.I)
_BY = re.compile(r"\bby\s+([^\s(;]+)", re.I)
_WITH = re.compile(r"\bwith\s+([^\s(;]+)", re.I)
_ID = re.compile(r"\bid\s+([^\s(;]+)", re.I)
_FOR = re.compile(r"\bfor\s+<?([^>\s;]+)", re.I)

#: The address the receiving server actually saw, as against the name the
#: connecting host claimed for itself.
_ADDRESS = re.compile(r"\[(?:IPv6:)?([0-9A-Fa-f:.]{3,45})\]")


def read_mail(path: Path) -> list[EvidenceRecord]:
    """Return the delivery record and the message's own headers."""
    suffix = path.suffix.lower()
    if suffix in SUFFIXES:
        try:
            with path.open("rb") as handle:
                return _claims(BytesHeaderParser().parsebytes(handle.read(_WINDOW)))
        except (OSError, ValueError):
            return []
    if suffix in OUTLOOK_SUFFIXES:
        return _outlook(path)
    return []


def _claims(message: Message) -> list[EvidenceRecord]:
    """The hops, then what the message says about itself."""
    hops = message.get_all("Received") or []
    found = [
        _hop(value, "email-delivery" if position == 0 else "email-relay")
        for position, value in enumerate(hops[:_MAX_HOPS])
    ]
    if header := _self_description(message):
        found.append(header)
    return [origin for origin in found if origin is not None]


def _outlook(path: Path) -> list[EvidenceRecord]:
    """Read a compound document as the message it is.

    Spec-only: assembled from [MS-OXMSG], and never run against a file Outlook
    wrote, because nothing on the developer's machine produces one.
    """
    from .embedded.ole import read_streams

    wanted = [*_TRANSPORT_HEADERS, *(name for pair in _MAPI_HEADERS.values() for name in pair)]
    streams = read_streams(path, wanted)
    if not streams:
        return []

    for name in _TRANSPORT_HEADERS:
        if (raw := streams.get(name)) is not None and (text := _text(name, raw)):
            return _claims(BytesHeaderParser().parsebytes(text.encode("utf-8", "replace")))

    # No headers means the message never crossed the internet, so there is no
    # delivery record to be had and none is invented. What it says about itself
    # is still worth reporting, as exactly that.
    fields = {}
    for label, names in _MAPI_HEADERS.items():
        for name in names:
            if (raw := streams.get(name)) is not None and (text := _text(name, raw)):
                fields[label] = " ".join(text.split())[:_MAX_VALUE]
                break
    if not fields:
        return []

    subject = fields.get("Subject")
    return [
        EvidenceRecord(
            source="email-header",
            note=f"subject {subject}" if subject else None,
            fields=fields,
        )
    ]


def _text(name: str, raw: bytes) -> str | None:
    """Decode a property stream by the type its name declares.

    An odd byte count cannot be UTF-16. Decoding it anyway would drop the last
    byte and hand back a name a character short, which is worse than nothing
    because it looks like a name.
    """
    if name.endswith("001F"):
        if len(raw) % 2:
            return None
        return raw.decode("utf-16-le", "replace").rstrip("\x00") or None
    return raw.decode("utf-8", "replace").rstrip("\x00") or None


def _hop(value: str, source: str) -> EvidenceRecord | None:
    """One server's note of taking the message from another."""
    said = " ".join(value.split())
    fields = {
        name: found.group(1)
        for name, pattern in (
            ("From", _FROM),
            ("By", _BY),
            ("With", _WITH),
            ("Id", _ID),
            ("For", _FOR),
        )
        if (found := pattern.search(said))
    }
    if address := _ADDRESS.search(said):
        fields["ConnectingAddress"] = address.group(1)
    if not fields:
        return None

    claimed = fields.get("From")
    seen = fields.get("ConnectingAddress")
    note = " from ".join(part for part in ("received", claimed) if part)
    if seen and seen != claimed:
        note = f"{note} at {seen}"

    return EvidenceRecord(
        source=source,
        # The server that wrote the line, which is the one thing in it that
        # server knew first-hand.
        tool=fields.get("By"),
        at=_moment(said),
        note=note,
        fields=fields,
    )


def _self_description(message: Message) -> EvidenceRecord | None:
    """What the message says about itself, none of which anybody checked."""
    fields = {}
    for name in _HEADERS:
        value = message.get(name)
        if value and (text := " ".join(str(value).split())):
            fields[name] = text[:_MAX_VALUE]
    if not fields:
        return None

    subject = fields.get("Subject")
    return EvidenceRecord(
        source="email-header",
        tool=next((fields[name] for name in _COMPOSER if name in fields), None),
        at=_moment(fields.get("Date", ""), whole=True),
        note=f"subject {subject}" if subject else None,
        fields=fields,
    )


def _moment(said: str, *, whole: bool = False) -> str | None:
    """The timestamp a header carries, in UTC.

    A `Received:` header puts it after the last semicolon, behind the `for`
    address which contains one of its own - so it is taken from the right rather
    than searched for.
    """
    stamp = said if whole else said.rpartition(";")[2]
    if not stamp.strip():
        return None
    try:
        when = parsedate_to_datetime(stamp.strip())
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        # `-0000` means the writer declined to say. UTC is the reading that
        # invents the least.
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
