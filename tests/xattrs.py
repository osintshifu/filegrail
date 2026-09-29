"""Writing an extended attribute, on whichever platform the test is running on.

The standard library exposes `os.setxattr` on Linux and nowhere else, which is
the same gap the reader has to close on the reading side. Writing one on macOS
means calling libc, so that is what this does - and it means the macOS half of
the reader is exercised on a macOS runner rather than only reasoned about.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
from pathlib import Path


def supported() -> bool:
    """Whether an attribute can be written here at all."""
    return hasattr(os, "setxattr") or sys.platform == "darwin"


def write(path: Path, name: str, value: bytes) -> bool:
    """Set one attribute, returning False where the filesystem refuses."""
    if hasattr(os, "setxattr"):
        try:
            os.setxattr(str(path), name, value)
        except OSError:
            return False
        return True
    if sys.platform != "darwin":
        return False
    return _darwin_write(path, name, value)


def _darwin_write(path: Path, name: str, value: bytes) -> bool:
    """`int setxattr(path, name, value, size, position, options)` on Darwin.

    Two arguments more than the Linux call, which is the whole reason the
    standard library declines to offer one interface for both.
    """
    library = ctypes.util.find_library("c")
    if library is None:  # pragma: no cover - only on a broken macOS
        return False
    libc = ctypes.CDLL(library, use_errno=True)
    libc.setxattr.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_int,
    ]
    libc.setxattr.restype = ctypes.c_int
    written = libc.setxattr(os.fsencode(str(path)), name.encode("utf-8"), value, len(value), 0, 0)
    return written == 0
