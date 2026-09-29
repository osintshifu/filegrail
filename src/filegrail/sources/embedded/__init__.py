"""Metadata a file carries about its own creation.

A download record says where a file came from. Embedded metadata answers the
neighbouring question - what produced it, who authored it, when, and for a
photograph or a video *where* - and it is frequently the only answer available,
because it survives copying, renaming, moving between machines and the expiry of
every browser history on the system.

Each reader lives in its own module and knows one family of containers. This
module chooses between them and turns whatever they find into an `EvidenceRecord`.
"""

from __future__ import annotations

import struct
import xml.etree.ElementTree as ElementTree
import zipfile
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from ...models import EvidenceRecord
from . import (
    aiff,
    ape,
    containers,
    documents,
    exif,
    fonts,
    id3,
    isobmff,
    jpeg,
    makernotes,
    matroska,
    ole,
    pe,
    photoshop,
    png,
    riff,
    vorbis,
    web,
)

#: A malformed container is ordinary: truncated downloads, Office lock files and
#: files with a misleading extension all land here, and none is an error.
_RECOVERABLE = (
    OSError,
    ValueError,
    struct.error,
    zipfile.BadZipFile,
    ElementTree.ParseError,
    KeyError,
    # A package may name a compression method this interpreter cannot undo, and
    # `zipfile` says so with `NotImplementedError` - two patched bytes per
    # member, and none of the types above describes it.
    NotImplementedError,
)

#: Every suffix any reader here claims. Used to skip files quickly.
SUFFIXES = (
    documents.PDF_SUFFIXES
    | documents.OOXML_SUFFIXES
    | exif.SUFFIXES
    | png.SUFFIXES
    | isobmff.SUFFIXES
    | containers.SUFFIXES
    | id3.SUFFIXES
    | riff.SUFFIXES
    | matroska.SUFFIXES
    | vorbis.SUFFIXES
    | ole.SUFFIXES
    | photoshop.SUFFIXES
    | web.SUFFIXES
    | pe.SUFFIXES
    | fonts.SUFFIXES
    | aiff.SUFFIXES
    | ape.SUFFIXES
)


def read_embedded_metadata(path: Path) -> EvidenceRecord | None:
    """Return what the file says about its own creation, if anything."""
    suffix = path.suffix.lower()
    if suffix not in SUFFIXES:
        return None

    for reader in (
        _from_documents,
        _from_web,
        _from_exif,
        _from_photoshop,
        _from_movie,
        _from_png,
        _from_container,
        _from_compound,
        _from_riff,
        _from_matroska,
        _from_vorbis,
        _from_audio,
        _from_aiff,
        _from_ape,
        _from_executable,
        _from_font,
    ):
        try:
            origin = reader(path, suffix)
        except _RECOVERABLE:
            continue  # one unreadable container must not end the scan
        if origin is not None:
            return origin
    return None


# --- per family --------------------------------------------------------------


def _from_documents(path: Path, suffix: str) -> EvidenceRecord | None:
    if suffix in documents.PDF_SUFFIXES:
        return documents.read_pdf(path)
    if suffix in documents.OOXML_SUFFIXES:
        return documents.read_ooxml(path)
    return None


