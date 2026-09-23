"""Format identification, held against DROID reading the same registry.

DROID is The National Archives' own implementation of PRONOM identification,
so where the two disagree about a file's bytes, this project is the one that is
wrong. It runs here against the signature files the package was compiled from,
checked by digest, over the validation corpus and a few files built to sit on
the edges of what is read.

One disagreement is expected and excused: DROID names a format from the
extension alone when no signature matches, and this project does not. Such a
name is excused only where the format has no signature that could have said it
from the bytes.

Needs DROID and the two signature files, so it has a job of its own:
`DROID` is the path to `droid.sh`, `PRONOM_SOURCES` the folder holding the
files named in `data/pronom.json`.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import os
import subprocess
from pathlib import Path

import pytest

from filegrail.pronom import WINDOW, identify, registry

from .specimens import SPECIMENS
from .test_pronom import WORD_97

DROID = os.environ.get("DROID")
SOURCES = os.environ.get("PRONOM_SOURCES")

pytestmark = pytest.mark.skipif(
    not (DROID and SOURCES),
    reason="DROID and PRONOM_SOURCES are not set",
)

ROOT = Path(__file__).resolve().parent.parent


def _sources() -> tuple[Path, Path]:
    described = registry().describe()
    folder = Path(SOURCES or "")
    return folder / described["signature_file"], folder / described["container_file"]


def _build_tool():
    spec = importlib.util.spec_from_file_location(
        "build_pronom", ROOT / "tools" / "build_pronom.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_shipped_registry_is_the_one_the_signature_files_compile_to():
    signature_file, container_file = _sources()
    shipped = json.loads((ROOT / "src" / "filegrail" / "data" / "pronom.json").read_text())

    # The compiled form records each file's digest, so this also proves DROID
    # below reads the very registry the package carries.
    assert shipped == _build_tool().compile_registry(signature_file, container_file)


def _edges(into: Path) -> None:
    """Files on the edges of what is read: the window at each end of the file, and a
    compound-document stream whose name opens on a control byte."""
    (into / "large.svg").write_bytes(
        b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" version="1.1">\n'
        + b"<!-- padding -->\n" * (WINDOW // 16)
        + b"</svg>\n"
    )
    (into / "word97.doc").write_bytes(WORD_97)
    (into / "frames.mp3").write_bytes(b"ID3" + b"\xff\xfb\x90\x00" * 30_000)
    (into / "broken.mp3").write_bytes(
        b"ID3" + bytes(4096) + b"\xff\xfb\x90\x00" * 30_000 + bytes(4096)
    )


def test_droid_names_every_file_as_this_project_does(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for specimen in SPECIMENS:
        for suffix in sorted(specimen.suffixes):
            specimen.write(corpus / f"{specimen.route.lower().replace(' ', '-')}{suffix}")
    _edges(corpus)

    signature_file, container_file = _sources()
    done = subprocess.run(
        [
            "bash",
            str(DROID),
            "-q",
            "-Nr",
            str(corpus),
            "-R",
            "-Ns",
            str(signature_file),
            "-Nc",
            str(container_file),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    theirs: dict[str, set[str]] = {}
    for row in csv.DictReader(io.StringIO(done.stdout)):
        if row["PUID"]:
            theirs.setdefault(Path(row["FILE_PATH"]).name, set()).add(row["PUID"])

    known = registry()
    from_bytes = {entry["puid"] for entry in known.formats.values() if entry["signatures"]}
    from_bytes |= {puid for _, puid, _ in known.containers}
    disagreements = {}
    for path in sorted(corpus.iterdir()):
        ours = {found.puid for found in identify(path)}
        droid = theirs.get(path.name, set())
        by_name_only = not ours and not droid & from_bytes
        if ours != droid and not by_name_only:
            disagreements[path.name] = (sorted(ours), sorted(droid))

    assert disagreements == {}
