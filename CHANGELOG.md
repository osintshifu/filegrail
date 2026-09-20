# Changelog

All notable changes to `filegrail` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

## 0.41.0 - 2026-09-20

### Added

- `filegrail photo PATH --out REPORT.html`: contact sheet, one plate per image, method coverage, separate fact, conflict and signal states. Images link from beside the page; `--embed` inlines them, `--image-budget` bounds them.
- JPEG structure without dependencies: markers through EOI, encoding, sampling, quantization and Huffman tables, restart intervals, scans, comments, trailing bytes, IJG quality match or estimate.
- EXIF follows IFD1, Interoperability and SubIFD directories, with bounds and cycle detection.
- Maker notes as an evidence block for Canon, Nikon, Apple, Olympus, Panasonic and Reconyx: body and lens serial, lens model, shutter count, owner name, firmware, frame number, trail-camera event, Apple Live Photo identifier.
- A preview carried in a maker note is read; one it only points at is reported.
- Photographs cluster by camera body and, separately, by lens.
- A maker note in the opposite byte order to its file is reported and its offsets are not followed.
- A record says how many entries a maker note declared and why an unread one was skipped.
- A scan bounds the content it reads out of carriers and names those it left closed.
- `filegrail[photo]`: preview, histograms, luminance gradient, bit planes, median residual, ELA at 90 and 75, thumbnail comparison.

### Fixed

- The end of a JPEG entropy-coded scan is found in blocks, not one byte at a time.
- A maker note value that does not decode as text no longer becomes a field.
- A field padded with null bytes at the front is read instead of coming back empty.
- Entries in signed and floating field types are counted.

### Security

- Photo reports make no network request, under an explicit content security policy. `--redact` omits every pixel-bearing image; one failed diagnostic does not end the rest.

## 0.40.4 - 2026-09-19

### Security

- Releases verify that the tag names the package version and points at the current `master`, then run tests on Python 3.10 and 3.13, Ruff, mypy, the package build and Twine before PyPI publication can begin.
- GitHub Actions are pinned to commit SHAs. Repository policy tests keep the release gate and the pins in place.

### Changed

- Local Claude review exports are ignored so screenshots and patches cannot enter a release through a broad staging command.

## 0.40.3 - 2026-09-19

### Changed

- HTML report: relationship rows carry family-coloured type pills, coloured file numbers and the focus button beside the name; finding and conflict references are framed wherever they appear; the status line under the graph is gone.

## 0.40.2 - 2026-09-19

### Changed

- HTML report: the graph toolbar is a lighter band with dark controls; the relationship-type chips sit on the canvas field.
- HTML report: investigative pivots carry a framed number, a family-coloured dot on the type and a corpus column that marks values seen in both metadata and content.

## 0.40.1 - 2026-09-19

### Changed

- HTML report: the graph toolbar, filters and canvas share one dark field; the canvas gradient fades into it with no seam.
- HTML report: key findings carry a framed number, a kind label beside the title and outlined file chips with the file number in colour; conflicts colour the file number the same way.

## 0.40.0 - 2026-09-19

### Changed

- HTML report: Fit frames the focused node with its neighbours, or the nodes a relationship-type filter lit up, and keeps clear of the open details panel; with nothing highlighted it frames the whole graph as before.
- HTML report: Reset is an icon and also restores the layout, spacing and label choices.
- HTML report: neutral grey surfaces and lines in place of the blue-tinted ones; the graph canvas has a deeper gradient.

## 0.39.1 - 2026-09-19

### Changed

- HTML report: the graph canvas sits on a darker, vignetted field; the full screen control is an icon.

### Fixed

- HTML report: in the node details panel, rows for identifier and person nodes carried a hidden copy button that pushed the focus button onto a second line.

## 0.39.0 - 2026-09-19

### Changed

- `--pivots` now searches document content as well as provenance and metadata. `--meta` keeps the search to provenance and metadata, `--content` to document content; either turns `--pivots` on by itself. Graph exports read both corpora too. Scan JSON `run` gains `metadata` beside `content`.

## 0.38.2 - 2026-09-19

### Fixed

- HTML report: in the graph's full-screen view, the rule that sizes the canvas also reached the small icons inside the node details panel and stretched each to the canvas height, so the focus buttons showed as empty boxes; the rule now applies to the canvas alone.

## 0.38.1 - 2026-09-19

### Fixed

- HTML report: on a phone the mark in the masthead grew to the height of the facts beside it and covered them; it is now capped and sits above the facts on a narrow screen, with each fact's label above its value.
- HTML report: in the graph's node details, each connected-to row is a fixed grid of relation, type, value and focus button, so the button is always inside the panel, in full screen too; the panel is a little wider and keeps a stable gutter for its scrollbar.

## 0.38.0 - 2026-09-19

### Changed

- Terminal report: the masthead carries the mark in the brand colour beside the name and the product line, and one line says when the scan ran and what it covered. Sections are numbered, with the title and a rule on one line. The summary lists the same figures as the HTML report, in the same order, with a note beside each; `Relationships` counts the graph's edges. The file index gives every file the same two-line shape, with the full block kept for `-v`. Coverage states are marked `●`, `◐` and `○`. The XMP derivation section is named `XMP LINEAGE`. The footer names the version and the time.
- Start screen: the mark in the brand colour beside the name and the product line, and every example fits beside its description on an 80-column terminal.
- HTML report: in the graph's node details, the connected-to rows wrap inside the panel and their focus buttons stay in reach, in full screen too; the dotted field, the edges and the nodes of other kinds carry less grey.

### Fixed

- Terminal report: a terminal without Unicode no longer gets a traceback from a separator or from a file name it cannot encode; the separator takes the ASCII glyph and the character is replaced.

## 0.37.1 - 2026-09-19

### Changed

- HTML report: the node details panel in the graph carries the node's colour on its top edge and beside its type, has more room inside and a quieter close control; scrollbars across the report are thin and unobtrusive.

## 0.37.0 - 2026-09-19

### Added

- HTML report: the graph panel, with its controls, can fill the screen; Esc or the same button brings the page back.

### Changed

- HTML report: findings are divided by a hairline only, with the finding number as plain text and the files as unframed tags; a finding that needs attention carries a short alert bar at its edge.
- HTML report: sections are separated by space rather than a rule.

## 0.36.0 - 2026-09-19

### Changed

- HTML report: the timeline is a timeline. Every dated record is one line on a spine: the clock, a node in the record's category colour, the verb as a chip, the file, the source with its match basis, and what the record said. Records are grouped under their day, whose heading names the weekday and stays at the top while the day scrolls past; a silence of a month or more between two days is written on the spine as `7 years later`. Category chips above narrow the list to one category.
- HTML report: the navigation bar's type is a step larger.

## 0.35.1 - 2026-09-19

### Changed

- HTML report: choosing a relation type lights its edges and the nodes they join in the graph, and the same choice is offered beside the table as a select; either control moves the other, and the SVG export keeps the highlight.

## 0.35.0 - 2026-09-19

### Added

- HTML report: the graph can be re-arranged in the page. Three layouts: the force-directed one the report ships, files on inner rings with identifiers around them grouped by type, and columns by type. A spacing slider spreads the nodes apart, and a labels control shows the main nodes, every node or none. The SVG export follows the arrangement on screen.

### Changed

- HTML report: the controls above the graph sit on a grid: find and focus on one row, arrangement and view controls on the next, the type filters below.
- HTML report: the summary cards are separate tiles, each with its category colour on the top edge and a larger figure.

## 0.34.1 - 2026-09-19

### Changed

- HTML report: tables and the findings panel sit on the page's own dark ground, with the header row one shade lighter; the timeline alternates a shade between one day's records and the next.

## 0.34.0 - 2026-09-19

### Changed

- HTML report: tables sit in a panel with a shaded header row, first and last columns padded from the edge, and secondary text a step brighter; the timeline's day rows carry an accent tick and keep the source and its match basis on one line.
- HTML report: key findings sit in one panel, each with its fields in an aligned two-column grid and its files as tags; a notable finding is marked by an alert edge.
- HTML report: the fold control is a chevron before the section title rather than a button at the far end of the heading.

### Removed

- HTML report: the by-period list above the timeline.

## 0.33.0 - 2026-09-19

### Added

- HTML report: every section folds to its heading, from the heading itself or the button beside it, and unfolds when a link or the navigation points into it.

### Changed

- HTML report: the timeline opens with the dated records by period, one row per year, month or day that holds a record, with a stacked bar by category, the count, and a line naming each run of empty periods between two rows; clicking a row limits the list to that period. The list itself puts the file first and the verb on the category chip.
- HTML report: the summary cards run files scanned, with origin, with metadata, pivots, relationships, need review, no evidence found, trace stores found.
- HTML report: graph nodes are coloured by what they stand for: files, people, devices, network addresses, money and other keys, each with a soft halo, on a dotted field with depth; the SVG export carries the same colours.
- HTML report: the mark in the navigation bar is solid, so it reads at 16 px; the masthead mark keeps a crisp stroke at any size.

## 0.32.0 - 2026-09-19

### Changed

- HTML report: the accent is a muted verdigris from the mark's own family, and every text size comes from one scale of seven steps, with the smallest labels raised to 11 px and the body, tables, notes and headings raised with them. Uppercase labels share one tracking, category chips and filter chips are larger, and the print palette follows the same family.

### Removed

- HTML report: the light theme and its toggle. The page is dark on screen and prints on paper.

## 0.31.1 - 2026-09-19

### Changed

- HTML report: a new accent and darker surfaces in both themes and in print; the mark carries the brand colour on its own token and is drawn as an outline with a light fill, so the accent can change without repainting it; prose, headings, labels and navigation are set in a sans-serif stack while paths, hashes, numbers and field values stay monospace. Nothing is fetched from the network.

### Fixed

- HTML report: the delta before a conflicting value printed as a control character and the digits `94` instead of Δ.

## 0.31.0 - 2026-09-19

### Added

- Files carried inside documents and messages are files of their own: an attachment in an `.eml` or `.msg`, a file attached to a PDF and an object packaged in an Office document are read under their own names, with their own evidence, the carrier as their parent and an `embedded in` relationship in the graph. Their origin is the carrier's, recorded by the `embedded-file` source.
- A `.gz`, `.bz2` or `.xz` that is not a tar is read as the one file it holds.

### Changed

- `--no-archives` also leaves files inside documents and messages unread.

## 0.30.8 - 2026-09-19

### Changed

- The roadmap states which steps of the evidence-depth round are implemented, what each still lacks, and that the file corpus behind the readers is local.
- The README navigation names the live example as an HTML report.

## 0.30.7 - 2026-09-18

### Changed

- The README masthead gives the product name more visual weight with a theme-aware wordmark, sets the local evidence statement in italics and links directly to the live example report.

## 0.30.6 - 2026-09-18

### Changed

- The README restores the full-size masthead tagline, connects its three concepts as an investigative sequence and adds a concise statement of its local, evidence-linked approach.

## 0.30.5 - 2026-09-18

### Changed

- The README masthead now separates the mark from navigation with whitespace, sharpens the text hierarchy and gives each status badge a distinct semantic colour.

## 0.30.4 - 2026-09-18

### Changed

- The README masthead restores the mechanically checked format count, removes the rule through the mark and gives the mark more horizontal space.

## 0.30.3 - 2026-09-18

### Changed

- The README status badges sit above the masthead, with more space between the mark and the product text.

## 0.30.2 - 2026-09-18

### Changed

- The README masthead places the mark beside the product name, positioning and status badges, with the section navigation beneath them.

## 0.30.1 - 2026-09-18

### Changed

- The README opens with the new mark, a plate filled with hex rows, in a version for each theme; the files are in `assets/`.
- The project lives under the renamed GitHub account `osintshifu`; every link, the package metadata and the example report address follow it.

## 0.30.0 - 2026-09-18

### Added

- MP4 and MOV: the `mdta` keys a phone writes are read, so a clip from an iPhone names its make, model, system version, creation time with its zone and location, and any other key is kept under its own name. Every track is listed with its handler, format and language, and a timecode track is noted.

## 0.29.0 - 2026-09-18

### Added

- Office packages: every relationship that points outside the package is listed, such as a template on a share, a linked workbook or a hyperlink, and DDE field instructions are reported as written. Both are observations; nothing is classified.
- PDF: each incremental update says which objects it replaced and which it added, so a document edited after it was signed shows what the edit touched.

## 0.28.0 - 2026-09-18

### Added

- Content Credentials are read from every container the tool already parses: TIFF and the raw formats built on it, WebP, WAV and AVI, MP4, MOV, M4A, HEIF and AVIF, and MP3. The record says which structure carried the manifest. The hard binding is checked where the manifest hashes the file's bytes; the binding used by MP4 and MOV is not computed, and the record says so by staying silent about it.

## 0.27.0 - 2026-09-18

### Added

- Files inside archives are files of their own: a member that carries evidence is reported with its own size, time, hash and evidence, the archive as its parent, and the archive's origin inherited as its own. Scan JSON names the `parent` and `member` of such a file.
- Evidence records say where in the file they were read from: the `where` of a record names the package part, the archive member or the document object, in scan JSON, in `explain` and in the HTML report.

### Removed

- The `archive-content` source. What a member said about itself was restated as metadata of the archive; it is now the member's own record.

## 0.26.0 - 2026-09-18

### Added

- PNG: the `eXIf` chunk is read, so a screenshot or a phone picture saved as PNG names its camera and capture time.
- Vorbis comments in Speex and Ogg FLAC streams, which carry no marker in front of the comment header.

### Fixed

- Firefox downloads were counted twice when the download had metadata, which doubled the timeline and forged an agreement between two copies of one record.
- A `docx`, `xlsx` or `pptx` with an encrypted member crashed `clean` instead of being declined.
- The macOS quarantine attribute was reported as a name match; it is an attribute of the file and is now marked as one.
- A PNG `Creation Time` in RFC 1123 form is read as a moment instead of being copied raw.
- A file reporting a creation time seconds after its download is no longer a timeline conflict; two clocks are allowed five minutes of skew.
- An IPTC datastream typed LONG in a TIFF was cut to a quarter of its length.
- A PDF page tree deeper than the interpreter's stack no longer raises; it is walked with a stack of its own.
- The recently-used list keeps a timestamp's own offset instead of stamping a Z onto it.
- `summary.with_origin` in scan JSON counts files with an origin record, not files with any evidence.
- The archive read budget bounds the members opened, not the findings kept.

## 0.25.3 - 2026-09-18

### Changed

- README rewritten around the investigative questions the tool answers: evidence model, match basis, worked investigation shapes, one section per evidence family, exit codes and JSON recipes.
- HTML report: the tab icon follows the accent colour.

## 0.25.2 - 2026-09-18

### Changed

- HTML report: a calmer blue accent, with the metadata category moved to indigo so the two stay apart; larger navigation links and summary cards, whose titles wrap instead of being cut; files and findings that need attention are labelled "needs review".

## 0.25.1 - 2026-09-18

### Changed

- HTML report: the masthead opens with the scan's facts, the mark beside them at their height, and the name as a small line above.

## 0.25.0 - 2026-09-18

### Added

- HTML report: a timeline of dated records, with a density strip that narrows the list to one period.
- HTML report: a picture of the evidence graph with pan, zoom, fit and SVG export; a node's details list what it is connected to, link to the files and open its pivot; the relationship table has its own filter and sort.
- HTML report: every table copies as tab-separated text; a floating button returns to the top.

### Changed

- HTML report redesigned: numbered sections, icon controls in the navigation, tighter hierarchy, corners and rhythm.

### Fixed

- PDF metadata: an incremental update now uses the current referenced Info dictionary instead of a superseded one left in the file.
- WOFF metadata: declared table and metadata lengths are bounded before their payloads are read.
- Timelines: timestamps with different UTC offsets are ordered by their actual instant and displayed consistently in UTC.

## 0.24.0 - 2026-09-18

### Added

