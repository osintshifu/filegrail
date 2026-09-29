"""Do the origin records agree with each other?

One record is a claim. Two records that agree are corroboration. Two that
disagree are a finding in their own right - a file downloaded twice, a file
copied after it arrived, or origin metadata that was replaced - and a report
that silently prints the higher-scoring one has destroyed the finding.
"""

from __future__ import annotations

from pathlib import Path

from filegrail.correlate import (
    AGREEMENT,
    ATTRIBUTION_CONFLICT,
    CONFLICT,
    NONE,
    PARTIAL,
    SELF_CONTRADICTORY,
    SINGLE,
    correlate,
)
from filegrail.models import FILENAME, EvidenceRecord, FileRecord
from filegrail.report import render_text
from filegrail.theme import Theme

PLAIN = Theme(colour=False, unicode=True, width=88)


def _record(*origins: EvidenceRecord, mtime: str = "2026-08-24T19:00:00Z") -> FileRecord:
    record = FileRecord(path="/case/a.pdf", size=4096, mtime=mtime)
    record.evidence.extend(origins)
    return record


def _download(url: str, **extra) -> EvidenceRecord:
    return EvidenceRecord(source="browser-download", url=url, tool="firefox", **extra)


def _zone(url: str, **extra) -> EvidenceRecord:
    return EvidenceRecord(source="windows-zone-identifier", url=url, **extra)


# --- the verdict -------------------------------------------------------------


def test_no_origin_record_at_all():
    verdict = correlate(_record(EvidenceRecord(source="device-metadata", tool="Canon")))

    assert verdict.state == NONE


def test_one_record_is_not_corroboration():
    """A single source is the ordinary case, and not a finding either way."""
    verdict = correlate(_record(_download("https://example.org/a.pdf")))

    assert verdict.state == SINGLE


def test_two_records_naming_the_same_url_agree():
    verdict = correlate(
        _record(_download("https://example.org/a.pdf"), _zone("https://example.org/a.pdf"))
    )

    assert verdict.state == AGREEMENT
    assert "browser download" in " ".join(verdict.reasons)


def test_trivial_url_differences_still_agree():
    """A trailing slash and a capitalised host are the same address."""
    verdict = correlate(
        _record(_download("https://Example.ORG/a.pdf"), _zone("https://example.org/a.pdf/"))
    )

    assert verdict.state == AGREEMENT


def test_the_same_host_by_a_different_path_is_partial():
    verdict = correlate(
        _record(_download("https://example.org/a.pdf"), _zone("https://example.org/copy/a.pdf"))
    )

    assert verdict.state == PARTIAL
    assert "example.org" in " ".join(verdict.reasons)


def test_different_hosts_conflict():
    verdict = correlate(
        _record(_download("https://example.com/a.pdf"), _zone("https://mirror.example.net/a.pdf"))
    )

    assert verdict.state == CONFLICT
    reasons = " ".join(verdict.reasons)
    assert "example.com" in reasons
    assert "mirror.example.net" in reasons


def test_a_file_claiming_to_predate_nothing_is_unremarkable():
    """Created before it was downloaded is the normal order of events."""
    verdict = correlate(
        _record(
            _download("https://example.org/a.pdf", at="2026-08-24T19:02:11Z"),
            EvidenceRecord(source="document-metadata", tool="Word", at="2026-08-01T10:00:00Z"),
        )
    )

    assert verdict.state == SINGLE
    assert not verdict.reasons


def test_a_file_claiming_to_postdate_its_download_is_flagged():
    """The bytes cannot have been authored after they arrived."""
    verdict = correlate(
        _record(
            _download("https://example.org/a.pdf", at="2026-08-01T10:00:00Z"),
            EvidenceRecord(source="document-metadata", tool="Word", at="2026-08-24T19:02:11Z"),
        )
    )

    assert any("after" in reason for reason in verdict.reasons)


def test_a_name_only_match_is_called_out():
    origin = _download("https://example.org/a.pdf")
    origin.match = FILENAME
    origin.match_note = "the file was moved or renamed since download"

    verdict = correlate(_record(origin))

    assert any("name" in reason for reason in verdict.reasons)


# --- what the report shows ---------------------------------------------------


def test_a_single_source_gets_no_verdict_line():
    """The common case must not be annotated, or the annotation means nothing."""
    output = render_text(
        [_record(_download("https://example.org/a.pdf"))], Path("/case"), theme=PLAIN
    )

    assert "agreement" not in output
    assert "conflict" not in output


