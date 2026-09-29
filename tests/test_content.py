"""What a file says, as opposed to what it records about itself."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from filegrail.sources.content import MAX_TEXT_BYTES, read_passages
from tests.compound import ole


def _text(path: Path) -> str:
    """Everything the passages hold, for the tests that are about the text."""
    found = read_passages(path)
    return " ".join(passage.text for passage in found) if found else ""


def _places(path: Path) -> list[str]:
    found = read_passages(path)
    return [passage.place for passage in found] if found else []


def _zip(path: Path, members: dict[str, str]) -> None:
    written = io.BytesIO()
    with zipfile.ZipFile(written, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, text in members.items():
            bundle.writestr(name, text)
    path.write_bytes(written.getvalue())


# --- files that are already text ----------------------------------------------


def test_a_text_file_is_its_own_text(tmp_path: Path):
    note = tmp_path / "notes.txt"
    note.write_text("write to ann.shaw@acme-legal.example", encoding="utf-8")

    assert _text(note) == "write to ann.shaw@acme-legal.example"


def test_utf_16_is_read_as_utf_16(tmp_path: Path):
    """A Windows editor writes a byte order mark, and a UTF-8 read of that puts
    a NUL between every letter - which breaks every pattern, not one accent."""
    note = tmp_path / "notes.txt"
    note.write_bytes("ann.shaw@acme-legal.example".encode("utf-16"))

    assert _text(note) == "ann.shaw@acme-legal.example"


def test_a_format_nothing_here_reads_says_so(tmp_path: Path):
    photo = tmp_path / "holiday.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xd9")

    assert read_passages(photo) is None


def test_the_text_of_one_file_is_bounded(tmp_path: Path):
    note = tmp_path / "huge.log"
    note.write_text("a" * (MAX_TEXT_BYTES * 2), encoding="utf-8")

    assert len(_text(note)) == MAX_TEXT_BYTES


def test_the_budget_is_spent_across_the_document_not_per_piece(tmp_path: Path):
    """A file cannot cost more by being cut into many pieces than by being one,
    which is the same reasoning `MAX_PARTS` applies to a package's members."""
    note = tmp_path / "huge.log"
    note.write_text(("x" * 999 + "\n") * (MAX_TEXT_BYTES // 999 + 10), encoding="utf-8")

    assert sum(len(passage.text) for passage in read_passages(note)) == MAX_TEXT_BYTES


# --- markup -------------------------------------------------------------------


def test_html_gives_up_its_text_and_its_links(tmp_path: Path):
    page = tmp_path / "invoice.html"
    page.write_text(
        "<html><head><style>a { color: #abc; }</style>"
        "<script>var host = 'tracker.example';</script></head>"
        "<body><p>Invoice from <b>Acme</b></p>"
        '<a href="https://acme-legal.example/pay">pay here</a></body></html>',
        encoding="utf-8",
    )

    text = _text(page)

    assert "Invoice from Acme" in " ".join(text.split())
    assert "https://acme-legal.example/pay" in text


def test_html_leaves_the_script_and_the_style_out(tmp_path: Path):
    """Neither is what the document says, and both are full of things that
    match: a colour is a hash, a bundler writes hosts nobody typed."""
    page = tmp_path / "page.html"
    page.write_text(
        "<html><style>.x { color: #aabbccddeeff00112233445566778899; }</style>"
        "<script>fetch('https://cdn.tracker.example/a.js');</script>"
        "<body>hello</body></html>",
        encoding="utf-8",
    )

    text = _text(page)

    assert "hello" in text
    assert "tracker.example" not in text


def test_a_namespace_declaration_is_not_something_the_document_said(tmp_path: Path):
    """Every XML file in the world names w3.org. It is markup, not content."""
    drawing = tmp_path / "logo.svg"
    drawing.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><title>Acme</title>'
        '<a href="https://acme-legal.example">brand</a></svg>',
        encoding="utf-8",
    )

    text = _text(drawing)

    assert "Acme" in text
    assert "https://acme-legal.example" in text
    assert "w3.org" not in text


# --- the zip-based document formats -------------------------------------------


def test_a_word_document_gives_up_its_body(tmp_path: Path):
    document = tmp_path / "letter.docx"
    _zip(
        document,
        {
            "docProps/core.xml": "<cp:coreProperties/>",
            "word/document.xml": "<w:document><w:t>Contact ann.shaw@acme-legal.example</w:t>"
            "</w:document>",
        },
    )

    assert "ann.shaw@acme-legal.example" in _text(document)


def test_a_word_document_footnote_counts_as_its_body(tmp_path: Path):
    document = tmp_path / "letter.docx"
    _zip(
        document,
        {
            "word/document.xml": "<w:document><w:t>see below</w:t></w:document>",
            "word/footnotes.xml": "<w:footnotes><w:t>ann.shaw@acme-legal.example</w:t>"
            "</w:footnotes>",
        },
    )

    text = _text(document)

    assert "see below" in text
    assert "ann.shaw@acme-legal.example" in text


def test_a_presentation_gives_up_every_slide(tmp_path: Path):
    deck = tmp_path / "deck.pptx"
    _zip(
        deck,
        {
            "ppt/slides/slide1.xml": "<p:sld><a:t>first</a:t></p:sld>",
            "ppt/slides/slide2.xml": "<p:sld><a:t>ann.shaw@acme-legal.example</a:t></p:sld>",
        },
    )

    text = _text(deck)

    assert "first" in text
    assert "ann.shaw@acme-legal.example" in text


def test_a_spreadsheet_gives_up_its_shared_strings(tmp_path: Path):
    book = tmp_path / "ledger.xlsx"
    _zip(
        book,
        {
            "xl/sharedStrings.xml": "<sst><si><t>ann.shaw@acme-legal.example</t></si></sst>",
            "xl/worksheets/sheet1.xml": "<worksheet><v>42</v></worksheet>",
        },
    )

    assert "ann.shaw@acme-legal.example" in _text(book)


def test_an_opendocument_file_gives_up_its_content(tmp_path: Path):
    document = tmp_path / "letter.odt"
    _zip(
        document,
        {
            "meta.xml": "<office:document-meta/>",
            "content.xml": "<office:body><text:p>ann.shaw@acme-legal.example</text:p>"
            "</office:body>",
        },
    )

    assert "ann.shaw@acme-legal.example" in _text(document)


def test_an_epub_gives_up_its_chapters(tmp_path: Path):
    book = tmp_path / "book.epub"
    _zip(
        book,
        {
            "META-INF/container.xml": "<container/>",
            "OEBPS/chapter1.xhtml": "<html><body><p>ann.shaw@acme-legal.example</p></body></html>",
        },
    )

    assert "ann.shaw@acme-legal.example" in _text(book)


def test_a_package_that_is_not_a_package_says_nothing(tmp_path: Path):
    document = tmp_path / "letter.docx"
    document.write_bytes(b"PK\x03\x04 and then nothing")

    assert read_passages(document) is None


# --- mail ---------------------------------------------------------------------


def test_a_message_gives_up_its_body_and_not_its_headers(tmp_path: Path):
    """The headers are already read as evidence of delivery. Repeating them here
    would count one address twice and file it under the wrong corpus."""
    message = tmp_path / "message.eml"
    message.write_bytes(
        b"From: sender@example.test\r\nTo: someone@example.test\r\n"
        b"Subject: the file\r\nContent-Type: text/plain\r\n\r\n"
        b"Write to ann.shaw@acme-legal.example\r\n"
    )

    text = _text(message)

    assert "ann.shaw@acme-legal.example" in text
    assert "sender@example.test" not in text


def test_a_message_body_is_decoded_before_it_is_read(tmp_path: Path):
    """Quoted-printable hides an address from anything reading the raw bytes."""
    message = tmp_path / "message.eml"
    message.write_bytes(
        b"From: sender@example.test\r\nContent-Type: text/plain\r\n"
        b"Content-Transfer-Encoding: quoted-printable\r\n\r\n"
        b"Write to ann=2Eshaw@acme-legal.example\r\n"
    )

    assert "ann.shaw@acme-legal.example" in _text(message)


def test_an_outlook_message_gives_up_its_body(tmp_path: Path):
    message = tmp_path / "message.msg"
    message.write_bytes(
        ole({"__substg1.0_1000001F": "ann.shaw@acme-legal.example".encode("utf-16-le")})
    )

    assert "ann.shaw@acme-legal.example" in _text(message)


def test_only_so_many_members_of_one_package_are_read(tmp_path: Path):
    """A deck can hold a thousand slides, and each one costs an open and a parse."""
    from filegrail.sources.content import MAX_PARTS

    deck = tmp_path / "deck.pptx"
    _zip(
        deck,
        {
            f"ppt/slides/slide{number}.xml": f"<p:sld><a:t>slide-{number}</a:t></p:sld>"
            for number in range(1, MAX_PARTS + 3)
        },
    )

    text = _text(deck)

    assert "slide-1" in text
    assert f"slide-{MAX_PARTS + 2}" not in text


def test_a_member_too_large_to_read_does_not_take_the_rest_with_it(tmp_path: Path):
    """`read_part` refuses one member; the document is not only that member."""
    from filegrail.sources.embedded.parts import MAX_PART_BYTES

    document = tmp_path / "letter.docx"
    _zip(
        document,
        {
            "word/document.xml": "<w:t>" + "a" * (MAX_PART_BYTES + 1) + "</w:t>",
            "word/footnotes.xml": "<w:t>ann.shaw@acme-legal.example</w:t>",
        },
    )

    text = _text(document)

    assert "ann.shaw@acme-legal.example" in text
    assert "aaaa" not in text


# --- where in the document ----------------------------------------------------
#
# The point of cutting the text into passages at all. An identifier reported as
# "invoice.docx" sends somebody back to search the file; one reported as
# "invoice.docx · slide 4" does not. Each place is written in the terms the
# format actually has - a Word file gets no page number, because pagination
# happens when something renders it and the file does not record where the
# breaks fell.


def test_a_text_file_is_addressed_by_line(tmp_path: Path):
    note = tmp_path / "notes.txt"
    note.write_text("first\n\nthird\nfourth\n", encoding="utf-8")

    assert _places(note) == ["line 1", "line 3", "line 4"]


def test_a_table_is_addressed_by_row_and_column(tmp_path: Path):
    """A row read as one line runs its columns together.

    The separator ends up inside the value: a URL in one column takes the `,`
    and the column after it, which is a value nobody can go and look at. Read
    as cells, the value is the cell and the place names the column it sat in.
    """
    table = tmp_path / "contacts.csv"
    table.write_text(
        "name,source_url,role\nK. Dabrowa,https://social.example.net/@kdabrowa,signed\n",
        encoding="utf-8",
    )

    found = {passage.place: passage.text for passage in read_passages(table)}

    assert found["row 2 · column 2"] == "https://social.example.net/@kdabrowa"
    assert "signed" not in found["row 2 · column 2"]
    assert found["row 2 · column 3"] == "signed"


def test_markup_is_addressed_by_the_line_of_the_file(tmp_path: Path):
    """`HTMLParser` reports the line the markup was on, which is a line of the
    file rather than a line of the text that came out of it."""
    page = tmp_path / "invoice.html"
    page.write_text(
        "<html>\n<body>\n<p>Invoice from Acme</p>\n"
        '<a href="https://acme-legal.example/pay">pay</a>\n</body>\n</html>\n',
        encoding="utf-8",
    )

    found = {passage.text.strip(): passage.place for passage in read_passages(page)}

    assert found["Invoice from Acme"] == "line 3"
    assert found["https://acme-legal.example/pay"] == "line 4"


def test_a_slide_is_addressed_by_its_number(tmp_path: Path):
    deck = tmp_path / "deck.pptx"
    _zip(
        deck,
        {
            "ppt/slides/slide1.xml": "<p:sld><a:t>opening</a:t></p:sld>",
            "ppt/slides/slide4.xml": "<p:sld><a:t>ann.shaw@acme-legal.example</a:t></p:sld>",
            "ppt/notesSlides/notesSlide4.xml": "<p:notes><a:t>ask about this</a:t></p:notes>",
        },
    )

    found = {passage.place: passage.text for passage in read_passages(deck)}

    assert found["slide 4"] == "ann.shaw@acme-legal.example"
    assert found["slide 4 notes"] == "ask about this"
    assert "slide 1" in found


def test_the_parts_of_a_word_document_are_named_apart(tmp_path: Path):
    document = tmp_path / "letter.docx"
    _zip(
        document,
        {
            "word/document.xml": "<w:t>see below</w:t>",
            "word/footnotes.xml": "<w:t>ann.shaw@acme-legal.example</w:t>",
            "word/comments.xml": "<w:t>check this</w:t>",
        },
    )

    assert sorted(_places(document)) == ["body", "comments", "footnotes"]


def test_a_workbook_names_its_sheets_and_its_strings(tmp_path: Path):
    book = tmp_path / "ledger.xlsx"
    _zip(
        book,
        {
            "xl/sharedStrings.xml": "<sst><si><t>ann.shaw@acme-legal.example</t></si></sst>",
            "xl/worksheets/sheet2.xml": "<worksheet><is><t>inline</t></is></worksheet>",
        },
    )

    assert sorted(_places(book)) == ["cell text", "sheet 2"]


def test_an_opendocument_file_keeps_its_headers_apart_from_its_body(tmp_path: Path):
    document = tmp_path / "letter.odt"
    _zip(
        document,
        {
            "content.xml": "<text:p>the letter</text:p>",
            "styles.xml": "<style:header><text:p>ann.shaw@acme-legal.example</text:p>"
            "</style:header>",
        },
    )

    found = {passage.place: passage.text for passage in read_passages(document)}

    assert found["body"] == "the letter"
    assert found["headers and footers"] == "ann.shaw@acme-legal.example"


def test_a_chapter_is_addressed_by_the_name_the_book_gives_it(tmp_path: Path):
    book = tmp_path / "book.epub"
    _zip(
        book,
        {
            "META-INF/container.xml": "<container/>",
            "OEBPS/chapter3.xhtml": "<html><body><p>ann.shaw@acme-legal.example</p></body></html>",
        },
    )

    assert _places(book) == ["chapter3.xhtml"]


def test_the_two_bodies_of_a_message_are_named_apart(tmp_path: Path):
    message = tmp_path / "message.eml"
    message.write_bytes(
        b'Content-Type: multipart/alternative; boundary="x"\r\n\r\n'
        b"--x\r\nContent-Type: text/plain\r\n\r\nplain body\r\n"
        b"--x\r\nContent-Type: text/html\r\n\r\n<p>rich body</p>\r\n"
        b"--x--\r\n"
    )

    found = {passage.place: passage.text.strip() for passage in read_passages(message)}

    assert found["body"] == "plain body"
    assert found["body (html)"] == "rich body"


# --- positions --------------------------------------------------------------
#
# A track file and a map file carry positions as structure, not prose: an
# attribute pair, or `lon,lat` with the longitude first. The reader renders
# each one as a `geo:` URI, which is the one spelling the coordinate detector
# takes without a hemisphere letter or a label - so the detectors need not
# know these formats exist, and a bare decimal pair is still never believed.


def test_a_gpx_waypoint_is_a_geo_uri_with_its_place(tmp_path: Path):
    path = tmp_path / "walk.gpx"
    path.write_text(
        '<gpx><wpt lat="52.2297" lon="21.0122"><name>Warsaw</name></wpt></gpx>',
        encoding="utf-8",
    )

    assert ("waypoint 1", "geo:52.2297,21.0122") in [tuple(p) for p in read_passages(path) or []]


def test_a_longitude_first_pair_is_turned_around(tmp_path: Path):
    """KML and GeoJSON both write `lon,lat`; a reader that forgot would put
    Warsaw in the Indian Ocean and nothing downstream could tell."""
    kml = tmp_path / "places.kml"
    kml.write_text(
        "<kml><Placemark><Point><coordinates>21.0122,52.2297,0</coordinates></Point>"
        "</Placemark></kml>",
        encoding="utf-8",
    )
    geojson = tmp_path / "places.geojson"
    geojson.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","geometry":'
        '{"type":"Point","coordinates":[21.0122,52.2297]}}]}',
        encoding="utf-8",
    )

    assert ("placemark 1", "geo:52.2297,21.0122") in [tuple(p) for p in read_passages(kml) or []]
    assert ("feature 1", "geo:52.2297,21.0122") in [tuple(p) for p in read_passages(geojson) or []]