- HTML report: relationship explorer with node search, concise notes, a detail block with every decoded field for every file with evidence, a print layout that keeps tables and evidence, coverage placed before the files, the system colour scheme by default.
- Web documents: Open Graph, JSON-LD, Microdata and RDFa.
- OLE: storage timestamps and CLSIDs, VBA and XLM indicators, Packager paths, orphaned entries.
- JPEG: JFIF, JFXX and ICC profile; Photoshop image resources.
- C2PA: actions and ingredients from the active manifest.
- PDF: incremental updates, trailer IDs, encryption, attachments, actions, forms, link targets and signatures.
- PE executables: headers, PDB records, Rich header, version resources, Authenticode presence.
- Fonts: `name`, `head`, `OS/2` and `fvar` tables, WOFF metadata.
- AIFF chunks and APEv2 tags.
- GoPro `udta` atoms and GPMF or CAMM telemetry summaries in MP4 and MOV.

## 0.23.0 - 2026-09-18

### Added

- Evidence graph in scan JSON, with GraphML and CSV exports.
- Run options and evidence coverage in JSON and graph exports.

### Fixed

- Bounded decompression in compressed parsers.

## 0.22.5 - 2026-09-16

### Added

- **A roadmap.** `ROADMAP.md`, linked from the README, lists the planned work
  in order: relationships between files and identifiers backed by evidence,
  their export as GraphML and CSV for graph and link-analysis tools, a
  relationship view in the HTML report, and export as CASE JSON-LD.

## 0.22.4 - 2026-09-16

### Changed

- **The README is reworded.** Its sections, format tables and examples stay as
  they were, and the descriptions are rewritten in plainer, shorter sentences.

## 0.22.3 - 2026-09-16

### Changed

- **`--content` is shown as an addition to `--pivots`.** The examples in the
  README, and those `filegrail` prints when run with no arguments, read
  `--pivots --content`, and `--help` says what it adds: it also looks for
  pivots in the text of supported documents. `--content` on its own still turns
  `--pivots` on, so existing commands give the same results.

## 0.22.2 - 2026-09-16

### Fixed

- **The logo at the top of the README is larger, and not only wider.** The
  vertical lockups filled half of their canvas, so widening the image in 0.22.1
  mostly widened the margin around it. They are framed by their clear space
  now, half the height of the mark on every side, and the name in the README
  logo comes out about 300 pixels across, where it was about 175.

## 0.22.1 - 2026-09-16

### Changed

- **Every release is published on GitHub, with its changelog section as the
  notes.** The releases page stopped at 0.3.0 and went on calling it the
  latest; every version since has a release there now.

### Fixed

- **The logo at the top of the README is shown at a size that reads.** The
  lockup sits on a wide canvas, and at the width it was given the name came out
  about a hundred pixels across.

- **The line under the package name on PyPI says what the README says:**
  "Trace file origins. Extract metadata. Find investigative pivots."

- **The version badge names the version released.** It asked PyPI at view
  time, and the image proxies of GitHub and PyPI kept the answer, so a new
  release page could show a version several releases old.

## 0.22.0 - 2026-09-16

### Added

- **A PDF span that states its own text is read as that text.** A browser
  printing to PDF draws the hyphen in an invoice number or a postcode with an
  alternate glyph that its font maps to nothing, and says in the span around
  it, with `/ActualText`, that the glyph is a hyphen. Read through the font
  alone, such a number came back as two values, neither of which is on the
  page. What the span states is what is read now.

### Changed

- **New logo and pictograms.** The HTML report draws the new mark in its
  masthead and tab icon, and the README shows the compact vertical lockup.

- **The README is reorganized around what a reader comes to find:** a quick
  start, what `filegrail` reads and from where, the formats, the pivots, the
  commands with common tasks, and `jq` examples for the JSON. The rules for
  what each pivot type takes and leaves out moved to `docs/FORMATS.md`.

### Fixed

- **A PDF that places every glyph itself reads as words.** A browser printing
  to PDF draws each glyph alone and moves the pen by its width, and every move
  was being taken as a line break, so an address came back one letter a line
  and invoices and receipts yielded none of their identifiers. The gap between
  glyphs is measured now, from the widths the font states: no gap joins them,
  a word's gap is a space, and anything else is a new line. A gap that cannot
  be measured, in a font that states no widths, is still a break. Measured
  against `pdftotext` on eighteen real documents, the identifiers found went
  from 22 of 35 to 31, and the one invented value is gone.

- **A simple font is read one byte at a time, whatever its `/ToUnicode`
  declares.** A publishing tool can give a TrueType font a map written with
  two-byte codes, and the text was being read in pairs, which lost every
  letter the font drew - in one document, the whole page footer with its
  email address and phone number.

- **The README no longer lists RTF `\info` fields.** They were never read; the
  RTF reader takes the application that wrote the file.

## 0.21.1 - 2026-09-16

### Fixed

- **A PDF that names its own glyphs no longer loses every accented letter.**
  A font that lists its encoding names them `oacute`, `zdotaccent`, `Lslash`,
  and only the unaccented ASCII names were being resolved - so a Polish
  document came back with its accents dropped and `Łódź` read as `d`. That is
  not a letter missing from a word, it is a different word, and the detectors
  that look for a person or an organisation were being handed it. A glyph name
  is resolved through the mark it spells now: a table of the accents, rather
  than of the thousands of letters they make.

## 0.21.0 - 2026-09-16

### Added

- **`--content` reads a PDF.** It was the one format the option refused, on the
  grounds that pulling the string literals out of a content stream gives
  readable text for about half of real documents and mush for the rest. That
  was an estimate, and measuring it found something else: the naive pull fails
  not because a PDF is unreadable but because it reads the wrong bytes - font
  programs instead of page content, and one byte at a time where a composite
  font is shown two.

  A PDF stores instructions rather than text, and the bytes in them are indices
  into whatever encoding each font happens to use. So every run is decoded
  through the font that draws it: the `/ToUnicode` CMap where the writer
  supplied one, a named encoding or `/Differences` otherwise, and printable
  ASCII for a font that states neither. A font whose glyphs resolve to nothing
  is skipped rather than read as bytes, and an encrypted document is refused,
  because the failure worth avoiding here is not unreadable prose - it is an
  address assembled out of the wrong glyphs. Dropping a run costs a lead;
  inventing one costs the investigation.

  A value is reported against `page 7`. A PDF records its pages as structure,
  which is why a page can be named here and cannot in a word processor's
  document, where pagination happens when something renders the file.

## 0.20.2 - 2026-09-16

### Fixed

- **Three things the README said about a scan document that were not so.**
  `unsearched` was listed as a key that appears when it is asked for, and it
  is in every document; `home` was listed as one that is always there, and it
  appears only when the scan read another profile; `schema` and
  `filegrail_version`, the first two keys of every document, were not listed
  at all. Each optional key now names the option that produces it, which is
  the question a reader had to answer by running the command twice.

- **The list of what correlation can report was missing one of the conflicts
  it reports.** A file stating that it was created after it arrived here has
  been a `timeline_conflict` since the first release, and the one list a
  reader checks to find out whether the tool would catch it did not say so.

- `CONTRIBUTING.md` now asks for `mypy`, which CI has had a job of its own
  for, and names the extra and the command behind the run against generated
  input. Following the file as written left a contributor with a red CI and
  nothing to have warned them.

- The lineage spec described a `Lineage` value per file. Nothing by that name
  was built: the identifiers are read back out of the records, and `Link` is
  what the module carries.

## 0.20.1 - 2026-09-16

### Fixed

- **The published example report no longer describes the machine that built
  it.** The page is built from an invented case, and its evidence coverage
  section was the one part of it that was not invented: it reported on the
  developer's own profile - which browsers were installed, how many profiles
  each had, how many files the desktop had opened lately, and the day the
  oldest trace on it was written. The builder now writes a profile of its own
  beside the case and scans with `--home`, so the coverage table is read from
  something invented too. Nothing in that profile names a file in the case, so
  the page reports the same files, findings, conflicts and pivots it did
  before, and two builds of it now differ only in the moment they were made.

## 0.20.0 - 2026-09-16

### Added

- **A file whose bytes are not the format its name claims now says so.** Every
  scanned file whose extension `filegrail` has an expectation for is read a few
  bytes deep, and where the format written there is not one that extension
  carries, the file gets a `file signature` record naming both, and the files
  it happened in are listed together under the key findings. A document that
  opens as an executable and a photograph that is really a PDF are each one
  rename away from looking ordinary in a file listing.

  Only the disagreement is recorded. A format written under several names is
  not one - a `.docx`, an `.epub` and a `.jar` are all zip archives, and each
  carries one legitimately. Neither is a file whose bytes match nothing here,
  nor an extension nothing here expects anything of: there is no claim to
  contradict, and saying so of every plain-text file in a directory would be
  noise standing in for a finding. Which formats are recognized, and which
  extensions carry each of them, is in `docs/FORMATS.md` and held against the
  reader by a test.

## 0.19.1 - 2026-09-16

### Fixed

- **The one worked `jq` example in the format reference named a key that has
  not existed since 0.8.0.** `.files[].origins[]` is `.files[].evidence[]`,
  as the schema table in the README has said all along, so a reader who
  copied the line got an empty result and no reason for it.

## 0.19.0 - 2026-09-16

### Fixed

- **A file that describes itself is no longer refused the origin of the
  archive it came out of.** The check was written to stop a known origin
  being overwritten by a second-hand one, and it read that way while the
  records it looked at were origins. When that collection widened to carry
  metadata and activity too, the check came along unchanged and quietly began
  to mean "nothing at all is known about this file". A photograph with EXIF
  has said where it was taken and still not said how it got here - the one
  question the archive could answer, for the one file the pass skipped.

- **A table is read a cell at a time.** A `.csv` or `.tsv` row read as one
  line runs its columns together, and a value at the end of one took the
  separator and the column after it: a URL arrived in the report with
  `,publisher` on the end, which is a value nobody can go and look at. The
  place says the row and the column now, rather than the line.

- **A block that contradicts itself no longer names itself on both sides.**
  Where one block records both when a thing was made and when it was changed,
  it stands on both sides of its own disagreement, and the report said `PDF
  Info is 2 hours earlier than PDF Info`. The two sides take the names of the
  fields now, which is what actually differs between them.

### Changed

- **The README no longer counts the formats.** A test held the badge to the
  readers, so the number could not drift, but the tables under it already say
  which extensions have one. `docs/FORMATS.md` states the count for a reader
  who wants it, and the test that holds it to the readers is still there.

## 0.18.1 - 2026-09-16

### Fixed

- **A manifest's claim that a model made the file is no longer shown without
  saying the signature was never checked.** The note was on the record and
  reached the terminal and the JSON, but the finding built its own rows and
  left it behind, so the HTML report carried the claim alone. The finding is
  `Declared AI-generated source` now, and it says `signature: not verified`
  beside the source type. The tool validates no certificate chain, and the
  report that travels furthest should be the last place to forget it.

### Changed

- The brand artwork no longer carries the C2PA manifest it was exported with.
  It was nine tenths of every SVG, and a repository is its own provenance for
  its own logo. Every drawing renders exactly as before.

## 0.18.0 - 2026-09-16

### Changed

- `--identify` is now `--pivots`, the name the report already uses for what
  it extracts, and the one its options line already printed. The old spelling
  still works and no longer appears in `--help`.
- The mark sets a diamond where it set a four-pointed star, and the README
  opens with the vertical lockup. The HTML report draws the new mark in its
  masthead and its tab icon; `assets/` carries the full set, in PNG and SVG.

## 0.17.1 - 2026-09-16

### Added

- An example report is published with the project and linked from the README:
  https://osintshifu.github.io/filegrail/example-report.html. The case it
  reports on was invented for it: photographs that share one camera body,
  documents that share an author, a PDF whose Info dictionary and XMP packet
  disagree about when and by what it was made, an image whose Content
  Credentials name a generative source, and a download that still carries the
  address it came from. No real file is reported on, because a report carries
  the names, addresses and paths of the files it reads.
  `tools/build_example.py` writes the case and renders the page, so a later
  version can be shown the same way.

### Changed

- The README leads with the project's lockup, which follows the reader's
  theme, and the banner it used to carry is now what GitHub shows as the
  repository's social preview.

## 0.17.0 - 2026-09-16

### Added

- `-o FILE` writes the report to a file rather than to standard output, in
  every form the scan prints: the terminal report, `--json` and `--html`. The
  HTML page then names the file it is, beside the target it was made from.

### Changed

- The HTML report is laid out in the project's own visual language: the mark
  and the wordmark in the masthead, under them the target, the profile, the
  scan and the options it ran with, set off by a rule; a menu bar that stays
  in view and follows the section being read; summary cards over a legend of
  the three evidence categories; and a file index that gives each file a dot
  per category, its type, size and modification time, and the origin record
  with the basis it was matched on. It still loads nothing from outside
  itself: the mark in the masthead and the tab icon are drawn in the page.

- The HTML report carries a light theme on a button, next to one that prints
  it. `Expand all` sits on each section that has something to open, and opens
  and closes only that section; a file that wants a second look starts open.

- Chips over the file index leave only the files a filter names, and the
  search box takes `/` from anywhere on the page. The pivot tabs wrap onto as
  many rows as they need, so a case with many types keeps none of them behind
  a scrollbar.

- A pivot names the first few files it was found in and keeps the rest behind
  `+N more`; the sample of where it was found now comes before that list, so
  the long column no longer starves the short one of width. Each file it
  names takes a line of its own, and what opens the rest - the `+N more` in a
  pivot, the file count in a key finding - carries the accent colour. The
  two count columns are headed `times` and `places`,
  which gives their width back to what is actually read.

- The places a pivot was found in are grouped by file and by source, so a
  value sitting five times in one file reads as one line carrying the five
  line numbers, rather than five lines that differ by a number. Eight of the
  twenty places a pivot keeps are shown, which after grouping takes fewer
  lines than five took before.

- More of the report leads somewhere: the pivot types found in a file link to
  the tab that lists every pivot of that type, a conflict links to the record
  that carries it as well as to the file's row, and a summary card is a link
  or it is not shown at all. The file index column that held both is named
  `findings & pivots`.

- A file's number and its name are one link, and a list a key finding folds
  away opens as a column, one file to a line. Once the masthead has scrolled
  out of view the mark appears in the menu bar and leads back to the top.

- The HTML report's notes no longer repeat how to read the report, and no
  section introduces itself. What each evidence category and each match basis
  means stays.

## 0.16.0 - 2026-09-16

### Changed

- The terminal report runs in the order of the HTML one - summary, key
  findings, files, investigative pivots, file detail, evidence coverage,
  conflicts, report notes - and says of two conflicting dates which one is how
  much earlier, in place of a bare delta. `CASE SUMMARY` is `SUMMARY`.

### Added

- `--html` prints the investigation report as one self-contained HTML page,
  for a scan of a directory or of a single file: the same sections, numbers
  and findings as the terminal report, with every number an anchor to click
  through, a search box and a filter for the files to review. It is dark and
  prints light. A Content-Security-Policy allows no network request, nothing
  is loaded from outside the page, a URL found in a file is text rather than a
  link, and every value that came out of a file is escaped.

- In the HTML report every table sorts by any column, sizes and counts by
  their value; a summary card opens the section it counts, with the file index
  filtered to the files it counts; and a copy button beside a path, a pivot, a
  conflicting value or a field copies the text shown, without opening it.

- The HTML report lists every investigative pivot, one tab a type, with the
  files each was found in as links and a sample of where, and says of two
  conflicting dates which one is how much earlier. Its sections run summary,
  key findings, files, pivots, file detail, evidence coverage, conflicts.

## 0.15.0 - 2026-09-16

### Added

- A Content Credentials record carries the claim generator, the software
  agent and the digital source type as fields, under the manifest's own
  names, rather than only inside its note.

### Changed

- A directory scan prints an investigation report. It opens with a case
  summary and the key findings the records establish together - AI-generated
  media, files that contradict themselves, files created at the same second,
  shared authors and camera bodies, GPS, files nothing was found for - then
  what this machine could be searched for, each conflict with both values and
  how far apart two dates are, a file index, the investigative pivots found in
  more than one file or crowded into one, and the detail of the files that
  need it. Files, findings, conflicts and pivots are numbered (`#001`, `F01`,
  `C01`, `P01`) and point at each other. A single file, `--timeline` and
  `--json` are unchanged.

- `-v` opens every file in the report, with every decoded field and the full
  pivot lists, and `--limit` shortens the list of files nothing was found
  for; neither changed the report before. `--brief` stops at the summary, the
  findings and a one-line index.

### Fixed

