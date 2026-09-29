"""A field name has to be a name somebody can look up.

The corpus printed thirty-odd rows like

    xmpMM:History/http://www.w3.org/1999/02/22-rdf-syntax-ns#:Seq/http://www.w3
    .org/1999/02/22-rdf-syntax-ns#:li/stEvt:action

which is three segments of RDF encoding wrapped around one segment of meaning,
under a namespace the prefix table happened not to list. Every part of that is
tested here: the prefixes that were missing, the array wrappers that are not
part of a property's name, and the history that already has a reader of its own
and does not need flattening into a field as well.
"""

from __future__ import annotations

import pytest

from filegrail.sources.xmp import read_xmp

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


def _packet(body: str) -> bytes:
    return f"""<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="{RDF}">
  <rdf:Description rdf:about=""
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/"
    xmlns:xmpTPg="http://ns.adobe.com/xap/1.0/t/pg/"
    xmlns:xapG="http://ns.adobe.com/xap/1.0/g/"
    xmlns:stEvt="http://ns.adobe.com/xap/1.0/sType/ResourceEvent#"
    xmlns:pdfuaid="http://www.aiim.org/pdfua/ns/id/">
{body}
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>""".encode()


@pytest.fixture
def read(tmp_path):
    """Read a packet written on its own, without a container around it.

    The reader searches for the packet rather than for a host format, so a bare
    one exercises the same path a JPEG does without the JPEG.
    """

    def go(body: str):
        target = tmp_path / "packet.xmp"
        target.write_bytes(_packet(body))
        return read_xmp(target)

    return go


@pytest.fixture
def fields(read):
    def go(body: str) -> dict[str, str]:
        origins = read(body)
        assert origins, "the packet produced no claim to read fields off"
        return origins[0].fields

    return go


@pytest.fixture
def names(fields):
    return lambda body: set(fields(body))


# --- every namespace has a prefix --------------------------------------------


def test_no_field_name_is_a_url(names):
    """A name a reader cannot say out loud is a name they cannot search for."""
    body = """
    <xmpTPg:SwatchGroups>
      <rdf:Seq><rdf:li><xapG:groupName>Default Swatch Group</xapG:groupName></rdf:li></rdf:Seq>
    </xmpTPg:SwatchGroups>
    <pdfuaid:part>1</pdfuaid:part>
    """

    assert not [name for name in names(body) if "http" in name]


def test_adobe_swatch_group_names_use_their_published_prefix(fields):
    body = """
    <xmpTPg:SwatchGroups>
      <rdf:Seq><rdf:li><xapG:swatchName>White</xapG:swatchName></rdf:li></rdf:Seq>
    </xmpTPg:SwatchGroups>
    """

    assert fields(body)["xmpTPg:SwatchGroups/xmpG:swatchName"] == "White"


def test_the_pdf_accessibility_part_is_named(fields):
    assert fields("<pdfuaid:part>1</pdfuaid:part>")["pdfuaid:part"] == "1"


# --- an array is how RDF spells "several", not part of the name --------------


def test_an_array_wrapper_is_not_a_segment_of_the_field_name(names):
    """`rdf:Seq` and `rdf:li` are encoding. A reader looking for the swatch
    name should not have to know how Adobe chose to nest it."""
    body = """
    <xmpTPg:SwatchGroups>
      <rdf:Seq>
        <rdf:li>
          <xapG:groupName>Default Swatch Group</xapG:groupName>
          <xapG:groupType>0</xapG:groupType>
        </rdf:li>
      </rdf:Seq>
    </xmpTPg:SwatchGroups>
    """

    found = names(body)

    assert "xmpTPg:SwatchGroups/xmpG:groupName" in found
    assert not [name for name in found if "rdf:" in name]


def test_several_entries_in_one_array_are_numbered_rather_than_lost(fields):
    """`setdefault` on a shared name kept the first and dropped the rest, so a
    document with two swatch groups reported one."""
    body = """
    <xmpTPg:SwatchGroups>
      <rdf:Seq>
        <rdf:li><xapG:groupName>First</xapG:groupName></rdf:li>
        <rdf:li><xapG:groupName>Second</xapG:groupName></rdf:li>
      </rdf:Seq>
    </xmpTPg:SwatchGroups>
    """

    found = fields(body)

    assert found["xmpTPg:SwatchGroups[1]/xmpG:groupName"] == "First"
    assert found["xmpTPg:SwatchGroups[2]/xmpG:groupName"] == "Second"