def test_a_conflict_is_reported():
    record = _record(
        _download("https://example.com/a.pdf"), _zone("https://mirror.example.net/a.pdf")
    )

    output = render_text([record], Path("/case"), theme=PLAIN)

    assert "conflict" in output


def test_a_conflict_shows_both_records_without_verbose():
    """A verdict that refers to evidence the report hid is not a verdict."""
    record = _record(
        _download("https://example.com/a.pdf"), _zone("https://mirror.example.net/a.pdf")
    )

    output = render_text([record], Path("/case"), theme=PLAIN)

    assert "example.com/a.pdf" in output
    assert "mirror.example.net/a.pdf" in output


def test_agreement_is_reported_too():
    record = _record(_download("https://example.org/a.pdf"), _zone("https://example.org/a.pdf"))

    output = render_text([record], Path("/case"), theme=PLAIN)

    assert "corroboration" in output


# --- what the file says about itself, said twice ------------------------------


def _iptc(**fields: str) -> EvidenceRecord:
    return EvidenceRecord(source="iptc", block="iptc", fields=dict(fields))


def _xmp(**fields: str) -> EvidenceRecord:
    return EvidenceRecord(
        source="xmp",
        block="xmp",
        fields={name.replace("_", ":"): v for name, v in fields.items()},
    )


def _exif(**fields: str) -> EvidenceRecord:
    return EvidenceRecord(source="device-metadata", block="exif", fields=dict(fields))


def test_a_camera_and_its_xmp_mirror_naming_different_models_is_a_finding():
    """The `tiff:` properties are the XMP serialisation of the EXIF tags - the
    specification says so - which is what makes them comparable at all. Two
    different cameras in one file is one of them having been rewritten."""
    record = _record(
        _exif(Make="Canon", Model="Canon PowerShot G9"),
        _xmp(tiff_Make="NIKON CORPORATION", tiff_Model="NIKON D700"),
    )

    findings = correlate(record).findings

    assert [f.kind for f in findings] == [ATTRIBUTION_CONFLICT, ATTRIBUTION_CONFLICT]
    assert "device metadata says Canon" in findings[0].text
    assert "XMP says NIKON CORPORATION" in findings[0].text


def test_a_camera_agreeing_with_its_mirror_says_nothing():
    record = _record(
        _exif(Make="Canon", Model="Canon PowerShot G9"),
        _xmp(tiff_Make="Canon", tiff_Model="Canon PowerShot G9"),
    )

    assert correlate(record).findings == []


def test_a_zoneless_tag_agrees_with_its_zoned_mirror():
    """EXIF writes no zone and the XMP mirror writes the same clock reading with
    one attached. Reading the tag as UTC and the mirror as an instant would make
    every photograph taken outside Greenwich contradict itself."""
    record = _record(
        _exif(DateTimeOriginal="2004:08:27 13:52:55"),
        _xmp(exif_DateTimeOriginal="2004-08-27T13:52:55+02:00"),
    )

    assert correlate(record).findings == []


def test_a_capture_time_moved_to_another_day_is_a_finding():
    record = _record(
        _exif(DateTimeOriginal="2004:08:27 13:52:55"),
        _xmp(exif_DateTimeOriginal="2004-08-28T13:52:55+02:00"),
    )

    assert [f.kind for f in correlate(record).findings] == [ATTRIBUTION_CONFLICT]


def test_a_bare_iim_day_agrees_with_a_full_xmp_stamp():
    """IIM records the day in one dataset and the clock in another, so its date
    field is eight digits. A day that agrees is not a conflict merely because
    the other writer also wrote down a time."""
    record = _record(
        _iptc(DateCreated="20190304"),
        _xmp(photoshop_DateCreated="2019-03-04T10:22:31+01:00"),
    )

    assert correlate(record).findings == []


def test_exposure_settings_are_left_out_of_the_comparison():
    """XMP writers put units, rationals and comma decimals in these - "f/5,6"
    against 5.6, "1/500 sec." against 0.002 - and a comparison that cannot read
    them would report a conflict on almost every photograph ever taken."""
    record = _record(
        _exif(FNumber="5.6", ExposureTime="0.002", FocalLength="105"),
        _xmp(exif_FNumber="f/5,6", exif_ExposureTime="1/500 sec.", exif_FocalLength="105,0 mm"),
    )

    assert correlate(record).findings == []