- The time a PDF says it was created is read with its UTC offset. A
  `CreationDate` of `D:20110224082252-07'00'` was placed on the timeline at
  08:22 UTC, seven hours early, and beside the XMP copy of the same instant
  it read as a different time.

- The number of files an identifier was found in counts every file. It was
  counted from the twenty places kept as a sample, by file name, so an author
  named in 28 files was said to be in 17, and two files of one name in two
  folders were one.

- `--cluster` groups one name written in two cases as one: `iSamples Team`
  and `iSamples team` were two authors of three files each rather than one
  of six.

- The last editor an Office 97-2003 document names in its summary,
  `LastAuthor`, is read as a person, as `lastModifiedBy` already was in the
  formats that replaced it.

## 0.14.0 - 2026-09-15

### Added

- `hostname` for the names of machines and servers no public DNS answers
  for: the machine a Windows shortcut was created on, the server in a UNC
  path and the hosts at either end of a `Received:` hop. A server in a UNC
  path that has a public name is now a `domain`.

- `ltc`, `doge`, `bch` and `xmr` for Litecoin, Dogecoin, Bitcoin Cash and
  Monero addresses, each believed only when its own checksum holds:
  Base58Check with the version byte naming the chain, Bech32 for `ltc1`,
  CashAddr's forty-bit polynomial, and Keccak-256 for Monero. A `3` address
  stays a `btc`.

- `sha512` for 128 hexadecimal digits, `cwe` for weakness ids and `ghsa` for
  GitHub security advisories.

- `message_id` from the `Message-ID`, `In-Reply-To` and `References`
  headers, so a saved reply and the message it answers turn up under one
  value.

### Changed

- `handle` takes the owner of any GitHub repository or raw-file URL, not
  only of a profile page.

## 0.13.1 - 2026-09-15

### Changed

- The readme is reorganised around the three categories of evidence and the
  investigative pivots a scan can extract, with a table of the questions each
  kind of evidence helps answer. No format, source, option, match basis or
  schema fact changed.

- The privacy note names every class of value a report may carry, vehicle and
  company registration numbers among them, and says that `--redact` removes
  credentials rather than every sensitive value.

- The limits say that C2PA certificate and signature trust is not verified,
  that a name-and-size match or a recorded author is not proof, and that no
  external service is queried.

## 0.13.0 - 2026-09-13

### Added

- `eth` for Ethereum addresses. A mixed-case address carries its checksum
  in the case - EIP-55 - and has to pass it; that takes a Keccak-256, which
  `hashlib` does not have (its SHA-3 pads differently and answers
  differently), so the sponge is forty lines of standard library. An
  address written all in one case carries no checksum and is taken by its
  shape.

- `vin` for vehicle identification numbers: bare when the North American
  check digit holds, and beside a `VIN` label as written, because Europe
  never required the digit and a real European VIN fails it.

- Registry numbers beside their label, none of which carries a checksum:
  `crn` for a UK company registration number, `cik` for a SEC filer id, as
  one number however many zeros a filing pads it with, and `vat` for an EU
  VAT id whose country is one - a Polish one being a `nip` already. And
  `asn` for autonomous system numbers, leaving out the product line and the
  quality standards spelled the same way.

## 0.12.1 - 2026-09-12

### Fixed

- `--redact` left a private key block in the output - the one credential
  that is nothing but its body. The body is now replaced by its
  fingerprint and the armour lines stay, so a reader still sees that a key
  was there. The same rule serves the `secret` identifier.

- `--redact` knew a Stripe secret key by its OpenAI spelling only. It now
  knows Stripe's live and test keys, npm, Hugging Face, Shopify, SendGrid
  and Twilio tokens and Telegram bot tokens by their shape, and so does
  the `secret` identifier, which reads the same list.

## 0.12.0 - 2026-09-12

### Added

- Two more things an incident report is made of: `path`, where a file sat
  on a Windows machine - a drive letter, an environment variable or a UNC
  share, which names a host - as one value however it is cased; and
  `executable`, the bare name of something Windows will run, on its own or
  inside a path or a URL. POSIX paths are not taken, a slash being in every
  URL and every fraction, and neither is anything ending in `.com`, which
  every domain does.

## 0.11.0 - 2026-09-12

### Fixed

- The text report printed only the identifier types it had always known -
  urls, domains, emails, ip addresses, coordinates and the three digests -
  and silently dropped every type added since: a wallet address or a
  person's name reached `--json` and not the page. Every type present is
  now printed, the known ones under their heading and any other under its
  own name, so a type can no longer go missing without a test noticing.

### Added

- Indicators a report of an incident is made of: `cve` ids, `registry` keys
  under any hive as one key, and IPv6 addresses in the two spellings that
  cannot be mistaken for code - all eight groups written out, or inside the
  brackets a URL puts round one. A digest written as colon-separated pairs,
  the way a certificate fingerprint is shown, is the same value as the bare
  spelling and folds into it.

- A digest that is the digest of an address seen in the same scan is named
  for it, in the report and as `of` in `--json`. A list of hashed addresses
  is how advertising platforms and Gravatar carry an address without writing
  it, and one address in the clear beside the list names an entry of it with
  certainty.

- The United States numbers: `ssn`, `ein` and `aba`. None can be trusted on
  its own - two have no checksum and the routing number's passes one random
  number in ten - so each is taken only beside the label that names it, and
  the shape has to be one that is issued: a social security area that exists,
  an employer prefix the IRS assigns, a routing prefix a bank can have. A
  social security number is the key to somebody's identity and is reported
  the way a credential is, as a fingerprint and never as the number.

- A `tracker` identifier type for analytics, tag-manager, advertising and
  affiliate ids - the same one on two sites is one owner. Those with a
  prefix of their own (UA-, G-, GTM-, AW-, DC-, pub-, pk_live_) are taken
  wherever they stand; a bare number only beside the service that issued it
  (Facebook Pixel, Yandex Metrica, Amazon Associates, Hotjar, Clarity). The
  snippets live in `<script>`, which the content reader leaves out; the ids
  survive in the loader and tracking-pixel URLs a page carries, which it
  keeps.

## 0.10.0 - 2026-09-12

### Added

- Four identifier types with a shape of their own: `onion` for version 3 Tor
  addresses, checked by their checksum; `mac` for hardware addresses in
  either spelling, reported as one value; `sid` for Windows account and
  group SIDs, leaving out the short well-known ones that name nothing in
  particular; and `bic` for bank identifier codes, which have no checksum
  and are taken only beside a `BIC` or `SWIFT` label.

- A `secret` identifier type: the API keys and tokens `--redact` already
  knows by their vendor prefix, JWTs, and private key blocks. A credential in
  a document is a finding, and a report that leaves the machine must not
  become the place it was copied to, so each is reported as its kind and the
  fingerprint redaction writes, never as the value. Every private key opens
  with the same line, so key blocks are one fact with a list of places.

- Three identifier types for who a file says made it. `person` is read from
  the fields whose name says so - an author line, a by-line, an artist tag,
  the display name on a mail header - and never from the text of a document,
  where a capitalised pair of words is a name, a town and a sign-off in equal
  measure. `org` is the company or credit a file records. `handle` is an
  account a file points at: the user in a profile URL on a known platform, or
  the login in a user directory the file carries in a template path or a
  recorded location. One spelling of a name is one entry; two spellings stay
  two, because deciding they are one would be guessing.

- The one way a name is read out of a document's text: when the text itself
  labels it. A name ending in a legal form - Sp. z o.o., GmbH, Ltd, Inc, LLC -
  is an `org`; a name after an honorific - Pan, Pani, Mr, Mrs, Dr, Prof - is a
  `person`; a Polish postcode with its town, or a UK postcode by its shape, is
  a `postcode`. Recall is low by design, and a capitalised pair of words on
  its own is still never believed.

## 0.9.0 - 2026-09-12

### Added

- Identifier types that carry their own checksum: `btc` for bitcoin addresses,
  legacy and `bc1` alike, `iban` for bank accounts, and the Polish `nip` and
  `regon`. One changed character fails the check, so a match is believed
  without a region hint. The tax numbers are the exception and are taken only
  beside their label or behind the `PL` of an EU VAT id: their check digit
  passes about one random number in eleven, and ten bare digits in a document
  are an order number far more often than a taxpayer. The arithmetic is the
  standard library, in `checksums.py`.

- `--content` reads track and map files - `.gpx`, `.kml`, `.geojson` - and
  reports the positions they carry as structure: every named point, and the
  start and the end of every track or line, since a track is thousands of
  points and a report is not the place for them. Each is written as a `geo:`
  URI, the one spelling the coordinate detector takes on its own, so a bare
  pair of decimals in a document is still never believed. KML and GeoJSON
  put the longitude first; the reader turns them around. `.graphml` and an
  Obsidian `.canvas` are read as the markup and JSON they are.

- `--content` reads a Gephi `.gexf` and a FreeMind `.mm` for the text a node
  keeps in an attribute, and three more packages: a `.kmz` for the map inside
  it, an `.xmind` for its topics, and a Maltego `.mtgx` for every graph it
  exports, entities and values included.

## 0.8.2 - 2026-09-06

### Changed

- The readme is rewritten. The description in front of every table is shorter
  and says what a reader gets. The capability table and the exit-code row say
  the same things in fewer words. No format, source, option, match basis or
  schema fact changed.

- The eleven folded terminal views were removed from the readme.

- The capability table no longer says how many identifier types there are. The
  count goes stale as types are added, and nothing fails when it does.

## 0.8.1 - 2026-09-06

### Fixed

- The readme described a report the tool no longer prints. The eleven folded
  views had been regenerated, but the sentence under each one still explained a
  strength meter that no longer exists, a `FILES IN DETAIL` section, an
  `EVIDENCE SOURCES` table, a corpus word beside every identifier, and an
  assessment `explain` no longer writes. `compare` had no caption at all.

- It listed `filegrail.scan/1` where the tool stamps `/2`. That is a contract a
  consumer would have believed. The schema list is a table now: which version
  each document is on, and what changed in it.

- The table of match bases printed the prose form - `read from the file` -
  where the report and `--json` both write `embedded`. A reader looking up what
  they had just seen would not have found it. Those prose labels had no other
  caller and are gone.

- The opening said `filegrail` combines *two* sources of information and named
  the machine's traces and the file's metadata. With `--content` it reads a
  third: the text inside the document, which is where an address in a letter
  comes from. Three now, named for what they are, with a sentence separating
  them from the three categories below - a shell command that fetched a file
  and one that merely opened it come from the same place and say different
  things.

- The third of those said what happens to the text and not what happens to
  what is in it. It names the identifier extraction now, and the types, and
  what the pairing is for: an address written in a letter matched against the
  address the file was fetched from.

- Five passages explained a design decision, compared the page with an earlier
  version of itself, or commented on the tool instead of saying what it does.
  A readme says what happens; why it happens that way belongs in
  `docs/DESIGN.md`.

## 0.8.0 - 2026-09-06

### Changed

- **Every report is rebuilt around one grammar.** A heading in capitals with
  its own counts beside it, a table with named columns and a rule the width of
  each one, `›` opening a record whose fields hang underneath it on `│` and
  `└`. `!` means one thing - this wants a second look - and `·` means one
  thing - nothing was found here. Eleven views that had grown their own shapes
  now read the same way, and a section with nothing in it is not printed.

- **A scan reads: summary, files, origin, metadata, activity, findings,
  relationships, unresolved.** The tally of what was read and the list of
  parsers that returned something are gone; every count in a heading is now of
  rows a reader can see underneath it. `INVENTORY` is gone with them - the type
  is a column in the table of files, where it can be compared.

- **The files nothing explained are `UNRESOLVED`,** a section of their own with
  the size and the last modification of each. They used to be a capped list at
  the end of the index.

- **`explain` shows the material rather than a reading of it.** The prose
  assessment was this tool's opinion; the command exists to show what an
  opinion would rest on. The sentences are still in `--json`.

- **`--timeline` drops the files nothing dated.** Nothing happened at a time
  nobody recorded, and a row for it was a date invented to fill a column. Each
  event now names what happened: captured, downloaded, delivered, extracted,
  opened, deleted.

- **Identifiers are grouped by type** - urls, domains, emails, ip addresses,
  coordinates, hashes - one row per place a value was seen, with the file, the
  source and the field it came from. Values seen under more than one source get
  a section of their own. A value too long to sit beside its columns takes the
  line instead of being wrapped into slivers.

- **The landing screen is the mark, and then things to type.** Twenty-three
  examples grouped by what is being asked about - a file, a directory, a kind
  of file - and the format and evidence-source lists it used to carry are in
  the readme and in `doctor`, where the question has been asked.

### Changed

- **The vocabulary is the industry's rather than this project's.** `filegrail`
  described a file's history in words it had defined for itself, and two of them
  collided with settled meanings. `acquisition` in digital forensics is the
  examiner taking custody of material - disk imaging, memory capture, a forensic
  copy - and using it for "a browser downloaded this" put the tool at odds with
  every reader who already knew the word. Provenance is now the subject, and
  under it a record answers one of three questions: **origin**, **metadata**,
  **activity**.

- **The central record is `EvidenceRecord`, not `Origin`.** One class carried a
  download row, a camera's EXIF and a trash record alike, and `FileRecord.origins`
  said all three were statements about where the file came from. They are
  `FileRecord.evidence` now, and each one carries its own `category`.

- **Every record says how it was matched to its file.** A download row found by
  path and one found by a name that happened to be the same are not equally
  firm, and the difference used to live in an English sentence that correlation
  had to read back with a substring search. It is a field: `recorded path`,
  `file name`, `name+size`, `container member`, `sidecar`, `file attribute`,
  `read from the file`, `inside a sync folder`. The size comparison behind a
  name match is now made against the file on disk rather than inferred from
  prose.

- **The confidence number is gone from everything a reader or a consumer sees.**
  There was never a statistical basis for `55`, and printing it as a five-block
  meter put "a browser wrote this down as it happened" and "a camera described
  itself" on one scale as more and less of the same thing. What remains is
  `SOURCE_PRIORITY`, which decides which record a one-row summary shows, is
  never printed and is never exported. Where the meter used to sit, the report
  prints the match basis.

- **`recorded / inherited / credentialed / self-reported / circumstantial /
  faint` is gone too.** Those six words described six unrelated properties - how
  a record was made, what it inherited, which standard signed it, what kind of
  inference it rests on - and stacking them as levels of one strength said they
  were comparable. Colour is now keyed by category, so it says which question a
  record answers and nothing about how much it is worth.

- **`Verdict` is `CorrelationResult` and `reconcile()` is `correlate()`.** The
  code deliberately does not decide which record is true, so it should not
  return something called a verdict. `conclusion` is `assessment` for the same
  reason.

- **`finding` means the result of an analysis.** A conflict, a corroboration, an
  impossible ordering. The presence of EXIF is not a finding, so the section
  that counted those is `SUMMARY`, `overview.findings()` is `overview.summary()`,
  and a file nothing was found for is reported as `no evidence found` rather
  than `no findings` - which never meant the file has no provenance, only that
  the supported sources held nothing that explains it.

- **Two sources were classified wrongly and are reclassified.** `filesystem`
  timestamps were `acquisition`, so every unexplained file looked as though
  something had explained how it arrived; they are `activity`. `email-relay`
  describes the transport of a message rather than the origin of the file, and
  is read as `metadata` alongside the other headers.

- Camera bodies, models and authors are `SHARED ATTRIBUTES` rather than
  `shared sources`: a source is an artifact or a parser, not a person or a
  device.

### Breaking

- `--json` documents change shape. `scan`, `explain` and `compare` are stamped
  `filegrail.scan/2`, `filegrail.explain/2` and `filegrail.compare/2`; `doctor`
  and `clean` did not change and keep `/1`.

  | was | is |
  |:---|:---|
  | `files[].origins` | `files[].evidence` |
  | `origins[].confidence` | gone; `evidence[].category` and `evidence[].match` |
  | `reconciliation` | `correlation` |
  | `conclusion` (explain) | `assessment` |
  | `acquisition` (compare) | `origin` |
  | `shared_sources` | `shared_attributes` |

## 0.7.0 - 2026-09-05

### Changed

- The report names things the way a person would, everywhere. A table now
  carries the names of its columns and a thin rule under each one; the index
  prints what its three marks mean above the rows rather than expecting them to
  be worked out; and the strength meter never appears without the word beside
  it, because five blocks are a shape and `direct` is what the shape means.

