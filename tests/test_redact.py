from __future__ import annotations

import json
from pathlib import Path

import pytest

from filegrail.cli import main
from filegrail.models import EvidenceRecord, FileRecord
from filegrail.redact import fingerprint, looks_like_secret, redact_text, redact_url


def test_strips_credential_query_parameters_but_keeps_the_url_readable():
    result = redact_url("https://api.example.org/v1/export?range=90d&api_key=s3cr3tvalue123")

    assert "s3cr3tvalue123" not in result
    assert "https://api.example.org/v1/export" in result
    assert "range=90d" in result
    assert "REDACTED:query" in result


def test_url_without_a_query_is_untouched():
    url = "https://example.org/reports/annual.pdf"
    assert redact_url(url) == url


def test_harmless_query_parameters_survive():
    url = "https://example.org/search?q=acme&page=2"
    assert redact_url(url) == url


def test_redacts_space_separated_argument():
    result = redact_text("curl --password hunter2seventy https://example.org")
    assert "hunter2seventy" not in result
    assert "--password" in result


def test_redacts_equals_separated_argument():
    assert "abcdef123456" not in redact_text("tool --token=abcdef123456")


def test_redacts_bearer_header():
    result = redact_text('curl -H "Authorization: Bearer abcdef1234567890"')
    assert "abcdef1234567890" not in result
    assert "Authorization: Bearer" in result


def test_redacts_url_credentials():
    assert "sup3rs3cret" not in redact_text("git clone https://user:sup3rs3cret@host/repo.git")


def test_redacts_vendor_tokens_and_keys():
    for secret in (
        "AKIAIOSFODNN7EXAMPLE",
        "ghp_abcdefghijklmnopqrstuvwxyz0123",
        "sk-abcdefghijklmnopqrstuvwx",
        # Built at run time: written out, these are the shapes the forge's
        # push protection takes for the real thing, and it declines the push.
        "sk_live_" + "a" * 26,
        "rk_test_" + "b" * 26,
        "npm_" + "c" * 36,
        "hf_" + "d" * 32,
        "shpat_" + "0123456789abcdef" * 2,
        "SG." + "e" * 22 + "." + "f" * 43,
        "123456789:" + "AAF" + "g" * 32,
        "SK" + "0123456789abcdef" * 2,
    ):
        assert secret not in redact_text(f"tool {secret}"), secret


def test_leaves_ordinary_commands_alone():
    command = "exiftool -json evidence/photo.jpg"
    assert redact_text(command) == command


def test_does_not_redact_documentation_placeholders():
    for value in ("${API_KEY}", "<token>", "changeme", "xxxxxxxx"):
        assert not looks_like_secret(value)


def test_does_not_redact_prose_words_in_credential_position():
    assert redact_text("tool --auth-mode environment") == "tool --auth-mode environment"


def test_fingerprint_is_stable_and_hides_the_value():
    secret = "hunter2seventy"
    handle = fingerprint(secret)

    assert handle == fingerprint(secret)
    assert len(handle) == 12
    assert secret not in handle
    assert not secret.startswith(handle)


def test_same_secret_twice_gets_the_same_fingerprint():
    output = redact_text("a --token=abcdef123456 and b --token=abcdef123456")
    marks = [part for part in output.split() if "REDACTED" in part]
    assert len(marks) == 2 and marks[0] == marks[1]


def test_origin_redacts_url_referrer_and_command():
    origin = EvidenceRecord(
        source="browser-download",
        url="https://example.org/f?token=abcdef123456",
        referrer="https://example.org/p?api_key=zyxwvu987654",
        command="curl --password hunter2seventy",
    )

    safe = origin.redacted()

    assert "abcdef123456" not in safe.url
    assert "zyxwvu987654" not in safe.referrer
    assert "hunter2seventy" not in safe.command
    assert safe.source == origin.source


def test_origin_redacts_note_and_location_too():
    """A mail subject or a typed place name is free text like any other.

    Both fields reach the report word for word, so a token in a forwarded
    subject line or a URL pasted where a place name belongs would ride
    through `--redact` untouched.
    """
    origin = EvidenceRecord(
        source="email-delivery",
        note="Fwd: your key sk-abcdefghijklmnopqrstuvwx",
        location="see https://vault.example.org/f?token=abcdef123456",
    )

    safe = origin.redacted()

    assert "sk-abcdefghijklmnopqrstuvwx" not in safe.note
    assert "abcdef123456" not in safe.location
    assert safe.note.startswith("Fwd: your key ")  # the subject itself survives


