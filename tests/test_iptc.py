"""IPTC IIM, the press byline that predates XMP and still travels with photographs."""

import struct
from pathlib import Path

from filegrail.models import METADATA, SOURCE_LABELS, SOURCE_PRIORITY, category
from filegrail.scan import scan
from filegrail.sources.iptc import read_iptc


def _dataset(number: int, value: bytes, record: int = 2) -> bytes:
    """One IIM dataset, whose length is measured rather than typed."""
    return b"\x1c" + bytes([record, number]) + struct.pack(">H", len(value)) + value


def _irb(resource: int, payload: bytes) -> bytes:
    """One 8BIM image-resource block, padded to an even size as the format requires."""
    block = b"8BIM" + struct.pack(">H", resource) + b"\x00\x00" + struct.pack(">I", len(payload))
    return block + payload + (b"\x00" if len(payload) % 2 else b"")


def _app13(*blocks: bytes) -> tuple[bytes, bytes]:
    return b"\xff\xed", b"Photoshop 3.0\x00" + b"".join(blocks)


def _jpeg(*segments: tuple[bytes, bytes]) -> bytes:
    out = b"\xff\xd8"
    for marker, payload in segments:
        out += marker + struct.pack(">H", len(payload) + 2) + payload
    return out + b"\xff\xd9"


def test_reads_the_byline_and_credit_from_a_jpeg(tmp_path: Path):
    photo = tmp_path / "wire.jpg"
    photo.write_bytes(
        _jpeg(
            _app13(
                _irb(
                    0x0404,
                    _dataset(80, b"Francisco Gonzalez")
                    + _dataset(110, b"Reuters")
                    + _dataset(116, b"(c) 2019 Reuters"),
                )
            )
        )
    )

    claim = read_iptc(photo)

    assert claim is not None
    assert claim.source == "iptc"
    assert claim.fields["By-line"] == "Francisco Gonzalez"
    assert claim.note == "by-line Francisco Gonzalez; credit Reuters; (c) 2019 Reuters"


def test_the_date_and_time_datasets_combine_into_one_moment(tmp_path: Path):
    """IIM splits a timestamp across two datasets and keeps the zone on the
    time. Read apart they are two strings; read together they are a moment."""
    photo = tmp_path / "dated.jpg"
    photo.write_bytes(
        _jpeg(_app13(_irb(0x0404, _dataset(55, b"20190304") + _dataset(60, b"124155+0100"))))
    )

    claim = read_iptc(photo)

    assert claim.at == "2019-03-04T11:41:55Z"


def test_the_place_reads_from_the_most_specific_dataset_outwards(tmp_path: Path):
    """A newsroom fills these separately. Read as one line they are an address;
    read as four fields nobody sees the place at all."""
    photo = tmp_path / "placed.jpg"
    photo.write_bytes(
        _jpeg(
            _app13(
                _irb(
                    0x0404,
                    _dataset(90, b"Firenze")
                    + _dataset(92, b"Ponte Vecchio")
                    + _dataset(95, b"Toscana")
                    + _dataset(101, b"Italy"),
                )
            )
        )
    )

    claim = read_iptc(photo)

    assert claim.location == "Ponte Vecchio, Firenze, Toscana, Italy"
    assert claim.geo is None


def test_the_originating_program_and_its_version_name_the_tool(tmp_path: Path):
    photo = tmp_path / "made.jpg"
    photo.write_bytes(
        _jpeg(_app13(_irb(0x0404, _dataset(65, b"Adobe Photoshop") + _dataset(70, b"7.0"))))
    )

    assert read_iptc(photo).tool == "Adobe Photoshop 7.0"


def test_without_a_character_set_the_bytes_read_as_latin_1(tmp_path: Path):
    """IIM predates Unicode. A block that does not declare UTF-8 is holding
    single-byte text, and decoding it as UTF-8 replaces the accents with
    question marks - which is losing a byline, not reading one."""
    photo = tmp_path / "accented.jpg"
    photo.write_bytes(_jpeg(_app13(_irb(0x0404, _dataset(80, b"Zo\xeb Mal\xe9")))))

    assert read_iptc(photo).fields["By-line"] == "Zoë Malé"


