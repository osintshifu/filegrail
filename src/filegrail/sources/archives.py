"""Propagate an archive's origin to the files extracted from it.

Extracting a download breaks the chain: the archive carries a browser record,
the files inside carry nothing. Matching archive members against files on disk
restores the link, which is often the difference between a directory with no
recorded origin and a complete answer.

Members are matched on name and uncompressed size. That is deliberately strict
enough to avoid claiming an origin for an unrelated file with a common name,
and the resulting origin is reported below a direct download.

An archive may hold several members sharing a base name at different sizes -
a top-level README.md and a second one under examples/, say - so every size
seen for a name is kept, not just the last.
"""

from __future__ import annotations

import bz2
import gzip
import hashlib
import lzma
import tarfile
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import TypeVar

from ..models import CONTAINER_MEMBER, EvidenceRecord
from ..util import Allowance, iso
from .c2pa import read_c2pa_manifest
from .compression import DAMAGED_STREAM
from .embedded import SUFFIXES, read_embedded_metadata, read_maker_notes
from .iptc import read_iptc
from .xmp import read_xmp

ARCHIVE_SUFFIXES = {".zip", ".whl", ".jar", ".tar", ".tgz", ".gz", ".bz2", ".xz"}

#: The most a long-name or extended-attribute header may say it carries. `tarfile`
#: reads such a header whole, into memory, on the size the header states, and
#: that size is a number the archive's author wrote: 859 bytes of bzip2 can say
#: a gigabyte. Real ones hold a path or a few attributes.
_MAX_HEADER_BYTES = 1024 * 1024
_HEADER_TYPES = (
    tarfile.GNUTYPE_LONGNAME,
    tarfile.GNUTYPE_LONGLINK,
    tarfile.XHDTYPE,
    tarfile.XGLTYPE,
    tarfile.SOLARIS_XHDTYPE,
)


_Entry = TypeVar("_Entry", bound=tarfile.TarInfo)


def _within_bound(info: _Entry) -> _Entry:
    if info.type in _HEADER_TYPES and info.size > _MAX_HEADER_BYTES:
        raise tarfile.ReadError("a header declares more than is read")
    return info


class _BoundedInfo(tarfile.TarInfo):
    """A tar entry that refuses a header larger than any real one.

    Both entry points are bounded because `tarfile` has two: current releases
    of every supported Python build an entry through `_frombuf`, and older ones
    through the public `frombuf`, which the newer ones no longer call.
    """

    @classmethod
    def frombuf(cls, buf: bytes | bytearray, encoding: str, errors: str) -> _BoundedInfo:
        return _within_bound(super().frombuf(buf, encoding, errors))

    @classmethod
    def _frombuf(
        cls, buf: bytes | bytearray, encoding: str, errors: str, **options: bool
    ) -> _BoundedInfo:
        return _within_bound(super()._frombuf(buf, encoding, errors, **options))  # type: ignore[misc,no-any-return]


def _open_tar(path: Path) -> tarfile.TarFile | None:
    """The tar at `path`, or None where it is not one.

    Not `tarfile.is_tarfile` followed by `tarfile.open`: that is two opens, and
    neither bounds what a header may ask to have read.
    """
    try:
        return tarfile.open(path, tarinfo=_BoundedInfo)
    except tarfile.TarError:
        return None


# Cap the work done on a single archive; a member list is cheap, but a
# deliberately hostile archive should not be able to stall a scan.
_MAX_MEMBERS = 50_000

#: What a package raises when it is not the package it says it is. `zipfile`
#: supplies the two that are neither `OSError` nor `ValueError`: a file that is
#: no archive at all, and one whose members name a compression method this
#: interpreter cannot undo - which a crafted archive says in two bytes per
#: member, and which used to leave here as `NotImplementedError` and end the run.
_UNREADABLE = (
    OSError,
    zipfile.BadZipFile,
    tarfile.TarError,
    EOFError,
    ValueError,
    NotImplementedError,
    *DAMAGED_STREAM,
)


def is_archive(path: Path) -> bool:
    return path.suffix.lower() in ARCHIVE_SUFFIXES


