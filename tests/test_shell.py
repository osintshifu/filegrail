from pathlib import Path

from filegrail.sources.shell import collect_shell_history


def _write_history(home: Path, name: str, content: str) -> None:
    path = home / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_matches_exact_argument(tmp_path: Path):
    _write_history(tmp_path, ".bash_history", "wget https://example.org/report.pdf\n")
    found = collect_shell_history({"report.pdf"}, home=tmp_path)
    assert "report.pdf" in found
    assert found["report.pdf"][0].tool == "wget"


def test_matches_basename_of_a_path_argument(tmp_path: Path):
    _write_history(tmp_path, ".bash_history", "exiftool ./evidence/photo.jpg\n")
    assert "photo.jpg" in collect_shell_history({"photo.jpg"}, home=tmp_path)


def test_short_name_does_not_match_by_substring(tmp_path: Path):
    _write_history(tmp_path, ".bash_history", "rm -f /tmp/unrelated.deb\n")
    assert collect_shell_history({"tmp"}, home=tmp_path) == {}


def test_reads_bash_timestamps(tmp_path: Path):
    _write_history(tmp_path, ".bash_history", "#1756633773\ncurl -O data.csv\n")
    origin = collect_shell_history({"data.csv"}, home=tmp_path)["data.csv"][0]
    assert origin.at is not None and origin.at.startswith("2025-")


def test_reads_zsh_extended_history(tmp_path: Path):
    _write_history(tmp_path, ".zsh_history", ": 1756633773:0;wget https://example.org/a.zip\n")
    origin = collect_shell_history({"a.zip"}, home=tmp_path)["a.zip"][0]
    assert origin.tool == "wget"
    assert origin.at is not None


def test_missing_history_file_is_not_an_error(tmp_path: Path):
    assert collect_shell_history({"anything.txt"}, home=tmp_path) == {}