def test_two_self_descriptions_disagreeing_about_the_byline_is_a_finding():
    """IIM and XMP hold the same facts, and tools maintain the XMP while leaving
    the IIM block as they found it. Two different photographers in one file is
    not a formatting difference - it is the trace of an attribution being
    changed, and printing both without a word leaves the reader to notice."""
    record = _record(
        _iptc(**{"By-line": "Francisco Gonzalez", "Credit": "Reuters"}),
        _xmp(dc_creator="Marta Nowak", photoshop_Credit="Agencja Wschod"),
    )

    findings = correlate(record).findings

    assert [f.kind for f in findings] == [ATTRIBUTION_CONFLICT, ATTRIBUTION_CONFLICT]
    assert "IPTC says Francisco Gonzalez" in findings[0].text
    assert "XMP says Marta Nowak" in findings[0].text
    assert "By-line" in findings[0].text


def test_two_self_descriptions_that_agree_are_not_a_finding():
    """One editor writes both blocks at once and keeps them consistent, so
    agreement here is the common case. Annotating it would put a line on almost
    every photograph, and a line on everything says nothing."""
    record = _record(
        _iptc(**{"By-line": "Ansel Adams", "Credit": "Magnum"}),
        _xmp(dc_creator="ansel  adams", photoshop_Credit="Magnum"),
    )

    assert correlate(record).findings == []


def _info(**fields: str) -> EvidenceRecord:
    return EvidenceRecord(source="document-metadata", block="pdf-info", fields=dict(fields))


def test_an_info_dictionary_and_its_xmp_naming_different_applications_is_a_finding():
    """A PDF carries the same facts twice, and XMP Part 3 publishes the pairing.
    Two different applications in one file is an export that stamped a fresh
    Info dictionary over XMP it carried through from the source document."""
    record = _record(
        _info(Creator="Adobe InDesign CC 13.1 (Macintosh)"),
        _xmp(xmp_CreatorTool="Adobe Illustrator CC 22.0 (Macintosh)"),
    )

    findings = correlate(record).findings

    assert [f.kind for f in findings] == [ATTRIBUTION_CONFLICT]
    assert "Creator: PDF Info says Adobe InDesign CC 13.1 (Macintosh)" in findings[0].text
    assert "XMP says Adobe Illustrator CC 22.0 (Macintosh)" in findings[0].text


def test_an_info_dictionary_and_its_xmp_disagreeing_about_the_title_is_a_finding():
    record = _record(
        _info(Title="Szybki wniosek", Author="OSINT360"),
        _xmp(dc_title="OSINT360 - potencjalni klienci", dc_creator="OSINT360"),
    )

    findings = correlate(record).findings

    assert [f.kind for f in findings] == [ATTRIBUTION_CONFLICT]
    assert "Title" in findings[0].text


def test_an_info_dictionary_agreeing_with_its_xmp_says_nothing():
    """One producer writes both blocks at the same save and keeps them
    consistent, which is the ordinary case and worth no line at all."""
    record = _record(
        _info(
            Title="Szybki wniosek",
            Author="OSINT360",
            Subject="Segmentacja klientow",
            Keywords="OSINT360, klienci",
            Creator="Writer",
            Producer="LibreOffice 25.2.3.2",
        ),
        _xmp(
            dc_title="Szybki wniosek",
            dc_creator="OSINT360",
            dc_description="Segmentacja klientow",
            pdf_Keywords="OSINT360, klienci",
            xmp_CreatorTool="Writer",
            pdf_Producer="LibreOffice 25.2.3.2",
        ),
    )

    assert correlate(record).findings == []


def test_an_info_dictionary_dated_months_from_its_xmp_is_a_finding():
    """A PDF writes `D:YYYYMMDDHHmmSS` with the offset in its own punctuation,
    and its XMP writes the same fact as ISO 8601. Three months between the two
    is an export stamped long after the XMP it carried through."""
    record = _record(
        _info(CreationDate="D:20180511143720-04'00'"),
        _xmp(xmp_CreateDate="2018-02-28T13:44:18-05:00"),
    )

    findings = correlate(record).findings

    assert [f.kind for f in findings] == [ATTRIBUTION_CONFLICT]
    assert "CreationDate" in findings[0].text


def test_an_info_dictionary_dated_with_its_xmp_says_nothing():
    record = _record(
        _info(CreationDate="D:20180511143720-04'00'", ModDate="D:20180511143721-04'00'"),
        _xmp(
            xmp_CreateDate="2018-05-11T14:37:20-04:00",
            xmp_ModifyDate="2018-05-11T14:37:21-04:00",
        ),
    )

    assert correlate(record).findings == []