def list_members(path: Path) -> dict[str, set[int]]:
    """Return {member base name: every uncompressed size seen for it}."""
    members: dict[str, set[int]] = {}

    def record(name: str, size: int) -> None:
        members.setdefault(Path(name).name, set()).add(size)

    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist()[:_MAX_MEMBERS]:
                    if not info.is_dir():
                        record(info.filename, info.file_size)
            return members

        if (listed := _open_tar(path)) is not None:
            with listed as bundle:
                for count, entry in enumerate(bundle):
                    if count >= _MAX_MEMBERS:
                        break
                    if entry.isfile():
                        record(entry.name, entry.size)
            return members
    except _UNREADABLE:
        return {}

    return members


#: How many members of one archive are opened for their metadata. An archive
#: of ten thousand photographs is not read ten thousand times: the section
#: exists to say what kind of thing is in there, and the first few answer that.
_MAX_READ = 25

#: A member larger than this is not copied out to be read. The readers all seek
#: rather than slurp, but the copy that precedes them does not.
_MAX_MEMBER_BYTES = 64 * 1024 * 1024


@dataclass(slots=True)
class Member:
    """One file inside an archive that a reader had something to say about."""

    name: str
    size: int
    mtime: str | None
    sha256: str | None
    evidence: list[EvidenceRecord]


def read_members(
    path: Path,
    *,
    hashing: bool = False,
    carried: Allowance | None = None,
    cut: list[str] | None = None,
) -> list[Member]:
    """The members of the archive that carry evidence, each read as a file.

    Read under its own name, with its own size and time, so what a member says
    stays the member's: a photograph taken in 2008 inside a zip written last
    week does not date the zip, and its fix is not the zip's location.

    The archive's path is added to `cut` when something inside it went unread -
    members past the limit, past the allowance, or damaged - because a list of
    members that is short for any of those reasons looks like an archive that
    simply held little.
    """
    found: list[Member] = []
    complete = True
    try:
        with _opened(path) as archive:
            if archive is None:
                return []
            for opened, (name, size, mtime, extract) in enumerate(archive):
                if opened >= _MAX_READ:
                    complete = False
                    break
                if carried is not None and carried.spent:
                    # One archive can hold more than the whole scan's allowance,
                    # so it is checked here and not only between carriers.
                    complete = False
                    break
                try:
                    raw = extract()
                except (*_UNREADABLE, RuntimeError):
                    complete = False
                    continue
                # Charged for the bytes that came out, not for the ones that went
                # on to say something: decompressing is the work being bounded.
                if carried is not None:
                    carried.take(len(raw))
                evidence = read_member(name, raw)
                if not evidence:
                    continue
                digest = hashlib.sha256(raw).hexdigest() if hashing else None
                found.append(Member(name, size, mtime, digest, evidence))
    except _UNREADABLE:
        complete = False
    if not complete and cut is not None:
        cut.append(str(path))
    return found


#: A member as the archive lists it: name, size, time, and a way to its bytes.
_Listed = tuple[str, int, "str | None", Callable[[], bytes]]


