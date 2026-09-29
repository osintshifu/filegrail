"""Every format this project says it reads, read.

`docs/FORMATS.md` and the README tables are already held against the readers by
`test_documented_formats.py`, which checks that the two lists agree. Agreeing is
not the same as being true: both would still agree if an extension were added to
a reader's set and nothing could ever be read under it.

This is the other half. One specimen per route, written under every extension
that route claims, and the values it carries have to come back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from filegrail.sources.embedded import SUFFIXES, read_embedded_metadata

from .specimens import SPECIMENS, Specimen, reported

_CASES = [
    pytest.param(specimen, suffix, id=f"{specimen.route}{suffix}")
    for specimen in SPECIMENS
    for suffix in sorted(specimen.suffixes)
]


@pytest.mark.parametrize("specimen,suffix", _CASES)
def test_a_format_the_project_claims_is_a_format_it_reads(
    tmp_path: Path, specimen: Specimen, suffix: str
):
    """The same bytes under every name its route claims. An extension that only
    ever appeared in a set and a documentation table fails here."""
    written = tmp_path / f"specimen{suffix}"
    specimen.write(written)

    found = read_embedded_metadata(written)

    assert found is not None, f"{specimen.route} read nothing under {suffix}"
    assert found.block == specimen.block
    said = reported(found)
    for name, value in specimen.expect.items():
        assert said.get(name) == value, f"{name}: {said.get(name)!r} is not {value!r}"


def test_every_format_the_readers_claim_has_a_specimen():
    """What this catches is a reader arriving with a suffix set of its own.

    Not an extension added to a set that already has a specimen: that one is
    swept automatically, under the specimen its route already owns, and it
    fails above if the reader cannot actually read it. Checked by mutation
    both ways round, because a completeness test comparing two views of one
    source proves nothing and reads exactly like one that does.
    """
    covered: set[str] = set()
    for specimen in SPECIMENS:
        covered |= set(specimen.suffixes)

    assert covered == set(SUFFIXES), {
        "claimed with no specimen": sorted(set(SUFFIXES) - covered),
        "specimen for something no reader claims": sorted(covered - set(SUFFIXES)),
    }


def test_no_two_specimens_answer_for_one_format():
    """Two specimens over one extension means one of them is not being checked
    against what the dispatcher actually does with it: the reader that runs
    first answers, and the other's expectations are then about nothing."""
    seen: dict[str, str] = {}
    for specimen in SPECIMENS:
        for suffix in specimen.suffixes:
            assert suffix not in seen, f"{suffix}: {seen.get(suffix)} and {specimen.route}"
            seen[suffix] = specimen.route
