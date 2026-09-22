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

#: How many bytes of images one report may produce when it carries them inside
#: itself. Every map is bounded on its own and a collection is not: two hundred
#: photographs from a phone measured 1.5 GB of HTML and 5.5 GB of memory to
#: build, which is not a report. Counted as the page carries them, four bytes
#: for every three, because the number a person wants is the size of the file
#: they end up with. The page still passes it a little, by the last photograph
#: admitted and by the markup around the images.
IMAGE_BUDGET = 16 * 1024 * 1024

#: And when it writes them out beside itself instead. Far larger, because the
#: page stays small either way and a browser loads only what is on screen: what
#: is bounded here is a directory on disk, not a document to be parsed whole.
LINKED_IMAGE_BUDGET = 512 * 1024 * 1024


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


@dataclass(slots=True)
class _Budget:
    """What is left of a report's allowance for pixel-bearing material.

    Spent in file order, and checked before a photograph rather than during it,
    so what comes back is the first photographs whole. The alternative - every
    photograph at a quality chosen by how many there were - would put maps of
    an unstated fidelity next to each other, and this report says what each of
    its images is.
    """

    limit: int | None
    used: int = 0

    @property
    def spent(self) -> bool:
        return self.limit is not None and self.used >= self.limit

    def take(self, artifacts: list[PhotoArtifact]) -> None:
        # Base64 is what a page holds, and it is four bytes for every three. A
        # directory holds the bytes themselves, but counting the larger of the
        # two keeps one allowance meaning one thing.
        self.used += sum(len(artifact.data) for artifact in artifacts) * 4 // 3


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

    #: Photographs whose pixel material is in the page. Fewer than all of them
    #: when the image budget ran out, and each of those says so for itself.
    rendered: int = 0

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
                        any(
                            fact.label in {"Embedded preview", "Maker note preview"}
                            for fact in one.facts
                        )
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
            *(
                (("images rendered", f"{self.rendered} of {len(self.photos)}"),)
                if self.rendered < len(self.photos)
                else ()
            ),
        )


def analyse_photos(
    records: list[FileRecord],
    root: Path,
    *,
    redact: bool = False,
    budget: int | None = IMAGE_BUDGET,
) -> PhotoCollection:
    """Augment supported on-disk still images with bounded photo findings.

    `budget` caps the pixel-bearing bytes of the whole report; `None` lifts the
    cap. Photographs past it keep every fact read from them and lose only their
    pictures, and say which.
    """
    allowance = _Budget(budget)
    photos: list[PhotoResult] = []
    for record in records:
        path = Path(record.path)
        if record.parent is not None or path.suffix.lower() not in PHOTO_SUFFIXES:
            continue
        if not path.is_file():
            continue
        photos.append(_analyse_photo(len(photos) + 1, record, path, redact, allowance))

    groups: dict[str, list[str]] = {}
    for photo in photos:
        if photo.serial:
            groups.setdefault(photo.serial, []).append(photo.path)
    camera_groups = tuple(
        (serial, tuple(paths)) for serial, paths in sorted(groups.items()) if len(paths) > 1
    )
    return PhotoCollection(
        str(root.resolve()),
        tuple(photos),
        redact,
        camera_groups,
        rendered=sum(1 for photo in photos if photo.artifacts),
    )


def _analyse_photo(
    number: int, record: FileRecord, path: Path, redact: bool, budget: _Budget
) -> PhotoResult:
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
    maker_preview = tags.maker.preview if tags and tags.maker else None
    for key, label, found in (
        ("embedded-preview", "Embedded preview", preview),
        ("maker-preview", "Maker note preview", maker_preview),
    ):
        if not found:
            continue
        if not redact and not budget.spent:
            artifacts.append(_preview_artifact(key, label, found))
        facts.append(
            PhotoFact(
                label,
                f"{_dimensions(found.width, found.height)}, {len(found.data)} bytes",
                FACT,
                found.source,
                found.sha256,
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
    elif budget.spent:
        methods.append(
            MethodCoverage(
                "Pixel diagnostics",
                "not evaluated",
                "the report's image budget is spent; the facts above are unaffected",
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
                    path, _largest_first(preview, maker_preview)
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

    budget.take(artifacts)
    evidence = tuple(record.redacted().evidence if redact else record.evidence)
    # The structural analysis quotes the file's own comments, so it answers for
    # the same promise the evidence records do and is redacted with them.
    if redact and jpeg is not None:
        jpeg = jpeg.redacted()
    camera = exif.camera(tags) if tags else _evidence_value(evidence, "Make", "Model")
    # A camera that fills the standard tag is the exception. `SerialNumber` and
    # `InternalSerialNumber` come from the vendor block, which is where most
    # bodies actually write it, and clustering already groups on all three.
    serial = _field(evidence, "BodySerialNumber", "SerialNumber", "InternalSerialNumber")
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


def _largest_first(*previews: EmbeddedPreview | None) -> list[EmbeddedPreview]:
    """The previews a file carries, biggest first.

    Only one is compared against the photograph, and the larger one shows more
    of whatever the comparison is for.
    """
    found = [preview for preview in previews if preview is not None]
    return sorted(found, key=lambda preview: len(preview.data), reverse=True)


def _preview_artifact(key: str, label: str, preview: EmbeddedPreview) -> PhotoArtifact:
    return PhotoArtifact(
        key,
        label,
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


def _field(evidence: tuple[EvidenceRecord, ...], *names: str) -> str | None:
    """The first of `names` any record carries, in the order they are given."""
    for name in names:
        value = next((record.fields[name] for record in evidence if record.fields.get(name)), None)
        if value:
            return value
    return None


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