@contextmanager
def _opened(path: Path) -> Iterator[Iterator[_Listed] | None]:
    """Yield (name, size, mtime, a callable returning the bytes) for each real file."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:

            def from_zip() -> Iterator[_Listed]:
                for info in archive.infolist()[:_MAX_MEMBERS]:
                    if not info.is_dir() and info.file_size <= _MAX_MEMBER_BYTES:
                        yield (
                            info.filename,
                            info.file_size,
                            _zip_time(info.date_time),
                            partial(archive.read, info),
                        )

            yield from_zip()
        return

    if (opened := _open_tar(path)) is not None:
        with opened as bundle:

            def from_tar() -> Iterator[_Listed]:
                for count, entry in enumerate(bundle):
                    if count >= _MAX_MEMBERS:
                        break
                    if entry.isfile() and entry.size <= _MAX_MEMBER_BYTES:
                        yield (
                            entry.name,
                            entry.size,
                            iso(entry.mtime),
                            partial(_tar_bytes, bundle, entry),
                        )

            yield from_tar()
        return

    if path.suffix.lower() in _SINGLE_FILE:
        yield _from_single(path)
        return

    yield None


#: A compressed file that is not a tar holds one file, which the suffix names
#: by leaving it off: `holiday.jpg.gz` carries `holiday.jpg`.
_SINGLE_FILE = {".gz", ".bz2", ".xz"}


def _from_single(path: Path) -> Iterator[_Listed]:
    # A damaged stream raises, to `read_members`, which names the file as read in
    # part; it is not swallowed here, where nothing would say that it happened.
    suffix = path.suffix.lower()
    if suffix == ".gz":
        with gzip.open(path, "rb") as unzipped:
            raw = unzipped.read(_MAX_MEMBER_BYTES + 1)
    elif suffix == ".bz2":
        with bz2.open(path, "rb") as unzipped:
            raw = unzipped.read(_MAX_MEMBER_BYTES + 1)
    else:
        with lzma.open(path, "rb") as unzipped:
            raw = unzipped.read(_MAX_MEMBER_BYTES + 1)
    if len(raw) > _MAX_MEMBER_BYTES:
        raise ValueError("larger than is read")
    yield (path.stem, len(raw), None, lambda: raw)


def _zip_time(stamp: tuple[int, int, int, int, int, int]) -> str | None:
    """A zip's DOS time, which names no zone; read as a clock reading in UTC."""
    try:
        return datetime(*stamp, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


def _tar_bytes(bundle: tarfile.TarFile, entry: tarfile.TarInfo) -> bytes:
    """One member's bytes, or none where the tar declines to open it."""
    handle = bundle.extractfile(entry)
    return handle.read() if handle is not None else b""


def read_member(name: str, raw: bytes) -> list[EvidenceRecord]:
    """Run the ordinary readers over one file carried inside another.

    The bytes are copied out to a temporary file under the member's own suffix,
    so a photograph inside a zip, a PDF or a message is read by the same
    readers, and read the same way, as one on disk.
    """
    suffix = Path(name).suffix.lower()
    if suffix not in SUFFIXES:
        return []

    with tempfile.TemporaryDirectory(prefix="filegrail-") as room:
        copy = Path(room) / f"member{suffix}"
        try:
            copy.write_bytes(raw)
        except OSError:
            return []

        found = []
        for reader in (read_c2pa_manifest, read_embedded_metadata, read_maker_notes, read_iptc):
            claim = reader(copy)
            if claim is not None:
                found.append(claim)
        found.extend(read_xmp(copy))
        return found


def inherited_origin(
    record: EvidenceRecord,
    archive_path: str,
    member: str | None = None,
    *,
    source: str = "archive-member",
) -> EvidenceRecord:
    """Rewrite an archive's own origin as one for a file that came out of it.

    The member did not arrive the way the archive did; it arrived *inside* the
    thing that arrived that way. The match basis is what keeps the difference
    visible, because the URL on the record is the archive's and not the file's.

    With `member`, the file is the member itself, read inside the archive; the
    match is membership and nothing weaker. Without it, the file is one on disk
    that matched a member by name and exact size.
    """
    archive_name = Path(archive_path).name
    if member is not None:
        note = f"inside {archive_name}"
        basis = _basis(source, archive_name)
    else:
        note = f"extracted from {archive_name}"
        basis = f"member of {archive_name}, matched by name and exact size"
    return replace(
        record,
        source=source,
        match=CONTAINER_MEMBER,
        match_note=basis,
        container=archive_path,
        bytes=None,
        mime=None,
        sha256=None,
        note=f"{record.note}; {note}" if record.note else note,
        where={"member": member} if member is not None else record.where,
    )


def _basis(source: str, carrier: str) -> str:
    """How the file is tied to its carrier: membership, said in the carrier's terms."""
    return f"embedded in {carrier}" if source == "embedded-file" else f"member of {carrier}"


def member_origin(
    archive_path: str, member: str, *, source: str = "archive-member"
) -> EvidenceRecord:
    """The one thing known about how a member got here: it is inside the archive."""
    return EvidenceRecord(
        source=source,
        match=CONTAINER_MEMBER,
        match_note=_basis(source, Path(archive_path).name),
        container=archive_path,
        note=f"inside {Path(archive_path).name}",
        where={"member": member},
    )
