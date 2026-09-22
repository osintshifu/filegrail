"""Optional, bounded pixel diagnostics for the dedicated photo report."""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Iterable
from io import BytesIO
from pathlib import Path
from typing import Any

from .photo import FACT, SIGNAL, PhotoArtifact, PhotoFact
from .preview import EmbeddedPreview

_MAX_SOURCE_PIXELS = 100_000_000

#: The whole report travels as one file, and a lossless PNG of a 1024 px
#: photograph costs an order of magnitude more than a high-quality JPEG of it.
#: What an artifact is decides how much of that saving it may take.
#:
#: A histogram is line art and a bit plane holds one bit per pixel. Both are
#: exact by construction and both compress well losslessly, so neither is
#: allowed to gain detail it never had.
_LOSSLESS = frozenset({"histogram", "bit-planes"})

#: A difference map is a measurement, and it is read at pixel scale as well as
#: across regions. Region structure survives ordinary compression intact, but
#: pixel-level agreement does not, so these maps are compressed only lightly.
_MEASURED = frozenset({"luminance-gradient", "noise-residual", "ela-q90", "ela-q75"})

#: Chroma is never subsampled: in a difference map the colour of a residual is
#: the measurement, not decoration.
_MEASURED_QUALITY = 93
_PHOTO_QUALITY = 88


def available() -> bool:
    """Return whether both optional pixel-processing libraries are importable."""
    return all(importlib.util.find_spec(name) is not None for name in ("PIL", "numpy"))


def analyse_pixels(
    path: Path, previews: Iterable[EmbeddedPreview], *, max_edge: int = 1024
) -> tuple[list[PhotoArtifact], list[PhotoFact]]:
    """Build bounded working pixels and isolate failure of each analytical method."""
    if not available():
        return [], [
            PhotoFact(
                "Pixel diagnostics",
                "optional Pillow and NumPy dependencies are unavailable",
                SIGNAL,
                "runtime capability",
            )
        ]
    if max_edge < 1:
        raise ValueError("max_edge must be positive")

    working = _working_image(path, max_edge)
    width, height = working.size
    artifacts = [
        _artifact(
            "main-preview",
            "Working image",
            "bounded RGB decode",
            working,
            f"RGB; longest edge <= {max_edge} px",
        )
    ]
    facts = [
        PhotoFact(
            "Pixel working image",
            f"{width} x {height} px",
            FACT,
            "bounded RGB decode",
            f"longest edge limited to {max_edge} px",
        )
    ]

    diagnostics: tuple[tuple[str, str, str, Callable[[], Any], str], ...] = (
        (
            "histogram",
            "RGB and luminance histogram",
            "channel histogram",
            lambda: _histogram(working),
            f"256 bins; RGB and luminance; working image {width} x {height} px",
        ),
        (
            "luminance-gradient",
            "Luminance gradient",
            "luminance gradient",
            lambda: _gradient(working),
            "central differences; luminance; normalized per image",
        ),
        (
            "bit-planes",
            "Selected luminance bit planes",
            "bit-plane decomposition",
            lambda: _bit_planes(working),
            "luminance bit planes 7, 4, 1, 0",
        ),
        (
            "noise-residual",
            "Local noise residual",
            "median residual",
            lambda: _noise_residual(working),
            "3 x 3 median residual; absolute; normalized per image",
        ),
        (
            "ela-q90",
            "Error level analysis, quality 90",
            "error level analysis",
            lambda: _ela(working, 90),
            "JPEG recompression quality=90; absolute RGB difference; normalized per image",
        ),
        (
            "ela-q75",
            "Error level analysis, quality 75",
            "error level analysis",
            lambda: _ela(working, 75),
            "JPEG recompression quality=75; absolute RGB difference; normalized per image",
        ),
    )
    for key, label, method, build, parameters in diagnostics:
        try:
            artifacts.append(_artifact(key, label, method, build(), parameters))
        except Exception as error:
            facts.append(_failure(label, method, error))

    for preview in previews:
        try:
            comparison = _preview_comparison(working, preview)
            artifacts.append(
                _artifact(
                    "embedded-preview-comparison",
                    "Main image and embedded preview comparison",
                    "embedded-preview comparison",
                    comparison,
                    (
                        f"embedded preview resized to {width} x {height} px; "
                        "absolute RGB difference; three panels"
                    ),
                )
            )
        except Exception as error:
            facts.append(_failure("Embedded preview comparison", "preview comparison", error))
        break

    return artifacts, facts


def _working_image(path: Path, max_edge: int) -> Any:
    Image = importlib.import_module("PIL.Image")
    ImageOps = importlib.import_module("PIL.ImageOps")

    with Image.open(path) as opened:
        width, height = opened.size
        if width < 1 or height < 1 or width * height > _MAX_SOURCE_PIXELS:
            raise ValueError("source image dimensions exceed the bounded decoder limit")
        opened.seek(0)
        image = ImageOps.exif_transpose(opened).convert("RGB")
    image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    return image