def _from_web(path: Path, suffix: str) -> EvidenceRecord | None:
    if suffix not in web.SUFFIXES:
        return None
    found = web.read_web_document(path)
    if not found:
        return None

    fields = found.fields
    author = _first(
        fields,
        (
            "author",
            "article:author",
            "citation_author",
            "dc.creator",
            "dcterms.creator",
            "jsonld:author",
            "microdata:author",
            "microdata:creator",
            "rdfa:author",
            "rdfa:creator",
        ),
    )
    publisher = _first(
        fields,
        ("publisher", "og:site_name", "jsonld:publisher", "microdata:publisher", "rdfa:publisher"),
    )
    title = _first(
        fields,
        (
            "title",
            "og:title",
            "twitter:title",
            "jsonld:headline",
            "jsonld:name",
            "microdata:headline",
            "microdata:name",
            "rdfa:headline",
            "rdfa:name",
        ),
    )
    canonical = _first(fields, ("canonical", "og:url", "jsonld:url", "microdata:url", "rdfa:url"))
    published = _first(
        fields,
        (
            "datePublished",
            "article:published_time",
            "citation_publication_date",
            "dcterms.issued",
            "dcterms.date",
            "date",
            "jsonld:datePublished",
            "microdata:datePublished",
            "microdata:dateCreated",
            "rdfa:datePublished",
            "rdfa:dateCreated",
        ),
    )

    notes = []
    if author:
        notes.append(f"author {_clip(author, 80)}")
    if publisher:
        notes.append(f"publisher {_clip(publisher, 80)}")
    if title:
        notes.append(f"title {_clip(title, 80)}")
    if not notes and canonical:
        notes.append(f"canonical {_clip(canonical, 120)}")

    # An image or URL declared by the page is useful as a pivot even when the
    # page omitted title and authorship.  A language or description by itself
    # is not enough to create a provenance record at the top of the report.
    if not notes and any(
        name in fields
        for name in (
            "og:image",
            "og:video",
            "og:audio",
            "twitter:image",
            "twitter:player",
            "jsonld:image",
            "jsonld:video",
            "jsonld:audio",
            "jsonld:contentUrl",
            "jsonld:embedUrl",
        )
    ):
        notes.append("linked media recorded")

    return _origin(
        "document-metadata",
        block="web-document",
        tool=_first(fields, ("generator", "application-name")),
        at=_normalise(published),
        note="; ".join(notes) or None,
        fields=dict(fields),
    )


def _from_exif(path: Path, suffix: str) -> EvidenceRecord | None:
    if suffix not in exif.SUFFIXES:
        return None
    tags = exif.read_exif(path)
    jpeg_metadata = jpeg.read_jpeg_metadata(path) if suffix in jpeg.SUFFIXES else None
    photoshop_metadata = (
        photoshop.read_photoshop_metadata(path)
        if suffix in photoshop.JPEG_SUFFIXES | photoshop.TIFF_SUFFIXES
        else None
    )
    if not tags and not jpeg_metadata and not photoshop_metadata:
        return None
    tags = tags or exif.Exif()

    device = exif.camera(tags)
    software = _string(tags.get(exif.SOFTWARE))
    tool = device or software or (photoshop_metadata.tool if photoshop_metadata else None)
    if device and software and software.lower() not in device.lower():
        tool = f"{device} (processed with {software})"

    taken = _exif_time(tags.get(exif.DATETIME_ORIGINAL) or tags.get(exif.DATETIME))
    location = _coordinates(exif.coordinates(tags))

    notes = []
    artist = _string(tags.get(exif.ARTIST))
    if artist:
        notes.append(f"artist {artist}")
    lens = _string(tags.get(exif.LENS_MODEL))
    if lens and device:
        notes.append(f"lens {lens}")
    if jpeg_metadata and jpeg_metadata.icc_description and jpeg_metadata.icc_evidence:
        notes.append(f"ICC profile {_clip(jpeg_metadata.icc_description, 80)}")
    elif jpeg_metadata and jpeg_metadata.icc_evidence:
        notes.append("ICC profile recorded")
    if jpeg_metadata and jpeg_metadata.jfxx_thumbnail:
        notes.append("JFXX thumbnail present")
    if tags.preview:
        notes.append("EXIF thumbnail present")
    if photoshop_metadata and photoshop_metadata.note:
        notes.append(photoshop_metadata.note)

    fields = _exif_fields(tags)
    if tags.preview:
        fields.update(
            {
                "Thumbnail:Format": "JPEG",
                "Thumbnail:Dimensions": f"{tags.preview.width}x{tags.preview.height}",
                "Thumbnail:Bytes": str(len(tags.preview.data)),
                "Thumbnail:SHA256": tags.preview.sha256,
            }
        )
    if jpeg_metadata:
        fields.update(jpeg_metadata.fields)
    if photoshop_metadata:
        fields.update(photoshop_metadata.fields)

    return _origin(
        "device-metadata" if device else "document-metadata",
        block="exif" if tags or jpeg_metadata else "photoshop-irb",
        tool=tool,
        at=taken,
        geo=location,
        note="; ".join(notes) or None,
        fields=fields,
    )


