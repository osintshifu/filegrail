"""Optional pixel methods stay detectable without becoming core dependencies."""

import importlib.util
from io import BytesIO
from pathlib import Path

import pytest

from filegrail.photopixels import analyse_pixels, available
from filegrail.preview import EmbeddedPreview


def test_reports_real_optional_dependency_availability():
    installed = all(importlib.util.find_spec(name) is not None for name in ("PIL", "numpy"))

    assert available() is installed


@pytest.mark.skipif(not available(), reason="photo extra is not installed")
def test_creates_bounded_declared_pixel_diagnostics(tmp_path: Path):
    from PIL import Image

    source = Image.new("RGB", (8, 8))
    source.putdata([(x * 30, y * 30, (x + y) * 15) for y in range(8) for x in range(8)])
    path = tmp_path / "pixels.png"
    source.save(path)

    embedded = Image.new("RGB", (4, 4), (120, 80, 40))
    buffer = BytesIO()
    embedded.save(buffer, format="JPEG", quality=80)
    preview = EmbeddedPreview("EXIF IFD1", "image/jpeg", buffer.getvalue(), 4, 4)

    artifacts, facts = analyse_pixels(path, [preview], max_edge=4)

    assert [(item.key, item.width, item.height) for item in artifacts] == [
        ("main-preview", 4, 4),
        ("histogram", 720, 260),
        ("luminance-gradient", 4, 4),
        ("bit-planes", 8, 8),
        ("noise-residual", 4, 4),
        ("ela-q90", 4, 4),
        ("ela-q75", 4, 4),
        ("embedded-preview-comparison", 12, 4),
    ]
    assert [(item.key, item.mime) for item in artifacts if item.mime != "image/jpeg"] == [
        ("histogram", "image/png"),
        ("bit-planes", "image/png"),
    ]
    assert all(
        item.data.startswith(b"\xff\xd8" if item.mime == "image/jpeg" else b"\x89PNG")
        for item in artifacts
    )
    assert [item.method for item in artifacts] == [
        "bounded RGB decode",
        "channel histogram",
        "luminance gradient",
        "bit-plane decomposition",
        "median residual",
        "error level analysis",
        "error level analysis",
        "embedded-preview comparison",
    ]
    assert facts[0].label == "Pixel working image"
    assert facts[0].value == "4 x 4 px"


@pytest.mark.skipif(not available(), reason="photo extra is not installed")
def test_declares_parameters_for_every_derived_map(tmp_path: Path):
    from PIL import Image

    path = tmp_path / "flat.jpg"
    Image.new("RGB", (6, 4), (90, 120, 150)).save(path, quality=95)

    artifacts, _facts = analyse_pixels(path, [], max_edge=1024)

    assert [item.parameters for item in artifacts] == [
        "RGB; longest edge <= 1024 px; report encoding JPEG quality 88",
        "256 bins; RGB and luminance; working image 6 x 4 px; report encoding lossless PNG",
        "central differences; luminance; normalized per image; report encoding JPEG quality 93",
        "luminance bit planes 7, 4, 1, 0; report encoding lossless PNG",
        "3 x 3 median residual; absolute; normalized per image; report encoding JPEG quality 93",
        "JPEG recompression quality=90; absolute RGB difference; normalized per image; "
        "report encoding JPEG quality 93",
        "JPEG recompression quality=75; absolute RGB difference; normalized per image; "
        "report encoding JPEG quality 93",
    ]


@pytest.mark.skipif(not available(), reason="photo extra is not installed")
def test_encodes_a_noise_map_that_defeats_the_jpeg_optimizer(tmp_path: Path):
    """Noise is what a residual map looks like, and it is what breaks the encoder.

    JPEG's optimizing pass wants one buffer for a whole scan, and a map of pure
    noise overflows it. Losing every derived map of one photograph to that is
    not a trade worth the few percent the pass saves.
    """
    import random

    from PIL import Image

    random.seed(7)
    noise = Image.new("RGB", (256, 256))
    noise.putdata(
        [
            (random.randrange(256), random.randrange(256), random.randrange(256))
            for _ in range(256 * 256)
        ]
    )
    path = tmp_path / "noise.png"
    noise.save(path)

    artifacts, facts = analyse_pixels(path, [], max_edge=256)

    assert [item.key for item in artifacts] == [
        "main-preview",
        "histogram",
        "luminance-gradient",
        "bit-planes",
        "noise-residual",
        "ela-q90",
        "ela-q75",
    ]
    assert [fact.label for fact in facts] == ["Pixel working image"]


@pytest.mark.skipif(not available(), reason="photo extra is not installed")
def test_isolates_one_failed_pixel_diagnostic(tmp_path: Path, monkeypatch):
    from PIL import Image

    path = tmp_path / "source.png"
    Image.new("RGB", (6, 4), (90, 120, 150)).save(path)

    def fail(_image):
        raise RuntimeError("gradient failed")

    monkeypatch.setattr("filegrail.photopixels._gradient", fail)
    artifacts, facts = analyse_pixels(path, [])

    assert "luminance-gradient" not in {item.key for item in artifacts}
    assert "noise-residual" in {item.key for item in artifacts}
    assert [(item.label, item.value, item.state) for item in facts[-1:]] == [
        ("Luminance gradient unavailable", "RuntimeError", "signal")
    ]
