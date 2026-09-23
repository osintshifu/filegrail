"""Every machine-readable document says what it is and what wrote it.

`--json` is a contract with software, not a convenience for reading. Something
piping filegrail into jq, a case tool or a log pipeline has to know which shape
it received and which release produced it. Without that, the first time a field
is renamed the breakage is silent and it happens in somebody else's program.

The stamp is cheapest now and gets more expensive every week: adding a key is
itself a change for anyone who enumerates them, so a tool with no consumers yet
is the only tool that can add one for free.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from filegrail import __version__
from filegrail.cli import PARSERS, main

#: `menu` inherits `--json` from the shared options but is interactive: it
#: refuses to run without a terminal, so it has no document to stamp.
INTERACTIVE = {"menu"}

#: `image` (and its alias `photo`) writes one HTML report and takes no `--json`. There is no
#: machine-readable document here to stamp, and inventing one would be a second
#: schema to keep for a reader nobody has asked for.
HTML_ONLY = {"image", "photo"}

#: `mcp` answers an agent in JSON-RPC, a protocol with its own versioning, and
#: takes no `--json`.
PROTOCOL = {"mcp"}


@pytest.fixture(autouse=True)
def elsewhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every source that reads a home directory at an empty one.

    These tests are about the envelope, not the evidence, and a run that reads
    the developer's own browser history is both slow and different on every
    machine it runs on.
    """
    empty = tmp_path / "home"
    empty.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: empty))
    return empty


@pytest.fixture
def case(tmp_path: Path) -> Path:
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    return tmp_path


def _arguments(name: str, case: Path) -> list[str]:
    return {
        "scan": [name, str(case)],
        "explain": [name, str(case / "a.txt")],
        "compare": [name, str(case / "a.txt"), str(case / "b.txt")],
        "doctor": [name],
        "clean": [name, str(case), "--out", str(case.parent / "cleaned")],
    }[name]


#: Every command that can be asked for JSON, and how to ask it for some.
DOCUMENTS = ("scan", "explain", "compare", "doctor", "clean")


def _run(capsys, name: str, case: Path) -> dict:
    assert main([*_arguments(name, case), "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def test_a_scan_says_which_shape_it_is(case: Path, capsys):
    assert _run(capsys, "scan", case)["schema"] == "filegrail.scan/2"


def test_an_explanation_says_which_shape_it_is(case: Path, capsys):
    assert _run(capsys, "explain", case)["schema"] == "filegrail.explain/2"


def test_a_comparison_says_which_shape_it_is(case: Path, capsys):
    assert _run(capsys, "compare", case)["schema"] == "filegrail.compare/2"


def test_a_survey_says_which_shape_it_is(case: Path, capsys):
    assert _run(capsys, "doctor", case)["schema"] == "filegrail.doctor/1"


def test_a_cleaning_run_says_which_shape_it_is(case: Path, capsys):
    assert _run(capsys, "clean", case)["schema"] == "filegrail.clean/1"


def test_a_document_whose_shape_did_not_change_kept_its_number():
    """The vocabulary refactor renamed fields in three of the five documents.
    Bumping the other two as well would send every consumer of `clean` and
    `doctor` to read a diff with nothing in it."""
    from filegrail.report import SCHEMAS

    assert SCHEMAS["clean"] == 1
    assert SCHEMAS["doctor"] == 1
    assert {SCHEMAS["scan"], SCHEMAS["explain"], SCHEMAS["compare"]} == {2}


def test_every_document_names_the_release_that_wrote_it(case: Path, capsys):
    """Two fields, because they answer two questions.

    The schema says how to read the document; the version says which build
    produced it, which is what a bug report needs and what a changelog entry
    can be matched against.
    """
    for name in DOCUMENTS:
        assert _run(capsys, name, case)["filegrail_version"] == __version__, name


def test_the_stamp_comes_before_the_content(case: Path, capsys):
    """`head` on a piped document should be enough to identify it."""
    for name in DOCUMENTS:
        assert list(_run(capsys, name, case))[:2] == ["schema", "filegrail_version"], name


def test_stamping_left_the_documents_otherwise_alone(case: Path, capsys):
    """The envelope is added around what was already there, not instead of it."""
    assert {"root", "files", "summary"} <= set(_run(capsys, "scan", case))
    assert {"file", "correlation", "assessment"} <= set(_run(capsys, "explain", case))
    assert {"assessment", "origin"} <= set(_run(capsys, "compare", case))
    assert {"sources", "horizon"} <= set(_run(capsys, "doctor", case))


def test_every_command_that_can_emit_json_is_covered_here():
    """A new command must be stamped too, or say here why it has nothing to stamp."""
    assert set(DOCUMENTS) | INTERACTIVE | HTML_ONLY | PROTOCOL == set(PARSERS), sorted(
        set(PARSERS) - set(DOCUMENTS) - INTERACTIVE - HTML_ONLY - PROTOCOL
    )


def test_the_terminal_report_does_not_leak_into_the_document(case: Path, capsys):
    """The report grew an overview, an inventory and a findings table. None of
    that belongs here: a consumer counts the files itself, and a key added to
    match a heading is a key somebody now has to keep.

    `with_origin` in particular keeps its name. The report stopped calling that
    number `traced` because the word claimed too much on screen; the JSON field
    has always said exactly what it counts.
    """
    document = _run(capsys, "scan", case)

    assert set(document["summary"]) == {"total", "with_origin"}
    assert not {"inventory", "findings", "attention", "overview"} & set(document)


def test_with_origin_counts_files_with_an_origin_record(tmp_path: Path):
    """A file whose only evidence is its own EXIF has metadata, not an origin."""
    import json

    from filegrail.models import EvidenceRecord, FileRecord
    from filegrail.report import render_json

    traced = FileRecord(path="/case/a.jpg", size=1, mtime="2026-01-01T00:00:00Z")
    traced.evidence.append(EvidenceRecord(source="browser-download", url="https://x.test/a"))
    described = FileRecord(path="/case/b.jpg", size=1, mtime="2026-01-01T00:00:00Z")
    described.evidence.append(EvidenceRecord(source="device-metadata", tool="Camera"))

    document = json.loads(render_json([traced, described], tmp_path))

    assert document["summary"] == {"total": 2, "with_origin": 1}