def _entry_count(count: int) -> str:
    return "1 entry" if count == 1 else f"{count} entries"


def read_maker_notes(path: Path) -> EvidenceRecord | None:
    """Return the vendor block a camera wrote beside its EXIF, if any.

    Read beside `read_embedded_metadata` rather than inside it, the way a C2PA
    manifest is: this is a second parser reading a second structure, and the
    things it names - the serial of the body, the shutter count, the name its
    owner typed in - are not EXIF and should not arrive claiming to be.
    """
    suffix = path.suffix.lower()
    if suffix not in exif.SUFFIXES:
        return None
    try:
        tags = exif.read_exif(path)
    except _RECOVERABLE:
        return None
    if tags is None or tags.maker is None:
        return None

    notes = tags.maker
    fields = {"Vendor": notes.vendor, **notes.fields}
    if notes.preview:
        # Described, never carried: the bytes stay out of the record the same
        # way the EXIF thumbnail's do, and the photo report reads them direct.
        fields.update(
            {
                "Preview:Format": "JPEG",
                "Preview:Dimensions": f"{notes.preview.width}x{notes.preview.height}",
                "Preview:Bytes": str(len(notes.preview.data)),
                "Preview:SHA256": notes.preview.sha256,
            }
        )
    if notes.declared_preview:
        at, length = notes.declared_preview
        fields["Preview:Declared"] = f"{length} bytes at offset {at} from the TIFF header"
    detail = [_entry_count(notes.entries), notes.scheme]
    # Named apart, because a reader given one number cannot tell this parser's
    # limits from a block that was moved after the camera wrote it.
    if notes.undecoded:
        detail.append(f"{_entry_count(notes.undecoded)} this reader could not read")
    if notes.distrusted:
        detail.append(
            f"{_entry_count(notes.distrusted)} dropped: the offsets address the file "
            "as it stood before it was rewritten"
        )
    if notes.preview:
        detail.append("carries a preview image")
    if notes.declared_preview and sum(notes.declared_preview) > path.stat().st_size:
        # The TIFF header sits at a positive offset, so a pointer past the end
        # of the whole file cannot resolve wherever that header is. The camera
        # wrote a picture the file no longer carries: it was re-saved smaller.
        detail.append("declared preview not present in this file")
    if notes.byte_order != makernotes.SAME_ORDER:
        # The camera writes the note in the file's own byte order. The other
        # order means something rewrote the file around the block.
        detail.append(f"byte order {notes.byte_order}")
    return EvidenceRecord(
        # The camera wrote this, the same as it wrote the EXIF beside it, so it
        # is the same source. The block is what says which structure it is.
        source="device-metadata",
        block="maker-notes",
        tool=notes.vendor if notes.vendor != "unknown" else None,
        note="; ".join(detail),
        fields=fields,
    )


def _from_photoshop(path: Path, suffix: str) -> EvidenceRecord | None:
    if suffix not in photoshop.DOCUMENT_SUFFIXES:
        return None
    found = photoshop.read_photoshop_metadata(path)
    if not found:
        return None
    return _origin(
        "document-metadata",
        block="photoshop-irb",
        tool=found.tool,
        note=found.note,
        fields=dict(found.fields),
    )


def _exif_fields(tags: exif.Exif) -> dict[str, str]:
    """Every decoded tag, named where the name is known.

    Unnamed tags keep their hex code rather than being dropped. They are mostly
    camera settings, but "mostly" is not a basis for discarding evidence, and a
    reader who does not recognise `0x9c9b` can still look it up.

    Maker notes are the one thing genuinely not reachable here: they are
    vendor-specific, undocumented and would need a parser per manufacturer.
    """
    found: dict[str, str] = {}
    for names, source in ((exif.TAG_NAMES, tags), (exif.GPS_TAG_NAMES, tags.gps)):
        for tag, value in source.items():
            found[names.get(tag, f"0x{tag:04x}")] = _plain(value)
    return found