- The reader table gives way in a narrow window instead of running off the
  edge. The column's own name goes first - the rows still read under a shorter
  heading - then the meter, so at forty-eight columns what is left standing is
  the word that carries the meaning.

- A long identifier keeps its line. A URL is the thing this section exists to
  be pivoted on, and one broken inside a path segment to make room for the word
  `url` beside it cannot be copied out of a terminal at all, so the type moves
  down into the gutter with the rest of what is said about the value.

- `clean` names a stripped block the way the rest of the report does - `PNG
  text` rather than the `png-text` its JSON writes - and abbreviates the path it
  was pointed at, as every other command does.

### Fixed

- A file carried one mark in the index and a different one over its own entry:
  flagged as needing a second look in the table of contents, bulleted as
  ordinary two screens later. Both now come from one rule in one place, which is
  what the legend above the index promises.

- The `profile` row printed a path in full while the `target` row directly above
  it abbreviated one. Two paths in the same block, written two ways, read as two
  different kinds of thing.

- The sentence under `doctor`'s horizon - the one that says what a horizon is
  for - was cut off at the edge of the terminal, so it stopped mid-clause and
  explained nothing. It wraps.

- `clean` reported `1 files`.

- The paragraph that explains why nothing matched had its lines broken by hand,
  so the sentence carrying the machine's own counts ran past the edge of the
  window as soon as a profile held five or six figures of download history. It
  is wrapped like every other paragraph now.

- Two claims the readme made about reading mail were not what the reader does.
  `--content` reads every *text* part of a message, an attached text file
  included, and a message body reaches the report as `body` or `body (html)`;
  the page said attachments were not read at all and named only `body`. Both
  are now held against the reader by a test that takes the vocabulary out of
  the module rather than keeping a copy of it.

### Documentation

- The readme had two places about reading document content: a section of its
  own for the format table and another under Analysis for what is done with it.
  The table has moved in beside the other format tables as **Document content**,
  and what a reader most wanted from it - *which identifiers come out of that
  text* - is now a table of its own: six types, what each one takes and, as
  usefully, what it refuses.

- Every table on the page is introduced by a sentence saying something the
  table does not: that a torrent is matched by name *and* exact size, that
  `clean` needs `--out` or `--check`, that a format missing from the cleanable
  list gets no copy written at all.

- The word printed beside every claim in a report - `direct`, `inherited`,
  `credentialed`, `self-reported`, `circumstantial`, `weak` - was nowhere on
  the page. It is a table now, saying what each word means and which sources
  earn it, because a reader meeting `self-reported` in output has otherwise
  been asked to work it out.

- The largest table on the page, sixteen metadata blocks and their extensions,
  is checked row by row against the reader each row names - in both directions,
  like the content and cleanable-format tables already were.

- Exit codes are written down: `1` from `clean` means metadata survived in a
  copy, which is the whole point of running it in a pipeline.

## 0.6.1 - 2026-09-05

### Added

- Eleven example views in the readme, each folded: one file, a whole directory
  top to bottom, the index alone, two records that disagree, `explain`, a
  timeline, identifiers over document content, files sharing a camera, two
  files compared, what the machine can answer at all, and the check before
  publishing. Real output from real runs rather than written out, and folded so
  the page stays a reference that answers *does it read this* in one look, with
  the output a click away for anyone who wants to see the shape of it.

### Fixed

- The timeline broke a URL inside itself. The claim was aligned under the file
  name, which looked tidier and left it a column too narrow for an address, so
  anything longer was hard-broken mid-token - the third renderer with the same
  fault, after `explain` and the identifier table. Every claim gets the page
  now, in the gutter rather than under the name.

## 0.6.0 - 2026-09-05

### Changed

- The readme is a reference rather than a walkthrough. Tables of what the tool
  reads, from where, and out of which formats, in place of prose and worked
  examples: the question a reader arrives with is usually *does it read this*,
  and a table answers it in one look. The header and the badges are unchanged.

  Every extension in it is checked against the readers by a test, both ways -
  the content table against what `--content` reads and the cleanable-format
  table against what `clean` can strip - so a format added to either cannot be
  left out of the page, and a format named on the page cannot be one nothing
  reads. That is stronger than the count in prose it replaces, which could only
  say how many there were.

## 0.5.2 - 2026-09-05

### Fixed

- The disclosure summary in the readme carried a `▶` of its own beside the one
  GitHub draws, so the row showed two triangles. GitHub styles a `<summary>` as
  a list item with a `disclosure-closed` marker; the character was redundant
  everywhere it rendered.

- The diagram of the three classes had grown a third column and reached
  ninety-seven characters, which scrolls sideways on the second thing a reader
  sees. The examples it held are a sentence underneath it now, and no block on
  the page is wider than the seventy-two columns the tool itself lays out to.

## 0.5.1 - 2026-09-05

### Changed

- The inventory is a table, a row to a type. Three entries packed across a line
  - each of them three figures - was a jumble however the columns were headed:
  the reader had to work out where one entry ended before reading any of it. A
  row costs vertical space and gives back the thing a table is for, and it is
  the same table at forty-eight columns as at a hundred and ten, where the
  packed version dropped a column and read differently at each width. The
  families underneath get a table of their own, since they answer a different
  question from the extensions above them.

- The profile a scan read is a row of the banner. It is a fact about the scan
  like the target and the counts, and it used to sit under the rule as a
  sentence with no label - the one line in the report saying the evidence did
  not come from the machine the report was run on.

### Fixed

- The readme shows the tool working before it explains it. The first thing on
  the page after the badges is a command and its real output, with the argument
  for the three classes underneath rather than in front of it, and the whole
  report is one clearly marked fold rather than a section of prose about a
  fold. Every block on the page is generated by running the tool.

- The counts of supported formats in `README.md` and `docs/FORMATS.md` are held
  against the readers by a test. The tables could not drift, because they are
  parsed; the sentences beside them could, and `68 file extensions` would have
  gone on saying sixty-eight after the sixty-ninth was added. Both numbers are
  correct today - 68 read for metadata, 43 read as text - and now they cannot
  quietly stop being. The badge at the top of the readme is held the same way.

## 0.5.0 - 2026-09-05

The report was reorganised. Nothing about what filegrail reads or claims has
changed; what changed is the order it says things in, and how much of the page
it says them on.

### Added

- **An index.** A scan went from the overview straight into a block per file,
  so a reader learned which files were worth opening by scrolling the whole
  report - on a case directory, hundreds of lines, and no answer to the first
  question anybody asks. There is a `FILES` section now: one line a file,
  whatever needs a second look at the top, then the rest in the order they were
  walked, and `FILES IN DETAIL` below it.

  It abbreviates, and it is allowed to precisely because it is an index: every
  file in it is written out in full underneath. Nothing is truncated even so -
  a name too long for its column takes the width it needs and the columns
  follow it, which is what the list it replaces already did.

- **`EVIDENCE STATE` in `explain`**: one line per class of evidence, whether or
  not the file has any. An absent class is a fact about the file rather than a
  gap in the report - a photograph nothing recorded the arrival of is a
  different thing from one whose arrival record disagrees with itself, and a
  section that simply does not appear cannot tell those apart.

- **The class of each claim is named** inside an entry, where there is more
  than one to tell apart. The order was already acquisition, then intrinsic,
  then interaction, and a reader had to know that to read it.

### Changed

- **A report that is not going to a terminal is laid out to 72 columns.** It
  used to take the width of whatever terminal produced it and bake that into
  the file. Open it anywhere narrower and every rule wraps, leaving a stray
  line of dashes outside the gutter that reads as damage rather than as a
  divider: measured, a report made at 110 and read at 72 wraps twelve lines,
  five of them rules, and that was a scan of three empty text files. Seventy-two
  is what a file survives being quoted, pasted, diffed and read in a side pane
  at - the width git uses for a commit body, for the same reason. `COLUMNS`
  still overrides it, and a terminal is still asked how wide it is.

- **`explain` answers first.** The conclusion was printed under everything it
  rests on, in the one command whose entire purpose is to be asked *why*.

- **A claim's value gets the page.** It used to share a line with the source
  name and the strength, which left it about a third of the width, and anything
  longer broke inside a token - so the URL in an `explain` report was an address
  nobody could open, copy or grep for. A field to a line fixes it, and the claim
  carries the same meter the scan prints rather than a second way of saying
  strength. The identifier table sizes its columns from what they hold instead
  of reserving a flat thirty, for the same reason.

- **Headings are upper case.** `theme.bold` and `theme.paint` both hand the text
  back untouched when colour is off, and colour is off in exactly the case that
  matters most - a file read months later by somebody who was not there. Case
  and position are the only emphasis left.

- **`--brief` stops at the index.** It used to be the same report with the
  decoded fields taken out, which is not a shorter answer to the question a
  large directory asks - it is the same length minus the detail.

### Removed

- The separate list of files with no findings, and the heading over each group
  of entries. Both were substitutes for an index. The files are index rows now,
  carrying the filesystem date that was the only thing that list added over a
  bare name, and `--limit` caps them with the wording it had. The ordering the
  group headings sat on - strongest class of evidence first - is unchanged.

## 0.4.1 - 2026-09-05

### Fixed

- The readme said a bare `filegrail` scans the current directory. It does not,
  and deliberately: starting an unasked-for scan of wherever the shell happens
  to be is a surprise, and in a home directory an expensive one. It introduces
  the tool, and `filegrail .` is the scan.

- The first example in the readme was not what the tool prints. It had lost the
  strength meter that ends every evidence line and the indentation every other
  block in the file has, and it listed four decoded fields where the scan shows
  eight. Replaced with the real output of a real run, down to the coordinates.

- `--out` was still documented as required. It has not been since `--check`
  arrived in this release, and `clean` now has six options of its own with a
  table to match - they were prose or nothing.

- `docs/FORMATS.md` did not say what `--content` reads. The file exists to be a
  list that cannot go stale, and it was held against the metadata readers only,
  so forty-three extensions of a new reader went undocumented without a test
  noticing. It has a section of that axis now, and the test holds it in both
  directions like the rest.

## 0.4.0 - 2026-09-05

### Added

- The freedesktop trash is read. Nothing else on a Linux desktop writes down
  where a file *used to be*: the specification keeps a deleted file and the
  record of its deletion side by side, the bytes in `files/` and a small text
  record with the same name in `info/`, holding the path it was deleted from
  and the moment it happened.

  The record is found from the file rather than from a profile, so a mounted
  image's trash reads without `--home` and all three layouts work from one
  rule - the home trash, and both of the per-volume ones, where the recorded
  path is relative to the top of that volume rather than absolute. That pairing
  is also why it ranks above every other source of its kind: the record is the
  trash's own bookkeeping for this exact file, not something matched to it by
  name afterwards.

  It is `interaction` and not acquisition. It proves this machine held the file
  at a path and removed it from there, and says nothing at all about where the
  bytes came from before that. The deletion moment carries no time zone - the
  specification writes the deleting machine's local time and records its offset
  nowhere - so it is read as UTC, the same choice this project makes for EXIF,
  and the record keeps the string as written for anybody who knows the machine.
  `doctor` reports what the trash holds and how far back it reaches, and does
  not guess why an empty one is empty.

- `--content` reads what documents say, not only what they record about
  themselves. `--identify` has always swept the metadata a scan decoded - an
  author line, a company, a producing URL, a GPS fix - which is where
  identifiers a body never mentions turn out to live. This adds the other side:
  the text of a Word or OpenDocument file, a slide deck, a spreadsheet's
  strings, HTML, XML, a message body, and files that are already text.

  **No dependency comes with it.** The formats where a text search fails
  hardest are zip archives of XML, and this package already opens them for
  their properties, with a bounded member reader written for exactly that
  hazard; the body is a different member of the same archive. PDF text is
  deliberately not read - pulling string literals out of a content stream is an
  afternoon's work that produces readable text for perhaps half of real
  documents and mush for the rest, and a confident wrong answer is worse than
  an absent one in a tool that reports evidence. Source code and RTF are out
  for reasons of the same kind, each written down where the decision was made.

  The two corpora are kept apart on every value rather than merged, because
  prose is an order of magnitude noisier than a property field and letting it
  into the metadata list would drown the half that is reliable. That separation
  is also what makes the answer worth having: a value a document names *and*
  the record of the file's arrival names was put there twice, by separate acts,
  and it is raised in the notable findings where a long report cannot bury it.
  Each entry in `--json` carries `corpora` and `acquired` for the same reason.

  Every value says where in the document it was found. The text is read in
  passages rather than as one string, and each passage is addressed in whatever
  terms its format actually has: a line for text and markup, a slide, a sheet,
  a named chapter, the body or the footnotes of a Word file, the body of a
  message. A Word file gets no page number - pagination happens when something
  renders it and the file does not record where the breaks fell, so a page
  there would be a number this invented. Scanning the passages apart rather
  than together costs about a fifth more and is the whole difference between
  `notes.md` and `notes.md · line 1`.

- `clean --check` writes nothing. It runs every stripper, reads the result back
  through the same readers, and says what would come out of each file and what
  a reader would still find in the copy - then exits 1 if any copy would not
  come out clean, so a directory can be gated before it is published rather
  than cleaned twice and inspected afterwards.

  `--out` is optional under it, and where one is given the check still reports
  a name already taken there: a dry run that skips the destination is a dry run
  of a different command. It does not create that directory, either - a mode
  that writes nothing does not get to leave one behind as the only trace that
  it ran. The readers open a path, so the stripped bytes are given a scratch
  one in the system's temporary directory and it is gone before the answer is,
  which is the whole point: no copy exists anywhere anybody could publish from.

- The two hand-written binary decoders are fuzzed. `cbor.py` reads a C2PA
  manifest and `bencode.py` reads a `.torrent`; both are `filegrail`'s own,
  because it takes no runtime dependencies, and both read bytes that arrived
  from somewhere else. `tests/test_properties.py` holds what they have to hold
  for inputs nobody chose - an arbitrary string of bytes is decoded or refused
  with the module's own error class, and a value encoded canonically decodes
  back to itself. It is driven by `hypothesis`, which is a new `fuzz` extra and
  a CI job of its own rather than part of `dev`: a run whose result depends on
  a seed does not belong among the nine jobs that answer *does this commit
  work*, and a red run in its own job is a finding rather than a rerun.

  The generator is handed each format's own alphabet alongside random bytes,
  and assembles an item of unstated length as a unit. Uniform noise practically
  never spells a container - the head has to be right before anything inside it
  is reached at all - and every decoder bug below was behind one.

- Every reader is held against files that stop in the middle.
  `tests/test_malformed.py` builds one valid file of each of thirteen formats,
  cuts each at a ladder of lengths, and offers every piece to every reader and
  to `clean`. Nothing is asserted about what comes back, only that something
  does. It needs no extra and runs with the rest of the suite, and the cuts are
  a fixed ladder rather than a sample, so a failure reproduces by running the
  suite again rather than by recovering a seed.

- The licence is declared as an SPDX expression, and the package says its
  annotations are meant to be used. `license = { text = "Apache-2.0" }` with the
  matching `License :: OSI Approved` classifier is the form PEP 639 replaced:
  free text in one field, repeated in another, with nothing able to parse
  either and both able to disagree. It is `license = "Apache-2.0"` plus
  `license-files` now, which reaches the built metadata as `License-Expression`
  and drops the deprecated classifier.

  `py.typed` goes in beside it. `mypy` has run over this package in CI since
  the beginning and none of that reached anyone installing it: without the
  marker a package is treated as untyped however well it is annotated. The file
  is empty; its presence is the whole statement. CI checks both it and the TLD
  list are inside the wheel, since neither is imported and nothing else would
  notice them going missing.

- `--no-skip` reads the directories a scan normally leaves alone. The skip list
  holds build output, caches and vendored copies - `dist`, `build`, `target`,
  `node_modules` and a dozen more - which bury a report and say nothing about
  how anything arrived. It is a sensible default and it was never a claim about
  what evidence is: an evidence directory may perfectly well be called `build`,
  and until now one would have vanished from the scan without a word.

