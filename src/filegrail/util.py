from __future__ import annotations

import ctypes
import ctypes.util
import functools
import hashlib
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath

_EPOCH_1601_OFFSET = 11_644_473_600  # seconds between 1601-01-01 and 1970-01-01

#: A drive letter or a UNC prefix: the two ways a path says it is a Windows one.
_WINDOWS_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


#: macOS takes two arguments the Linux call does not - a position for resource
#: forks and a flags word - which is why the standard library offers one
#: interface and not the other.
_DARWIN_GETXATTR = (
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.c_uint32,
    ctypes.c_int,
)


@dataclass
class Allowance:
    """What is left of a scan's allowance for reading what files carry.

    Opening a carrier is the one cost of a scan the tree does not show: a
    directory of small archives can hold more than the disk it sits on. Held by
    the scan and handed to the readers, so what is counted is the bytes actually
    extracted, whether or not the member turned out to carry evidence. Counting
    only the members that produced evidence would let a thousand archives of
    unreadable content pass the allowance untouched, which is what happened.
    """

    limit: int | None = None
    used: int = 0

    @property
    def spent(self) -> bool:
        return self.limit is not None and self.used >= self.limit

    def take(self, size: int) -> None:
        self.used += size


def xattrs_readable() -> bool:
    """Whether an extended attribute can be read on this platform at all."""
    return hasattr(os, "getxattr") or _darwin_libc() is not None


def read_xattr(path: Path | str, name: str) -> bytes | None:
    """One extended attribute, or None where there is none to read.

    `os.getxattr` is a Linux interface. The standard library does not expose
    the call on macOS, so every reader here that guarded on `hasattr` did
    nothing on macOS - including the one for `kMDItemWhereFroms`, which is a
    macOS attribute and the reason the guard existed. Reading it means calling
    libc, the same way creation timestamps already do.
    """
    if hasattr(os, "getxattr"):
        try:
            return os.getxattr(str(path), name)
        except OSError:
            return None
    libc = _darwin_libc()
    if libc is None:
        return None
    return _darwin_read(libc, str(path), name)


def _darwin_libc() -> ctypes.CDLL | None:
    if sys.platform != "darwin":
        return None
    return _darwin_handle()


@functools.cache
def _darwin_handle() -> ctypes.CDLL | None:
    """libc, found once and kept: `read_xattr` runs per file.

    Only the expensive part is remembered. The platform check above stays
    live because tests steer it through `sys.platform`, and a frozen first
    answer would pin every later call to whatever ran first.
    """
    library = ctypes.util.find_library("c")
    if library is None:  # pragma: no cover - only on a broken macOS
        return None
    try:
        return ctypes.CDLL(library, use_errno=True)
    except OSError:  # pragma: no cover - only on a broken macOS
        return None


def _darwin_read(libc: ctypes.CDLL, path: str, name: str) -> bytes | None:
    """Ask for the size first, then for the value: the attribute can change."""
    libc.getxattr.argtypes = list(_DARWIN_GETXATTR)
    libc.getxattr.restype = ctypes.c_ssize_t
    encoded_path = os.fsencode(path)
    encoded_name = name.encode("utf-8")

    size = libc.getxattr(encoded_path, encoded_name, None, 0, 0, 0)
    if size <= 0:
        return None
    buffer = ctypes.create_string_buffer(size)
    read = libc.getxattr(encoded_path, encoded_name, buffer, size, 0, 0)
    if read < 0:
        return None
    return buffer.raw[:read]


def basename(recorded: str) -> str:
    """The file name out of a path that another machine may have written.

    `Path` knows only the separator of the machine reading it, so a Windows
    download record split with `PosixPath` has no directory at all and its
    whole spelling comes back as the name. Under `--home` that is the ordinary
    case rather than a curiosity, and it makes every name match silently fail.

    A backslash counts as a separator only where the path announces itself as a
    Windows one, because a backslash is a legal character in a POSIX file name
    and mangling those would trade one silent failure for another.
    """
    if _WINDOWS_PATH.match(recorded):
        return PureWindowsPath(recorded).name
    return PurePosixPath(recorded).name


