"""Format identification against the PRONOM registry compiled into the package."""

from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

from filegrail.cli import main
from filegrail.pronom import WINDOW, identify

from .compound import ole
from .pdf import document
from .specimens import _wave
from .test_blocks import _ooxml

#: A Word 97 document as far as the registry looks: the text stream, and the
#: class name in `\x01CompObj`, a stream whose name opens on a control byte.
WORD_97 = ole(
    {
        "WordDocument": bytes(64),
        "\x01CompObj": bytes(40) + b"\x10\x00\x00\x00Word.Document.8\x00",
    }
)


def _puids(path: Path) -> list[str]:
    return [found.puid for found in identify(path)]


def test_an_office_document_is_named_by_its_members_and_a_plain_zip_as_a_zip(tmp_path):
    report = _ooxml(tmp_path / "report.docx")
    legacy = tmp_path / "report.doc"
    legacy.write_bytes(WORD_97)
    plain = tmp_path / "plain.zip"
    with zipfile.ZipFile(plain, "w") as archive:
        archive.writestr("notes.txt", "nothing an office suite wrote")

    (word,) = identify(report)
    assert (word.puid, word.name, word.basis) == (
        "fmt/412",
        "Microsoft Word for Windows",
        "container",
    )
    assert [(found.puid, found.basis) for found in identify(legacy)] == [("fmt/40", "container")]
    assert [(found.puid, found.basis) for found in identify(plain)] == [("x-fmt/263", "signature")]


def test_a_format_with_priority_over_another_is_the_only_one_named(tmp_path):
    # A WAV matches the signature of every RIFF file as well as its own, and
    # the registry says which of the two wins.
    sound = tmp_path / "call.wav"
    sound.write_bytes(_wave())

    assert _puids(sound) == ["fmt/6"]


def test_bytes_the_registry_does_not_know_are_not_identified_from_the_name(tmp_path):
    notes = tmp_path / "notes.txt"
    notes.write_text("met the courier at nine\n")

    assert identify(notes) == []


def test_a_sequence_tied_to_the_start_is_not_looked_for_in_the_tail(tmp_path):
    # SVG 1.1 needs its closing tag inside the part of the file read from the
    # start. Past it, the file is XML and nothing more, which is what DROID says.
    drawing = tmp_path / "large.svg"
    drawing.write_bytes(
        b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" version="1.1">\n'
        + b"<!-- padding -->\n" * (WINDOW // 16)
        + b"</svg>\n"
    )

    assert _puids(drawing) == ["fmt/101"]


def test_a_chain_of_frames_that_breaks_at_the_end_is_rejected_without_backtracking(tmp_path):
    # MPEG audio is recognised by seven frame headers, each within a window of
    # the one before, ending near the end of the file. Tried as one regular
    # expression, a file of frames that ends in the wrong place backtracks
    # through every choice of every frame before it gives up.
    audio = tmp_path / "broken.mp3"
    audio.write_bytes(b"ID3" + bytes(4096) + b"\xff\xfb\x90\x00" * 30_000 + bytes(4096))

    started = time.monotonic()
    found = _puids(audio)

    assert "fmt/134" not in found
    assert time.monotonic() - started < 5


def test_scan_json_carries_the_formats_the_bytes_match(tmp_path, capsys):
    pdf = tmp_path / "letter.pdf"
    pdf.write_bytes(document([b"BT /F1 12 Tf (x) Tj ET"]))

    home = tmp_path / "home"
    home.mkdir()
    main(["scan", str(pdf), "--json", "--home", str(home)])
    payload = json.loads(capsys.readouterr().out)

    (entry,) = payload["files"]
    assert entry["formats"] == [
        {
            "puid": "fmt/18",
            "name": "Acrobat PDF 1.4 - Portable Document Format",
            "version": "1.4",
            "mime": "application/pdf",
            "basis": "signature",
        }
    ]


def test_the_report_names_the_format_beside_the_type(tmp_path, capsys):
    pdf = tmp_path / "letter.pdf"
    pdf.write_bytes(document([b"BT /F1 12 Tf (x) Tj ET"]))

    home = tmp_path / "home"
    home.mkdir()
    main(["scan", str(pdf), "--no-color", "--home", str(home)])

    assert "fmt/18 Acrobat PDF 1.4 - Portable Document Format" in capsys.readouterr().out


def test_compare_sets_the_two_formats_side_by_side(tmp_path, capsys):
    pdf = tmp_path / "letter.pdf"
    pdf.write_bytes(document([b"BT /F1 12 Tf (x) Tj ET"]))
    sound = tmp_path / "call.wav"
    sound.write_bytes(_wave())
    home = tmp_path / "home"
    home.mkdir()

    main(["compare", str(pdf), str(sound), "--no-color", "--home", str(home)])

    (row,) = [
        line for line in capsys.readouterr().out.splitlines() if line.strip().startswith("format")
    ]
    assert row.split()[1:] == ["fmt/18", "fmt/6"]


def test_a_package_whose_members_cannot_be_read_is_named_as_its_container(tmp_path):
    # The general-purpose flag marks every member encrypted, which the zip
    # module refuses to read without a password.
    report = _ooxml(tmp_path / "report.docx")
    data = bytearray(report.read_bytes())
    for header, flags_at in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        start = data.find(header)
        while start != -1:
            data[start + flags_at] |= 1
            start = data.find(header, start + 4)
    report.write_bytes(bytes(data))

    assert _puids(report) == ["x-fmt/263"]
