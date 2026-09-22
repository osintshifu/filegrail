"""JPEG structure facts that do not require decoding image pixels."""

import io
import struct
from pathlib import Path

from filegrail.photojpeg import _entropy_marker, analyse_jpeg, jpeg_size


def _segment(marker: int, payload: bytes) -> bytes:
    return b"\xff" + bytes((marker,)) + struct.pack(">H", len(payload) + 2) + payload


def _jpeg(*, sof: int = 0xC0, trailing: bytes = b"") -> bytes:
    dqt = bytes((0,)) + bytes((1,)) * 64 + bytes((1,)) + bytes((1,)) * 64
    dht = bytes((0,)) + bytes((1,)) + bytes(15) + b"\x00"
    frame = (
        b"\x08"
        + struct.pack(">HHB", 24, 32, 3)
        + b"\x01\x22\x00"
        + b"\x02\x11\x01"
        + b"\x03\x11\x01"
    )
    scan = b"\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00"
    return (
        b"\xff\xd8"
        + _segment(0xDB, dqt)
        + _segment(0xC4, dht)
        + _segment(0xDD, b"\x00\x08")
        + _segment(0xFE, b"camera note")
        + _segment(sof, frame)
        + _segment(0xDA, scan)
        + b"\x11\xff\x00\x22\xff\xd0\x33"
        + b"\xff\xd9"
        + trailing
    )


def test_reads_jpeg_structure_through_entropy_data_and_eoi(tmp_path: Path):
    photo = tmp_path / "frame.jpg"
    photo.write_bytes(_jpeg())

    found = analyse_jpeg(photo)

    assert found is not None
    assert (found.width, found.height) == (32, 24)
    assert found.encoding == "baseline DCT"
    assert found.precision == 8
    assert found.components == ((1, 2, 2, 0), (2, 1, 1, 1), (3, 1, 1, 1))
    assert found.scans == 1
    assert found.restart_interval == 8
    assert found.comments == ("camera note",)
    assert [marker.name for marker in found.markers] == [
        "SOI",
        "DQT",
        "DHT",
        "DRI",
        "COM",
        "SOF0",
        "SOS",
        "RST0",
        "EOI",
    ]
    quantization = [
        (table.identifier, table.precision, len(table.values)) for table in found.quantization
    ]
    assert quantization == [
        (0, 8, 64),
        (1, 8, 64),
    ]
    assert [(table.table_class, table.identifier, table.symbols) for table in found.huffman] == [
        ("DC", 0, 1)
    ]
    assert found.quality is not None
    assert found.quality.quality == 100
    assert found.quality.exact is True
    assert found.trailing_bytes == 0


def test_reports_progressive_scans_and_bytes_after_eoi(tmp_path: Path):
    photo = tmp_path / "progressive.jpg"
    photo.write_bytes(_jpeg(sof=0xC2, trailing=b"hidden"))

    found = analyse_jpeg(photo)

    assert found is not None
    assert found.encoding == "progressive DCT"
    assert found.scans == 1
    assert found.trailing_bytes == 6


def test_jpeg_size_rejects_a_truncated_frame():
    assert jpeg_size(b"\xff\xd8\xff\xc0\x00\x11\x08\x00") is None


def test_reads_16_bit_quantization_table(tmp_path: Path):
    photo = tmp_path / "precision.jpg"
    dqt = bytes((0x10,)) + b"".join(struct.pack(">H", index + 1) for index in range(64))
    photo.write_bytes(b"\xff\xd8" + _segment(0xDB, dqt) + b"\xff\xd9")

    found = analyse_jpeg(photo)

    assert found is not None
    assert len(found.quantization) == 1
    assert found.quantization[0].precision == 16
    assert found.quantization[0].values == tuple(range(1, 65))
    assert found.quality is None


def test_marks_nonstandard_quantization_as_nearest_estimate(tmp_path: Path):
    photo = tmp_path / "nonstandard-quality.jpg"
    dqt = bytes((0,)) + bytes((2,)) * 64
    photo.write_bytes(b"\xff\xd8" + _segment(0xDB, dqt) + b"\xff\xd9")

    found = analyse_jpeg(photo)

    assert found is not None
    assert found.quality is not None
    assert (found.quality.quality, found.quality.exact, found.quality.distance) == (99, False, 42)


