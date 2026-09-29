"""The validation corpus, read by somebody else's implementation.

A fixture built from a specification and read by the parser it was built for
agrees with itself. That is the whole of what a synthetic corpus proves on its
own, and it is a weaker claim than it looks: a file can be readable here and
unreadable by every other tool, because this project's readers search for
payloads rather than walk container structure. A reader that searches is the
right choice for evidence work - a truncated download still gives up its
metadata - but it means a malformed fixture passes silently, and every test
resting on that fixture is then testing the search rather than the format.

`exiftool` is the reference because it is the tool this field already trusts,
it reads nearly everything, and it is strict about structure in the places that
matter. What is checked is narrow on purpose: for each specimen, the value this
project reports has to be a value `exiftool` also finds. Not that the two agree
about everything - `exiftool` reports hundreds of tags this project has no
opinion on, and comparing those would be a wall of noise nobody reads.

This found the PDF specimen carrying an information dictionary that the cross
reference table did not list, which `qpdf` independently called damage, and an
Ogg page with no checksum that no other implementation would open. Both were
read perfectly here and by nothing else.

Like the CASE validator, this needs a tool that is not a development
dependency, so it has a job of its own and skips where the tool is absent.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from .specimens import SPECIMENS

pytestmark = pytest.mark.skipif(
    shutil.which("exiftool") is None,
    reason="exiftool is not installed",
)

#: Routes where `exiftool` reports nothing this project could be compared
#: against, and why. A reason here is a statement about the other tool, never
#: about a specimen being hard to read - a specimen nothing else can open
#: belongs in the findings, not in this table.
#:
#: `test_no_route_is_excused_from_a_comparison_that_would_work` holds every
#: entry against a real run, so an entry that stops being true fails rather
#: than quietly excusing a specimen that has started to fall apart.
UNCOMPARABLE: dict[str, str] = {
    "ODF package": "exiftool lists the package members and does not parse meta.xml",
    "EPUB package": "exiftool lists the package members and does not parse the OPF",
    "RTF": "exiftool reads the RTF info group, not the generator control word",
    "Web page": "exiftool does not extract meta elements from HTML",
    "Notebook": "exiftool does not open .ipynb",
    "SVG": "exiftool reports the version attribute without the application that wrote it",
    # Not a limit of the other tool. The HEIF specimen names an `Exif` item in
    # its item table and puts the payload in `mdat`, with nothing locating one
    # from the other, which is what it was built to test: that a reader does
    # not stop at the item table. A real encoder writes an item location box,
    # and until this specimen does too it shows that the payload can be found
    # by searching, not that a HEIF can be read. Left as it stands rather than
    # rewritten here, because making it a real HEIF is a question about the
    # reader and not only about the fixture.
    "EXIF in HEIF": "the specimen has no item location box, so only a search finds its payload",
}


def _reported(corpus: Path) -> dict[str, dict[str, object]]:
    """Everything `exiftool` says about the corpus, by path."""
    done = subprocess.run(
        ["exiftool", "-q", "-json", "-groupNames", "-recurse", str(corpus)],
        capture_output=True,
        text=True,
        check=False,
    )
    if not done.stdout.strip():  # pragma: no cover - only when exiftool fails outright
        pytest.fail(done.stderr or "exiftool returned nothing")
    return {item["SourceFile"]: item for item in json.loads(done.stdout)}


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, dict[str, object]]]:
    """The corpus written once, and one run of `exiftool` over the whole of it."""
    into = tmp_path_factory.mktemp("corpus")
    for specimen in SPECIMENS:
        for suffix in sorted(specimen.suffixes):
            specimen.write(into / _named(specimen, suffix))
    return into, _reported(into)


def _readable(corpus: tuple[Path, dict[str, dict[str, object]]], specimen) -> str | None:
    """The first extension of this route `exiftool` both opens and understands.

    Any of them will do. The route is one set of bytes under several names, and
    which names the other tool happens to know is a fact about its extension
    table, not about whether the file is a real file of its format: it opens
    `.wav` and not `.rmi`, `.mkv` and not `.mk3d`, `.exe` and not `.cpl`.
    """
    into, said = corpus
    for suffix in sorted(specimen.suffixes):
        theirs = said.get(str(into / _named(specimen, suffix)))
        if theirs is not None and all(
            any(value in str(reported) for reported in theirs.values())
            for value in specimen.expect.values()
        ):
            return suffix
    return None


def _named(specimen, suffix: str) -> str:
    return f"{specimen.route.lower().replace(' ', '-')}{suffix}"


_COMPARABLE = [
    pytest.param(specimen, id=specimen.route)
    for specimen in SPECIMENS
    if specimen.route not in UNCOMPARABLE
]


@pytest.mark.parametrize("specimen", _COMPARABLE)
def test_another_implementation_finds_what_this_one_reports(corpus, specimen):
    """The specimen has to be a real file of its format, not one that happens
    to be searchable. A value only this project can find is the signature of a
    fixture built the way the specification reads rather than the way an
    encoder writes."""
    into, said = corpus
    if _readable(corpus, specimen) is not None:
        return

    # What the other tool did say, because without it this failure costs a
    # round trip through CI to find out whether the specimen is malformed or
    # the reference tool is missing a library. It was the second one once
    # already: exiftool without `Archive::Zip` reads an Office package as an
    # opaque file and reports nothing, which looks exactly like a bad fixture.
    saw = {
        suffix: sorted(str(key) for key in (said.get(str(into / _named(specimen, suffix))) or {}))
        for suffix in sorted(specimen.suffixes)
    }
    pytest.fail(
        f"{specimen.route}: no extension gave exiftool "
        f"{sorted(specimen.expect.values())}. It reported: {saw}"
    )


def test_no_route_is_excused_from_a_comparison_that_would_work(corpus):
    """An excuse that has stopped being true is worse than no excuse, because
    it reads as a decision somebody took. If the other tool learns a format, or
    a specimen is rebuilt properly, the entry has to go."""
    wrongly_excused = [
        specimen.route
        for specimen in SPECIMENS
        if specimen.route in UNCOMPARABLE and _readable(corpus, specimen) is not None
    ]

    assert not wrongly_excused, f"comparable after all: {wrongly_excused}"


def test_the_table_of_excuses_names_only_routes_that_exist():
    """The failure mode the CASE export already had once: a table keyed on a
    name nothing produces is never applied and never noticed."""
    routes = {specimen.route for specimen in SPECIMENS}
    assert set(UNCOMPARABLE) <= routes, sorted(set(UNCOMPARABLE) - routes)
