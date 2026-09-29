"""The libc lookup behind creation times happens once per process, not per file.

`birth_time` reaches for statx(2) on Linux, and finding libc for it goes
through `ctypes.util.find_library`, which shells out to ldconfig. Done per
file, the lookup dwarfs the reading: on a local corpus of 105 files it was
0.53 s of a 0.89 s scan. The answer cannot change while the process runs, so
the handle - and equally the discovery that statx is not there - is worth
remembering the first time. The Darwin xattr reader keeps libc the same way,
because `read_xattr` runs per file too.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import importlib
import sys
import time
from pathlib import Path

import pytest

from filegrail import util


@pytest.fixture
def fresh():
    """`filegrail.util` with no libc handle remembered yet, restored after.

    What these tests watch is process-wide state, so each starts from a
    reloaded module rather than inheriting whatever an earlier test left
    behind - and reloads once more afterwards so it leaves nothing itself.
    """
    yield importlib.reload(util)
    importlib.reload(util)


@pytest.fixture
def lookups(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every libc lookup made, while still answering each one honestly."""
    calls: list[str] = []
    real = ctypes.util.find_library

    def counting(name: str) -> str | None:
        calls.append(name)
        return real(name)

    monkeypatch.setattr(ctypes.util, "find_library", counting)
    return calls


def test_a_second_file_does_not_pay_for_another_libc_lookup(
    fresh, lookups: list[str], tmp_path: Path
):
    one = tmp_path / "one.bin"
    two = tmp_path / "two.bin"
    one.write_bytes(b"first")
    two.write_bytes(b"second")

    fresh.birth_time(one)
    settled = len(lookups)

    fresh.birth_time(two)
    fresh.birth_time(one)

    assert len(lookups) == settled


def test_statx_being_unavailable_is_remembered_too(
    fresh, lookups: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """A process without statx answers None every time, but searches once."""
    if sys.platform != "linux":
        pytest.skip("only Linux reaches statx for a creation time")

    def refuse(*args: object, **kwargs: object) -> ctypes.CDLL:
        raise OSError("no libc to load")

    monkeypatch.setattr(ctypes, "CDLL", refuse)
    target = tmp_path / "opaque.bin"
    target.write_bytes(b"payload")

    assert fresh.birth_time(target) is None
    settled = len(lookups)

    assert fresh.birth_time(target) is None
    assert len(lookups) == settled


def test_the_darwin_xattr_reader_keeps_its_libc_handle(
    fresh, lookups: list[str], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sys, "platform", "darwin")

    fresh._darwin_libc()
    settled = len(lookups)

    fresh._darwin_libc()

    assert len(lookups) == settled


def test_a_fresh_file_is_born_about_now(tmp_path: Path):
    """The statx road still ends at a real timestamp once the handle is kept."""
    if sys.platform != "linux":
        pytest.skip("st_birthtime covers the platforms that do not need statx")

    before = time.time()
    target = tmp_path / "fresh.bin"
    target.write_bytes(b"payload")

    born = util.birth_time(target)

    if born is None:
        pytest.skip("this filesystem keeps no creation time")
    assert before - 2 <= born <= time.time() + 2