def test_reads_multiple_progressive_scans(tmp_path: Path):
    photo = tmp_path / "multiscan.jpg"
    scan = _segment(0xDA, b"\x01\x01\x00\x00\x00\x00")
    photo.write_bytes(b"\xff\xd8" + scan + b"\x11" + scan + b"\x22\xff\xd9")

    found = analyse_jpeg(photo)

    assert found is not None
    assert found.scans == 2
    assert [marker.name for marker in found.markers] == ["SOI", "SOS", "SOS", "EOI"]


def test_rejects_truncated_or_invalid_segments(tmp_path: Path):
    truncated = tmp_path / "truncated.jpg"
    truncated.write_bytes(b"\xff\xd8\xff\xdb\x00\x43\x00\x01")
    invalid_table = tmp_path / "zero-table.jpg"
    invalid_table.write_bytes(b"\xff\xd8" + _segment(0xDB, bytes((0,)) + bytes(64)) + b"\xff\xd9")

    assert analyse_jpeg(truncated) is None
    assert analyse_jpeg(invalid_table) is None


class _Exhausting(io.BytesIO):
    """A file that will not be read from for ever.

    The scan reads on until it has a byte to decide on, and a file whose last
    bytes could still begin a marker never gives it one. Counting the reads
    turns that into a failure this suite can report, rather than a run that
    never ends: there is no portable timeout to lean on here.
    """

    def __init__(self, data: bytes, limit: int = 64) -> None:
        super().__init__(data)
        self.reads = 0
        self.limit = limit

    def read(self, size: int | None = -1) -> bytes:
        self.reads += 1
        if self.reads > self.limit:
            raise AssertionError("the entropy scan read past the end of the file")
        return super().read(size if size is not None else -1)


def test_an_entropy_scan_ending_in_padding_bytes_stops_at_the_end_of_the_file():
    """A run of 0xFF at the end of a file is padding before a marker that is not there.

    Padding is kept in hand because the marker it introduces may straddle the
    block boundary. When the file ends instead, there is nothing to complete it
    with, and the scan has to end on the read returning nothing rather than on
    what is still held.
    """
    markers: list = []

    assert _entropy_marker(_Exhausting(b"scan data\xff\xff"), markers) == (None, 0)
    assert _entropy_marker(_Exhausting(b"scan data\xff"), markers) == (None, 0)
    assert markers == []


def test_a_scan_claiming_more_restarts_than_a_file_may_hold_is_refused():
    """The marker budget is a file's, so it has to bind inside a single scan.

    Counted on the way out it bounds nothing: a scan declaring millions of
    restart markers is read into memory in full before anything checks.
    """
    from filegrail.photojpeg import _MAX_SEGMENTS

    markers: list = []

    found, restarts = _entropy_marker(io.BytesIO(b"\xff\xd0" * (_MAX_SEGMENTS * 2)), markers)

    assert found is None
    assert len(markers) == _MAX_SEGMENTS
    assert restarts == _MAX_SEGMENTS


def test_redaction_blanks_the_bytes_a_comment_segment_opens_with(tmp_path: Path):
    """A byte map prints what it names, and a comment's bytes are the comment.

    Redaction takes the text out of `comments`; without this it would come back
    one line below, in the opening bytes the byte map shows beside each segment.
    """
    path = tmp_path / "noted.jpg"
    path.write_bytes(_jpeg())
    analysis = analyse_jpeg(path)
    assert analysis is not None
    assert b"camera note" in next(marker.head for marker in analysis.markers if marker.code == 0xFE)

    redacted = analysis.redacted()
    assert all(marker.head == b"" for marker in redacted.markers if marker.code == 0xFE)
    # Every other segment keeps the bytes that say what it is.
    assert next(marker.head for marker in redacted.markers if marker.code == 0xD8) == b"\xff\xd8"
