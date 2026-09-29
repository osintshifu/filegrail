"""Files carried inside documents and messages, read as files of their own.

A PDF can carry an attachment, a message the files sent with it, and an Office
document an object packaged from another file. Each is read under its own
name by the same readers a file on disk gets, and reported as a file inside
its carrier, the way a member of an archive already is: with its own record,
its own evidence and the carrier as its parent. What the carried file says
stays its own; a photograph attached to a PDF does not give the PDF a camera.

The work is bounded the way an archive's is: the same number of files opened
per carrier and the same size per file, and a carrier itself is only opened
below a size of its own.
"""

from __future__ import annotations

import email
import email.policy
import re
import zipfile
import zlib
from collections.abc import Callable, Iterable
from pathlib import Path

from ..util import Allowance
from .archives import _MAX_MEMBER_BYTES, _MAX_READ, Member, _zip_time, read_member
from .embedded.documents import (
    OOXML_SUFFIXES,
    PDF_SUFFIXES,
    _inflated_streams,
    _parse_pdf_date,
    _pdf_string,
)
from .embedded.ole import SUFFIXES as OLE_SUFFIXES
from .embedded.ole import attachments, packaged_objects
from .mail import OUTLOOK_SUFFIXES
from .mail import SUFFIXES as MAIL_SUFFIXES

#: A carrier larger than this is not opened for what it carries.
_MAX_CARRIER_BYTES = 256 * 1024 * 1024

#: One carried file: its name inside the carrier, its bytes, and a time where
#: the carrier records one.
Carried = tuple[str, bytes, "str | None"]

_Lister = Callable[[bytes], Iterable[Carried]]


def read_children(
    path: Path, *, hashing: bool = False, carried: Allowance | None = None
) -> list[Member]:
    """The files carried inside `path` that a reader had something to say about."""
    lister = _lister(path.suffix.lower())
    if lister is None:
        return []
    try:
        if path.stat().st_size > _MAX_CARRIER_BYTES:
            return []
        data = path.read_bytes()
    except OSError:
        return []

    found: list[Member] = []
    names: set[str] = set()
    try:
        for opened, (name, raw, mtime) in enumerate(lister(data)):
            if opened >= _MAX_READ:
                break
            if carried is not None:
                if carried.spent:
                    break
                carried.take(len(raw))
            if len(raw) > _MAX_MEMBER_BYTES:
                continue
            evidence = read_member(name, raw)
            if not evidence:
                continue
            name = _unique(name, names)
            digest = _sha256(raw) if hashing else None
            found.append(Member(name, len(raw), mtime, digest, evidence))
    except (ValueError, zlib.error, zipfile.BadZipFile, EOFError, RuntimeError):
        return found
    return found


def _lister(suffix: str) -> _Lister | None:
    if suffix in PDF_SUFFIXES:
        return _pdf_children
    if suffix in MAIL_SUFFIXES:
        return _mail_children
    if suffix in OUTLOOK_SUFFIXES:
        return _outlook_children
    if suffix in OOXML_SUFFIXES:
        return _ooxml_children
    if suffix in OLE_SUFFIXES:
        return _ole_children
    return None


def _unique(name: str, taken: set[str]) -> str:
    """Two attachments called `scan.pdf` are two files; the second says so."""
    candidate, count = name, 1
    while candidate in taken:
        count += 1
        stem, dot, suffix = name.rpartition(".")
        candidate = f"{stem} ({count}).{suffix}" if dot else f"{name} ({count})"
    taken.add(candidate)
    return candidate


def _sha256(raw: bytes) -> str:
    import hashlib

    return hashlib.sha256(raw).hexdigest()


# --- PDF ---------------------------------------------------------------------