def _plain(value: object) -> str:
    """A tag value as text, without float noise like 4.699999999999999."""
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    if isinstance(value, list):
        return ", ".join(_plain(item) for item in value)
    return str(value)


def _from_movie(path: Path, suffix: str) -> EvidenceRecord | None:
    if suffix not in isobmff.SUFFIXES:
        return None
    movie = isobmff.read_movie(path)
    if not movie:
        return None

    telemetry = movie.telemetry
    device = " ".join(part for part in (movie.make, movie.model) if part) or None
    if not device and telemetry and telemetry.devices:
        device = telemetry.devices[0]  # the camera names itself in its own track
    tool = device or movie.encoder
    if device and movie.encoder:
        tool = f"{device} (encoded with {movie.encoder})"

    fields = {
        name: str(value)
        for name, value in (
            ("Encoder", movie.encoder),
            ("Make", movie.make),
            ("Model", movie.model),
            ("CreationTime", movie.created),
            ("Location", _coordinates(movie.coordinates)),
        )
        if value
    }
    for key, kept in movie.items.items():
        fields[f"QuickTime:{key}"] = kept
    for index, track in enumerate(movie.tracks, 1):
        said = " ".join(
            part
            for part in (
                track.handler.decode("ascii", "replace").strip() if track.handler else "",
                track.format.decode("ascii", "replace").strip() if track.format else "",
                track.language or "",
            )
            if part
        )
        if said:
            fields[f"Track[{index}]"] = said
    if any(track.handler == b"tmcd" for track in movie.tracks):
        fields["Timecode"] = "track present"
    for name, label in (
        ("firmware", "GoPro:Firmware"),
        ("lens", "GoPro:Lens"),
        ("camera_serial", "GoPro:CameraSerial"),
        ("media_uid", "GoPro:MediaUID"),
    ):
        if name in movie.gopro:
            fields[label] = movie.gopro[name]

    notes = []
    geo = _coordinates(movie.coordinates)
    if telemetry:
        kind = telemetry.kind
        if telemetry.devices:
            fields[f"{kind}:Device"] = ", ".join(telemetry.devices)
        if telemetry.streams:
            fields[f"{kind}:Streams"] = ", ".join(telemetry.streams)
        if telemetry.gps_points:
            fields[f"{kind}:GPSPoints"] = str(telemetry.gps_points)
            for name, value in (
                ("GPSStart", telemetry.gps_start),
                ("GPSEnd", telemetry.gps_end),
                ("GPSFirst", _coordinates(telemetry.gps_first)),
                ("GPSLast", _coordinates(telemetry.gps_last)),
                ("GPSFix", telemetry.gps_fix),
            ):
                if value is not None:
                    fields[f"{kind}:{name}"] = str(value)
            span = f"GPS track of {telemetry.gps_points} points"
            if telemetry.gps_start and telemetry.gps_end:
                span += f" from {telemetry.gps_start} to {telemetry.gps_end}"
            notes.append(span)
            # The first fix stands for the recording where the container did
            # not write a location of its own.
            geo = geo or _coordinates(telemetry.gps_first)

    return _origin(
        "device-metadata" if device else "document-metadata",
        block="isobmff",
        tool=tool,
        at=movie.created or (telemetry.gps_start if telemetry else None),
        geo=geo,
        note="; ".join(notes) or None,
        fields=fields,
    )


def _png_exif(path: Path) -> exif.Exif | None:
    raw = png.read_exif_chunk(path)
    if not raw:
        return None
    try:
        return exif._parse_tiff(raw)
    except (struct.error, ValueError):
        return None