def test_a_track_gives_only_its_start_and_its_end(tmp_path: Path):
    """A track is thousands of points and a report is not the place for them;
    where it began and where it stopped is what a reader wants to know."""
    path = tmp_path / "run.gpx"
    path.write_text(
        '<gpx><trk><trkseg><trkpt lat="52.1" lon="21.1"/><trkpt lat="52.2" lon="21.2"/>'
        '<trkpt lat="52.3" lon="21.3"/></trkseg></trk></gpx>',
        encoding="utf-8",
    )

    found = [tuple(p) for p in read_passages(path) or []]

    assert ("track 1 start", "geo:52.1,21.1") in found
    assert ("track 1 end", "geo:52.3,21.3") in found
    assert not [p for p in found if "52.2" in p[1]]


def test_a_graph_file_gives_up_its_labels(tmp_path: Path):
    path = tmp_path / "links.graphml"
    path.write_text(
        '<graphml><node id="n0"><data key="d0">ann.shaw@acme-legal.example</data></node></graphml>',
        encoding="utf-8",
    )

    assert "ann.shaw@acme-legal.example" in _text(path)


# --- labels in attributes, and packages of maps and graphs -------------------


def test_a_graph_label_in_an_attribute_is_read(tmp_path: Path):
    """GEXF and FreeMind keep the text of a node in an attribute, where a
    reader that only keeps addresses would never look."""
    path = tmp_path / "network.gexf"
    path.write_text(
        '<gexf><graph><nodes><node id="0" label="ann.shaw@acme-legal.example"/></nodes>'
        "</graph></gexf>",
        encoding="utf-8",
    )

    assert "ann.shaw@acme-legal.example" in _text(path)


