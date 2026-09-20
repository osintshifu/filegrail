# Photo Forensics Report

## Goal

Add a dedicated `filegrail photo PATH --out REPORT.html` workflow that produces a
self-contained, offline HTML report for still-image examination. The report must
combine FileGrail's existing provenance and metadata evidence with bounded image
structure analysis, embedded previews and optional pixel diagnostics. It must not
claim that an image is authentic or manipulated.

## Product boundary

- `filegrail scan --html` remains the cross-format investigation report.
- `filegrail photo` accepts one file or a directory and selects still images itself.
- The report classifies output as facts, conflicts, signals or not evaluated.
- No aggregate authenticity score or confidence percentage is emitted.
- Core structural analysis keeps the package's zero-runtime-dependency guarantee.
- Pixel diagnostics are enabled by the optional `filegrail[photo]` extra containing
  Pillow and NumPy only.
- The command remains useful without the extra and explains which diagnostics were
  not evaluated.
- Source files are opened read-only. No extracted preview is written beside evidence.

## Structural analysis

### TIFF and EXIF

Walk IFD0, EXIF IFD, GPS IFD, IFD1, Interoperability IFD and SubIFDs with bounds,
cycle detection, depth and entry limits. Preserve unknown decoded tags by numeric
name. Recognize compressed JPEG previews described by IFD1
`JPEGInterchangeFormat` and `JPEGInterchangeFormatLength`.

An embedded preview descriptor contains its source, media type, byte length, pixel
dimensions where a bounded header parser can obtain them, SHA-256, and the validated
bytes for the photo report. Binary bytes never enter `EvidenceRecord.fields` or JSON.

JFIF, JFXX and Photoshop Image Resource Block thumbnails use the same descriptor
shape when their formats can be safely decoded. A malformed offset, length or image
header produces no preview and never aborts the scan.

### JPEG

Walk marker segments through EOI with explicit bounds. Record marker order and
offsets, SOF encoding, precision, dimensions, components and sampling, DQT matrices,
DHT summaries, DRI, SOS count, comments, EOI and trailing bytes. A quantization
estimate distinguishes exact IJG table matches from the nearest heuristic quality.
It describes the observable encoding, not the image's first save.

### Consistency

Report mechanically supported conflicts such as JPEG header dimensions versus EXIF
pixel dimensions, invalid preview bounds, contradictory metadata values already
identified by FileGrail, and an embedded preview whose aspect ratio materially
differs from the main image. Pixel differences are signals, not proof of editing.

## Optional pixel diagnostics

When Pillow and NumPy are importable, create bounded derived PNG artifacts for:

- a main-image report preview;
- RGB and luminance histograms;
- luminance gradient;
- selected bit planes;
- local noise residual;
- ELA at more than one declared JPEG quality;
- an embedded-preview comparison when a preview exists.

Every diagnostic records the method and parameters used. Input is normalized to a
bounded working image before computation. Failures are isolated per diagnostic.
Without the optional extra, the report says `not evaluated` rather than presenting
absence as a negative result.

## HTML report

The report is one offline file with an explicit CSP and data-URI images only. It
contains a collection summary followed by one numbered plate per photograph:

```text
+---------------------------------------------------------------------+
| FILEGRAIL PHOTO LAB                  case facts / methods / coverage |
+-----------------------------+---------------------------------------+
| collection contact sheet    | cameras, formats, previews, conflicts |
+-----------------------------+---------------------------------------+
| #001 image stage            | evidence rail                         |
| original / embedded preview | identity, time, GPS, structure        |
+-----------------------------+---------------------------------------+
| diagnostic strips and method notes                                  |
+---------------------------------------------------------------------+
```

### Visual system

- `light table` #E7ECEE: page ground.
- `negative sleeve` #17232B: image stages and masthead.
- `paper` #FAFBFB: evidence surfaces.
- `registration cyan` #287D8C: links, focus and structural facts.
- `inspection amber` #A96721: signals and not-evaluated methods.
- `conflict red` #A23F3F: validated contradictions only.
- Body type uses the local system sans stack; file identities use Georgia; byte
  offsets and hashes use the local monospace stack.
- Registration-corner marks around images are the single characteristic visual
  device. Borders, numbering and colour always encode evidence state.
- No gradients, decorative shadows, generic equal-size card grid, automatic motion
  or external assets.
- Keyboard focus, responsive layout, print layout and reduced-motion behavior are
  mandatory.

The main image and derived maps are size-capped before embedding. `--redact` omits
all pixel-bearing previews and diagnostics because redacting text does not make an
image safe to share.

## CLI and outputs

Primary interface:

```text
filegrail photo PATH --out photo-report.html
```

Options in the first release: `--out`, `--redact`, `--no-recurse`, `--hash` and
`--version`. The command writes HTML only. A missing path, unsupported single file,
unwritable output or absent images returns a non-zero exit with a concrete message.

## Verification

- Synthetic fixtures cover offsets, malformed lengths, cycles and marker boundaries.
- The local corpus verifies real IFD1 previews, including the existing 160x120 JPEG
  previews.
- Python 3.10 and the default environment run the targeted and full suites.
- Ruff, format and mypy pass.
- The package builds and its wheel metadata exposes the optional `photo` extra.
- The generated report is structurally tested and visibly reviewed at desktop and
  narrow viewport sizes before release.