def iso(ts: float | None) -> str | None:
    """Format a POSIX timestamp as UTC ISO-8601, or None."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def chrome_time(value: int | None) -> str | None:
    """Chromium stores microseconds since 1601-01-01 UTC."""
    if not value:
        return None
    return iso(value / 1_000_000 - _EPOCH_1601_OFFSET)


def firefox_time(value: int | None) -> str | None:
    """Firefox stores microseconds since the Unix epoch."""
    if not value:
        return None
    return iso(value / 1_000_000)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def birth_time(path: Path) -> float | None:
    """Return the file creation time where the platform exposes one.

    macOS and Windows report it through os.stat. Linux needs statx(2), which
    CPython does not expose, so it is read directly when available.
    """
    try:
        stat = path.stat()
    except OSError:
        return None

    # macOS and the BSDs carry it on the stat result; the type stubs describe
    # Linux, where it is absent, which is exactly what the guard is for.
    if hasattr(stat, "st_birthtime"):
        return float(stat.st_birthtime)  # type: ignore[attr-defined]
    if os.name == "nt":
        return float(stat.st_ctime)
    return _statx_btime(path)


class _StatxTimestamp(ctypes.Structure):
    _fields_ = [
        ("tv_sec", ctypes.c_int64),
        ("tv_nsec", ctypes.c_uint32),
        ("__reserved", ctypes.c_int32),
    ]


class _Statx(ctypes.Structure):
    _fields_ = [
        ("stx_mask", ctypes.c_uint32),
        ("stx_blksize", ctypes.c_uint32),
        ("stx_attributes", ctypes.c_uint64),
        ("stx_nlink", ctypes.c_uint32),
        ("stx_uid", ctypes.c_uint32),
        ("stx_gid", ctypes.c_uint32),
        ("stx_mode", ctypes.c_uint16),
        ("__spare0", ctypes.c_uint16),
        ("stx_ino", ctypes.c_uint64),
        ("stx_size", ctypes.c_uint64),
        ("stx_blocks", ctypes.c_uint64),
        ("stx_attributes_mask", ctypes.c_uint64),
        ("stx_atime", _StatxTimestamp),
        ("stx_btime", _StatxTimestamp),
        ("stx_ctime", _StatxTimestamp),
        ("stx_mtime", _StatxTimestamp),
        ("stx_rdev_major", ctypes.c_uint32),
        ("stx_rdev_minor", ctypes.c_uint32),
        ("stx_dev_major", ctypes.c_uint32),
        ("stx_dev_minor", ctypes.c_uint32),
        ("__spare2", ctypes.c_uint64 * 14),
    ]


_STATX_BTIME = 0x800
_AT_FDCWD = -100


@functools.cache
def _statx_func() -> Callable[..., int] | None:
    """statx(2) out of libc, or None where there is nothing to call.

    Locating libc goes through ldconfig and costs more than the call it
    enables; done per file it was most of a scan's runtime. Neither the
    handle nor its absence changes within a process, so one answer serves
    every file - the refusal included.
    """
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
        return libc.statx
    except (OSError, AttributeError):
        return None


def _statx_btime(path: Path) -> float | None:
    """Read stx_btime via statx(2). Returns None when unsupported."""
    statx = _statx_func()
    if statx is None:
        return None

    buffer = _Statx()
    result = statx(
        ctypes.c_int(_AT_FDCWD),
        ctypes.c_char_p(os.fsencode(str(path))),
        ctypes.c_int(0),
        ctypes.c_uint(_STATX_BTIME),
        ctypes.byref(buffer),
    )
    if result != 0 or not (buffer.stx_mask & _STATX_BTIME):
        return None
    return float(buffer.stx_btime.tv_sec) + float(buffer.stx_btime.tv_nsec) / 1e9