def test_file_record_redacts_every_origin():
    record = FileRecord(path="/case/a", size=1, mtime="2026-08-24T19:00:00Z")
    record.evidence.append(
        EvidenceRecord(source="shell-history", command="tool --token=abcdef123456")
    )

    safe = record.redacted()

    assert "abcdef123456" not in safe.evidence[0].command
    assert "abcdef123456" in record.evidence[0].command  # original untouched


# --- the commands that print evidence ----------------------------------------
#
# `--redact` began life as a scan option, but `explain` exists precisely to
# print every source behind a finding, including the ones that disagree, and
# `compare` prints the route each file arrived by. Both render URLs, so both
# can render a credential in one. A flag that covers the least dense of the
# three is a flag a user learns to trust and then gets caught by.


SECRET = "abcdef1234567890"
SECRET_URL = f"https://media.example.org/v/12?access_token={SECRET}"


def _downloaded(directory: Path, name: str, url: str) -> Path:
    """A media file beside the record a download tool wrote for it."""
    media = directory / name
    media.write_bytes(b"")
    media.with_suffix(".info.json").write_text(
        json.dumps({"webpage_url": url, "title": "quarterly briefing"}), encoding="utf-8"
    )
    return media


def _unwrapped(printed: str) -> str:
    """The output as one run of characters, so a wrapped value reads whole."""
    return "".join(printed.split())


def _invocation(command: str, media: Path, other: Path) -> list[str]:
    if command == "compare":
        return ["compare", str(media), str(other)]
    return [command, str(media)]


@pytest.mark.parametrize("command", ("scan", "explain", "compare"))
@pytest.mark.parametrize("shape", ("--no-color", "--json", "--html"))
def test_a_command_that_prints_a_credentialed_url_can_redact_it(
    command: str, shape: str, tmp_path: Path, monkeypatch, capsys
):
    """Whatever surfaces the URL has to be able to hide the credential in it.

    The set is derived, not listed: the plain run has to print the secret for
    the assertion about the redacted run to mean anything, so a command that
    stops carrying it fails here loudly instead of passing on nothing.

    Both assertions are made against the output with its whitespace collapsed,
    because a long URL wraps rather than being truncated and the wrap can fall
    inside the credential. Read raw, a secret split across two lines would
    answer "not printed" to the first assertion and, worse, "not present" to
    the second.
    """
    # These commands build their own theme from the terminal, so the width has
    # to be pinned or the wrap point - and with it what a substring search over
    # the output can see - depends on whoever is running the suite.
    monkeypatch.setenv("COLUMNS", "110")

    if shape == "--html" and command != "scan":
        pytest.skip("--html is an output of a scan")
    media = _downloaded(tmp_path, "briefing.mp4", SECRET_URL)
    other = _downloaded(tmp_path, "annex.mp4", "https://media.example.org/v/13")
    argv = _invocation(command, media, other)

    assert main([*argv, shape]) == 0
    assert SECRET in _unwrapped(capsys.readouterr().out)

    assert main([*argv, shape, "--redact"]) == 0
    printed = _unwrapped(capsys.readouterr().out)
    assert SECRET not in printed
    assert "REDACTED" in printed
    assert "media.example.org" in printed  # the address itself is evidence and stays


def test_redacts_a_private_key_block_and_keeps_its_armour():
    """The armour says what was there; the body is the secret. A key pasted
    into a note arrives as one multi-line value, and a key on one line
    arrives without its footer - both lose the body and nothing else. The
    fixtures are assembled at run time: written out, the forge's push
    protection takes them for the real thing and declines the push."""
    armour = "-----"
    head = f"{armour}BEGIN RSA PRIVATE KEY{armour}"
    foot = f"{armour}END RSA PRIVATE KEY{armour}"
    body = "MIIEow" + "A" * 40 + "\n" + "zr8Qb" + "B" * 30 + "\n"

    redacted = redact_text(f"found in note: {head}\n{body}{foot}")
    one_line = redact_text(f"key {armour}BEGIN PRIVATE KEY{armour} MIIEvQ{'C' * 30} then more")

    assert "MIIEow" not in redacted and "zr8Qb" not in redacted
    assert redacted.count("[REDACTED:private_key:") == 1
    assert head in redacted and foot in redacted
    assert "MIIEvQ" not in one_line and "then more" in one_line