def test_a_zipped_map_gives_up_its_positions(tmp_path: Path):
    path = tmp_path / "places.kmz"
    _zip(
        path,
        {
            "doc.kml": "<kml><Placemark><Point><coordinates>21.0122,52.2297,0"
            "</coordinates></Point></Placemark></kml>"
        },
    )

    assert ("placemark 1", "geo:52.2297,21.0122") in [tuple(p) for p in read_passages(path) or []]


def test_a_mind_map_gives_up_its_json_body(tmp_path: Path):
    path = tmp_path / "case.xmind"
    _zip(path, {"content.json": '[{"rootTopic":{"title":"ann.shaw@acme-legal.example"}}]'})

    found = read_passages(path) or []

    assert [p.place for p in found] == ["body"]
    assert "ann.shaw@acme-legal.example" in found[0].text


def test_a_maltego_graph_gives_up_its_entities(tmp_path: Path):
    path = tmp_path / "case.mtgx"
    _zip(
        path,
        {
            "Graphs/Graph1.graphml": '<graphml><node id="n0"><data key="d0">'
            '<mtg:MaltegoEntity type="maltego.EmailAddress"><mtg:Properties>'
            '<mtg:Property name="email"><mtg:Value>ann.shaw@acme-legal.example</mtg:Value>'
            "</mtg:Property></mtg:Properties></mtg:MaltegoEntity></data></node></graphml>"
        },
    )

    found = read_passages(path) or []

    assert [p.place for p in found] == ["graph 1"]
    assert "ann.shaw@acme-legal.example" in found[0].text