def test_a_modification_date_moved_away_from_its_xmp_is_a_finding():
    """Unlike EXIF `DateTime`, whose XMP mirror is maintained by tools that
    leave the tag alone, both of a PDF's modification dates are written by the
    producer at the same save. A gap between them is one of the two blocks not
    having been rewritten."""
    record = _record(
        _info(ModDate="D:20180511143721-04'00'"),
        _xmp(xmp_ModifyDate="2018-04-05T17:19:03-04:00"),
    )

    assert [f.kind for f in correlate(record).findings] == [ATTRIBUTION_CONFLICT]


def test_a_pdf_stamp_without_punctuation_still_reads_as_a_moment():
    """LibreOffice writes `D:20260707080205Z'` - no separator before the clock,
    where every other writer this compares puts a `T` or a space. Read as
    unreadable it would be silently skipped, and the thirteen years between
    this and its XMP would go unreported."""
    record = _record(
        _info(CreationDate="D:20260707080205Z'"),
        _xmp(xmp_CreateDate="2026-07-07T08:02:05Z"),
    )

    assert correlate(record).findings == []


def test_one_instant_written_in_two_zones_is_not_a_disagreement():
    """Both of a PDF's stamps carry an offset, and one machine varies it across
    the year - the corpus has a file whose Info says -04'00' and whose XMP says
    -05:00. Comparing the readings and ignoring what the writers said about
    their zone would call a single instant a contested attribution."""
    record = _record(
        _info(CreationDate="D:20180511143720-04'00'"),
        _xmp(xmp_CreateDate="2018-05-11T13:37:20-05:00"),
    )

    assert correlate(record).findings == []


def test_one_reading_in_two_zones_is_a_disagreement():
    """The other side of the same rule. Two stamps an hour apart are two
    moments, and sharing a wall clock does not make them one."""
    record = _record(
        _info(CreationDate="D:20180511143720-04'00'"),
        _xmp(xmp_CreateDate="2018-05-11T14:37:20-05:00"),
    )

    assert [f.kind for f in correlate(record).findings] == [ATTRIBUTION_CONFLICT]


def test_a_zone_can_carry_a_stamp_across_midnight():
    """Both name 2018-05-12T03:37:20Z, on either side of local midnight. The
    readings disagree about the day, and the day is all a zoneless comparison
    has to go on."""
    record = _record(
        _info(CreationDate="D:20180511233720-04'00'"),
        _xmp(xmp_CreateDate="2018-05-12T00:37:20-03:00"),
    )

    assert correlate(record).findings == []


def test_the_producer_string_is_left_out_of_the_comparison():
    """One library writes its own name into both blocks at one save, and Adobe
    PDF Library 15 writes it two ways: `Adobe PDF Library 15.0` into the Info
    dictionary and `Adobe PDF library 15.00` into the XMP. Case and spacing are
    already forgiven; the trailing zero is not, and a pair that reports a tool
    disagreeing with itself would put a line on Adobe exports at large."""
    record = _record(
        _info(Producer="Adobe PDF Library 15.0"),
        _xmp(pdf_Producer="Adobe PDF library 15.00"),
    )

    assert correlate(record).findings == []


def _text_chunks(**fields: str) -> EvidenceRecord:
    return EvidenceRecord(
        source="document-metadata",
        block="png-text",
        fields={name.replace("_", " "): value for name, value in fields.items()},
    )


def test_png_text_chunks_naming_a_different_application_than_the_xmp_is_a_finding():
    """XMP Part 3 maps the standard PNG keywords onto XMP properties, and `Software`
    is one of them - in a PNG it names the application that made the image, which
    is what `xmp:CreatorTool` holds."""
    record = _record(
        _text_chunks(Software="matplotlib 3.9.0"),
        _xmp(xmp_CreatorTool="Adobe Photoshop 25.0"),
    )

    findings = correlate(record).findings

    assert [f.kind for f in findings] == [ATTRIBUTION_CONFLICT]
    assert "Software: PNG text says matplotlib 3.9.0" in findings[0].text