#: An object that opens a stream, with its dictionary. The lookahead keeps the
#: match inside one object, so an object without a stream is never joined to
#: the next one that has.
_PDF_STREAM_OBJECT = re.compile(
    rb"(?P<number>\d+)\s+(?P<generation>\d+)\s+obj\s*<<(?P<dictionary>(?:(?!endobj).)*?)>>"
    rb"\s*stream\r?\n",
    re.DOTALL,
)
_PDF_EMBEDDED_FILE = re.compile(rb"/Type\s*/EmbeddedFile\b")
_PDF_LENGTH = re.compile(rb"/Length\s+(\d+)(?!\s+\d+\s+R)")
_PDF_FILTER = re.compile(rb"/Filter\s*(?:\[\s*)?/(\w+)")
_PDF_FILESPEC = re.compile(rb"/Type\s*/Filespec\b")
_PDF_FILESPEC_STREAM = re.compile(rb"/EF\s*<<[^>]*?/U?F\s*(\d+)\s+\d+\s+R")
_PDF_ENDSTREAM = re.compile(rb"\r?\n?endstream")


def _pdf_children(data: bytes) -> Iterable[Carried]:
    names = _pdf_filespec_names(data + _inflated_streams(data))
    for match in _PDF_STREAM_OBJECT.finditer(data):
        dictionary = match.group("dictionary")
        if not _PDF_EMBEDDED_FILE.search(dictionary):
            continue
        body = _pdf_stream_body(data, match.end(), dictionary)
        if body is None:
            continue
        number = int(match.group("number"))
        name = names.get(number) or f"object {number}"
        modified = _parse_pdf_date(_pdf_string(dictionary, b"ModDate"))
        yield name, body, modified


def _pdf_stream_body(data: bytes, start: int, dictionary: bytes) -> bytes | None:
    """The stream's bytes, decoded where the filter is one an attachment uses."""
    length = _PDF_LENGTH.search(dictionary)
    end = -1
    if length is not None:
        end = start + int(length.group(1))
        if end > len(data) or not _PDF_ENDSTREAM.match(data, end):
            end = -1
    if end < 0:
        closing = _PDF_ENDSTREAM.search(data, start)
        if closing is None:
            return None
        end = closing.start()
    raw = data[start:end]
    filters = _PDF_FILTER.findall(dictionary)
    if not filters:
        return raw
    if filters != [b"FlateDecode"]:
        return None
    inflated = zlib.decompressobj().decompress(raw, _MAX_MEMBER_BYTES + 1)
    return inflated if len(inflated) <= _MAX_MEMBER_BYTES else None


def _pdf_filespec_names(data: bytes) -> dict[int, str]:
    """Which stream object each file specification names, and what it calls it."""
    names: dict[int, str] = {}
    for match in _PDF_FILESPEC.finditer(data):
        window = data[max(0, match.start() - 512) : match.end() + 512]
        reference = _PDF_FILESPEC_STREAM.search(window)
        name = _pdf_string(window, b"UF") or _pdf_string(window, b"F")
        if reference is not None and name:
            names.setdefault(int(reference.group(1)), Path(name.replace("\\", "/")).name)
    return names


# --- messages ----------------------------------------------------------------


def _mail_children(data: bytes) -> Iterable[Carried]:
    message = email.message_from_bytes(data, policy=email.policy.default)
    for part in message.walk():
        if part.is_multipart():
            continue
        name = part.get_filename()
        if not name:
            continue
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            yield Path(name.replace("\\", "/")).name, payload, None


def _outlook_children(data: bytes) -> Iterable[Carried]:
    for name, raw in attachments(data):
        yield name, raw, None


# --- Office ------------------------------------------------------------------

_OOXML_EMBEDDING = re.compile(r"(?:^|/)embeddings/[^/]+$")


def _ooxml_children(data: bytes) -> Iterable[Carried]:
    import io

    with zipfile.ZipFile(io.BytesIO(data)) as package:
        for info in package.infolist():
            if info.is_dir() or not _OOXML_EMBEDDING.search(info.filename):
                continue
            if info.file_size > _MAX_MEMBER_BYTES:
                continue
            raw = package.read(info)
            if Path(info.filename).suffix.lower() == ".bin":
                for name, payload in packaged_objects(raw):
                    yield f"{info.filename}/{name}", payload, None
            else:
                yield info.filename, raw, _zip_time(info.date_time)


def _ole_children(data: bytes) -> Iterable[Carried]:
    for name, raw in packaged_objects(data):
        yield name, raw, None
