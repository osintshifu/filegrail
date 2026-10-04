"""ISO 8601 as files write it, read the same way on every supported Python."""

from __future__ import annotations

import pytest

from filegrail.util import utc_timestamp


@pytest.mark.parametrize(
    ("written", "utc"),
    [
        ("2026-09-30T10:11:12Z", "2026-09-30T10:11:12Z"),
        ("2026-09-30T10:11:12+02:00", "2026-09-30T08:11:12Z"),
        # `datetime.fromisoformat` before 3.11 refused each of these.
        ("2026-09-30T10:11:12+0200", "2026-09-30T08:11:12Z"),
        ("2026-09-30T10:11:12-05", "2026-09-30T15:11:12Z"),
        ("2026-09-30T10:11:12.5Z", "2026-09-30T10:11:12.500000Z"),
        ("2026-09-30T10:11:12.1234567Z", "2026-09-30T10:11:12.123456Z"),
        ("20260930T101112Z", "2026-09-30T10:11:12Z"),
        # No offset is read as UTC; a date alone is its midnight.
        ("2026-09-30T10:11:12", "2026-09-30T10:11:12Z"),
        ("2026-09-30", "2026-09-30T00:00:00Z"),
    ],
)
def test_a_timestamp_is_read_as_the_same_instant_on_every_python(written: str, utc: str):
    assert utc_timestamp(written) == utc


@pytest.mark.parametrize(
    "written", [None, "", "not a date", "2026-13-01T00:00:00Z", "2026-09-30T25:00:00Z"]
)
def test_what_is_not_a_timestamp_is_none(written: str | None):
    assert utc_timestamp(written) is None