- `Zone.Identifier` is read on machines that are not Windows. It is the richest
  thing Windows writes down about a download - the address, the referrer and
  the zone the bytes came from - and it was reachable only from Windows, which
  put it out of reach of the one workflow built to want it. `--home` exists for
  reading a profile off a mounted image, and an examiner doing that is not
  running Windows.

  Nothing exotic is needed to get at it. `ntfs-3g` maps named data streams into
  the `user.` namespace and does so by default, so the stream is simply
  `user.Zone.Identifier`; Samba's `vfs_streams_xattr` stores the same bytes
  under a prefix of its own, and both spellings are read. The named-stream
  syntax is still only asked for on Windows, because a colon is a legal
  character in a POSIX file name and trying it elsewhere could open a file that
  merely happens to be called that.

  `doctor` gained a row for it, since a scan can now read a source `doctor`
  never mentioned.

### Changed

- `clean` exits 1 when a copy it wrote still carries something a reader can
  find. It printed *Do not publish these* and exited 0, which is a
  contradiction nothing automated could see - the report was already saying the
  run had not done what its own summary claimed. The exit code answers one
  question in both modes, *would every copy come out clean*, so a file no
  stripper here handles does not count against it: it produces no copy at all.

- Type checking runs in strict mode. The configuration used to name the flags
  that could be turned on, on the principle that a flag nothing satisfies is a
  comment rather than a check - and what it could not name was forty-two
  missing annotations, in twenty-two bare `dict`, `list` and `tuple` types and
  twenty parameters and returns nobody had written down. Those are written, so
  the boundary the list described is gone and `strict` replaces it.

  Two of them turned out to be worth having. `_which_is_stale` in `explain`
  was annotated here as taking a list of origins and is called with a list of
  findings, which the checker refused the moment the claim was made in
  writing; and `compare` decided whether two files existed in a loop the
  checker could not follow, which means a reader could not either. It builds
  the pair one file at a time now and answers for each before reading the next.

### Fixed

- Four ways a small file could end a whole run, none of them found by reading
  the code.

  A CBOR indefinite-length string whose chunks are not strings reached
  `b"".join` and raised `TypeError`, and a map keyed by a container inside a
  container reached the dictionary and raised `TypeError` for an unhashable
  key. Both are `CborError` now, which is the one refusal every caller of that
  decoder catches: a hundred and twelve bytes of crafted JPEG used to end a
  scan with a traceback, and a scan that ends is a scan whose remaining files
  were never looked at.

  A package naming a compression method this interpreter cannot undo raises
  `NotImplementedError` out of `zipfile`, which is neither `OSError` nor
  `ValueError` and so appeared in no reader's list of what a broken file can
  raise. Two patched bytes per member did the same thing to a scan.
  `sources/embedded`, `sources/archives` and `clean` all account for it now.

  `clean` raised `BadZipFile` on a truncated `.docx` or `.odt`, and `IndexError`
  on a JPEG that ends between the two bytes of a marker. The command already
  had the right answer for both - *the file could not be taken apart safely* -
  and it could not reach it. This is the one command that writes, so a
  traceback in the middle leaves copies on disk and says nothing about the
  files it never got to.

- A scan says which directories it did not look inside. `os.walk` swallows
  access errors by default, so a directory that could not be opened produced no
  files, nothing in the report was about it, and nothing in the report said so
  - on exit code zero. That is precisely the confusion the tool exists to
  prevent: `no findings` is a claim about a file that was looked at, and this
  one never was. It matters most in the case `--home` was built for, since a
  profile mounted from an image routinely carries directories this user cannot
  read.

  The closing lines of a report now name them, and keep the two reasons apart
  rather than merging them into one count. A directory that could not be read
  is a hole in the evidence; a directory skipped by name is a choice this tool
  made and can be told not to make. Both are in `--json` under `unsearched`.

- `LICENSE` is the Apache License 2.0. It had been reflowed and cut by about a
  third: the APPENDIX was gone and so were normative sentences from section 1,
  including the whole definition of what a "Contribution" is - *"means any form
  of electronic, verbal, or written communication sent to the Licensor"*, and
  the clause excluding communication conspicuously marked otherwise. 1078 words
  where the licence has 1581.

  Nothing about that is cosmetic. `pyproject.toml`, the README badge and the
  metadata on PyPI all say Apache-2.0, and the file under that name said
  something else, which is why GitHub reported the repository as carrying no
  licence at all and why the same shortened text was shipping inside the wheel.
  Section 4 of the licence asks that recipients be given a copy of *the*
  Licence; a copy with clauses removed is not one. A tool that lists
  `Intended Audience :: Legal Industry` can least afford this particular bug.

  The text is now verbatim from `apache.org`, and a test pins its sha256 beside
  the licence the package declares - one licence stated twice, held together
  the way the version already is.

- A crafted document no longer costs what it says it does. ODF, OOXML and EPUB
  keep what they say about themselves in a named part inside a zip, and those
  four parts were read with `ZipFile.read`, which returns as much as the
  member's header declares. XML deflates at roughly fifteen hundred to one, so
  a **780 KB `.docx` whose `docProps/core.xml` declared 601 MB took 1.2 GB of
  memory and four and a half seconds** - allocated twice, once as bytes and
  once as the tree parsed from them. A directory of them is an out-of-memory
  kill. The same file now costs 33 MB and a tenth of a second.

  Every member goes through `read_part`, which reads through `ZipFile.open`
  with a bound on the decompressed stream and so needs no agreement between
  what the archive claims and what it holds. The bound is four megabytes, the
  same figure the PDF reader already allowed itself for inflated object
  streams; real property parts are kilobytes, and the ones that are not are not
  property parts. A test reads the modules' own source and fails on a bare
  `archive.read(`, because the thing to hold is the absence of a call and any
  test that lists today's sites would miss tomorrow's.

- A TIFF is parsed where it lies instead of being read into memory. `.tif`,
  `.tiff`, `.dng`, `.nef`, `.cr2`, `.arw`, `.orf` and `.rw2` all come through
  the TIFF path, and it was the one reader in the tree without a bound of any
  kind: a 419 MB file took 433 MB to answer with a few hundred bytes of tags,
  and a directory of raw frames from a camera is the ordinary case rather than
  an attack. It now takes 23 MB, which is the interpreter.

  Mapping rather than a window over the head, because an IFD offset may point
  anywhere in the file and a window would be wrong rather than merely smaller.
  The reader gained a way to fail it did not have - an empty file cannot be
  mapped, where reading one returned an empty string - so `read_exif` is now
  tested directly for that case and not only through the dispatcher whose net
  would have hidden it.

- `clean` no longer loses files. Every copy was written straight into `--out`
  under the file's own name, so two folders each holding a `photo.jpg` produced
  one copy: the second replaced the first, and the report said two files had
  been cleaned while one existed. That is the worse half of it. Somebody strips
  metadata from a tree of photographs, reads a summary that says the work is
  done, and publishes a directory that is missing files.

  A copy now mirrors the tree it came from - `case/a/photo.jpg` is written to
  `out/a/photo.jpg` - which is what keeps two files sharing a name apart.

- `clean` does not write over a file that is already at the destination path.
  The destination is a directory the user chose and may hold work of their own;
  an unrelated file with a colliding name was replaced without a word. It is
  now reported and skipped, and `--overwrite` asks for the old behaviour. This
  is the one command in the project that writes a file, so removing one nobody
  asked about is the failure it can least afford.

- `--redact` reaches `explain` and `compare`. It had only ever been a scan
  option, and `explain` is the command that prints the most of what it would
  remove: its whole purpose is to show every source behind a finding, including
  the ones that disagree, so a download URL carrying a session token reached the
  terminal in full. `compare` prints the route each file arrived by, which is
  the same URL. Asking either for `--redact` did not print an unredacted report
  — it failed with `unrecognized arguments`, which is the better half of the
  bug, but a user who has learned the flag on `scan` has no reason to expect
  the command that shows more to offer less.

  The flag now lives in a parent parser beside `--home` rather than in
  `_common()`, because it belongs to the commands that render evidence and to no
  others. `doctor` reports which sources exist and `clean` reports file names
  and the blocks taken out of them; neither can carry a credential, and an
  option that does nothing there would read as a promise.

## 0.3.0 - 2026-09-05

### Added

- `filegrail clean` writes copies of files with their metadata removed. JPEG
  segments, PNG chunks, the `udta` and `meta` atoms of an ISO base media file
  along with the two timestamps in its movie header, and the property parts of
  the zip-based Office and OpenDocument formats. `--type` and `--ext` narrow it
  the way they narrow a scan, so a directory can be cleaned one format at a
  time.

  **The original is never touched.** This is the only command that writes
  anything, and the rest of the tool rests on not writing, so copies go to
  `--out` - which is required, and refused if it sits inside the directory
  being read.

  Every copy is then read back with the readers that find metadata in the first
  place, and whatever they can still see is reported. A stripper is written per
  format and a format can carry a block somewhere it does not reach: a packet
  appended after a JPEG's end marker survives, and the check is what says so
  rather than leaving somebody to publish on the strength of the word
  *cleaned*.

  Two decisions worth stating. A movie is not shortened - its sample tables
  address the media by absolute offset, so the metadata atoms keep their length,
  become `free` boxes and have their payloads overwritten. And a document's
  property parts are emptied rather than deleted, because they are named in the
  package relationships and a part that is named and then missing is a broken
  document rather than a clean one.

  **PDF is deliberately not cleaned.** Without a library the only safe way to
  change one is an incremental update, which leaves the old `Info` dictionary
  physically in the file and merely stops pointing at it. For a cleaning tool
  that is worse than doing nothing, so it does nothing and says so.

### Changed

- The type annotations are checked. There were 362 of them and nothing verified
  any of them, which in a project that holds its format documentation against
  the readers with a test was the one large body of claims with no invariant
  behind it. `mypy` runs in CI now, against the oldest supported interpreter so
  that a construct newer than the floor fails here rather than on somebody's
  3.10.

  It found no defect a user would have met. What it found were annotations that
  were not true: `_origin` declared a required `block` for a value that is
  optional, one name stood for a tuple and a regex match inside a single
  function, and the tally table was typed loosely enough that calling its
  predicates was checked by nothing. Those are fixed rather than silenced.

  Only settings that already pass are enabled, because a flag nothing satisfies
  is a comment rather than a check.

## 0.2.0 - 2026-09-05

### Added

- Folders a sync client keeps in step with an account are read - Nextcloud,
  Dropbox, Syncthing and the Linux OneDrive client - and a file inside one is
  reported as being inside it, with the account or server named where the
  configuration names it.

  Two limits are worth stating rather than discovering. **Who put the file
  there is not readable**: Dropbox encrypts its file cache, and for all of
  these that answer lives on the server. And **sync runs both ways** - a file
  in a synced folder may have arrived from the account or may have been made
  here and pushed to it, and containment cannot tell those apart. So this is
  recorded as something that handled the file rather than as an account it came
  from, which is what is actually known.

  Containment is decided by path components rather than by text, because
  `Nextcloud-old` is not inside `Nextcloud` and comparing the two as strings
  says that it is.

  `doctor` reports which clients are configured and how many folders they name.

- The files inside an archive are read for their metadata, one at a time and
  without unpacking it. A photograph in a zip has the same EXIF it would have
  on disk, and none of it was being read; the archive was known only by the
  names and sizes it listed.

  The claim that comes back is about the **archive**, and that is the whole
  difficulty. The member's moment and its coordinates do not survive into it: a
  photograph taken in 2008 inside a zip written last week does not date the
  zip, and a zip has never been anywhere. Both keep saying what they say in the
  fields, under the name of the member they came from.

  Members are read by the ordinary readers rather than by anything new, so no
  format is understood twice. Only members a reader claims are opened, only
  below a size, and only the first twenty-five: the section says what kind of
  thing is in there, and an archive of ten thousand photographs is not read ten
  thousand times to say it.

- A `.torrent` is read for the files it distributes. It lists its members by
  name and exact size, which is the pairing the archive reader already makes,
  so a file matching both is given the torrent as an origin: the trackers it
  was announced to, the client that wrote it, any comment, and a magnet address
  built from the info hash.

  Unlike an archive member this is not an inherited origin. An archive passes
  on where the archive came from; a torrent states where the content came from
  itself, so every matching record gets it - including ones that already know
  something about themselves. A photograph with EXIF is no less interesting for
  also having been in a torrent.

  The clients' own stores are read as well as the scanned tree - qBittorrent's
  `BT_backup`, Transmission's `torrents`, Deluge's `state` - because that is
  the ordinary case: a downloaded file rarely has a `.torrent` beside it and
  the client has kept one all along. `doctor` reports whether a store was
  found, and the invariant holding the survey against the sources is what
  noticed that it had to.

  The claim is undated. A torrent's creation date is when the torrent was made,
  which can be years before anything in it was fetched.

  Reading one meant a bencode decoder, which joins the CBOR decoder as
  something the standard library does not provide and the zero-dependency rule
  will not import. It refuses non-canonical input rather than being lenient
  about it: an info hash is taken over the `info` value exactly as written, so
  bytes no honest encoder produced would hash to something that identifies
  nothing.

### Fixed

- `--type` lists every family it accepts. The help text was written by hand and
  `mail` had been added to the families without it, so `--type mail` worked and
  nothing said so. It is generated from the families now, and a test holds it
  there.

- An archive is no longer swept for XMP and IPTC blocks in its own raw bytes.
  Those readers look for a block wherever it turns up, and inside a container
  what they find is a member's - which is how a zip came to be reported as
  "made by Adobe Photoshop Elements" because a photograph inside it was. Now
  that the members are read under their own names, the sweep is both redundant
  and wrong.

## 0.1.0 - 2026-09-05

### Fixed

- The wheel can be built. `packages` already carried everything under the
  package directory, including the IANA TLD list, and the `force-include` entry
  added the same file at the same path a second time - which hatchling refuses,
  so **no wheel had ever been produced**. The entry rested on an assumption
  that turned out to be wrong, and nothing tested it because nothing had built
  the project. CI now builds it, checks the data file is inside, installs what
  it built and runs it.

### Added

- The file names messaging clients give to what they save are recognised.
  WhatsApp writes `IMG-20240115-WA0001.jpg` and its siblings for video, audio,
  voice messages, documents and stickers; Telegram Desktop writes
  `photo_2024-01-15_12-30-45.jpg`. A file carrying one came through that client
  far more often than not.

  It is worth being exact about what this is not. It names no sender and no
  conversation, because those stores cannot be read: Telegram Desktop encrypts
  `tdata` and keeps no chat history in it, Signal Desktop's database is
  SQLCipher behind an operating-system-wrapped key, and Discord and Slack keep
  no local message database at all. Reading any of them would mean a crypto
  dependency, which this project does not have. `FORMATS.md` says so where the
  rest of what is deliberately not read is listed.

  So this is a name and nothing else, and it is ranked below an application
  having opened the file - which at least happened. A name is typed as easily
  as it is written and is lost the moment somebody renames the file.

  The claim is left undated on purpose. The name carries a day, and for
  Telegram a clock with no zone on it, and putting either on the timeline would
  place the file at a moment nothing recorded. A pattern matching the shape but
  not the calendar - `IMG-20241315-WA0001.jpg` - is read as the coincidence it
  is and reported as nothing.

- The record `yt-dlp` writes beside what it fetched is read. `--write-info-json`
  leaves `<name>.info.json` next to the media, and that document names the page
  the bytes came from, the uploader and channel, the publication date, and the
  moment the fetch ran. It is an acquisition record in the plainest sense - the
  program that got the bytes wrote down where it got them - and unlike a
  browser database it travels with the file.

  It ranks below the attributes an operating system attaches to the file
  itself. A sidecar is a separate file paired to the media by name alone, so a
  copy that brings one and not the other, or a rename, breaks that pairing in a
  way an extended attribute cannot be broken, and nothing in the document
  proves it describes the file it happens to sit beside.

  The moment reported is the fetch and not the publication. `upload_date` can
  be years earlier, and reading it as the arrival would put the file on the
  timeline before it was ever on this machine.

  `filesize_approx` is not carried as a byte count. It is an estimate for the
  format that was chosen, and reporting it as the size would produce a size
  mismatch that nothing is actually wrong about.