def test_png_text_chunks_agreeing_with_the_xmp_say_nothing():
    record = _record(
        _text_chunks(
            Title="Q3 revenue",
            Author="Jan Kowalski",
            Description="quarterly figures",
            Copyright="(c) 2026 Acme",
            Software="matplotlib 3.9.0",
        ),
        _xmp(
            dc_title="Q3 revenue",
            dc_creator="Jan Kowalski",
            dc_description="quarterly figures",
            dc_rights="(c) 2026 Acme",
            xmp_CreatorTool="matplotlib 3.9.0",
        ),
    )

    assert correlate(record).findings == []


def test_a_png_creation_time_is_compared_against_the_xmp():
    record = _record(
        _text_chunks(Creation_Time="2023-07-30T14:22:01+00:00"),
        _xmp(xmp_CreateDate="2019-01-15T09:00:00Z"),
    )

    assert [f.kind for f in correlate(record).findings] == [ATTRIBUTION_CONFLICT]


def test_a_png_creation_time_in_the_format_the_specification_asks_for_is_skipped():
    """PNG says `Creation Time` should be RFC 1123 - `Sun, 30 Jul 2023 14:22:01
    +0000` - which nothing here can read, though the writers that put a date
    there mostly write ISO. Unreadable is not disagreement, so the pair is
    skipped rather than reported, and the comparison stays silent instead of
    inventing a conflict on every PNG that follows the specification."""
    record = _record(
        _text_chunks(Creation_Time="Sun, 30 Jul 2023 14:22:01 +0000"),
        _xmp(xmp_CreateDate="2019-01-15T09:00:00Z"),
    )

    assert correlate(record).findings == []


def test_a_camera_software_tag_is_not_paired_with_the_creating_application():
    """EXIF `Software` is the last thing that processed the file and
    `xmp:CreatorTool` is the application that made it. They are different facts
    and differ in ordinary use - a photograph edited in GIMP after being
    exported from Photoshop Elements says both, truthfully. The pairing belongs
    to a PDF Info dictionary, where `/Creator` does mean the creating
    application, and applying it to EXIF would invent a conflict."""
    record = _record(
        _exif(Software="GIMP 2.4.5"),
        _xmp(xmp_CreatorTool="Adobe Photoshop Elements 3.0"),
    )

    assert correlate(record).findings == []


def test_a_riff_software_field_is_not_read_as_a_tiff_tag():
    """`tiff:Software` is the XMP serialisation of the EXIF tag, and the mirror
    exists because that correspondence is published. A WAV's INFO list also has
    a field spelled Software, and it is a different fact - the mirror is between
    two standards, not between two words. Both claims are `document-metadata`,
    so a mirror keyed on the source cannot tell them apart."""
    record = _record(
        EvidenceRecord(
            source="document-metadata",
            block="riff",
            fields={"Software": "Audacity 3.4.2"},
        ),
        EvidenceRecord(source="xmp", block="xmp", fields={"tiff:Software": "Adobe Audition 24.0"}),
    )

    assert correlate(record).findings == []


def test_a_contested_attribution_is_not_labelled_by_the_origin_state():
    """`state` describes how the origin records relate. Printing it over a
    finding that came from somewhere else labels one thing with the name of
    another - and "no origin record", in the colour of good news, is a
    strange headline for two photographers contradicting each other."""
    record = _record(
        _iptc(**{"By-line": "Francisco Gonzalez"}),
        _xmp(dc_creator="Marta Nowak"),
    )

    output = render_text([record], Path("/case"), theme=PLAIN)

    assert "attribution conflict" in output
    assert "ORIGIN" not in output


def test_a_contested_attribution_brings_both_self_descriptions_on_screen():
    """The report shows one metadata record, the leading one. A finding that names
    IPTC while the report prints only the XMP is a verdict about evidence the
    reader cannot see - the same reason a conflicting origin record is
    brought forward."""
    iptc = _iptc(**{"By-line": "Francisco Gonzalez"})
    iptc.tool = "Adobe Photoshop 7.0"
    xmp = _xmp(dc_creator="Marta Nowak")
    xmp.tool = "darktable 4.6.1"

    output = render_text([_record(iptc, xmp)], Path("/case"), theme=PLAIN)

    # The tool heads a rendered claim and appears nowhere in a finding's text,
    # so seeing both is seeing both claims rather than one claim and a quotation.
    assert "Adobe Photoshop 7.0" in output
    assert "darktable 4.6.1" in output


# --- the file contradicting itself -------------------------------------------


