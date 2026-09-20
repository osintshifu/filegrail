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
    assert all(item.mime == "image/png" and item.data.startswith(b"\x89PNG") for item in artifacts)
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
        "RGB; longest edge <= 1024 px",
        "256 bins; RGB and luminance; working image 6 x 4 px",
        "central differences; luminance; normalized per image",
        "luminance bit planes 7, 4, 1, 0",
        "3 x 3 median residual; absolute; normalized per image",
        "JPEG recompression quality=90; absolute RGB difference; normalized per image",
        "JPEG recompression quality=75; absolute RGB difference; normalized per image",
    ]


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