- An editing history recorded out of order is reported. `xmpMM:History` is a
  sequence and the reader already keeps the order the encoder wrote, so a step
  dated before the one it follows contradicts the list it sits in - a clock
  moved, a zone was got wrong, or the history was written by something other
  than the sequence of events it claims to describe.

  It arrives as `impossible_order`, the same kind as a document modified before
  it was created, because it is the same class of problem: the file's own
  account of itself in an order that cannot have happened. Only the first
  inversion is reported - one is enough to say the account is unreliable, and a
  history that goes backwards usually does so repeatedly, which would bury
  every other finding about the file.

  Two steps at the same moment are not backwards. An application that saves and
  exports in one action writes both at the same second, and equal is not
  decreasing.

- `--cluster` groups the scan by the sources more than one file names. A
  directory is a list of files; a case is the smaller number of authors and
  cameras that produced them, and the section exists to turn the first reading
  into the second.

  Three axes, kept apart because they do not identify equally well. A body
  serial is assigned per unit and names one physical camera. A make and model
  names a product thousands of people own, which is a different claim and is
  never merged with the first - a reader told that two photographs "came from
  the same camera" on the strength of a model name has been told something the
  metadata does not support. An author field holds a name somebody typed, and
  two people can type one name.

  A field naming several authors is read as several. These formats separate
  them with a semicolon, and reading the value whole invented a person nobody
  is while hiding every real author in it - in the local corpus it split one
  author across three near-identical groups. A comma is deliberately not a
  separator: `Smith, John` is one person written surname first.

  The author fields are the ones the overview already counts rather than a
  second list beside it, so a block that learns to report an author becomes
  clusterable in the same change.

  It is on `--json` as `shared_sources`, with every path, and on the menu.

- A block whose own two timestamps run backwards is reported. Where a document
  records both when it was made and when it was last changed - a PDF `Info`
  dictionary, OOXML core properties, an XMP packet - and the change comes
  first, the block is contradicting itself. That needs no second source to be
  wrong, which is what makes it different from the timeline conflict already
  reported: that one is the file disagreeing with the machine it arrived on,
  this one is the file disagreeing with itself. It arrives as its own finding
  kind, `impossible_order`, so a consumer can tell the two apart without
  reading the sentence.

  Only pairs a reader actually emits are compared. A rule written for a block
  that records neither field could never fire, and so could never be found
  wrong.

  Two stamps are ranked only where they were written to the same standard of
  precision. One writer naming its zone while the other stays silent can differ
  by most of a day, and calling that an impossible order would be inventing the
  half nobody wrote down - so it is left alone instead.

  The verdict no longer heads such a finding with the acquisition state. A file
  whose dates run backwards has said nothing about how it arrived, and printing
  `no acquisition record` above the contradiction labelled one thing with the
  name of another; it now reads `contradicts itself`.

- The C2PA hard binding is checked. A manifest carries a hash of the asset it
  describes, with its own bytes cut out of the range so it is not hashing
  itself, and recomputing that hash needs no key, no certificate and no trust
  list - only the file. So a manifest lifted onto a different image, and an
  asset edited after its manifest was written, are both reported now, where
  before the tool could only repeat what the manifest said about itself.

  This is deliberately not signature verification and the report does not let
  the two be confused: a claim now reads `hash binding matches; signature not
  verified`. The first says the manifest is about these bytes. The second is
  still the open question of whether anyone should be believed about it.

  Finding the assertion meant reading JUMBF labels rather than guessing at
  payloads by their shape, so every box is now filed under the label its
  description box gives it. `c2pa.hash.data` is found by name, and an
  assertion that omits its algorithm inherits it from the claim, the way the
  specification says to.

### Changed

- The report carries the wordmark. It is redirected to a file more often than
  it is read on screen, and a `report.txt` that does not say what produced it is
  a wall of text somebody has to identify from memory. The banner is the landing
  screen's mark with the version, the tagline, the target and the scan
  statistics - and none of the repository, licence, usage or commands, because a
  report is not an introduction.

- The inventory counts formats rather than spellings. `JPG 20` beside `JPEG 1`
  was one format counted twice; `jpg`, `jpe`, `tif`, `yml` and `htm` fold to the
  name the format is usually called by, and `audit.tar.gz` is `TAR.GZ` rather
  than `GZ`, which said nothing the file name had not. Presentation only -
  `--type`, `--ext` and the record keep the extension the filesystem has.

- `findings` prints `metadata` and `acquisition evidence` even at zero. This
  tool stands on those two things, and a scan that read a great deal of the
  first and none of the second has found that out; leaving the row off made an
  answer look like an omission. `authors / creators` joins them, keyed on the
  block rather than on the field name - `Creator` is the application in a PDF
  Info dictionary and the person in OOXML core properties, and one flat list of
  names would have counted every PDF's typesetter as its author. `dated claims`
  is `timestamps`, and identifiers are counted in identifiers rather than files.

- `attention` is `notable findings`, and it no longer uses `●`. Coordinates and
  Content Credentials are findings, not problems, and the heading said
  otherwise. `●` means *this is a file* everywhere else in the report, so
  spending it on a count line cost the gutter the one symbol it has for that;
  only the contested `!` keeps a glyph. `carry` became `contain` throughout.

- Every file with no findings is listed by default. `--limit` defaulted to 25
  and hid the rest behind a line saying how to see them, which is the same
  objection that put every decoded field on screen without asking: nobody should
  run the tool twice for data it had the first time. `--brief` caps the list at
  25 now, and an explicit `--limit N` is obeyed as given.

- The report answers the directory before it answers a file. It used to open on
  its first entry, which is the seventh question an analyst asks; the six that
  come first now have sections of their own. A masthead saying what was scanned
  and how much of it answered, an `inventory` of every type present with its
  share of the files and the bytes, a `findings` table naming what was found, and
  an `attention` block for the few things a long report otherwise buries. A scan
  of a single file skips all four - there is nothing to inventory but itself.

- Three names that described the model rather than the contents. The masthead
  said `73 of 105 traced` over a count of files carrying any origin at all: a
  PDF with an Info dictionary has not been traced anywhere, it has described
  itself, and the closing line repeated the same number as `have a recorded
  origin`. Both now count files, findings and silence separately. The
  self-reported section is headed `file metadata` rather than `claimed by the
  file itself`, and the list at the end is `no findings` rather than `no recorded
  origin` - which named a narrower case than the list has ever held, since a file
  is in it only when nothing at all was found. Each claim inside still reads
  `self-reported` beside its own source, so no methodological care is lost.

- The reader table moved to the end, under `metadata sources`. It answers which
  readers produced results, which is a technical question and was standing in
  for what was actually found.

- The landing screen is twenty-four lines instead of forty. It says what the
  tool is for in three - metadata, provenance, analysis - then six ways in, the
  command names, and where the rest is. The option table it used to reprint is
  in `filegrail help <command>`, which is where somebody looking for an option
  goes anyway. The tagline says both halves of the job.

- Every claim records which metadata block it was decoded from, beside the
  source it already carried. The two answer different questions. `source` names
  what the reader *found* - `device-metadata` where a file named a camera,
  `document-metadata` where it did not - and is what confidence, colour and
  kind turn on. `block` names what it *read*: `pdf-info`, `png-text`, `exif`,
  `ole-summary`, `iptc`, `xmp`. It appears in `--json` as `block`, and a record
  that decoded no metadata block does not have one.

  Nine readers answer to `document-metadata`, which is why the distinction had
  to exist before a PDF pairing could. Keyed on the source, the EXIF mirror
  reached all nine: a WAV's `INFO` list has a field spelled Software, and beside
  an XMP packet the tool reported `Software: RIFF INFO says Audacity 3.4.2, XMP
  says Adobe Audition 24.0` - a contested attribution between a RIFF field and a
  TIFF tag, invented out of two standards sharing a word. `Mirror.left` and
  `Mirror.right` now name blocks, and `left` is a plain string rather than a
  tuple of source names.

- The conclusion no longer ranks two blocks it has no basis to rank. IIM and a
  camera's EXIF tags go stale because an editor rewrites the XMP and copies them
  through untouched, and the sentence said so. A PDF has no such direction: one
  producer writes both blocks, and an exporter stamps a fresh Info dictionary
  while carrying the XMP through from the source document - the corpus file has
  XMP from February beside an Info dictionary from May, so naming the Info as
  the likelier to be stale would have stated the opposite of what happened.
  A pairing now carries which of its two sides an editor keeps current, or that
  it has no answer, and the conclusion follows it. `--json` carries it too, as
  `maintained` on a finding that has one.

- A claim is named by its block where the source would only say `document
  metadata`. That label names a category rather than a thing, and the summary
  collapsed a whole corpus into one line reading `document metadata 39` when it
  could say which nineteen were OOXML properties and which six were PDF Info.
  Every other source keeps its own name: `device metadata` says the block held a
  make and a model, which is why it outranks a bare document property, and
  `EXIF` would throw that away.

- The WAV and AVI block is `riff` rather than `riff-info`. That reader decodes
  three chunk families and already names every field for the standard it came
  from - `bext:Originator` beside `id3:encoder` beside a plain INFO field - so
  the block only had to name where they were all found. It named one of the
  three instead, and a broadcast recording carrying no INFO list at all was
  reported under the label of the chunk it did not have. `matroska` and
  `isobmff` are named for their containers for the same reason.

- Two timestamps are compared as instants where both writers said what zone they
  were in, and as readings where either did not. The zone used to be dropped
  outright, which EXIF requires - it writes no zone at all while its XMP mirror
  writes the same reading with one attached - but a PDF carries an offset in
  both of its blocks, and one machine varies it across the year. The corpus has
  an export whose Info dictionary says `-04'00'` where its XMP says `-05:00`,
  the same laptop either side of a daylight change; comparing the readings would
  have reported a single moment as a contested attribution.

- Modes are commands now, not flags: `filegrail explain FILE`,
  `filegrail compare A B`, `filegrail doctor`, `filegrail menu`,
  `filegrail help <command>`. `--doctor` and `--explain` were modes wearing an
  option's clothes - each ignored most of the other options, and every pair of
  them was mutually exclusive, which is exactly the shape subcommands exist to
  express. `filegrail <path>` still scans with no command word, because that is
  what people do most of the time and making them type `scan` would be ceremony.
- `-v`, `-j` and `-h` short forms. The evidence-source table moved off the
  landing screen into `doctor`, where the question has actually been asked;
  what the screen says instead is described above.

### Fixed

- Metadata field names are names. A packet whose namespace the prefix table had
  never listed printed the URI instead, four times over inside one name:
  `xmpMM:History/http://www.w3.org/1999/02/22-rdf-syntax-ns#:Seq/...:li/stEvt:action`.
  RDF's own namespace was the worst of them, and this file had been defining it
  two lines above the table since the reader was written; `xmpG`, `xml` and
  `pdfuaid` were missing too.

  The array wrappers went with them. `rdf:Seq` and `rdf:li` are how RDF spells
  "several of these" and say nothing about the property, so they are no longer
  path segments - a swatch group is `xmpTPg:SwatchGroups/xmpG:groupName`, and
  several of them are numbered rather than dropped on each other's name, which
  is what `setdefault` had been doing in silence. One corpus PDF carries
  Illustrator's entire default palette, so an array reports its first three
  entries and states how many there were, the way the edit history already
  bounds itself.

  The edit history is no longer flattened into the fields at all. Every step is
  already its own dated claim with its own `stEvt:` fields, and walking the
  sequence a second time printed each of them twice.

  `--json` carries the corrected names. The document's shape is unchanged and no
  field changed meaning, so the schema number stands: what moved is the reader's
  own naming of things inside an open dictionary, and the names it moved from
  were not usable.

- Field names, file names, identifiers and scanned paths wrap instead of being
  cut. `DESIGN.md` has said nothing is truncated since the first release, and
  four XMP fields were printing as `xmpMM:DerivedFrom/stRef…` - four rows nobody
  could tell apart, over four values nobody could attribute to a field. A name
  too wide for its column now takes a line of its own and its value follows
  underneath. `--timeline` was cutting names and claims for the same reason.

- The identifiers section is ASCII on a terminal that cannot print a middot. The
  separator inside a place string was written once and printed as written.

### Added

- `--home DIR` reads the browser, shell and desktop history of another user
  profile instead of the current one, on `scan`, `explain`, `compare` and
  `doctor`. `scan()` and `survey()` had taken a home directory as an argument
  since they were written; nothing offered it on the command line, so the
  answer was always about the machine doing the asking - which is the wrong
  machine whenever the interesting one is a mounted image or a copied profile.

  It works across platforms without porting, because the profile locations for
  Linux, macOS and Windows were already in one list and searched under whatever
  home is given. A Windows Chrome profile read from Linux resolves.

  Two things change when the traces are not this machine's, and both are things
  the report would otherwise have got wrong. `this machine` becomes `that
  machine` and the report names the profile it read - on paper a foreign-profile
  report was previously indistinguishable from a local one. And when there is no
  acquisition record, the advice to run `doctor` now carries the same `--home`,
  because sending a reader to survey their own laptop about somebody else's
  profile wastes the one step that would have told them the truth.

  A `--home` that does not exist is refused rather than searched. Every source
  would come back empty, and a run that found nothing because it looked in the
  wrong place is indistinguishable from one that found nothing because there was
  nothing to find - which is the exact confusion `doctor` exists to prevent.

- Every `--json` document now begins with what it is: a `schema` naming the
  shape, and a `filegrail_version` naming the build that wrote it. The four
  shapes are `filegrail.scan/1`, `filegrail.explain/1`, `filegrail.compare/1`
  and `filegrail.doctor/1`.

  `--json` is a contract with software, not a convenience for reading, and it
  had no way to say which contract. Something switching on the keys it found
  would break silently the first time a field was renamed, in a program nobody
  here can see. The stamp is also the kind of thing that can only be added for
  free once: adding a key is itself a change for anyone who enumerates them, so
  the cheapest moment to do it is before there are consumers. The schema number
  moves only when a field changes meaning or leaves - a new field is not a
  break, and neither is a release, which is why the two live in separate keys.

  `explain` and `compare` built their JSON inline in the command layer, so
  there were four documents defined in two files. All four are now rendered in
  `report.py` through one function, which is what makes the stamp a single
  decision rather than four.

- Reconciliation now compares a PDF's `Info` dictionary against its XMP, and a
  PNG's text chunks against theirs. Both pairings are published in Part 3 of the
  XMP specification, alongside the IIM and EXIF ones already checked: the Info
  entries are the legacy form of `dc:title`, `dc:creator`, `dc:description`,
  `pdf:Keywords` and `xmp:CreatorTool`, and the standard PNG keywords map the
  same way.

  One producer writes both of a PDF's blocks at one save, so agreement is the
  ordinary case and worth no line. A difference is the trace of an export that
  stamped a fresh Info dictionary over XMP carried through from the source
  document. On the developer's corpus this finds an InDesign export whose Info
  names InDesign where its XMP still names the Illustrator document behind it,
  three months earlier - and a Writer export whose title and creation date
  belong to a thirteen-year-old file.

  `/Producer` is left out. It names the library that wrote both blocks, so it
  disagrees with itself rather than with anything: Adobe PDF Library 15 puts
  `Adobe PDF Library 15.0` in the Info dictionary and `Adobe PDF library 15.00`
  in the XMP. `/Trapped` is left out because it is a PDF name object rather than
  a string, and the reader takes only string values.

  The PNG pairing is spec-only. No file in the corpus carries both a text chunk
  and an XMP packet, so it has been read against synthetic files alone. Its
  `Creation Time` is compared where it can be read; the specification asks for
  RFC 1123, which nothing here parses, and an unreadable stamp is skipped rather
  than reported.

  Reading a PDF's dates needed the moment comparison taught the form a PDF
  writes. `D:20180511143720-04'00'` opens with two letters the day pattern would
  not match past and runs the clock straight into the day with none of the
  separators the clock pattern looked for, so every PDF timestamp came back
  unreadable - and an unreadable stamp is never compared. They were being
  skipped in silence.