def test_the_character_set_dataset_selects_utf_8(tmp_path: Path):
    photo = tmp_path / "unicode.jpg"
    photo.write_bytes(
        _jpeg(
            _app13(
                _irb(
                    0x0404,
                    _dataset(90, b"\x1b%G", record=1) + _dataset(80, "Zoë Malé".encode()),
                )
            )
        )
    )

    assert read_iptc(photo).fields["By-line"] == "Zoë Malé"


def _extended(number: int, value: bytes, size_bytes: int = 4) -> bytes:
    """A dataset using IIM's extended length form, for values over 32767 bytes."""
    header = b"\x1c" + bytes([2, number]) + struct.pack(">H", 0x8000 | size_bytes)
    return header + len(value).to_bytes(size_bytes, "big") + value


def test_an_extended_length_dataset_is_read(tmp_path: Path):
    """A caption longer than 32767 bytes cannot state its length in two bytes,
    so IIM sets the top bit and says how many bytes the real length takes. A
    reader that misses this does not lose one field - it loses its place in the
    stream and every dataset after it."""
    caption = b"A " + b"very " * 30 + b"long caption"
    photo = tmp_path / "wordy.jpg"
    photo.write_bytes(
        _jpeg(_app13(_irb(0x0404, _extended(120, caption) + _dataset(80, b"Ansel Adams"))))
    )

    claim = read_iptc(photo)

    assert claim.fields["Caption-Abstract"] == caption.decode()
    assert claim.fields["By-line"] == "Ansel Adams"


def test_iptc_is_metadata_ranked_below_xmp(tmp_path: Path):
    """Modern tools maintain XMP and leave the IIM block untouched, so a byline
    here is the older of the two accounts and often the staler - but it is still
    purpose-built for attribution, which a bare document property is not."""
    photo = tmp_path / "ranked.jpg"
    photo.write_bytes(_jpeg(_app13(_irb(0x0404, _dataset(80, b"Ansel Adams")))))

    claim = read_iptc(photo)

    assert category(claim) == METADATA
    assert claim.priority == 51
    assert SOURCE_PRIORITY["document-metadata"] < claim.priority < SOURCE_PRIORITY["xmp"]
    assert SOURCE_LABELS["iptc"] == "IPTC"


