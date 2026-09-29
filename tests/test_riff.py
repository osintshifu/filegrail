"""RIFF containers: what a WAV or an AVI says about its own making."""

import struct
from pathlib import Path

from filegrail.sources.embedded import read_embedded_metadata
from filegrail.sources.embedded.riff import read_riff


def chunk(fourcc: bytes, payload: bytes) -> bytes:
    """One RIFF chunk: a name, a little-endian length, and even padding."""
    return fourcc + struct.pack("<I", len(payload)) + payload + b"\x00" * (len(payload) % 2)


def riff(form: bytes, chunks: list[bytes]) -> bytes:
    body = form + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def info(entries: list[tuple[bytes, bytes]]) -> bytes:
    return chunk(b"LIST", b"INFO" + b"".join(chunk(name, raw + b"\x00") for name, raw in entries))


def id3_tag(frames: list[tuple[bytes, str]]) -> bytes:
    body = b""
    for identifier, text in frames:
        payload = b"\x03" + text.encode("utf-8")
        body += identifier + struct.pack(">I", len(payload)) + b"\x00\x00" + payload
    size = bytes(((len(body) >> shift) & 0x7F) for shift in (21, 14, 7, 0))
    return b"ID3\x03\x00\x00" + size + body


def wav(tmp_path: Path, chunks: list[bytes], name: str = "take.wav") -> Path:
    path = tmp_path / name
    path.write_bytes(riff(b"WAVE", [chunk(b"fmt ", b"\x01\x00" * 8), *chunks]))
    return path


# --- the ID3 tag WAV keeps in a chunk ----------------------------------------


def test_an_id3_tag_inside_a_chunk_is_read(tmp_path: Path):
    """The ID3 reader alone never found this: it requires the tag at byte zero,
    and a WAV begins with RIFF."""
    audio = wav(tmp_path, [chunk(b"id3 ", id3_tag([(b"TSSE", "Lavf60.3.100")]))])

    assert read_embedded_metadata(audio).tool == "Lavf60.3.100"


def test_the_tag_and_the_info_list_are_kept_apart(tmp_path: Path):
    """Two writers touched the file and said different things. Merging them
    into one dictionary would quietly drop whichever was written second."""
    audio = wav(
        tmp_path,
        [
            info([(b"ISFT", b"Adobe Audition 3.0")]),
            chunk(b"id3 ", id3_tag([(b"TSSE", "Lavf60.3.100")])),
        ],
    )

    fields = read_embedded_metadata(audio).fields

    assert fields["Software"] == "Adobe Audition 3.0"
    assert fields["id3:encoder"] == "Lavf60.3.100"


# --- INFO fields -------------------------------------------------------------


def test_an_unlisted_field_keeps_its_four_character_code(tmp_path: Path):
    """RIFF's published list is from 1991 and writers have added to it since.
    A code this tool cannot name is still something a reader can look up."""
    audio = wav(tmp_path, [info([(b"ISFT", b"Reaper"), (b"IPRT", b"3")])])

    assert read_riff(audio).info["IPRT"] == "3"


def test_a_utf8_value_is_not_read_as_latin1(tmp_path: Path):
    audio = wav(tmp_path, [info([(b"IART", "Björk".encode())])])

    assert read_riff(audio).info["Artist"] == "Björk"


def test_a_latin1_value_is_not_rejected(tmp_path: Path):
    """RIFF says Latin-1 and older recorders wrote it. Bytes that are not valid
    UTF-8 are read the way the specification says, not replaced with question
    marks."""
    audio = wav(tmp_path, [info([(b"IART", "Björk".encode("latin-1"))])])

    assert read_riff(audio).info["Artist"] == "Björk"


def test_the_credited_people_reach_the_note(tmp_path: Path):
    audio = wav(
        tmp_path,
        [info([(b"IART", b"Studio Quartet"), (b"IENG", b"M. Nowak"), (b"ICOP", b"(c) 2019 PR3")])],
    )

    note = read_embedded_metadata(audio).note

    assert "artist Studio Quartet" in note
    assert "engineer M. Nowak" in note
    assert "copyright (c) 2019 PR3" in note


def test_a_field_nobody_summarises_still_reaches_the_record(tmp_path: Path):
    """The report has room for four fields. An investigation cannot know in
    advance which of the twenty-odd INFO codes it will turn out to need."""
    audio = wav(
        tmp_path,
        [info([(b"ISFT", b"Reaper"), (b"IGNR", b"Field recording"), (b"IMED", b"DAT")])],
    )

    fields = read_embedded_metadata(audio).fields

    assert fields["Genre"] == "Field recording"
    assert fields["Medium"] == "DAT"


