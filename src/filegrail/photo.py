"""Orchestration and typed findings for still-image analysis."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .models import EvidenceRecord, FileRecord
from .photojpeg import JpegAnalysis, analyse_jpeg
from .preview import EmbeddedPreview
from .sources.embedded import exif

FACT = "fact"
CONFLICT = "conflict"
SIGNAL = "signal"
NOT_EVALUATED = "not evaluated"

PHOTO_SUFFIXES = exif.SUFFIXES | {".png", ".apng", ".bmp", ".dib", ".gif", ".jfif"}


@dataclass(frozen=True, slots=True)
class PhotoFact:
    """One bounded observation with an explicit evidential state."""

    label: str
    value: str
    state: str
    method: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class PhotoArtifact:
    """Pixel-bearing material retained only for the dedicated report."""

    key: str
    label: str
    method: str
    mime: str
    data: bytes
    width: int | None = None
    height: int | None = None
    parameters: str | None = None


@dataclass(frozen=True, slots=True)
class MethodCoverage:
    """Whether one analytical method ran, and what its boundary was."""

    name: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class PhotoResult:
    """All report data for one still image."""

    number: int
    path: str
    name: str
    format: str
    size: int
    mtime: str
    sha256: str | None
    width: int | None
    height: int | None
    camera: str | None
    serial: str | None
    evidence: tuple[EvidenceRecord, ...]
    jpeg: JpegAnalysis | None
    facts: tuple[PhotoFact, ...]
    artifacts: tuple[PhotoArtifact, ...]
    methods: tuple[MethodCoverage, ...]


@dataclass(frozen=True, slots=True)
class PhotoCollection:
    """A deterministic photo set and its cross-file grouping facts."""

    root: str
    photos: tuple[PhotoResult, ...]
    redacted: bool
    camera_groups: tuple[tuple[str, tuple[str, ...]], ...]

    @property
    def summary(self) -> tuple[tuple[str, str], ...]:
        formats = Counter(photo.format for photo in self.photos)
        format_text = ", ".join(f"{name}: {formats[name]}" for name in sorted(formats)) or "none"
        return (
            ("photographs", str(len(self.photos))),
            ("formats", format_text),
            (
                "embedded previews",
                str(
                    sum(
                        any(item.key == "embedded-preview" for item in one.artifacts)
                        for one in self.photos
                    )
                ),
            ),
            (
                "conflicts",
                str(sum(fact.state == CONFLICT for one in self.photos for fact in one.facts)),
            ),
            (
                "signals",
                str(sum(fact.state == SIGNAL for one in self.photos for fact in one.facts)),
            ),
        )


def analyse_photos(
    records: list[FileRecord], root: Path, *, redact: bool = False
) -> PhotoCollection:
    """Augment supported on-disk still images with bounded photo findings."""
    photos: list[PhotoResult] = []
    for record in records:
        path = Path(record.path)
        if record.parent is not None or path.suffix.lower() not in PHOTO_SUFFIXES:
            continue
        if not path.is_file():
            continue
        photos.append(_analyse_photo(len(photos) + 1, record, path, redact))

    groups: dict[str, list[str]] = {}
    for photo in photos:
        if photo.serial:
            groups.setdefault(photo.serial, []).append(photo.path)
    camera_groups = tuple(
        (serial, tuple(paths)) for serial, paths in sorted(groups.items()) if len(paths) > 1
    )
    return PhotoCollection(str(root.resolve()), tuple(photos), redact, camera_groups)


def _analyse_photo(number: int, record: FileRecord, path: Path, redact: bool) -> PhotoResult:
    suffix = path.suffix.lower()
    facts: list[PhotoFact] = []
    artifacts: list[PhotoArtifact] = []
    methods: list[MethodCoverage] = []

    jpeg = None
    if suffix in exif.JPEG_SUFFIXES | {".jfif"}:
        try:
            jpeg = analyse_jpeg(path)
        except Exception as error:  # one analyser must not abort the collection
            methods.append(MethodCoverage("JPEG structure", "failed", type(error).__name__))
        else:
            status = "evaluated" if jpeg is not None else "failed"
            detail = "marker stream parsed" if jpeg is not None else "invalid JPEG marker stream"
            methods.append(MethodCoverage("JPEG structure", status, detail))
    else:
        methods.append(MethodCoverage("JPEG structure", "not applicable", "not a JPEG file"))

    tags = None
    if suffix in exif.SUFFIXES:
        try:
            tags = exif.read_exif(path)
        except Exception as error:  # malformed metadata remains local to this method
            methods.append(MethodCoverage("EXIF metadata", "failed", type(error).__name__))
        else:
            detail = "EXIF directories parsed" if tags is not None else "no EXIF directories found"
            methods.append(MethodCoverage("EXIF metadata", "evaluated", detail))
    else:
        methods.append(
            MethodCoverage("EXIF metadata", "not applicable", "format has no EXIF reader")
        )

    width = jpeg.width if jpeg else None
    height = jpeg.height if jpeg else None
    if jpeg and width and height:
        facts.append(PhotoFact("JPEG dimensions", f"{width} x {height} px", FACT, "JPEG SOF"))
        if jpeg.encoding and jpeg.precision:
            noun = "component" if len(jpeg.components) == 1 else "components"
            value = f"{jpeg.encoding}, {jpeg.precision}-bit, {len(jpeg.components)} {noun}"
            facts.append(PhotoFact("JPEG encoding", value, FACT, "JPEG SOF"))
        facts.append(PhotoFact("JPEG scans", str(jpeg.scans), FACT, "JPEG SOS"))
        if jpeg.quality:
            wording = "exact IJG table match" if jpeg.quality.exact else "nearest IJG estimate"
            facts.append(
                PhotoFact(
                    "JPEG quality tables",
                    f"quality {jpeg.quality.quality}, {wording}",
                    FACT,
                    "JPEG DQT",
                    f"absolute table distance {jpeg.quality.distance}",
                )
            )
        if jpeg.trailing_bytes:
            facts.append(
                PhotoFact(
                    "Bytes after JPEG EOI",
                    str(jpeg.trailing_bytes),
                    SIGNAL,
                    "JPEG marker walk",
                    "Appended bytes are observable but do not by themselves "
                    "establish manipulation.",
                )
            )

    preview = tags.preview if tags else None
    if preview:
        if not redact:
            artifacts.append(_preview_artifact(preview))
        dimensions = _dimensions(preview.width, preview.height)
        facts.append(
            PhotoFact(
                "Embedded preview",
                f"{dimensions}, {len(preview.data)} bytes",
                FACT,
                preview.source,
                preview.sha256,
            )
        )

    source_evidence = tuple(record.evidence)
    exif_width = _integer_field(source_evidence, "ExifImageWidth", "PixelXDimension", "ImageWidth")
    exif_height = _integer_field(
        source_evidence, "ExifImageHeight", "PixelYDimension", "ImageLength"
    )
    if (
        width
        and height
        and exif_width
        and exif_height
        and (width, height)
        != (
            exif_width,
            exif_height,
        )
    ):
        facts.append(
            PhotoFact(
                "Dimension mismatch",
                f"JPEG {width} x {height} px; EXIF {exif_width} x {exif_height} px",
                CONFLICT,
                "JPEG SOF versus EXIF",
            )
        )
    if width and height and preview and preview.width and preview.height:
        main_ratio = width / height
        preview_ratio = preview.width / preview.height
        if abs(main_ratio - preview_ratio) / main_ratio > 0.05:
            facts.append(
                PhotoFact(
                    "Preview aspect ratio",
                    f"main {main_ratio:.3f}; preview {preview_ratio:.3f}",
                    SIGNAL,
                    "JPEG SOF versus embedded preview",
                    "A material ratio difference is a review signal, not proof of editing.",
                )
            )

    if redact:
        methods.append(
            MethodCoverage(
                "Pixel diagnostics",
                "not evaluated",
                "pixel-bearing artifacts omitted by redaction",
            )
        )
    else:
        from . import photopixels

        if not photopixels.available():
            methods.append(
                MethodCoverage(
                    "Pixel diagnostics",
                    "not evaluated",
                    "install the photo extra to enable bounded pixel methods",
                )
            )
        else:
            try:
                pixel_artifacts, pixel_facts = photopixels.analyse_pixels(
                    path, [preview] if preview else []
                )
            except Exception as error:
                methods.append(MethodCoverage("Pixel diagnostics", "failed", type(error).__name__))
            else:
                artifacts.extend(pixel_artifacts)
                facts.extend(pixel_facts)
                derived = sum(item.key != "main-preview" for item in pixel_artifacts)
                methods.append(
                    MethodCoverage(
                        "Pixel diagnostics",
                        "evaluated",
                        f"{derived} derived maps produced",
                    )
                )

    evidence = tuple(record.redacted().evidence if redact else record.evidence)
    camera = exif.camera(tags) if tags else _evidence_value(evidence, "Make", "Model")
    serial = _field(evidence, "BodySerialNumber")
    return PhotoResult(
        number,
        str(path),
        path.name,
        _format_name(suffix),
        record.size,
        record.mtime,
        record.sha256,
        width,
        height,
        camera,
        serial,
        evidence,
        jpeg,
        tuple(facts),
        tuple(artifacts),
        tuple(methods),
    )


def _preview_artifact(preview: EmbeddedPreview) -> PhotoArtifact:
    return PhotoArtifact(
        "embedded-preview",
        "Embedded EXIF preview",
        preview.source,
        preview.mime,
        preview.data,
        preview.width,
        preview.height,
    )


def _dimensions(width: int | None, height: int | None) -> str:
    return f"{width} x {height} px" if width and height else "dimensions unavailable"


def _format_name(suffix: str) -> str:
    return {
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".jpe": "JPEG",
        ".jfif": "JPEG",
        ".tif": "TIFF",
        ".tiff": "TIFF",
    }.get(suffix, suffix.removeprefix(".").upper())


def _field(evidence: tuple[EvidenceRecord, ...], name: str) -> str | None:
    return next((record.fields[name] for record in evidence if record.fields.get(name)), None)


def _integer_field(evidence: tuple[EvidenceRecord, ...], *names: str) -> int | None:
    for name in names:
        value = _field(evidence, name)
        if value:
            try:
                parsed = int(value)
            except ValueError:
                continue
            if parsed > 0:
                return parsed
    return None


def _evidence_value(evidence: tuple[EvidenceRecord, ...], first: str, second: str) -> str | None:
    parts = tuple(value for name in (first, second) if (value := _field(evidence, name)))
    return " ".join(parts) or None