def test_a_language_alternative_still_reports_the_text_itself(fields):
    """The common case, and the one that must not regress: `dc:title` in an
    `rdf:Alt` is a title, not a structure."""
    body = """
    <dc:title><rdf:Alt><rdf:li xml:lang="x-default">Report</rdf:li></rdf:Alt></dc:title>
    """

    assert fields(body)["dc:title"] == "Report"


def test_an_empty_title_does_not_become_a_row_about_its_language(names):
    """Acrobat writes `<rdf:li xml:lang="x-default"/>` for a title nobody set.
    `x-default` under a name ending in `:lang` is the encoding describing
    itself, which is the same thing `rdf:about` is and is skipped for the same
    reason."""
    body = """
    <dc:title><rdf:Alt><rdf:li xml:lang="x-default"/></rdf:Alt></dc:title>
    <xmp:CreatorTool>Acrobat</xmp:CreatorTool>
    """

    found = names(body)

    assert "xmp:CreatorTool" in found
    assert not [name for name in found if "lang" in name]


# --- the history has a reader of its own -------------------------------------


def test_the_edit_history_is_not_also_flattened_into_the_fields(read):
    """Each step is already reported as its own dated claim with its own
    `stEvt:` fields. Walking the sequence a second time as a struct printed the
    same events again under names built out of RDF plumbing."""
    body = """
    <xmp:CreatorTool>Illustrator</xmp:CreatorTool>
    <xmpMM:History>
      <rdf:Seq>
        <rdf:li>
          <stEvt:action>saved</stEvt:action>
          <stEvt:when>2018-01-29T10:09:15-06:00</stEvt:when>
          <stEvt:softwareAgent>Adobe Illustrator CC 22.0</stEvt:softwareAgent>
        </rdf:li>
      </rdf:Seq>
    </xmpMM:History>
    """

    origins = read(body)

    assert not [name for name in origins[0].fields if name.startswith("xmpMM:History/")]
    assert any(origin.source == "xmp-history" for origin in origins)
    assert any(origin.fields.get("stEvt:action") == "saved" for origin in origins)


def test_an_undated_step_is_still_summarised_where_it_can_be_seen(fields):
    """A step with no `stEvt:when` cannot become a dated claim without
    inventing a moment, so it stays a field - and that has to survive the
    history no longer being walked as a struct."""
    body = """
    <xmpMM:History>
      <rdf:Seq>
        <rdf:li>
          <stEvt:action>converted</stEvt:action>
          <stEvt:parameters>from application/postscript</stEvt:parameters>
        </rdf:li>
      </rdf:Seq>
    </xmpMM:History>
    """

    found = fields(body)

    assert found["xmpMM:History[1]"] == "converted from application/postscript"


# --- a long array does not take the report over ------------------------------


def test_an_array_of_structs_is_bounded_and_says_what_it_dropped(fields):
    """One corpus PDF carries Illustrator's default palette: forty-five
    colorants of seven fields each. Reporting every one buries the file's
    provenance under its colour picker; reporting only the first in silence is
    how the old code lost forty-four of them without saying so."""
    swatches = "".join(
        f"<rdf:li><xapG:swatchName>Colour {index}</xapG:swatchName></rdf:li>" for index in range(45)
    )
    body = f"<xmpTPg:SwatchGroups><rdf:Seq>{swatches}</rdf:Seq></xmpTPg:SwatchGroups>"

    found = fields(body)

    assert found["xmpTPg:SwatchGroups[1]/xmpG:swatchName"] == "Colour 0"
    assert len([name for name in found if "swatchName" in name]) < 45
    assert found["xmpTPg:SwatchGroups"] == "45 entries, 3 shown"


def test_a_short_array_is_reported_whole_with_no_note(fields):
    swatches = "".join(
        f"<rdf:li><xapG:swatchName>Colour {index}</xapG:swatchName></rdf:li>" for index in range(2)
    )
    body = f"<xmpTPg:SwatchGroups><rdf:Seq>{swatches}</rdf:Seq></xmpTPg:SwatchGroups>"

    found = fields(body)

    assert found["xmpTPg:SwatchGroups[2]/xmpG:swatchName"] == "Colour 1"
    assert "xmpTPg:SwatchGroups" not in found


def test_the_swatch_namespace_uses_the_prefix_adobe_publishes(fields):
    """Adobe writes `xmpG` in its own files, which is what a reader searching
    for one of these names will have in front of them."""
    body = """
    <xmpTPg:SwatchGroups>
      <rdf:Seq><rdf:li><xapG:swatchName>White</xapG:swatchName></rdf:li></rdf:Seq>
    </xmpTPg:SwatchGroups>
    """

    assert "xmpTPg:SwatchGroups/xmpG:swatchName" in fields(body)
