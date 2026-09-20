# Photo Forensics Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a separate offline HTML photo-forensics report with native EXIF preview and JPEG structure analysis plus optional Pillow/NumPy diagnostics.

**Architecture:** Keep structural parsers in focused standard-library modules and return typed photo-analysis objects rather than adding binary data to `EvidenceRecord`. The `photo` command reuses the normal scan for provenance, augments each selected image with photo analysis, and gives a dedicated renderer bounded data-URI artifacts. Pixel work lives behind runtime capability detection and the `photo` optional dependency group.

**Tech Stack:** Python 3.10 standard library, dataclasses, Pillow and NumPy optional extra, pytest, self-contained HTML/CSS.

**Spec:** `docs/specs/2026-09-20-photo-forensics-report.md`

## Global Constraints

- Core runtime dependencies remain empty.
- Optional photo dependencies are Pillow and NumPy only.
- Source files are read-only and every binary offset and allocation is bounded.
- Reports say facts, conflicts, signals and not evaluated, never authenticity scores.
- Python 3.10 through 3.13 and Windows path behavior remain supported.
- Tests use `Path` for expected paths and raw commands run through `rtk proxy`.
- No code is copied from GPL reference projects.

---

### Task 1: EXIF IFD traversal and embedded JPEG previews

**Files:**
- Modify: `src/filegrail/sources/embedded/exif.py`
- Modify: `src/filegrail/sources/embedded/__init__.py`
- Test: `tests/test_photo_exif.py`

**Interfaces:**
- Produces: `EmbeddedPreview(source: str, mime: str, data: bytes, width: int | None, height: int | None)`.
- Produces: `Exif.preview: EmbeddedPreview | None`, `Exif.interop`, `Exif.thumbnail`, and `Exif.sub_ifds` decoded collections.
- Consumes: existing TIFF payload returned by `_jpeg_exif`, `_webp_chunk`, `_heif_exif` or the mapped TIFF file.

- [ ] Write a synthetic TIFF/JPEG test whose IFD0 next pointer reaches IFD1 tags `0x0103`, `0x0201` and `0x0202`, and assert the returned preview bytes, dimensions and SHA-256 source fields.
- [ ] Run `rtk proxy .venv/bin/python -m pytest tests/test_photo_exif.py -q` and confirm failure because `Exif.preview` does not exist.
- [ ] Add bounded IFD result parsing that returns entries plus the next pointer, follows EXIF/GPS/Interop/SubIFD pointers with a visited set, and validates compressed JPEG preview offsets and lengths.
- [ ] Run the targeted test and confirm it passes.
- [ ] Add malformed offset, cycle and oversized preview tests, watch them fail, then reject each malformed structure without raising.
- [ ] Add textual preview fields and note in `_from_exif` without serializing preview bytes, then run `tests/test_formats.py`, `tests/test_embedded.py` and the new tests.
- [ ] Commit `Add bounded EXIF preview traversal`.

### Task 2: JPEG structure and quantization analysis

**Files:**
- Create: `src/filegrail/photojpeg.py`
- Test: `tests/test_photo_jpeg.py`

**Interfaces:**
- Produces: `JpegAnalysis` with `width`, `height`, `encoding`, `precision`, `components`, `scans`, `restart_interval`, `markers`, `quantization`, `huffman_tables`, `comments`, `eoi_offset`, `trailing_bytes`, `quality`.
- Produces: `analyse_jpeg(path: Path) -> JpegAnalysis | None` and `jpeg_size(data: bytes) -> tuple[int, int] | None`.

- [ ] Write a minimal hand-checked JPEG fixture containing SOF0, DQT, DHT, DRI, COM, SOS and EOI and assert literal parsed values.
- [ ] Run the targeted test and confirm import failure for `filegrail.photojpeg`.
- [ ] Implement a bounded marker walker including entropy-data handling, stuffed bytes and restart markers until EOI.
- [ ] Run the test and confirm it passes.
- [ ] Add failing tests for progressive SOF2, multiple scans, 16-bit DQT, truncated segments and bytes after EOI, then implement the smallest handling for each.
- [ ] Add failing literal tests for exact IJG quality tables and a non-standard nearest-table result, then implement exact-versus-nearest wording.
- [ ] Run `tests/test_photo_jpeg.py` and existing JPEG/clean tests.
- [ ] Commit `Add native JPEG structure analysis`.

### Task 3: Photo analysis model and collection orchestration

**Files:**
- Create: `src/filegrail/photo.py`
- Test: `tests/test_photo.py`

**Interfaces:**
- Consumes: `FileRecord`, `Exif.preview`, `analyse_jpeg` and optional pixel module.
- Produces: `PhotoFact`, `PhotoArtifact`, `PhotoResult`, `PhotoCollection` and `analyse_photos(records, root, redact=False)`.

