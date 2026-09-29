from pathlib import Path

from filegrail.models import EvidenceRecord, FileRecord
from filegrail.report import render_text
from filegrail.theme import ARCHIVE_WIDTH, EVIDENCE, Theme, detect


class _Stream:
    """The two attributes theme detection actually looks at."""

    def __init__(self, tty: bool, encoding: str = "utf-8") -> None:
        self._tty = tty
        self.encoding = encoding

    def isatty(self) -> bool:
        return self._tty


def _record() -> FileRecord:
    record = FileRecord(path="/case/a.txt", size=1, mtime="2026-08-24T19:00:00Z")
    record.evidence.append(
        EvidenceRecord(
            source="browser-download", url="https://example.org/a.txt", at="2026-08-24T19:00:00Z"
        )
    )
    return record


def test_a_pipe_gets_no_colour(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")

    assert detect(_Stream(tty=False)).colour is False


def test_a_terminal_gets_colour(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")

    assert detect(_Stream(tty=True)).colour is True


def test_no_color_is_honoured(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "xterm-256color")

    assert detect(_Stream(tty=True)).colour is False


def test_dumb_terminal_gets_no_colour(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("TERM", "dumb")

    assert detect(_Stream(tty=True)).colour is False


def test_explicit_choice_beats_detection(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")

    assert detect(_Stream(tty=False), colour=True).colour is True


def test_plain_output_contains_no_escape_sequences():
    theme = Theme(colour=False, unicode=True, width=88)

    output = render_text([_record()], Path("/case"), theme=theme)

    assert "\x1b" not in output
    assert "example.org" in output


def test_styled_output_contains_escape_sequences():
    theme = Theme(colour=True, unicode=True, width=88)

    output = render_text([_record()], Path("/case"), theme=theme)

    assert "\x1b[" in output


def test_ascii_fallback_avoids_box_drawing():
    theme = Theme(colour=False, unicode=False, width=88)

    output = render_text([_record()], Path("/case"), theme=theme)

    assert output.isascii()


def test_the_run_progress_meter_is_the_only_meter_left():
    """The evidence meter drew one number as five blocks and read as a
    strength; the coverage bar counts files done out of files found, which is
    arithmetic about the run rather than a rating of anything."""
    theme = Theme(colour=False, unicode=False, width=88)

    assert not hasattr(theme, "meter")
    assert theme.coverage(6, 12).count("#") == 6


def test_width_is_clamped_to_a_readable_range(monkeypatch):
    monkeypatch.setenv("COLUMNS", "400")
    assert detect(_Stream(tty=True)).width <= 110

    monkeypatch.setenv("COLUMNS", "20")
    assert detect(_Stream(tty=True)).width >= 48


def test_every_source_is_painted_by_its_category():
    """One table decides what a source is about; the palette follows it, so a
    source cannot be coloured as one thing and reported as another."""
    from filegrail.models import SOURCE_CATEGORIES

    theme = Theme(colour=True, unicode=True, width=88)

    assert set(SOURCE_CATEGORIES.values()) <= set(EVIDENCE)
    for source, expected in SOURCE_CATEGORIES.items():
        assert theme.evidence(source) == expected, source


# --- the width a report that outlives its terminal is laid out to -------------


def test_a_report_not_going_to_a_terminal_is_laid_out_for_reading_later(monkeypatch):
    """A redirected report outlives the terminal that made it.

    Baking that terminal's width into a file makes every rule wrap the moment
    somebody opens it somewhere narrower, and a wrapped rule is a stray line of
    dashes that reads as a damaged file rather than as a divider.
    """
    monkeypatch.delenv("COLUMNS", raising=False)

    # The literal, not the constant: 72 is a decision - what a file survives
    # being quoted, pasted, diffed and read in a side pane at - and a test that
    # compares the constant to itself would let that decision drift unnoticed.
    assert detect(_Stream(tty=False)).width == 72
    assert ARCHIVE_WIDTH == 72


def test_a_terminal_still_gets_its_own_width(monkeypatch):
    monkeypatch.setenv("COLUMNS", "104")

    assert detect(_Stream(tty=True)).width == 104


def test_a_named_width_is_honoured_even_when_redirected(monkeypatch):
    """The escape hatch for somebody who wants a wide file on purpose."""
    monkeypatch.setenv("COLUMNS", "100")

    assert detect(_Stream(tty=False)).width == 100