def _artifact(key: str, label: str, method: str, image: Any, parameters: str) -> PhotoArtifact:
    """Encode one analytical output, saying in its parameters how it was stored.

    A reader has to be able to tell a measurement from the report's own
    encoding, so the encoding is named beside every other parameter rather
    than left to be inferred from the media type.
    """
    buffer = BytesIO()
    if key in _LOSSLESS:
        image.save(buffer, format="PNG", optimize=False, compress_level=9)
        mime, encoding = "image/png", "lossless PNG"
    else:
        quality = _MEASURED_QUALITY if key in _MEASURED else _PHOTO_QUALITY
        # `optimize` is deliberately off. Its second Huffman pass wants one
        # buffer for a whole scan and a residual map is close to pure noise,
        # which overflows it and loses the map. A few percent is not worth that.
        image.save(buffer, format="JPEG", quality=quality, subsampling=0, optimize=False)
        mime, encoding = "image/jpeg", f"JPEG quality {quality}"
    width, height = image.size
    return PhotoArtifact(
        key,
        label,
        method,
        mime,
        buffer.getvalue(),
        width,
        height,
        f"{parameters}; report encoding {encoding}",
    )


def _histogram(image: Any) -> Any:
    Image = importlib.import_module("PIL.Image")
    ImageDraw = importlib.import_module("PIL.ImageDraw")

    canvas = Image.new("RGB", (720, 260), "white")
    draw = ImageDraw.Draw(canvas)
    values = image.histogram()
    series = (
        (values[0:256], (190, 55, 55)),
        (values[256:512], (45, 145, 75)),
        (values[512:768], (45, 90, 180)),
        (image.convert("L").histogram(), (35, 45, 52)),
    )
    peak = max(max(channel) for channel, _colour in series) or 1
    for channel, colour in series:
        points = [
            (20 + index * 680 / 255, 240 - count * 220 / peak)
            for index, count in enumerate(channel)
        ]
        draw.line(points, fill=colour, width=2)
    draw.rectangle((19, 19, 701, 241), outline=(115, 125, 130), width=1)
    return canvas


def _gradient(image: Any) -> Any:
    Image = importlib.import_module("PIL.Image")
    np = importlib.import_module("numpy")
    luminance = np.asarray(image.convert("L"), dtype=np.float32)
    if min(luminance.shape) < 2:
        magnitude = np.zeros_like(luminance)
    else:
        vertical, horizontal = np.gradient(luminance)
        magnitude = np.hypot(horizontal, vertical)
    return Image.fromarray(_normalise(magnitude), mode="L")


def _bit_planes(image: Any) -> Any:
    Image = importlib.import_module("PIL.Image")
    np = importlib.import_module("numpy")
    luminance = np.asarray(image.convert("L"), dtype=np.uint8)
    height, width = luminance.shape
    canvas = Image.new("L", (width * 2, height * 2))
    for position, bit in enumerate((7, 4, 1, 0)):
        plane = ((luminance >> bit) & 1) * 255
        tile = Image.fromarray(plane.astype(np.uint8), mode="L")
        canvas.paste(tile, ((position % 2) * width, (position // 2) * height))
    # A bit plane holds one bit per pixel. Storing it as one, without dither
    # inventing intermediate values, is both exact and a fraction of the size.
    return canvas.convert("1", dither=Image.Dither.NONE)


def _noise_residual(image: Any) -> Any:
    Image = importlib.import_module("PIL.Image")
    ImageFilter = importlib.import_module("PIL.ImageFilter")
    np = importlib.import_module("numpy")
    source = np.asarray(image, dtype=np.int16)
    median = np.asarray(image.filter(ImageFilter.MedianFilter(3)), dtype=np.int16)
    difference = np.abs(source - median)
    return Image.fromarray(_normalise(difference), mode="RGB")


def _ela(image: Any, quality: int) -> Any:
    Image = importlib.import_module("PIL.Image")
    np = importlib.import_module("numpy")
    encoded = BytesIO()
    image.save(encoded, format="JPEG", quality=quality, subsampling=2, optimize=False)
    encoded.seek(0)
    with Image.open(encoded) as reopened:
        recompressed = np.asarray(reopened.convert("RGB"), dtype=np.int16)
    source = np.asarray(image, dtype=np.int16)
    return Image.fromarray(_normalise(np.abs(source - recompressed)), mode="RGB")


def _preview_comparison(image: Any, preview: EmbeddedPreview) -> Any:
    Image = importlib.import_module("PIL.Image")
    ImageOps = importlib.import_module("PIL.ImageOps")
    np = importlib.import_module("numpy")
    with Image.open(BytesIO(preview.data)) as opened:
        embedded = ImageOps.exif_transpose(opened).convert("RGB")
    embedded = embedded.resize(image.size, Image.Resampling.LANCZOS)
    source = np.asarray(image, dtype=np.int16)
    other = np.asarray(embedded, dtype=np.int16)
    difference = Image.fromarray(_normalise(np.abs(source - other)), mode="RGB")
    width, height = image.size
    canvas = Image.new("RGB", (width * 3, height))
    canvas.paste(image, (0, 0))
    canvas.paste(embedded, (width, 0))
    canvas.paste(difference, (width * 2, 0))
    return canvas


def _normalise(values: Any) -> Any:
    np = importlib.import_module("numpy")
    peak = float(values.max()) if values.size else 0.0
    if peak <= 0:
        return np.zeros(values.shape, dtype=np.uint8)
    return np.clip(values.astype(np.float32) * (255.0 / peak), 0, 255).astype(np.uint8)


def _failure(label: str, method: str, error: Exception) -> PhotoFact:
    return PhotoFact(
        f"{label} unavailable",
        type(error).__name__,
        SIGNAL,
        method,
        "This diagnostic failed in isolation; other methods remain valid.",
    )