- [ ] Write a test with one JPEG `FileRecord` and assert a literal collection summary, photo identity, preview descriptor, structural facts and method coverage.
- [ ] Run the test and confirm import failure for `filegrail.photo`.
- [ ] Implement immutable/slotted result dataclasses and orchestration for supported still-image suffixes.
- [ ] Run the targeted test and confirm it passes.
- [ ] Add failing tests for dimension conflict, aspect-ratio signal, grouping by camera body serial, redaction clearing artifacts, unsupported files and per-analyzer failure isolation.
- [ ] Implement the minimal rules and collection grouping that satisfy those tests.
- [ ] Run the targeted tests and `tests/test_analysis.py tests/test_correlate.py`.
- [ ] Commit `Model photo forensic findings`.

### Task 4: Optional bounded pixel diagnostics

**Files:**
- Create: `src/filegrail/photopixels.py`
- Modify: `pyproject.toml`
- Test: `tests/test_photo_pixels.py`

**Interfaces:**
- Produces: `available() -> bool` and `analyse_pixels(path, previews, max_edge=1024) -> tuple[list[PhotoArtifact], list[PhotoFact]]`.
- Artifacts are PNG bytes with method, media type, dimensions and parameter text.

- [ ] Write a capability test that exercises the real installed optional dependencies and a deterministic 8x8 Pillow image test for bounded main preview output.
- [ ] Run the test and confirm import failure for `filegrail.photopixels`.
- [ ] Add `photo = ["Pillow>=10,<13", "numpy>=1.24,<3"]` and implement bounded RGB loading plus deterministic PNG encoding.
- [ ] Run the targeted test and confirm it passes.
- [ ] Add one failing behavior test each for histogram, luminance gradient, bit-plane panel, median noise residual, ELA at qualities 90 and 75, and preview comparison; use literal dimensions, method names and parameter strings rather than pixel-perfect snapshots where encoders may differ.
- [ ] Implement each diagnostic using Pillow and NumPy only, isolating failures per method and capping the working image at 1024 pixels on its longest edge.
- [ ] Run the targeted tests in Python 3.13 and Python 3.10.
- [ ] Commit `Add optional photo pixel diagnostics`.

### Task 5: Dedicated offline HTML renderer

**Files:**
- Create: `src/filegrail/photohtml.py`
- Test: `tests/test_photo_html.py`

**Interfaces:**
- Consumes: `PhotoCollection`.
- Produces: `render_photo_html(collection, output=None, now=None) -> str`.

- [ ] Write a report test asserting the CSP, collection facts, numbered plate, evidence states, data-URI artifact, method parameters, escaped file-derived text and absence of external URLs.
- [ ] Run the targeted test and confirm import failure for `filegrail.photohtml`.
- [ ] Implement semantic HTML and the approved light-table token system with contact-sheet index, evidence rail, registration-corner image stage and collapsible diagnostic strips.
- [ ] Run the report test and confirm it passes.
- [ ] Add failing tests for no images, unavailable pixel methods, redacted media omission, responsive/print CSS hooks and output-relative title metadata.
- [ ] Implement those states, then run `tests/test_photo_html.py tests/test_htmlreport.py`.
- [ ] Generate a real corpus report in `/tmp`, serve it locally and inspect desktop plus narrow screenshots; correct only issues visible in the render and rerun tests.
- [ ] Commit `Add offline photo forensics report`.

### Task 6: CLI, documentation, examples and release verification

**Files:**
- Modify: `src/filegrail/cli.py`
- Modify: `src/filegrail/about.py`
- Modify: `README.md`
- Modify: `docs/FORMATS.md`
- Modify: `CHANGELOG.md`
- Modify: `pyproject.toml`
- Modify: `src/filegrail/__init__.py`
- Test: `tests/test_commands.py`
- Test: `tests/test_documented_formats.py`

**Interfaces:**
- Produces command: `filegrail photo PATH --out REPORT.html [--redact] [--no-recurse] [--hash]`.

- [ ] Write CLI tests for help, a single image, recursive directory selection, no images, unsupported single file, required `--out`, redaction and optional dependency coverage.
- [ ] Run the CLI tests and confirm `photo` is rejected as an unknown command.
- [ ] Register `_photo_parser` and `_photo`, reuse the normal scanner for evidence, select still images, run photo analysis and atomically write the HTML output.
- [ ] Run the CLI tests and confirm they pass.
- [ ] Document installation, command behavior, analytical limits, report sections and optional dependency behavior; update the command landing screen and format documentation.
- [ ] Run `tests/test_documented_formats.py tests/test_about.py tests/test_commands.py`.
- [ ] Bump the next patch version in `pyproject.toml` and `src/filegrail/__init__.py`, add the changelog entry, and rebuild `docs/example-report.html` only if the existing investigation renderer changed.
- [ ] Run fresh full verification on Python 3.13 and 3.10, Ruff, format, mypy, build and twine check.
- [ ] Review the entire diff against this plan and the spec, then commit the release, push `master`, wait for all 12 CI jobs, tag only after green CI, push the tag and verify the published package from a clean Python 3.10 virtual environment.

## Self-review

- Every approved first-release requirement maps to Tasks 1 through 6.
- Advanced PRNU, learned models, resampling and steganalysis remain outside this release as specified.
- Binary preview and diagnostic bytes stay outside `EvidenceRecord` and JSON.
- The structural report works with zero dependencies; optional methods report explicit coverage.
- Every production behavior begins with a targeted failing test and has a fresh verification command.