def test_a_pdf_modified_before_it_was_created_is_a_contradiction():
    """Not a surprising order of events. An impossible one."""
    record = _record(
        EvidenceRecord(
            source="document-metadata",
            block="pdf-info",
            fields={"CreationDate": "D:20260824190000Z", "ModDate": "D:20260101120000Z"},
        )
    )

    verdict = correlate(record)

    assert [f for f in verdict.findings if "before it was created" in f.text]


def test_an_office_document_modified_before_it_was_created():
    record = _record(
        EvidenceRecord(
            source="document-metadata",
            block="ooxml-properties",
            fields={"created": "2026-08-24T19:00:00Z", "modified": "2026-01-01T12:00:00Z"},
        )
    )

    assert [f for f in correlate(record).findings if "before it was created" in f.text]


def test_xmp_modified_before_it_was_created():
    record = _record(
        EvidenceRecord(
            source="xmp",
            block="xmp",
            fields={
                "xmp:CreateDate": "2026-08-24T19:00:00Z",
                "xmp:ModifyDate": "2026-01-01T12:00:00Z",
            },
        )
    )

    assert [f for f in correlate(record).findings if "before it was created" in f.text]


def test_the_ordinary_order_is_not_a_finding():
    """Created, then modified later. The normal life of a document."""
    record = _record(
        EvidenceRecord(
            source="document-metadata",
            block="pdf-info",
            fields={"CreationDate": "D:20260101120000Z", "ModDate": "D:20260824190000Z"},
        )
    )

    assert not correlate(record).findings


def test_two_stamps_that_cannot_be_ranked_are_left_alone():
    """One writer said which zone it was in and the other did not, on the same
    day. Ranking them would be inventing the missing half."""
    record = _record(
        EvidenceRecord(
            source="document-metadata",
            block="pdf-info",
            fields={"CreationDate": "D:20260824190000Z", "ModDate": "D:20260824120000"},
        )
    )

    assert not correlate(record).findings


def test_a_self_contradiction_is_not_headlined_as_an_origin_state():
    """`state` describes the origin records. A file whose own dates run
    backwards has said nothing about its origin, and heading that finding
    "no origin record" labels one thing with the name of another."""
    record = _record(
        EvidenceRecord(
            source="document-metadata",
            block="pdf-info",
            fields={"CreationDate": "D:20260824190000Z", "ModDate": "D:20260101120000Z"},
        )
    )

    assert correlate(record).headline == SELF_CONTRADICTORY


def _edit(when: str | None, said: str = "saved") -> EvidenceRecord:
    return EvidenceRecord(source="xmp-history", block="xmp-history", at=when, note=said)


def test_an_editing_history_that_runs_backwards_is_a_contradiction():
    """`xmpMM:History` is an ordered sequence, so a step dated before the one
    it follows is the file disagreeing with its own account of itself."""
    record = _record(
        _edit("2026-08-24T19:00:00Z", "created"),
        _edit("2026-01-01T12:00:00Z", "exported"),
    )

    assert [f for f in correlate(record).findings if "runs backwards" in f.text]


def test_an_editing_history_in_order_is_not_a_finding():
    record = _record(
        _edit("2026-01-01T12:00:00Z", "created"),
        _edit("2026-08-24T19:00:00Z", "exported"),
    )

    assert not correlate(record).findings


def test_two_steps_at_the_same_moment_are_not_backwards():
    """An application that saves and exports in one action writes both at the
    same second. Equal is not decreasing."""
    record = _record(
        _edit("2026-01-01T12:00:00Z", "saved"),
        _edit("2026-01-01T12:00:00Z", "exported"),
    )

    assert not correlate(record).findings


def test_a_creation_time_seconds_after_arrival_is_clock_skew_not_a_conflict():
    """Two clocks wrote the two moments. A file that reports being created a
    few seconds after it was downloaded is not a file made after it arrived."""
    from filegrail.correlate import TIMELINE_CONFLICT

    close = _record(
        _download("https://x.test/a", at="2026-08-24T12:00:00Z"),
        EvidenceRecord(source="document-metadata", tool="Writer", at="2026-08-24T12:00:40Z"),
    )
    later = _record(
        _download("https://x.test/a", at="2026-08-24T12:00:00Z"),
        EvidenceRecord(source="document-metadata", tool="Writer", at="2026-08-24T12:20:00Z"),
    )

    assert TIMELINE_CONFLICT not in [f.kind for f in correlate(close).findings]
    assert TIMELINE_CONFLICT in [f.kind for f in correlate(later).findings]