def _from_png(path: Path, suffix: str) -> EvidenceRecord | None:
    if suffix not in png.SUFFIXES:
        return None
    text = png.read_png_text(path)
    if not text and not png.read_exif_chunk(path):
        return None

    tool = _first(text, png.SOFTWARE_KEYS)
    created = _normalise(_first(text, png.DATE_KEYS))
    author = _first(text, png.AUTHOR_KEYS)

    notes = []
    if author:
        notes.append(f"author {author}")
    # PNG 1.5 added an `eXIf` chunk with the same TIFF payload as a JPEG's
    # APP1, and phones and screenshot tools write one.
    tags = _png_exif(path)
    if tags:
        device = exif.camera(tags)
        tool = tool or device
        if device and tool and device.lower() not in tool.lower():
            tool = f"{device} (processed with {tool})"
        created = created or _exif_time(tags.get(exif.DATETIME_ORIGINAL) or tags.get(exif.DATETIME))
        notes.append("EXIF chunk present")
    generation = _first(text, png.GENERATOR_KEYS)
    if generation:
        notes.append(f"generation parameters recorded: {_clip(generation)}")

    # The XMP packet is decoded by its own reader into named properties. Left
    # here it would be a second copy of the same evidence, clipped mid-element
    # and unreadable as either markup or a value.
    fields = {name: value for name, value in text.items() if name != png.XMP_KEYWORD}
    if tags:
        fields.update(_exif_fields(tags))

    return _origin(
        "document-metadata",
        block="png-text",
        tool=tool,
        at=created,
        note="; ".join(notes) or None,
        fields=fields,
    )


def _from_container(path: Path, suffix: str) -> EvidenceRecord | None:
    if suffix not in containers.SUFFIXES:
        return None
    found = containers.read_container(path)
    if not found:
        return None

    notes = []
    if found.author:
        notes.append(f"author {found.author}")
    if found.title:
        notes.append(f"title {_clip(found.title, 80)}")

    return _origin(
        "document-metadata",
        block=found.block,
        tool=found.tool,
        at=_normalise(found.created),
        note="; ".join(notes) or None,
        fields=dict(found.fields),
    )


def _from_compound(path: Path, suffix: str) -> EvidenceRecord | None:
    if suffix not in ole.SUFFIXES:
        return None
    found = ole.read_ole(path)
    if not found:
        return None

    notes = []
    if found.author:
        notes.append(f"author {found.author}")
    if found.last_author and found.last_author != found.author:
        notes.append(f"last edited by {found.last_author}")
    if found.company:
        notes.append(f"company {found.company}")
    if found.title:
        notes.append(f"title {_clip(found.title, 80)}")
    if found.storages:
        notes.append(f"storage metadata {len(found.storages)}")
    if found.vba_storage:
        notes.append("VBA storage present")
    if found.xlm_macro_sheets:
        notes.append(f"XLM macro sheets {found.xlm_macro_sheets}")
    if found.native_streams:
        notes.append(f"embedded object streams {found.native_streams}")
    if found.orphaned_entries:
        notes.append(f"orphaned directory entries {len(found.orphaned_entries)}")
    if found.root_clsid and not notes:
        notes.append("root CLSID recorded")

    fields = {
        name: value
        for name, value in (
            ("Application", found.tool),
            ("Author", found.author),
            ("LastAuthor", found.last_author),
            ("Company", found.company),
            ("Title", found.title),
            ("Created", found.created),
            ("RootCLSID", found.root_clsid),
            ("VBAStorage", "present" if found.vba_storage else None),
            (
                "XLMMacroSheets",
                str(found.xlm_macro_sheets) if found.xlm_macro_sheets else None,
            ),
            ("Ole10NativeStreams", str(found.native_streams) if found.native_streams else None),
        )
        if value
    }
    for index, storage in enumerate(found.storages, 1):
        for name, value in (
            ("Name", storage.name),
            ("CLSID", storage.clsid),
            ("Created", storage.created),
            ("Modified", storage.modified),
        ):
            if value:
                fields[f"Storage[{index}]:{name}"] = value
    for index, embedded in enumerate(found.embedded_objects, 1):
        for name, value in (
            ("Filename", embedded.filename),
            ("SourcePath", embedded.source_path),
            ("TempPath", embedded.temp_path),
            ("Size", str(embedded.size)),
        ):
            if value:
                fields[f"EmbeddedObject[{index}]:{name}"] = value
    for index, orphaned in enumerate(found.orphaned_entries, 1):
        for name, value in (
            ("Name", orphaned.name),
            ("Type", orphaned.kind),
            ("CLSID", orphaned.clsid),
            ("Created", orphaned.created),
            ("Modified", orphaned.modified),
            ("Size", str(orphaned.size)),
        ):
            if value:
                fields[f"OrphanedEntry[{index}]:{name}"] = value

    return _origin(
        "document-metadata",
        block="ole-summary",
        tool=found.tool,
        at=_normalise(found.created),
        note="; ".join(notes) or None,
        fields=fields,
    )


