"""Everything a reader decoded, kept rather than summarised.

The report answers "where did this come from" and stays short to do it. An
investigation asks a different question - "what else does this file say" - and
cannot know in advance which field will matter. So readers keep what they
decode, `--json` always carries it, and the text report shows it on request.
"""

from __future__ import annotations

import json
from pathlib import Path

from filegrail.models import EvidenceRecord, FileRecord
from filegrail.report import render_json, render_text
from filegrail.theme import Theme

PLAIN = Theme(colour=False, unicode=False, width=88)

FIELDS = {
    "Make": "NIKON",
    "Model": "COOLPIX P6000",
    "BodySerialNumber": "3001234",
    "GPSDateStamp": "2008:10:22",
    "DateTimeDigitized": "2008:10:22 16:38:20",
}


def _record(fields: dict[str, str] | None = None) -> FileRecord:
    record = FileRecord(path="/case/holiday.jpg", size=4096, mtime="2026-08-24T19:00:00Z")
    record.evidence.append(
        EvidenceRecord(
            source="device-metadata",
            tool="NIKON COOLPIX P6000",
            at="2008-10-22T16:38:20Z",
            fields=dict(FIELDS if fields is None else fields),
        )
    )
    return record


def test_fields_reach_the_json_without_a_flag():
    """Machine-readable output is where the full record belongs by default."""
    payload = json.loads(render_json([_record()], Path("/case")))

    fields = payload["files"][0]["evidence"][0]["fields"]
    assert fields["BodySerialNumber"] == "3001234"
    assert fields["GPSDateStamp"] == "2008:10:22"


def test_the_report_shows_every_field_by_default():
    output = render_text([_record()], Path("/case"), theme=PLAIN)

    for name, value in FIELDS.items():
        assert name in output, name
        assert value in output, value


def test_brief_stops_before_any_field_block():
    """`--brief` is the index and what leads to it. It used to be the same
    report with the fields taken out, which is not a shorter answer to the
    question a large directory asks - it is the same length minus the detail."""
    output = render_text([_record()], Path("/case"), theme=PLAIN, brief=True)

    assert "BodySerialNumber" not in output
    assert "FILES IN DETAIL" not in output


def test_the_field_block_keeps_the_report_inside_the_width():
    theme = Theme(colour=False, unicode=False, width=56)
    long_fields = {"UserComment": "x" * 400, "ImageDescription": "y" * 200}

    output = render_text([_record(long_fields)], Path("/case"), theme=theme)

    assert not [line for line in output.splitlines() if len(line) > 56]


def test_redaction_sweeps_the_fields():
    """A free-text tag is a place a credential can hide, so it must be swept."""
    secret = "https://api.example.org/v1?api_key=sk-live-9f2b7c4e1d8a6350f4a1"
    record = _record({"UserComment": secret, "Model": "COOLPIX P6000"})

    redacted = record.redacted()

    assert "sk-live-9f2b7c4e1d8a6350f4a1" not in json.dumps(redacted.to_dict())
    assert redacted.evidence[0].fields["Model"] == "COOLPIX P6000"


def test_an_origin_without_fields_serialises_cleanly():
    record = FileRecord(path="/case/a.txt", size=1, mtime="2026-08-24T19:00:00Z")
    record.evidence.append(EvidenceRecord(source="filesystem"))

    payload = json.loads(render_json([record], Path("/case")))

    assert "fields" not in payload["files"][0]["evidence"][0]