def test_a_scan_surfaces_the_iptc_claim(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    case = tmp_path / "case"
    case.mkdir()
    (case / "wire.jpg").write_bytes(
        _jpeg(_app13(_irb(0x0404, _dataset(80, b"Ansel Adams") + _dataset(110, b"Magnum"))))
    )

    record = scan(case, home=home, use_shell_history=False)[0]

    assert [origin.source for origin in record.evidence if origin.source == "iptc"] == ["iptc"]


def test_the_record_version_reads_as_a_number_not_a_control_character(tmp_path: Path):
    """Dataset 0 is a 16-bit version, the one field of the application record
    that is not text. Decoded as text it puts a control character in the report,
    which is neither readable nor a fact anybody can use."""
    photo = tmp_path / "versioned.jpg"
    photo.write_bytes(
        _jpeg(_app13(_irb(0x0404, _dataset(0, b"\x00\x02") + _dataset(80, b"Ansel Adams"))))
    )

    fields = read_iptc(photo).fields

    assert fields["RecordVersion"] == "2"
    assert "2:0" not in fields


# --- the other containers, and broken ones -----------------------------------


def test_reads_iptc_from_a_tiff(tmp_path: Path):
    """TIFF carries the same image-resource block under tag 34377."""
    irb = _irb(0x0404, _dataset(80, b"Dorothea Lange"))
    values_at = 8 + 2 + 12 + 4
    raw = tmp_path / "plate.tiff"
    raw.write_bytes(
        b"MM\x00\x2a"
        + struct.pack(">I", 8)
        + struct.pack(">H", 1)
        + struct.pack(">HHII", 0x8649, 7, len(irb), values_at)
        + struct.pack(">I", 0)
        + irb
    )

    assert read_iptc(raw).fields["By-line"] == "Dorothea Lange"


def test_reads_iptc_from_a_photoshop_document(tmp_path: Path):
    irb = _irb(0x0404, _dataset(80, b"Walker Evans"))
    header = (
        b"8BPS"
        + struct.pack(">H", 1)
        + b"\x00" * 6
        + struct.pack(">HIIHH", 3, 1, 1, 8, 3)
        + struct.pack(">I", 0)  # colour mode data
        + struct.pack(">I", len(irb))
    )
    document = tmp_path / "layered.psd"
    document.write_bytes(header + irb)

    assert read_iptc(document).fields["By-line"] == "Walker Evans"


def test_an_unrelated_resource_does_not_hide_the_one_that_matters(tmp_path: Path):
    """A file carries many 8BIM blocks; only 0x0404 holds an IIM datastream."""
    photo = tmp_path / "many.jpg"
    photo.write_bytes(
        _jpeg(
            _app13(
                _irb(0x03ED, b"\x00\x48\x00\x00\x00\x48\x00\x00"),  # resolution
                _irb(0x0404, _dataset(80, b"Gordon Parks")),
            )
        )
    )

    assert read_iptc(photo).fields["By-line"] == "Gordon Parks"


def test_a_block_claiming_more_than_it_holds_yields_nothing(tmp_path: Path):
    photo = tmp_path / "truncated.jpg"
    body = b"Photoshop 3.0\x00" + b"8BIM\x04\x04\x00\x00" + struct.pack(">I", 4096) + b"\x1c\x02P"
    photo.write_bytes(_jpeg((b"\xff\xed", body)))

    assert read_iptc(photo) is None


def test_one_broken_block_does_not_end_a_scan(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    case = tmp_path / "case"
    case.mkdir()
    (case / "a-broken.jpg").write_bytes(
        _jpeg((b"\xff\xed", b"Photoshop 3.0\x00" + b"8BIM\x04\x04" + b"\xff" * 9))
    )
    (case / "b-sound.jpg").write_bytes(_jpeg(_app13(_irb(0x0404, _dataset(80, b"Robert Capa")))))

    records = scan(case, home=home, use_shell_history=False)

    assert len(records) == 2
    assert any(origin.fields.get("By-line") == "Robert Capa" for origin in records[1].evidence)


def test_reads_a_raw_iim_datastream_from_tiff_tag_33723(tmp_path: Path):
    """Some TIFF writers store the datastream directly, with no Photoshop block
    around it. There is no marker to search for then - `\\x1c\\x02` is two bytes
    and would match anything - so the tag has to be found through the IFD."""
    iim = _dataset(80, b"Berenice Abbott") + _dataset(90, b"New York")
    values_at = 8 + 2 + 12 + 4
    raw = tmp_path / "plate.tiff"
    raw.write_bytes(
        b"MM\x00\x2a"
        + struct.pack(">I", 8)
        + struct.pack(">H", 1)
        + struct.pack(">HHII", 0x83BB, 7, len(iim), values_at)  # tag 33723, UNDEFINED
        + struct.pack(">I", 0)
        + iim
    )

    claim = read_iptc(raw)

    assert claim.fields["By-line"] == "Berenice Abbott"
    assert claim.location == "New York"


def test_a_datastream_stored_as_longs_is_read_in_full(tmp_path: Path):
    """Some writers type tag 33723 as LONG. The count is then in 4-byte units,
    and reading it as bytes leaves three quarters of the block behind."""
    iim = _dataset(80, b"Berenice Abbott") + _dataset(90, b"New York")
    iim += b"\x00" * (-len(iim) % 4)
    values_at = 8 + 2 + 12 + 4
    raw = tmp_path / "plate.tiff"
    raw.write_bytes(
        b"MM\x00\x2a"
        + struct.pack(">I", 8)
        + struct.pack(">H", 1)
        + struct.pack(">HHII", 0x83BB, 4, len(iim) // 4, values_at)  # tag 33723, LONG
        + struct.pack(">I", 0)
        + iim
    )

    claim = read_iptc(raw)

    assert claim.fields["By-line"] == "Berenice Abbott"
    assert claim.location == "New York"