def _from_riff(path: Path, suffix: str) -> EvidenceRecord | None:
    if suffix not in riff.SUFFIXES:
        return None
    found = riff.read_riff(path)
    if not found:
        return None

    # One machine captured the sound and another wrote the file out. Naming
    # only the second hands back the studio and loses the field.
    recorder = found.broadcast.get("Originator")
    editor = found.info.get("Software") or found.frames.get("encoder")
    tool = recorder or editor
    if recorder and editor and editor.lower() not in recorder.lower():
        tool = f"{recorder} (edited with {editor})"

    notes = []
    for label, value in (
        ("description", found.broadcast.get("Description")),
        ("artist", found.info.get("Artist") or found.frames.get("artist")),
        ("title", found.info.get("Title") or found.frames.get("title")),
        ("engineer", found.info.get("Engineer")),
        ("copyright", found.info.get("Copyright")),
    ):
        if value:
            notes.append(f"{label} {_clip(value, 80)}")

    return _origin(
        "document-metadata",
        block="riff",
        tool=tool,
        # When the recording started beats when the file was written out.
        at=_normalise(found.originated)
        or _normalise(found.info.get("DateCreated") or found.frames.get("date")),
        note="; ".join(notes) or None,
        # Each standard keeps its own names. The three can disagree, and one
        # merged dictionary would silently hide whichever was written last.
        fields=dict(found.info)
        | {f"bext:{name}": value for name, value in found.broadcast.items()}
        | {f"id3:{name}": value for name, value in found.frames.items()},
    )


def _from_matroska(path: Path, suffix: str) -> EvidenceRecord | None:
    if suffix not in matroska.SUFFIXES:
        return None
    found = matroska.read_matroska(path)
    if not found:
        return None

    # The library that muxed the file and the application a person used are two
    # different answers, and ffmpeg writes its own name into both - so they are
    # only named separately when they are actually different.
    writing = found.fields.get("WritingApp")
    muxing = found.fields.get("MuxingApp")
    tool = writing or muxing
    if writing and muxing and muxing.lower() != writing.lower():
        tool = f"{writing} (muxed with {muxing})"

    title = found.fields.get("Title")
    return _origin(
        "document-metadata",
        block="matroska",
        tool=tool,
        at=found.at,
        note=f"title {_clip(title, 80)}" if title else None,
        fields=dict(found.fields),
    )


def _from_vorbis(path: Path, suffix: str) -> EvidenceRecord | None:
    if suffix not in vorbis.SUFFIXES:
        return None
    found = vorbis.read_comments(path)
    if not found:
        return None

    # The specification calls these names case-insensitive and ffmpeg takes it
    # at its word, writing every one in lower case - so they are looked up that
    # way and kept in the record exactly as the writer wrote them.
    notes = []
    for label, name in (("artist", "ARTIST"), ("title", "TITLE"), ("engineer", "ENGINEER")):
        if value := _first(found, (name,)):
            notes.append(f"{label} {_clip(value, 80)}")

    return _origin(
        "document-metadata",
        block="vorbis-comment",
        # The vendor string is written by whatever produced the file, so it is
        # the weaker answer of the two and never the wrong one.
        tool=_first(found, ("ENCODER", "Vendor")),
        at=_normalise(_first(found, ("DATE",))),
        note="; ".join(notes) or None,
        fields=dict(found),
    )