# --- the broadcast extension -------------------------------------------------


def bext(
    *,
    description: bytes = b"",
    originator: bytes = b"",
    reference: bytes = b"",
    date: bytes = b"",
    time: bytes = b"",
    history: bytes = b"",
) -> bytes:
    """A BWF `bext` chunk, laid out as EBU Tech 3285 fixes it."""
    return chunk(
        b"bext",
        description.ljust(256, b"\x00")
        + originator.ljust(32, b"\x00")
        + reference.ljust(32, b"\x00")
        + date.ljust(10, b"\x00")
        + time.ljust(8, b"\x00")
        + struct.pack("<QH", 0, 1)  # time reference, version
        + b"\x00" * 254  # UMID, loudness, reserved
        + history,
    )


def test_a_broadcast_wave_names_the_machine_that_recorded_it(tmp_path: Path):
    audio = wav(tmp_path, [bext(originator=b"Sound Devices MixPre-6")])

    assert read_embedded_metadata(audio).tool == "Sound Devices MixPre-6"


def test_the_origination_date_and_time_become_one_moment(tmp_path: Path):
    """BWF splits the two across neighbouring fields, and either alone is a
    worse answer than the pair."""
    audio = wav(tmp_path, [bext(originator=b"Zoom F8n", date=b"2019-03-04", time=b"10:22:31")])

    assert read_embedded_metadata(audio).at == "2019-03-04T10:22:31Z"


def test_an_empty_origination_date_is_not_invented(tmp_path: Path):
    """ffmpeg writes the chunk with the date left as nulls unless it is told
    one. Nulls are an absence, not a moment at the start of the epoch."""
    audio = wav(tmp_path, [bext(originator=b"Zoom F8n")])

    assert read_embedded_metadata(audio).at is None


def test_the_recorder_is_named_alongside_the_editor(tmp_path: Path):
    """One machine captured the sound and another wrote the file out. Reporting
    only the second would hand back the studio and lose the field."""
    audio = wav(
        tmp_path,
        [bext(originator=b"Sound Devices MixPre-6"), info([(b"ISFT", b"Adobe Audition 3.0")])],
    )

    assert read_embedded_metadata(audio).tool == (
        "Sound Devices MixPre-6 (edited with Adobe Audition 3.0)"
    )


def test_the_recording_date_outranks_the_date_the_editor_wrote(tmp_path: Path):
    audio = wav(
        tmp_path,
        [
            bext(originator=b"Zoom F8n", date=b"2019-03-04", time=b"10:22:31"),
            info([(b"ICRD", b"2021-11-02")]),
        ],
    )

    assert read_embedded_metadata(audio).at == "2019-03-04T10:22:31Z"


def test_the_coding_history_is_kept_whole(tmp_path: Path):
    """It is the chain of everything done to the sound, written one line per
    step, and the last line is not a summary of the ones above it."""
    history = b"A=ANALOGUE,M=stereo,T=Nagra IV-S\r\nA=PCM,F=48000,W=24,M=stereo,T=Zoom F8n"
    audio = wav(tmp_path, [bext(originator=b"Zoom F8n", history=history)])

    kept = read_embedded_metadata(audio).fields["bext:CodingHistory"]

    assert "Nagra IV-S" in kept
    assert "Zoom F8n" in kept


def test_the_slate_reaches_the_note(tmp_path: Path):
    audio = wav(
        tmp_path,
        [bext(originator=b"Zoom F8n", description=b"Interview, take 3", reference=b"SD0012345")],
    )

    origin = read_embedded_metadata(audio)

    assert "Interview, take 3" in origin.note
    assert origin.fields["bext:OriginatorReference"] == "SD0012345"


def test_a_chunk_too_short_to_be_bext_is_not_read_as_one(tmp_path: Path):
    """The layout is fixed and unlabelled: every field is found by counting
    bytes, so a short chunk would have its neighbours read as its contents."""
    audio = wav(tmp_path, [chunk(b"bext", b"Interview, take 3".ljust(400, b"\x00"))])

    assert read_riff(audio) is None


# --- walking the container ---------------------------------------------------


