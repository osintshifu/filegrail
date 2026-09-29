"""Telemetry tracks beside the video: GoPro's GPMF and Google's CAMM."""

import struct
from pathlib import Path

from filegrail.sources.embedded import read_embedded_metadata


def _atom(category: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + category + payload


def _klv(key: bytes, kind: bytes, size: int, repeat: int, payload: bytes) -> bytes:
    return (
        key
        + kind
        + bytes([size])
        + struct.pack(">H", repeat)
        + payload
        + b"\x00" * (-len(payload) % 4)
    )


def _nested(key: bytes, children: list[bytes]) -> bytes:
    body = b"".join(children)
    return _klv(key, b"\x00", 1, len(body), body)


def _text(key: bytes, text: str) -> bytes:
    return _klv(key, b"c", 1, len(text), text.encode("ascii"))


def _movie(
    tmp_path: Path, name: str, format_: bytes, samples: list[bytes], udta: bytes = b""
) -> Path:
    """An MP4 whose metadata track's sample tables point at real offsets."""
    stsd = _atom(b"stsd", struct.pack(">II", 0, 1) + _atom(format_, b"\x00" * 8))
    stsc = _atom(b"stsc", struct.pack(">II", 0, 1) + struct.pack(">III", 1, 1, 1))
    stsz = _atom(
        b"stsz",
        struct.pack(">III", 0, 0, len(samples))
        + b"".join(struct.pack(">I", len(s)) for s in samples),
    )
    hdlr = _atom(b"hdlr", b"\x00" * 8 + b"meta" + b"\x00" * 12 + b"GoPro MET\x00")

    def build(offsets: list[int]) -> bytes:
        stco = _atom(
            b"stco",
            struct.pack(">II", 0, len(offsets)) + b"".join(struct.pack(">I", o) for o in offsets),
        )
        stbl = _atom(b"stbl", stsd + stsc + stsz + stco)
        trak = _atom(b"trak", _atom(b"mdia", hdlr + _atom(b"minf", stbl)))
        return _atom(b"ftyp", b"mp41") + _atom(
            b"moov", trak + (_atom(b"udta", udta) if udta else b"")
        )

    head = build([0] * len(samples))
    offsets = []
    at = len(head) + 8
    for sample in samples:
        offsets.append(at)
        at += len(sample)
    path = tmp_path / name
    path.write_bytes(build(offsets) + _atom(b"mdat", b"".join(samples)))
    return path


def _gpmf_sample(utc: bytes, points: list[tuple[int, int]]) -> bytes:
    gps = _nested(
        b"STRM",
        [
            _text(b"STNM", "GPS (Lat., Long., Alt., 2D speed, 3D speed)"),
            _klv(b"GPSF", b"L", 4, 1, struct.pack(">I", 3)),
            _klv(b"GPSU", b"U", 16, 1, utc),
            _klv(b"SCAL", b"l", 4, 5, struct.pack(">5i", 10000000, 10000000, 1000, 1000, 100)),
            _klv(
                b"GPS5",
                b"l",
                20,
                len(points),
                b"".join(struct.pack(">5i", lat, lon, 120000, 1500, 1600) for lat, lon in points),
            ),
        ],
    )
    accl = _nested(
        b"STRM", [_text(b"STNM", "Accelerometer"), _klv(b"ACCL", b"s", 6, 1, b"\x00" * 6)]
    )
    return _nested(
        b"DEVC",
        [
            _klv(b"DVID", b"L", 4, 1, struct.pack(">I", 1)),
            _text(b"DVNM", "HERO12 Black"),
            gps,
            accl,
        ],
    )


def test_a_gopro_recording_names_its_device_firmware_and_gps_track(tmp_path: Path):
    udta = (
        _atom(b"FIRM", b"H23.01.02.32.00\x00")
        + _atom(b"LENS", b"LAJ8112801234567\x00")
        + _atom(b"CAME", bytes(range(16)))
    )
    path = _movie(
        tmp_path,
        "GX010042.MP4",
        b"gpmd",
        [
            _gpmf_sample(b"260918093000.000", [(521234567, 210123456), (521234600, 210123500)]),
            _gpmf_sample(b"260918093001.000", [(521234700, 210123600)]),
        ],
        udta,
    )

    found = read_embedded_metadata(path)

    assert found is not None
    assert found.source == "device-metadata"
    assert found.tool == "HERO12 Black"
    assert found.geo == "52.123457, 21.012346"
    assert found.at == "2026-09-18T09:30:00Z"
    assert found.note == "GPS track of 3 points from 2026-09-18T09:30:00Z to 2026-09-18T09:30:01Z"
    assert found.fields["GoPro:Firmware"] == "H23.01.02.32.00"
    assert found.fields["GoPro:CameraSerial"] == bytes(range(16)).hex()
    assert found.fields["GPMF:Device"] == "HERO12 Black"
    assert found.fields["GPMF:Streams"] == (
        "GPS (Lat., Long., Alt., 2D speed, 3D speed), Accelerometer"
    )
    assert found.fields["GPMF:GPSLast"] == "52.12347, 21.01236"
    assert found.fields["GPMF:GPSFix"] == "3"


def test_a_camm_track_gives_the_gps_track_and_its_clock(tmp_path: Path):
    def fix(epoch: float, latitude: float, longitude: float) -> bytes:
        return struct.pack("<HH", 0, 6) + struct.pack(
            "<diddd6f", epoch, 3, latitude, longitude, 15.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0
        )

    path = _movie(
        tmp_path,
        "walk.mp4",
        b"camm",
        [fix(1_789_723_800.0, 50.06143, 19.93658), fix(1_789_723_860.0, 50.06200, 19.93700)],
    )

    found = read_embedded_metadata(path)

    assert found is not None
    assert found.geo == "50.06143, 19.93658"
    assert found.fields["CAMM:GPSPoints"] == "2"
    assert found.fields["CAMM:GPSStart"] == "2026-09-18T09:30:00Z"
    assert found.fields["CAMM:GPSEnd"] == "2026-09-18T09:31:00Z"