def _from_audio(path: Path, suffix: str) -> EvidenceRecord | None:
    if suffix not in id3.SUFFIXES:
        return None
    frames = id3.read_id3(path)
    if not frames:
        return None

    notes = []
    for key, label in (("artist", "artist"), ("title", "title")):
        if frames.get(key):
            notes.append(f"{label} {_clip(frames[key], 80)}")

    return _origin(
        "document-metadata",
        block="id3",
        tool=frames.get("encoder"),
        at=_normalise(frames.get("date")),
        note="; ".join(notes) or None,
    )


def _from_executable(path: Path, suffix: str) -> EvidenceRecord | None:
    if suffix not in pe.SUFFIXES:
        return None
    found = pe.read_executable(path)
    if not found:
        return None

    strings = found.strings
    product = strings.get("ProductName") or strings.get("FileDescription")
    version = strings.get("ProductVersion") or found.product_version
    tool = f"{product} {version}".strip() if product and version else product

    notes = []
    if company := strings.get("CompanyName"):
        notes.append(f"company {_clip(company, 80)}")
    if original := strings.get("OriginalFilename"):
        notes.append(f"original name {_clip(original, 80)}")
    if found.pdb_path:
        notes.append(f"PDB {_clip(found.pdb_path, 100)}")
    if found.signature_size:
        notes.append("Authenticode signature present")
    if found.reproducible:
        notes.append("reproducible build")
    if found.linker:
        notes.append(f"linker {found.linker}")

    fields = {
        name: str(value)
        for name, value in (
            ("Machine", found.machine),
            ("Subsystem", found.subsystem),
            ("LinkerVersion", found.linker),
            ("LinkTime", found.linked),
            ("ReproducibleBuild", "yes" if found.reproducible else None),
            ("PDBPath", found.pdb_path),
            ("PDBGuid", found.pdb_guid),
            ("PDBAge", found.pdb_age),
            ("FileType", found.file_type),
            ("FileVersion", strings.get("FileVersion") or found.file_version),
            ("ProductVersion", version),
            (
                "Authenticode",
                f"present, {found.signature_size} bytes" if found.signature_size else None,
            ),
        )
        if value is not None
    }
    if found.rich:
        fields["RichHeader"] = f"{len(found.rich)} entries"
        for index, (product_id, build, count) in enumerate(found.rich[: pe._MAX_RICH_LISTED], 1):
            fields[f"RichEntry[{index}]"] = f"id {product_id}, build {build}, count {count}"
    for name, value in strings.items():
        fields.setdefault(name, value)

    # A link time is placed on the timeline only where it can be one. A
    # reproducible build writes a hash in its place, on purpose.
    return _origin(
        "document-metadata",
        block="pe-header",
        tool=tool,
        at=found.linked if pe.plausible(found.linked) and not found.reproducible else None,
        note="; ".join(notes) or None,
        fields=fields,
    )


def _from_font(path: Path, suffix: str) -> EvidenceRecord | None:
    if suffix not in fonts.SUFFIXES:
        return None
    font = fonts.read_font(path)
    if not font:
        return None

    names = font.names
    tool = names.get("Manufacturer") or font.meta.get("meta:vendor") or font.vendor_id

    notes = []
    if family := names.get("TypographicFamily") or names.get("Family"):
        notes.append(f"family {_clip(family, 80)}")
    if designer := names.get("Designer") or font.meta.get("meta:credit[1]:name"):
        notes.append(f"designer {_clip(designer, 80)}")
    if version := names.get("Version"):
        notes.append(f"version {_clip(version.removeprefix('Version ').split(';', 1)[0], 40)}")

    container = font.container
    if font.fonts > 1:
        container = f"{container} collection of {font.fonts} fonts"
    fields: dict[str, str] = dict(names)
    for name, value in (
        ("Created", font.created),
        ("Modified", font.modified),
        ("FontRevision", font.revision),
        ("VendorID", font.vendor_id),
        ("EmbeddingRights", font.embedding),
        ("Container", container),
    ):
        if value:
            fields[name] = value
    if font.axes:
        fields["Axes"] = ", ".join(axis for axis, _, _, _ in font.axes)
        for axis, low, default, high in font.axes:
            fields[f"Axis[{axis}]"] = f"{low:g} to {high:g}, default {default:g}"
    fields.update(font.meta)

    return _origin(
        "document-metadata",
        block="font-tables",
        tool=tool,
        at=font.created,
        note="; ".join(notes) or None,
        fields=fields,
    )