def test_the_info_list_is_found_after_the_frames(tmp_path: Path):
    """AVI writes its INFO list at the end, past everything else in the file."""
    movie = tmp_path / "capture.avi"
    movie.write_bytes(
        riff(
            b"AVI ",
            [
                chunk(b"LIST", b"movi" + chunk(b"00db", b"\x00" * (5 * 1024 * 1024))),
                info([(b"ISFT", b"VirtualDub build 35491")]),
            ],
        )
    )

    assert read_embedded_metadata(movie).tool == "VirtualDub build 35491"


def test_frame_data_is_not_mined_for_metadata(tmp_path: Path):
    """Anything at all can appear inside a frame, including bytes that read as
    a chunk header. Believing them would let a file forge its own provenance."""
    movie = tmp_path / "capture.avi"
    movie.write_bytes(
        riff(
            b"AVI ",
            [
                chunk(b"LIST", b"movi" + info([(b"ISFT", b"Not the editor")])),
                info([(b"ISFT", b"VirtualDub build 35491")]),
            ],
        )
    )

    assert read_riff(movie).info["Software"] == "VirtualDub build 35491"


def test_a_value_may_not_reach_past_the_list_holding_it(tmp_path: Path):
    """Once a length is impossible the offsets after it are guesses. A parser
    that keeps reading them absorbs the audio into the editor's name."""
    unterminated = b"ISFT" + struct.pack("<I", 64) + b"Real name"
    body = b"WAVE" + chunk(b"LIST", b"INFO" + unterminated) + chunk(b"data", b"\xff" * 128)
    audio = tmp_path / "overrun.wav"
    audio.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)

    assert read_riff(audio) is None


def test_a_chunk_reaching_past_the_real_file_is_refused(tmp_path: Path):
    """The header's own length is a claim like any other, so the end of the
    walk is the end of the file - otherwise an overstated header makes every
    impossible chunk length look reasonable."""
    unterminated = b"ISFT" + struct.pack("<I", 4096) + b"Real name"
    body = b"WAVE" + chunk(b"LIST", b"INFO" + unterminated)
    audio = tmp_path / "overstated.wav"
    audio.write_bytes(b"RIFF" + struct.pack("<I", 1 << 30) + body)

    assert read_riff(audio) is None


def test_a_truncated_tag_is_refused_rather_than_half_read(tmp_path: Path):
    """A tag that ran out of file yields frames that look whole and are not.
    Reporting "Adobe Audi" as the editor is worse than reporting nothing."""
    tag = id3_tag([(b"TSSE", "Lavf60.3.100")])
    body = b"WAVE" + b"id3 " + struct.pack("<I", len(tag) + 4096) + tag
    audio = tmp_path / "cut-short.wav"
    audio.write_bytes(b"RIFF" + struct.pack("<I", 1 << 30) + body)

    assert read_riff(audio) is None


def test_a_header_that_overstates_the_file_still_reads(tmp_path: Path):
    """A recorder that loses power writes the length it intended, not the one
    it achieved. The chunks that did land are still evidence."""
    body = b"WAVE" + info([(b"ISFT", b"Sound Devices MixPre")])
    audio = tmp_path / "interrupted.wav"
    audio.write_bytes(b"RIFF" + struct.pack("<I", 1 << 30) + body)

    assert read_riff(audio).info["Software"] == "Sound Devices MixPre"


def test_nesting_cannot_run_away(tmp_path: Path):
    payload = info([(b"ISFT", b"Buried")])
    for _ in range(1500):
        payload = chunk(b"LIST", b"junk" + payload)
    audio = tmp_path / "nested.wav"
    audio.write_bytes(riff(b"WAVE", [payload]))

    read_riff(audio)  # must return rather than exhaust the stack


# --- files with nothing to say -----------------------------------------------


def test_a_file_that_is_not_riff_is_not_claimed(tmp_path: Path):
    audio = tmp_path / "misnamed.wav"
    audio.write_bytes(b"\x00" * 64)

    assert read_riff(audio) is None
    assert read_embedded_metadata(audio) is None


def test_a_big_endian_riffx_file_is_left_alone(tmp_path: Path):
    """RIFX is the same layout with the lengths the other way round. Reading
    one here would turn every length into a different number and report
    whatever those offsets happened to land on."""
    audio = tmp_path / "motorola.wav"
    audio.write_bytes(b"RIFX" + riff(b"WAVE", [info([(b"ISFT", b"Reaper")])])[4:])

    assert read_riff(audio) is None


def test_a_bare_recording_makes_no_claim(tmp_path: Path):
    audio = wav(tmp_path, [chunk(b"data", b"\x00" * 32)])

    assert read_embedded_metadata(audio) is None
