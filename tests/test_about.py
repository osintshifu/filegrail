"""The screen `filegrail` shows when it is run with nothing to do.

Typing the name of a tool and having it start work on the current directory is
a surprise, and in a home directory an expensive one. Bare `filegrail`
introduces itself and says how to point it somewhere instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from filegrail import REPOSITORY, __version__, about
from filegrail.cli import COMMANDS as CLI_COMMANDS
from filegrail.cli import main
from filegrail.theme import Theme

#: The screen prints the repository without its scheme, so the line fits beside
#: the wordmark on an eighty-column terminal.
SHOWN_REPOSITORY = REPOSITORY.split("//", 1)[-1]

PLAIN = Theme(colour=False, unicode=False, width=80)

WIDTHS = [48, 56, 64, 80, 88, 110]


def _screen(theme: Theme | None = None) -> str:
    return about.render(theme=theme or PLAIN)


def test_the_version_shown_is_the_pyproject_version():
    """One number stated twice: importers read `__version__`, installers read
    pyproject. A release where the two drift apart answers "which filegrail is
    this" differently depending on who is asked, and nothing else holds the
    pair together."""
    pyproject = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text("utf-8")
    declared = re.search(r'(?m)^version = "([^"]+)"$', pyproject)

    assert declared is not None, "pyproject.toml no longer declares its version on one line"
    assert declared.group(1) == __version__


def test_the_readme_badge_names_the_version_being_released():
    """The badge states the version rather than asking PyPI for it at view
    time: the image proxies of GitHub and PyPI cache that answer, and a new
    release page went on showing a version several releases old."""
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text("utf-8")
    badge = re.search(r"img\.shields\.io/badge/pypi-v([0-9][0-9.]*)-", readme)

    assert badge is not None, "README.md no longer carries the PyPI version badge"
    assert badge.group(1) == __version__


def test_the_changelog_has_notes_for_the_version_being_released():
    """The release workflow publishes this section as the GitHub release, and it
    runs after the package is already on PyPI: a missing section fails a release
    that cannot be taken back."""
    import runpy

    tool = runpy.run_path(
        str(Path(__file__).resolve().parent.parent / "tools" / "release_notes.py")
    )

    assert tool["notes"](__version__).strip()


def test_it_says_what_it_is():
    screen = _screen()

    assert "filegrail" in screen
    assert __version__ in screen
    assert SHOWN_REPOSITORY in screen


def test_it_says_how_to_scan_the_current_folder():
    """The one thing someone needs next, and the one thing a bare run no
    longer does for them."""
    assert "filegrail <path>" in _screen()


def test_it_shows_the_wordmark():
    assert "filegrail" in _screen()


def test_a_checkout_is_told_what_makes_the_examples_work(monkeypatch):
    """Printing `filegrail` at a shell that has no such command is how the
    screen gets disproved on the reader's first attempt."""
    monkeypatch.setattr(about.sys, "argv", ["/data/filegrail/src/filegrail/cli.py"])
    monkeypatch.setattr(about.shutil, "which", lambda name: None)
    monkeypatch.setenv("PYTHONPATH", "src")

    screen = _screen(Theme(colour=False, unicode=False, width=92))

    assert "alias filegrail=" in screen
    assert "pipx install filegrail" in screen
    assert "PYTHONPATH=src" in screen


def test_an_installed_run_says_nothing_about_installing(monkeypatch):
    monkeypatch.setattr(about.shutil, "which", lambda name: "/usr/local/bin/filegrail")

    screen = _screen()

    assert "alias filegrail=" not in screen
    assert "pipx install" not in screen


def test_the_tagline_says_both_halves_of_what_it_does():
    assert "Trace origins" in _screen()
    assert "Reveal metadata" in _screen()


def test_it_shows_a_short_way_in_rather_than_every_example():
    screen = _screen()

    for start in ("filegrail suspicious.pdf", "filegrail ~/Downloads", "filegrail doctor"):
        assert start in screen, start
    for flag in ("--pivots", "--timeline"):
        assert flag in screen, flag


def test_every_command_is_named():
    """`image` used to pass this by appearing inside `image.jpg` in an example,
    which is how the overview went on offering `photo` after the command was
    renamed. The list itself is what has to name them."""
    listed = set(about.COMMANDS)

    assert listed | {"help", "photo"} == set(CLI_COMMANDS), listed
    for command in about.COMMANDS:
        assert f" {command} " in _screen().replace("\n", " "), command


def test_it_fits_a_screen_without_scrolling():
    """It grew from six examples to twenty-three, grouped by what is being
    asked about. That is worth the lines - a reader who cannot find the flag
    they need goes to `--help` and reads forty - but it is not worth a page
    that scrolls before the first command appears."""
    screen = about.render(theme=Theme(colour=False, unicode=True, width=96))

    assert len(screen.splitlines()) <= 50, len(screen.splitlines())


def test_it_does_not_list_the_evidence_sources():
    """That table belongs in `doctor`, where the question has been asked."""
    screen = _screen()

    assert "content credentials" not in screen
    assert "doctor" in screen


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("unicode_ok", [True, False])
def test_it_stays_inside_the_terminal_width(width: int, unicode_ok: bool):
    theme = Theme(colour=False, unicode=unicode_ok, width=width)

    screen = about.render(theme=theme)

    assert not [line for line in screen.splitlines() if len(line) > width]


def test_an_ascii_terminal_gets_ascii():
    screen = about.render(theme=Theme(colour=False, unicode=False, width=80))

    assert screen.isascii()


# --- how the command line reaches it ----------------------------------------


def test_a_bare_run_introduces_itself_and_scans_nothing(capsys):
    assert main([]) == 0

    out = capsys.readouterr().out
    assert SHOWN_REPOSITORY in out
    assert "SUMMARY" not in out  # a report heading, which must not appear here


def test_help_with_no_command_shows_the_same_screen(capsys):
    assert main(["help"]) == 0

    assert SHOWN_REPOSITORY in capsys.readouterr().out


def test_an_explicit_dot_still_scans(tmp_path: Path, monkeypatch, capsys):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert main(["."]) == 0

    out = capsys.readouterr().out
    assert "ORIGIN" in out or "FILE" in out
    assert SHOWN_REPOSITORY not in out


def test_a_path_with_flags_still_scans(tmp_path: Path, capsys):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")

    assert main([str(tmp_path), "--no-color"]) == 0

    assert "FILE" in capsys.readouterr().out