def _from_aiff(path: Path, suffix: str) -> EvidenceRecord | None:
    if suffix not in aiff.SUFFIXES:
        return None
    found = aiff.read_aiff(path)
    if not found:
        return None

    notes = []
    if author := found.info.get("Author") or found.frames.get("artist"):
        notes.append(f"author {_clip(author, 80)}")
    if title := found.info.get("Name") or found.frames.get("title"):
        notes.append(f"title {_clip(title, 80)}")

    return _origin(
        "document-metadata",
        block="aiff",
        tool=found.frames.get("encoder"),
        at=_normalise(found.frames.get("date")),
        note="; ".join(notes) or None,
        fields=dict(found.info)
        | found.sound
        | {f"id3:{name}": value for name, value in found.frames.items()},
    )


def _from_ape(path: Path, suffix: str) -> EvidenceRecord | None:
    if suffix not in ape.SUFFIXES:
        return None
    items = ape.read_ape(path)
    if not items:
        return None

    # Keys are whatever the writer chose, in whatever case; they are looked up
    # case-insensitively and kept in the record exactly as written.
    lower = {name.lower(): value for name, value in items.items()}
    tool = lower.get("tool name")
    if tool and (version := lower.get("tool version")):
        tool = f"{tool} {version}"
    tool = tool or lower.get("encoder") or lower.get("encodedby")

    notes = []
    for key, label in (("artist", "artist"), ("title", "title")):
        if value := lower.get(key):
            notes.append(f"{label} {_clip(value, 80)}")

    return _origin(
        "document-metadata",
        block="ape-tag",
        tool=tool,
        at=_normalise(lower.get("year") or lower.get("date")),
        note="; ".join(notes) or None,
        fields=dict(items),
    )


# --- shared ------------------------------------------------------------------


def _origin(
    source: str,
    *,
    block: str | None,
    tool: str | None = None,
    at: str | None = None,
    geo: str | None = None,
    note: str | None = None,
    fields: dict[str, str] | None = None,
) -> EvidenceRecord | None:
    """Build a claim, or None when the reader found nothing worth reporting.

    `fields` alone is not enough: a file whose only decoded tags are resolution
    and colour space has said nothing about where it came from, and inventing a
    claim for it would put noise at the top of a provenance report.
    """
    if not any((tool, at, geo, note)):
        return None
    return EvidenceRecord(
        source=source, block=block, tool=tool, at=at, geo=geo, note=note, fields=fields or {}
    )


def _coordinates(value: tuple[float, float] | None) -> str | None:
    return f"{value[0]}, {value[1]}" if value else None


def _exif_time(value: object) -> str | None:
    """EXIF writes 'YYYY:MM:DD HH:MM:SS' with no zone; it is read as UTC."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.strptime(value.strip().strip("\x00"), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _normalise(value: str | None) -> str | None:
    if not value:
        return None
    if "," in value:  # RFC 1123, as libpng's own example writes `Creation Time`
        try:
            parsed = parsedate_to_datetime(value.strip())
        except (TypeError, ValueError, IndexError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y"):
        try:
            parsed = datetime.strptime(value.strip()[: len(pattern) + 6].rstrip("Z"), pattern)
        except ValueError:
            continue
        return parsed.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _first(values: dict[str, str], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        for candidate, value in values.items():
            if candidate.lower() == key.lower() and value.strip():
                return value.strip()
    return None


def _clip(value: str, limit: int = 160) -> str:
    collapsed = " ".join(value.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def _string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