- Saved messages, read for how they travelled. `Received:` headers are the only
  part of an email not written by the sender: each mail server prepends its own
  as the message passes through, so they read from the bottom up. Each hop
  becomes an event of its own, the way a recorded XMP edit does, so the whole
  chain lands on `--timeline` in order.

  They are not ranked alike, because they are not worth the same. The topmost
  was written by the recipient's own server and nobody else could have forged
  it; it goes in at 78, below the attributes an operating system keeps outside
  the file and above an archive's inheritance. Every hop under it was written by
  a machine the sender may control, and those go in at 45. What the message says
  about itself - who it is from, what the subject was, which client composed it
  - is a self-description checked by nobody and goes in at 30, the weakest in
  the table, because forging a `From` line takes nothing but typing it.

  The address each server actually saw is kept beside the name the connecting
  host claimed for itself, and both reach `--identify` along with the addresses
  and domains in the headers. A message id does not: RFC 5322 builds one to the
  same shape as a mailbox, so it matches every test for an address and nobody
  can write to it. Its domain is still reported - that names the host that
  minted it, which is a real fact about where the message was written.

  `.eml` only. An mbox holds many messages and one record per file has no honest
  way to describe them all; `.msg` keeps its headers as MAPI properties inside a
  compound document, which is a different reader. Both are left for their own
  design rather than half-answered here.

- Vorbis comments, which FLAC, Ogg Vorbis and Opus all carry: one layout in
  three containers. FLAC keeps the block among the metadata blocks at the front
  of the file and those can be walked exactly; Ogg keeps it in the second packet
  and it is found by the marker that opens it, rather than by reassembling Ogg
  pages for a block that has already been located. The cost of that shortcut is
  named where it lands: a comment block long enough to be split across pages
  stops being readable partway, so every length is checked against what was
  actually read and whatever was recovered is returned as it stands.

  The names are case-insensitive by specification, and ffmpeg takes it at its
  word - every field it writes is in lower case. The first draft looked them up
  shouted and so found nothing at all in the files ffmpeg produces, which is a
  reader agreeing with the specification and disagreeing with reality. They are
  looked up without regard to case now and kept in the record exactly as the
  writer wrote them; shouting a studio's own field names back at it is editing
  the evidence.

  Cover art arrives base64-encoded in a comment like any other and is left out.
  It is not provenance, and a screenful of it would bury the handful of values
  that are.

- Matroska and WebM, read through EBML. `.mkv` and `.webm` were already
  selectable with `--type video` and no reader claimed them, so a scan narrowed
  to the films read nothing out of them. The container names the application a
  person used and the library that muxed the file, and those are only reported
  separately when they differ - ffmpeg writes its own name into both, and
  "Lavf60.16.100 (muxed with Lavf60.16.100)" is a sentence about nothing.

  The tag block is open by design: a muxer puts anything there the format has no
  field for, under whatever name it likes. Those names are kept as written,
  because a reader that knows only a fixed list throws away the ones that
  mattered.

  Matroska counts its segment date in nanoseconds from the start of 2001, not
  from 1970. Read as a Unix time it puts every file made this century
  thirty-one years early, which is wrong in a way that looks plausible enough to
  go unnoticed. The field is also signed, so a muxer handed a wrong clock has
  what it wrote read back rather than turned into the year 586.

  A segment can decline to state its own length - a muxer writing to a pipe does
  not know it - and then it runs to the end of its parent. `ffmpeg -f webm
  pipe:1` writes exactly that, and the first draft of this reader returned
  nothing at all for such a file. Only a master element may do it; a leaf that
  tries is refused, because there the value would be however much of the file
  happened to follow.

- Files in one scan are linked to each other by the identifiers XMP carries for
  exactly that purpose. A master, the export made from it and the web rendition
  made from that now say so in the report, in both directions - `derived from`,
  `source of`, `descends from`, `original of`, `same document`.

  A shared original document is reported as a common ancestor and never as a
  derivation. The corpus explains why: `osint360-klienci-zastosowania.pdf`
  carries an `xmp:CreateDate` of 2013 inside a document made in 2026, because a
  LibreOffice template dragged its whole XMP block along. Everything ever made
  from that template shares an original and shares nothing else. For the same
  reason an identifier shared by more than eight files is counted rather than
  paired off - that is a template sitting under a directory, not a lineage, and
  pairing it would be a square number of links saying nothing.

  Two guards worth naming. Half of a `DerivedFrom` reference is looked up only
  in its own index, because PowerPoint writes one uuid as both the document and
  the instance and matching across the two would make each of its exports an
  instance of the rest. And a null uuid identifies nothing, so it joins nothing:
  it is what a writer emits when it has nothing to say.

  A link is not an origin. An origin is one source's claim about where a file
  came from; a link is a relation between two records that exists only because
  both were scanned together, so it lives on the record rather than among the
  claims. An ancestor's download record is deliberately *not* inherited down a
  derivation edge - an archive inherits because the bytes were literally inside
  it, and an edited export is a different file. `docs/specs/` has the reasoning.

  The developer's corpus produces no links at all: 105 files, twenty identifiers
  and not one of them shared. That is the honest result for a collection of
  unrelated downloads, and the feature was verified instead against a chain
  written by `exiftool`.

- Reconciliation now compares a camera's own tags against their XMP mirror, the
  way it already compared IIM against XMP. The pairing is the XMP
  specification's own - the `tiff:` and `exif:` properties are defined as the
  serialisation of those tags - so a difference is one of the two blocks having
  been rewritten rather than two tools writing one fact differently.

  What is compared is what the camera said about taking the picture: the make,
  the model, the software, the artist, the lens, the body serial number, the
  description, and the two capture timestamps. Exposure settings are left out on
  purpose. XMP writers put units, rationals and comma decimals in them - `f/5,6`
  against 5.6, `1/500 sec.` against 0.002, `105,0 mm` against 105 - and a
  comparison that cannot read those would report a contested attribution on
  almost every photograph ever taken. `xmp:ModifyDate` against EXIF `DateTime`
  is left out for the opposite reason: tools maintain one and not the other, so
  the two drift apart in ordinary use and a finding there would say nothing
  while diluting the ones that do.

  Timestamps are compared as moments rather than as characters. EXIF writes a
  local reading with no zone, XMP writes the same reading with an offset
  attached, and IIM writes a bare eight-digit day - three spellings of one fact.
  Comparing their characters would have found conflicts in three of the
  twenty-two files in the developer's corpus that carry two self-descriptions,
  and every one of them would have been invented. That also fixes a conflict the
  IIM comparison could already have reported and nobody had a file to trigger:
  `DateCreated` as `20190304` against `2019-03-04T10:22:31+01:00`.

  A finding now carries the two blocks it is between, so the conclusion names
  them instead of talking about the IPTC block of a file that has none, and a
  consumer reading the JSON does not have to parse the sentence to learn which
  two pieces of evidence disagree.

- The broadcast extension, `bext`, which is what a field recorder writes into
  a WAV: the machine that made the recording, the moment it started, a slate
  line for the take, and the coding history - one line per processing step, so
  a take that went through an analogue deck before it was digitised says so on
  its first line. The lines are kept apart, because the chain is the evidence
  and folding it into one sentence loses where each step began.

  Where a file has both, the recorder is named first and the editor after it -
  "Sound Devices MixPre-6 (edited with Adobe Audition 3.0)" - for the reason
  the EXIF reader already names a camera before the software that processed
  its picture. Naming only the last writer hands back the studio and loses the
  field. The recording moment likewise outranks the date the editor wrote.

  It stays at `document-metadata` rather than being promoted to
  `device-metadata`. `Originator` is free text and is a recorder about as often
  as it is a company, and a reader cannot tell which from the file.

- RIFF `LIST/INFO`, which is where a WAV or an AVI records who edited it.
  `ISFT` names the software, `ICRD` the date, `IART` and `IENG` the people
  credited; the twenty-odd remaining codes are kept under their published
  names, or under the code itself where a writer invented one.

  This began as a repair rather than an addition. `.wav` was on the ID3
  reader's list of extensions, and that reader requires the tag at byte zero
  while a WAV begins with `RIFF` - so the format was advertised and could never
  return anything. A WAV that does carry an ID3 tag keeps it in a chunk, which
  is read there now, and `.wav` has left the ID3 reader's list, because the
  claim it made was false.

  AVI arrives with it and costs nothing: the container is the same list of
  chunks and the INFO block is the same block. In a large file it sits after
  the frames, so the walk seeks over payloads instead of reading them - three
  megabytes of video cost 0.08 ms - and it does not descend into the lists
  holding sample data. Anything at all can appear inside a frame, chunk headers
  included, and a file must not be able to forge its own provenance in its own
  payload.

  Verified against files written by ffmpeg and by alsa-utils, including one
  carrying no metadata at all, which is reported as carrying none. The `id3 `
  chunk is the exception: nothing available here writes one, so that path rests
  on the specification and on constructed files.

- Reconciliation reaches what a file says about itself. IPTC and XMP hold the
  same facts under different names - Adobe published the pairing when it moved
  IIM into XMP - and an editor maintains the XMP while leaving the IIM block as
  it found it. Two photographers in one file is therefore not a formatting
  difference but the trace of an attribution being changed, and until now the
  report printed both without a word and left the reader to notice.

  Agreement stays silent. One editor writing both blocks at once and keeping them
  consistent is the ordinary case, and a line on almost every photograph would
  say nothing. Only the difference is reported, as `attribution_conflict`, and
  the conclusion names what disagrees while saying plainly that which side was
  rewritten is a question it can raise and not answer.

  A contested file now brings both self-descriptions on screen, for the reason
  the report already brought forward a conflicting acquisition record: a verdict
  about evidence the reader cannot see is not a verdict. The block is headlined
  `contested attribution` rather than the acquisition state, which described
  something else entirely and was printed in the colour of good news.

- IPTC IIM, read from the Photoshop image-resource block that carries it - which
  means JPEG, TIFF and PSD from one search, because the block is the same
  structure wherever it is embedded. TIFF gets a second path: some writers store
  the datastream directly in tag 33723 with no Photoshop block around it, and
  there is no marker to search for then - a datastream begins `\x1c\x02`, two
  bytes that would match almost anything - so that one is reached through the
  directory. IIM is what a newsroom writes into a picture: who took it, who is to
  be credited, where it was taken and under what terms it may be used.

  Ranked at 51, just below XMP. The two hold the same kind of self-description
  and IIM is the older of them; modern tools maintain the XMP and leave the IIM
  block as they found it, so a byline there is frequently a record of an earlier
  state of the file rather than its current one. That makes it the weaker claim
  and, for exactly the same reason, evidence worth keeping.

  Two details a specification-shaped reader gets wrong. IIM predates Unicode, so
  a block that does not declare UTF-8 in record 1 holds single-byte text, and
  decoding it as UTF-8 turns every accent into a replacement character - losing a
  byline rather than reading one. And a length with its top bit set is not a
  length: the remaining bits count how many bytes the real length occupies, which
  is how a caption longer than 32767 bytes is carried. Reading that as an
  ordinary length does not skip one field, it loses the reader's place in the
  stream and every dataset after it.

- The tagline says both halves of what the tool does: `trace origins, extract
  metadata`. It said only the first, and the landing screen it sits on had ten
  examples without one that mentioned metadata - including `filegrail
  suspicious.pdf`, the command that prints the whole field tree, described as
  `one file`. The capability now sits in the examples, where a reader looks for
  capabilities, rather than in a second slogan under the first.

  Four characters longer than the line it replaces, because `where files came
  from` spent five words on one idea and the wordmark says `filegrail` directly
  above it. The banner, both READMEs and the `aria-label` say the same thing.

  `--home` and `--timeline` are in the options list. `--home` is the newest
  thing the tool can do and was on the screen nowhere.

- Timestamps print to the second. GTK writes microseconds into
  `recently-used.xbel` and a shortcut carries the filesystem's own precision, so
  a claim from either sat beside a dozen stamps that stop at the second and read
  as an inconsistency rather than as precision. `--json` still carries every
  digit, and `--timeline` already did this.

- `explain` puts a blank line under the rule before naming the profile it read,
  the way the scan report does.

- The README is rewritten around what the tool does rather than around how its
  evidence model works. `What filegrail does` opens with metadata extraction and
  provenance reconstruction as two named capabilities; `Metadata analysis` is a
  section of its own rather than a table two thirds of the way down; the
  contents list and the per-section back-links are gone, and the anchors that
  remain are the six a reader actually jumps to.

  Some reference material moved out rather than being reworded: the confidence
  table, the four reconciliation pairings, the `source` and `block` fields in
  `--json`, and the spec-only readers. [`FORMATS.md`](docs/FORMATS.md) carries the
  format and block detail; the rest is in `CHANGELOG.md` and `DESIGN.md`.

- The README says what it can read before it says how it ranks it. The metadata
  half was one item in a list of seven in the opening paragraph, which is a
  strange way to describe the substance of the tool - `CONTRIBUTING.md` calls it
  exactly that. It now has its own sentence, with the count and a link, and the
  `Supported metadata` section opens with the scale rather than with a note
  about output formatting. macOS quarantine was missing from the list of traces
  entirely.

  The JSON section said nine readers answer to `document-metadata`. That was
  true before three more were added; fifteen blocks can carry it now, which is
  every block there is.

- [`FORMATS.md`](docs/FORMATS.md): the complete list of what can be read out of a
  file, with the metadata block each format produces, what is deliberately not
  read, and which three readers are written from a specification rather than
  tested against files the originating software wrote.

  It lives outside the README because it is the one table guaranteed to grow -
  `CONTRIBUTING.md` asks for new readers, and a README that swells with every
  one of them rots. And because out here it can be held against the code:
  `tests/test_documented_formats.py` parses the tables and compares them with
  what the readers actually declare, in both directions. A format that is read
  and undocumented fails, and so does one documented that nothing reads.

  That makes it the first document in this repository that cannot quietly stop
  being true. A list of formats in prose is otherwise the kind of documentation
  most certain to rot: every new reader is a line somebody has to remember, and
  nothing notices when they do not.

- The Windows Recent folder is read. A `.lnk` under
  `AppData/Roaming/Microsoft/Windows/Recent` is the counterpart of a
  `recently-used.xbel` entry and is ranked with it: opening a file proves
  contact, not acquisition, and this does not pretend otherwise.

  What a shortcut adds is *where the file was when it was opened*. It records
  the volume by type, serial number and label, a network share by name, and -
  where the tracker block survives - the NetBIOS name of the machine that
  created the link. That supports a statement nothing else here could make:
  this file was opened from a removable volume, or from an optical disc, or
  from `\\fileserver\projects`. It remains a fact about handling rather than
  about arrival, however suggestive it reads, and it is filed as one.

  The shortcut also records the size and last-write time of what it pointed at,
  so a name match can be corroborated the way a download record's is. The
  recorded path is a Windows one and is split as such, which is the fix from
  earlier in these notes doing its work a second time.

  Spec-only in one direction: nothing available writes a `.lnk`, so the
  fixtures are assembled from [MS-SHLLINK]. The folder walk and the matching
  around it are ordinary.

- macOS quarantine is read: the `com.apple.quarantine` attribute on the file,
  and the LaunchServices `QuarantineEventsV2` database under the user's home.
  The attribute names the application, the moment and an event identifier; the
  database says what that identifier stands for - the URL the bytes came from
  and the page that linked to it.

  They are two halves of one record rather than two witnesses, so they are
  reported as one claim. Emitting both would read as corroboration, and a
  subsystem agreeing with itself corroborates nothing.

  Two epochs, which is the trap in the format. The attribute counts seconds
  from 1970 and writes them in hexadecimal; the database counts them from 2001,
  the way every Core Foundation timestamp does. Reading either with the other's
  epoch puts the download decades from where it happened.

  The database is what makes this worth having away from a Mac. It sits under
  the home directory, so `--home` reaches it from anywhere - and since a file
  copied out of an image rarely keeps its extended attributes, a row whose
  recorded URL ends in the file's name is matched that way, marked as a name
  match like any other.

  `matched_by_name` now takes the reason a name was all there was. A download
  record keeps the path the file was saved to, so a name match there really
  does mean it moved; a quarantine row keeps no path at all, and saying it
  moved would describe a disagreement between two things where only one of them
  exists.

- A saved Outlook message is read for how it travelled. `.msg` was already
  opened as a compound document, because its Office-style summary properties
  sit where a `.doc`'s do; what was never read is
  `PR_TRANSPORT_MESSAGE_HEADERS`, the stream holding the internet headers. That
  block is the same RFC 5322 text an `.eml` starts with, so it goes through the
  same parser and yields the same `Received:` chain - the one part of a message
  the sender did not write. Both spellings of the property are asked for, UTF-16
  and 8-bit, because which one a message carries depends on the sender's Outlook
  and not on anything in the message.

  A message delivered inside one Exchange organisation never crosses the
  internet and has no such headers. No delivery record is invented for it; what
  it says about itself - subject, sender, message id - is reported as exactly
  that, from the MAPI properties, and only where the headers are absent, since
  a header block already carries its own.

  Spec-only. Nothing on the developer's machine writes a `.msg`, so every
  fixture is assembled from [MS-OXMSG] and the reader has never been run
  against a file Outlook produced. The container walk underneath it is not:
  that is the same one the corpus exercises through real `.doc` files, now
  exposed as `read_streams` so a reader of a compound document that is not an
  Office one does not have to walk a FAT of its own.

- `doctor` reports the desktop's list of recently opened files, and how far
  back the shell history and that list reach. It surveyed browsers, the
  operating system's origin attribute, the shell, creation timestamps and C2PA
  - but not `recently-used.xbel`, which a scan reads on every run. The file
  opens by promising to say up front what could be searched, and a reader could
  be handed a finding from a source the survey had never mentioned. An
  incomplete promise of that kind is worse than none, because nothing tells the
  reader where the gap is.

  `HOME_SOURCES` now names every source that reads a home directory beside the
  checks that report it, and a test holds it against `sources` itself, so the
  next collector added without a check fails rather than going unreported.

  The note under the horizon said a file older than it cannot be resolved from
  browser history. With a shell and a desktop list beside them it was
  describing one row of three, and reading as though the other two carried no
  limit at all.

### Fixed

- An ODF document reported three fields where it carried eight, and two of the
  three were invented. `meta:user-defined` is a list of arbitrary document
  properties whose names live in an attribute rather than in the tag, and it was
  read like every other child element: the first value won, the rest were
  dropped, and the attribute names of the others scattered into fields of their
  own. The corpus spreadsheet came back saying `user-defined 16.0300`, `name
  AppVersion` and `value-type float` - three lines, none of which anybody wrote,
  in place of six properties.

  They are now keyed on the name the document gave them, and collected apart so
  that a real element always wins: a user-defined property may legitimately be
  called `creator`, and it does not get to answer for `dc:creator`.

  Attributes are still read from every other child, because the statistics
  element keeps its page, table and word counts in them and nowhere else. That
  was the reason the rule existed; `user-defined` was the case it did not fit.

- The macOS where-from attribute could never be read on macOS. `os.getxattr`
  is a Linux interface - the standard library does not expose the call on macOS
  at all - and every reader here guarded on `hasattr(os, "getxattr")`, so on
  the one platform `kMDItemWhereFroms` exists, the reader that exists for it
  did nothing. `doctor` said so, which is why this survived: it reported the
  source as unavailable there and was believed.

  Attributes now go through `util.read_xattr`, which calls libc on macOS the
  same way creation timestamps already do. macOS takes two arguments the Linux
  call does not, a position and a flags word, which is why one interface does
  not cover both. The tests write an attribute the same way, so the macOS path
  is exercised on a macOS runner rather than reasoned about.

  The macOS attribute is also read under the `user.` namespace, which is where
  a copy carries it onto a system with no other namespace to put it in - the
  same reason the quarantine attribute is read under both names.

- `doctor` counts in the singular where there is one of something. Four checks
  wrote `1 records`, `1 files`, `1 downloads` and `1 shortcuts`, which is the
  kind of seam that makes a report look assembled rather than written.

- A download record written by another operating system never matched by name.
  `Path` knows only the separator of the machine reading it, so
  `C:\Users\Alice\Downloads\evidence.zip` split with `PosixPath` has no
  directory at all and its whole spelling comes back as the file name. Every
  Windows record read from Linux or macOS therefore failed to match silently.

  Names are now taken with `util.basename`, which treats a backslash as a
  separator only where the path announces itself as a Windows one - a drive
  letter or a UNC prefix - because a backslash is a legal character in a POSIX
  file name and mangling those would trade one silent failure for another.

  The bug was invisible before `--home` because a record and the file it
  described came from the same machine, so both were spelled the same way.

### Changed

- A place and a coordinate are two fields now. `geo` holds a latitude/longitude
  pair this tool decoded itself, from EXIF or an ISO 6709 atom; `location` holds
  a place written as a name. They had shared one field, which was tolerable while
  every coordinate arrived already decoded and became untenable the moment IPTC
  turned up recording "Firenze, Italy" and meaning it. A decoded fix can be put on
  a map; a typed name is a claim like any other text, and a report that prints
  them on the same line has stopped saying which it has.

  `--json` gains a `geo` key, and `location` no longer carries coordinates.
  `--identify` reads its trusted coordinate pair from `geo`, which is also the
  name it has always used for that identifier - one word for one thing, in the
  claim line and the identifier list alike.

- XMP, read from wherever a container embeds the packet: JPEG, TIFF and raw,
  PNG, PDF, MP4, HEIC, SVG. EXIF says which camera made a photograph. XMP is the
  only metadata standard in wide use that says what happened to it afterwards,
  and it keeps that as a sequence rather than one field - so `xmpMM:History`
  becomes one claim per recorded edit instead of a flattened list, and an editing
  sequence lands on `--timeline` beside the download that brought the file in.

  An edit that records no time stays a field rather than becoming a claim: the
  timeline supplies a file's own timestamps to a claim carrying none, which would
  place an editing action at a moment nothing recorded. Ranked at 52, between a
  camera naming its own model and a bare document property, because an editor
  writing free text about itself is the weaker claim of the two. The packet is
  located by its root element rather than by a path through each container, which
  is what lets one reader serve every format that embeds one - and what let the
  local corpus find the two defects a specification-shaped fixture could not: a
  root element under an unexpected prefix, and a namespace spelled without its
  trailing slash. Signatures do not enter into it. XMP has none.

- PNG text chunks no longer repeat the raw XMP packet. It arrived clipped at 4096
  characters, so what reached the field tree was unparseable markup sitting beside
  the properties the XMP reader now decodes out of it.

- `--identify` knows a software field by its name whatever namespace precedes it.
  The guard that keeps `LibreOffice 25.2.3.2` out of the address list matched
  `Producer` exactly, so `pdf:Producer` walked straight past it - as did
  `exif:GPSVersionID`, which reads 2.2.0.0 in almost every geotagged photograph
  ever taken and has never been an address.

- `filegrail compare A B`: what two files record about themselves that agrees,
  what differs, how each one arrived, and how far apart they claim to have been
  created. Two files can share an earlier life without sharing an acquisition
  path, and that combination - one camera, two routes - says something neither
  file says alone. It reports what agrees; it never concludes that two files are
  "the same".

### Added

- `--explain`, for one file. The report answers *what do we know*; this answers
  *why should I believe it*, which is the question that decides whether a finding
  can be used. It adds no data. It lays out every record under the question it
  answers, names the ones that support each other and the ones that contradict
  each other, and draws the conclusion in sentences - so that a reader can
  disagree with it. A verdict nobody can argue with is a verdict nobody should
  trust.

- Evidence strength replaces the bare number on the meter line: `direct`,
  `inherited`, `credentialed`, `self-reported`, `circumstantial`, `weak`.
  Printing `55` invited it to be read as a probability, which it never was -
  there is no statistical basis for `55`, only a defensible ordering of how
  directly a source knows what it claims. The number still ranks sources against
  each other and still appears in `--json`.
- A download record matched to a file by name is now checked against the size
  the record kept. A size that agrees is corroboration the name alone cannot
  give; one that disagrees very likely means the record is about a different
  file that happens to share the name, and the reconciliation says so.
- The desktop's recently-used list, read from the freedesktop
  `recently-used.xbel` every GTK application writes. It names the application
  that opened a file and when - the graphical equivalent of shell history, and
  ranked just below it, because opening a file proves contact rather than
  acquisition.

- `--doctor`, which reports what this machine can be asked before anything is
  asked of it: which browser profiles are readable and how many records they
  hold, whether this filesystem carries extended attributes (tested, not assumed
  from the platform), whether the shell kept timestamps, whether creation times
  exist, and how far back the browser records reach. `no recorded origin` can
  mean the evidence was searched and the file was not in it, or that the
  evidence was never there to search, and a reader who assumes the first when
  the second is true has drawn a conclusion the tool never supported.

- Reconciliation between acquisition records. Where two independent sources say
  how a file arrived, the report now says whether they agree, agree only about
  the host, or contradict each other, and prints what each one claims. It also
  flags a file whose own metadata reports a creation time *after* it arrived,
  and a download record that was tied to the file by name rather than by path.
  A disagreement brings every acquisition record on screen without `--verbose`,
  because a verdict that refers to evidence the report hid is not a verdict. A
  single uncorroborated record - the ordinary case - is left unannotated, since
  a label on every entry says nothing. `--json` carries the verdict too.

### Fixed

- A downloaded file no longer loses everything it recorded about itself. Claims
  were ranked against each other by confidence and only the winner printed, so a
  browser download record (90) silently deleted a camera's EXIF (55) - and with
  it the capture time, the body serial number and the GPS fix, which is usually
  the most valuable thing in the file. Acquisition and intrinsic provenance
  answer different questions and are now both printed, acquisition first.
  `--verbose` still shows every claim.

### Changed

- Nothing in the report is truncated any more. A value too long for the line
  wraps onto the next one instead of ending in an ellipsis - the file name, the
  origin, the source line, every labelled fact and every field. A cut-off value
  is one the reader has to go and fetch another way, which defeats having read
  the file at all.
- Every decoded field is printed by default, as a tree (`+-` / `\\-`) hanging off
  the claim it belongs to. `--full` is gone; `--brief` collapses the tree back to
  a summary for anyone scanning a large tree.
- Gutter glyphs are padded to a common width. The ASCII arrow is `<-`, two
  characters, so the left edge previously stepped sideways in ASCII mode and one
  wrapped line ran a column past the terminal width.

### Fixed

- HEIC, HEIF and AVIF now yield their EXIF. The reader took the first
  `Exif\0\0` in the file, but encoders write that as the item type in the
  `infe` entry, so it found the item table and decoded nothing — every file in
  the family came back empty. It now scans on until a TIFF header follows the
  marker. A Nokia 8.3 sample that previously reported nothing now reports its
  software, its capture time and its GPS coordinates.
- The SVG generator comment is read again. Its pattern held `{3,120?}`, which
  is not a quantifier — the `?` sits inside the braces — so Python matched the
  literal text and the Illustrator and Matplotlib comments never resolved. Only
  the Inkscape attribute path was tested, so a green suite hid it.

### Added

- Every metadata field a reader decodes is now kept, not just the handful the
  report summarises. `Origin` carries them structured and named, `--json` always
  includes them, and `--full` prints them in the terminal. A geotagged JPEG went
  from four reported facts to fifty: EXIF integer types were never decoded at
  all, so `BodySerialNumber`, `GPSTimeStamp`, `GPSAltitude` and `Orientation`
  were invisible. PDF now reads `Title`, `Subject` and `Keywords`; OOXML and ODF
  take every property their parts declare, which is where `revision`,
  `lastPrinted`, `TotalTime` and `editing-duration` live. `--redact` sweeps the
  new fields, because a tag like `UserComment` is free text and can hold a
  credential.
- `--identify`, which pulls the emails, domains, URLs, IPv4 addresses,
  cryptographic hashes and geographic coordinates out of the metadata a scan
  already read, deduplicated across files and each one carrying the file and
  field it came from. The detectors are ported from DirSifu (MIT, same author),
  including what they deliberately refuse to match. One rule is new here: a
  dotted quad or a build hash inside a field that names software is a version,
  not an address - this corpus is made of strings like
  `LibreOffice/24.2.7.2$Linux_X86_64`, and the field name is known, so the
  question can be settled rather than guessed.
- `--type` and `--ext`, to narrow a scan to the file types you care about.
  `--type image` beats listing the twenty-five extensions the word stands for,
  and the families are built from the extension sets the readers already
  declare, so teaching a reader a new format also teaches the filter. The filter
  is applied while walking, before a file is opened, hashed or parsed. An empty
  result names the filter rather than reading as "this folder holds nothing".
- A landing screen. `filegrail` with no arguments now introduces itself - name,
  version, author, repository, licence, worked examples and the sources it reads
  with their confidences - instead of silently scanning the current directory.
  Starting an unasked-for scan of wherever the shell happens to be is a surprise,
  and in a home directory an expensive one; the screen says `filegrail .` for the
  folder you are standing in. `--about` prints it again from anywhere. Nothing on
  it waits for input, so it works piped and in a script.
- An interactive front end, `filegrail --menu`, for choosing a view without
  memorising flags. It is printed text and `input()` rather than curses, so it
  keeps the zero-dependency promise and works over SSH and on Windows. It
  refuses to start when output is redirected, and it prints the `filegrail`
  command it is about to run — a menu should make itself unnecessary.
- Legacy Office documents. A `.doc`, `.xls` or `.ppt` is a compound file, and
  the two property-set streams every Office release has written since 1995 give
  the application, the author, the last editor, the company, the title and the
  creation date. Both the regular sector chain and the mini stream are followed,
  because a spreadsheet pads its summary to the cutoff while a Word document
  does not. Still no runtime dependency: the container reader is standard
  library throughout.
- `tests/test_corpus.py`, which runs against real files in `test-data/` when
  that directory exists and skips when it does not. It asserts that a decodable
  EXIF payload, or a compound document's summary, never comes back empty,
  whatever container holds it. Both fixes above are the class of defect a
  synthetic fixture cannot reach.

### Changed

- Redesigned the terminal report, and wrote the system down in
  [`DESIGN.md`](docs/DESIGN.md) so it can be argued with. Entries are bound together
  by a one-character gutter (`●` a file, `←` its origin, `│` a continuation)
  instead of drifting indentation; colour now encodes only *which class of
  source* made a claim, so five colours learned once let a folder be triaged by
  eye; findings are ordered strongest evidence first, and grouped under headings
  once a class actually collects more than one file. The summary is an aligned
  table rather than a run-on line, and the masthead carries a coverage meter.
- Colour depth is detected rather than assumed: TrueColor when `COLORTERM` says
  so, 256 otherwise, and a 16-colour fallback for terminals that have neither.
- No rendered line can exceed the terminal width. Every right-aligned column now
  clips the text beside it first, which is enforced across six widths and both
  glyph sets by `tests/test_layout.py` — a wrapped line was previously possible
  on a narrow window and nothing would have caught it.
- Timestamps in the unexplained-files column are trimmed to the second.
- Renamed the project to `filegrail`. The previous name was crowded on GitHub,
  including one repository that is the same tool by concept.
- `--no-recurse` is listed in the README, having been implemented but not
  documented.

## 0.1.0

The first working version. It reconstructs where files came from by reading
records that already exist, rather than asking anyone to wrap their commands.

### Sources

- Browser download history for the Chromium family and Firefox: originating
  page, referrer, redirect chain, timestamp and size. Profiles are copied before
  being read, so a running browser is neither disturbed nor modified.
- Operating system origin metadata: the Windows `Zone.Identifier` stream, the
  macOS `kMDItemWhereFroms` attribute and the Linux `user.xdg.origin.url`
  extended attribute.
- Archive membership, so files extracted from a downloaded archive inherit its
  origin instead of losing it.
- Embedded metadata from more than twenty formats: EXIF for JPEG, TIFF and its
  raw variants, WebP and HEIC, **including GPS coordinates**; PNG text chunks,
  which carry the producing software and the prompt recorded by generative
  tools; MP4 and MOV atoms; PDF `Info` dictionaries, including compressed object
  streams; Office Open XML and OpenDocument; EPUB, RTF, SVG, Jupyter notebooks
  and ID3 frames.
- C2PA Content Credentials, read from the JUMBF manifest in PNG and JPEG, which
  report the producing application and whether a model generated the file. The
  signature is not verified and every claim says so.
- Shell history, at low confidence, as corroboration only.
- Filesystem creation and modification times, via `statx(2)` on Linux.

### Output

- A styled terminal report, hand-rolled so the tool keeps no runtime
  dependencies, degrading to the same layout in plain text when piped, under
  `NO_COLOR` or `TERM=dumb`, and to ASCII where the glyphs cannot be printed.
- `--json` for machine-readable output, `--timeline` for a chronological view,
  `--unknown-only` for files nothing accounts for.
- `--redact`, which strips credentials from URLs, referrers and commands and
  replaces each with a short non-reversible fingerprint.
- An explanation when nothing matches, rather than a bare zero, because a
  pruned browser history is missing evidence and not a malfunction.
