<div align="center">

[![PyPI](https://img.shields.io/badge/pypi-v0.45.0-3775A9?style=flat-square)](https://pypi.org/project/filegrail/) ![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-9A6700?style=flat-square) ![93 formats](https://img.shields.io/badge/formats-93-8250DF?style=flat-square) ![Runtime dependencies](https://img.shields.io/badge/runtime_dependencies-0-00897B?style=flat-square) ![Local and read-only](https://img.shields.io/badge/local_%26_read--only-yes-1F883D?style=flat-square) [![CI](https://github.com/osintshifu/filegrail/actions/workflows/ci.yml/badge.svg)](https://github.com/osintshifu/filegrail/actions/workflows/ci.yml) ![License](https://img.shields.io/badge/license-Apache--2.0-BC4C00?style=flat-square)

</div>

<br>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/osintshifu/filegrail/master/assets/filegrail-mark-04-plate-ondark-512.png">
  <img align="left" hspace="28" src="https://raw.githubusercontent.com/osintshifu/filegrail/master/assets/filegrail-mark-04-plate-onlight-512.png" alt="FileGrail logomark" width="112">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/osintshifu/filegrail/master/assets/filegrail-wordmark-ondark.svg">
  <img src="https://raw.githubusercontent.com/osintshifu/filegrail/master/assets/filegrail-wordmark-onlight.svg" alt="FileGrail" width="160">
</picture>

**LOCAL FILE INTELLIGENCE**<br>Provenance → Metadata → Investigative Pivots.<br><em>Runs locally. Keeps every finding tied to its source.</em>

<br clear="left">
<br>

<div align="center">

[Quick start](#quick-start) · [Why FileGrail](#why-filegrail) · [Evidence model](#evidence-model) · [Sources](#evidence-sources) · [Metadata](#embedded-metadata) · [Formats](#supported-formats) · [Content](#document-content) · [Pivots](#investigative-pivots) · [Analysis](#analysis-and-correlation) · [Reports](#html-investigation-reports) · [CASE](#caseuco-export) · **[Live HTML report](https://osintshifu.github.io/filegrail/example-report.html)** · [Images](#digital-image-examination) · [Usage](#usage) · [Automation](#automation-and-exports)

</div>

---

FileGrail is a local file intelligence tool for reconstructing file provenance, extracting structured metadata and embedded telemetry, surfacing investigative pivots, and finding evidence-backed relationships between files.

It combines what a file says about itself with what the surrounding system recorded about it: browser downloads, operating-system attributes, shell history, archives, torrent stores, recent-file records, synchronization context, filesystem timestamps, document history, embedded identifiers and other available sources.

FileGrail preserves **where a finding came from, how it was associated with the file, where inside the evidence it was found, and where independent sources support or contradict each other**.

Analysis stays local and makes no network requests. The structural core requires **zero runtime dependencies**; bounded pixel diagnostics are an explicit optional extra.

Files being examined are never modified. Metadata removal, when explicitly requested with `filegrail clean`, is performed on separate copies and the result is scanned again.

---

## Why FileGrail

FileGrail is designed to answer investigative questions about a file, not only to list the metadata stored inside it:

> Where did the file come from?

> How did it reach this machine?

> What does the file record about its author, device, software, location and history?

> What did the operating system or another application record about the same file?

> Do those independent records agree?

> What identifiers inside the file can be followed further?

> Which other files share the same camera, author, document lineage, archive, torrent, hash or investigative pivot?

A single file is examined across several independent evidence layers instead of being treated as an isolated container.

| Investigation question | FileGrail can use |
| --- | --- |
| **Where did this file come from?** | Browser history, `Zone.Identifier`, macOS Where From, quarantine records, XDG attributes, shell fetch commands, archive membership, torrent stores, `yt-dlp` sidecars, mail delivery headers |
| **What does the file reveal about itself?** | EXIF, XMP, IPTC, C2PA, document properties, PDF structures, OLE/CFB structures, media tags, telemetry, mail headers, PE resources, font tables and more |
| **What happened to it locally?** | Recent-file records, Windows shortcuts, trash metadata, sync context and filesystem timestamps |
| **What can I pivot on?** | URLs, domains, IP addresses, accounts, hashes, hostnames, message IDs, wallet addresses, infrastructure identifiers, people, organizations and many other structured values |
| **What is connected?** | Shared identifiers, camera serials, authors, XMP derivation, archives, torrents, hashes and graph relationships |
| **Where does the evidence disagree?** | Conflicting origins, inconsistent timestamps, metadata disagreements, size mismatches, C2PA hard-binding failures and weaker association methods |

FileGrail does not automatically turn recorded metadata into attribution.

A camera model is not a person.  
An author field is not identity proof.  
A filename match is not an exact-path match.  
A C2PA claim is not automatically a trusted claim.  
A timestamp written by an application is not automatically ground truth.

Those distinctions are preserved in the output.

---

## Evidence model

FileGrail keeps different types of evidence separate because they answer different questions.

### Origin

Evidence describing how the file reached the examined environment.

Examples:

- browser download history;
- Windows `Zone.Identifier`;
- macOS Where From and quarantine records;
- Linux XDG origin attributes;
- shell commands that fetched a file;
- archive or torrent membership;
- `yt-dlp` sidecars;
- delivery headers of a saved message;
- messenger file-name patterns, kept as weak associations.

### Metadata

Information stored inside the file itself.

Examples:

- camera and lens information;
- GPS coordinates;
- document authors and editors;
- creation and modification timestamps;
- generating software;
- PDF structures;
- XMP history;
- C2PA manifests;
- media tags;
- PE version resources;
- embedded telemetry;
- mail headers and relay hops;
- the file signature compared with the extension;
- the file format identified from its bytes, as a PRONOM PUID.

### Activity

Evidence showing that the local environment handled the file.

Examples:

- Windows Recent shortcuts;
- Linux Recent Documents;
- trash records;
- synchronization roots;
- filesystem creation and modification times;
- shell commands that referenced the file without fetching it.

### Content

What the document actually says rather than what it records about itself.

With `--pivots`, FileGrail reads supported document text and structured content and passes it through the same investigative-pivot detectors used for metadata. `--meta` keeps the search to metadata and provenance, `--content` to the document text.

The source text itself is not added to the report.

### Relationships

Evidence-backed links between files and other entities.

Examples:

- file -> email address;
- file -> domain;
- file -> camera serial;
- file -> author;
- file -> archive;
- file -> torrent;
- file -> SHA-256;
- file -> XMP-derived file;
- email address -> domain;
- URL -> host.

### Corroboration and conflicts

Independent sources can support each other or disagree.

FileGrail keeps both instead of choosing one automatically.

A browser timestamp, EXIF capture time, XMP creation date and filesystem birth time are separate observations, even when they describe the same file.

---

## Match basis

Every evidence record preserves **how it became associated with the file**.

Different association methods have different investigative meaning.

| Match basis | Meaning |
| --- | --- |
| `embedded` | Read directly from the file |
| `file-attribute` | Attached to this exact file by the filesystem or operating system |
| `recorded-path` | An external record contains the file's path |
| `sidecar` | A separate file associated by naming convention |
| `name+size` | File name and exact size both match |
| `filename` | Only the file name matches |
| `container-member` | Read from or associated through an archive/container member |
| `sync-root` | The file is located inside a supported synchronized directory |

A filename-only association is therefore not presented as equivalent to an operating-system attribute attached to the file itself.

---

## Quick start

Requires Python 3.10+ on Linux, macOS or Windows.

Install with `pipx`:

```bash
pipx install filegrail
```

or:

```bash
uv tool install filegrail
```

Analyze one file:

```bash
filegrail suspicious.pdf
```

Analyze a directory recursively:

```bash
filegrail ./evidence
```

Extract investigative pivots from provenance, metadata and document content:

```bash
filegrail ./evidence --pivots
```

Pivots from provenance and metadata only, no document opened:

```bash
filegrail ./evidence --pivots --meta
```

Build a timeline:

```bash
filegrail ./evidence --timeline
```

Create a self-contained HTML investigation report:

```bash
filegrail ./evidence --pivots --html -o report.html
```

[View an example HTML report](https://osintshifu.github.io/filegrail/example-report.html), built from an invented case.

---

## What an investigation can look like

### Downloaded document

A document can connect:

```text
browser download record
        ↓
original URL and referrer
        ↓
local file
        ↓
OOXML / PDF / OLE metadata
        ↓
author · last editor · software · timestamps
        ↓
URLs · emails · domains · identifiers in content
```

### Photograph

A photograph can connect:

```text
local origin evidence
        ↓
image
        ↓
EXIF · XMP · IPTC · C2PA
        ↓
camera model · body serial · GPS · software · edit history
        ↓
other files sharing the same device or metadata identifiers
```

### Extracted archive member

```text
archive download origin
        ↓
ZIP / TAR member
        ↓
name + exact uncompressed size
        ↓
extracted file
        ↓
embedded metadata and investigative pivots
```

### PDF

```text
origin evidence
        ↓
PDF
        ↓
document identifiers · creator · producer
        ↓
incremental updates · forms · actions · attachments · signatures
        ↓
page text
        ↓
investigative pivots
```

FileGrail keeps each step tied to the evidence that produced it.

---

## Evidence sources

FileGrail combines evidence embedded inside files with traces stored elsewhere on the examined system.

### Provenance and local activity

What can be recovered depends on which local records still exist.

| Source | Information read |
| --- | --- |
| **Chromium-family browser history** | Download URL, referrer, timestamp, recorded path and recorded size from Chrome, Chromium, Brave, Edge and Vivaldi |
| **Firefox history** | Download URL, timestamp, recorded path and size where available |
| **Windows `Zone.Identifier`** | `HostUrl`, `ReferrerUrl`, `ZoneId` |
| **macOS Where From** | Origin URL and referrer from `kMDItemWhereFroms` |
| **macOS quarantine** | Origin, referrer, downloading application and quarantine time |
| **Linux XDG attributes** | `user.xdg.origin.url`, `user.xdg.referrer.url` |
| **Shell history** | Fetch commands such as `curl`, `wget`, `yt-dlp`, `aria2c`, `scp`, `rsync`, `git`, `gh`, `aws`; other commands naming a file are retained as activity |
| **Archives** | Member names and sizes; extracted files can be matched back to archive members |
| **Embedded files** | Attachments in `.eml` and `.msg` messages, files attached to a PDF and objects packaged in Office documents, each read as a file of its own with the carrier as its parent |
| **Torrent files** | Trackers, client, comment, info hash, magnet link and member information |
| **Torrent client stores** | qBittorrent, Transmission and Deluge local torrent records |
| **`yt-dlp` sidecars** | Page URL, uploader, channel, publication date, extractor and fetch time |
| **Linux Recent Documents** | Recently opened paths |
| **Windows Recent shortcuts** | `.lnk` records associated with previously opened files |
| **Sync folders** | Nextcloud, Dropbox, Syncthing and OneDrive account/root context |
| **Freedesktop trash** | Original path and deletion time |
| **Filesystem** | File creation and modification timestamps |
| **Messenger naming patterns** | WhatsApp and Telegram Desktop file-name patterns, explicitly treated as weak associations |

Inspect the evidence sources available on the current system:

```bash
filegrail doctor
```

Analyze a copied profile, mounted user directory or another evidence set:

```bash
filegrail doctor --home /mnt/profile
filegrail /mnt/evidence --home /mnt/profile
```

Without `--home`, FileGrail reads supported records from the profile of the user running the command.

Shell history can be excluded:

```bash
filegrail ./evidence --no-shell-history
```

### Evidence coverage

A missing result is not the same thing as a source having been checked successfully.

The JSON output records the state of every evidence source as `searched`, `unavailable`, `partial` or `disabled`, together with:

- artifacts found;
- records read;
- unreadable paths;
- skipped paths;
- effective profile;
- active scan options.

The same coverage accompanies graph exports, so downstream analysis can tell a source that was searched and held nothing from a source that could not be searched.

---

## Embedded metadata

FileGrail keeps original field names and exposes decoded fields instead of reducing everything to a small normalized subset.

A camera body serial may connect images to one physical device.  
A PDB path may expose a build environment.  
An Office template path may identify an internal share.  
A PDF document ID can link revisions or derived files.  
A telemetry track can reveal movement even when ordinary GPS metadata is absent.

`--brief` reduces the presentation. JSON keeps the full structured result.

| Metadata block | Extensions | Data extracted |
| --- | --- | --- |
| **EXIF** | `.jpg` `.jpeg` `.jpe` `.tif` `.tiff` `.dng` `.nef` `.cr2` `.arw` `.orf` `.rw2` `.webp` `.heic` `.heif` `.avif` | Camera, lens, software, capture time and GPS; JPEG JFIF/JFXX and ICC profile metadata |
| **Photoshop resources** | `.jpg` `.jpeg` `.jpe` `.tif` `.tiff` `.psd` `.psb` | Resolution, JPEG settings, embedded-thumbnail descriptors, paths, workflow URLs and version information |
| **PNG text** | `.png` `.apng` | Software, creation time, author and other text stored in the image; camera, capture time and the other EXIF tags of an `eXIf` chunk |
| **ISO BMFF** | `.mp4` `.m4v` `.mov` `.qt` `.3gp` `.m4a` `.heic` `.heif` `.avif` | Encoder or recording device, creation time and location, including the `mdta` keys a phone writes; every track with its format and language, and whether a timecode track is present; GoPro firmware, lens and camera serial; a GPMF or CAMM telemetry track summarised as device, streams and GPS track |
| **Matroska** | `.mkv` `.mk3d` `.webm` `.mka` | Writing application, creation date and tags |
| **RIFF/BWF** | `.wav` `.wave` `.rmi` `.avi` | Info fields such as title and software, recorder information, coding history and ID3 tags where present |
| **Vorbis comments** | `.flac` `.ogg` `.oga` `.opus` `.spx` | Encoder and every tag |
| **AIFF** | `.aif` `.aiff` `.aifc` | Name, author, copyright and annotations, sound description and ID3 tags where present |
| **APE tag** | `.ape` `.mpc` `.wv` `.ofr` | Encoder, artist, title, year and every other text tag |
| **ID3** | `.mp3` `.aac` `.tta` | Encoding software, artist, title, date and other tags |
| **PDF Info** | `.pdf` | Producer, creator, author, title, subject, keywords and dates; incremental updates and what each replaced or added, document IDs, encryption, attachments, scripts, forms, link targets and signatures |
| **OOXML properties** | `.docx` `.docm` `.dotx` `.xlsx` `.xlsm` `.xltx` `.pptx` `.pptm` | Application, author, last editor, company, template, revision count and editing time; links outside the package such as templates, workbooks and hyperlinks; DDE fields |
| **OLE properties** | `.doc` `.dot` `.xls` `.xlt` `.ppt` `.pot` `.pps` `.msg` | Summary properties, storage metadata, orphaned entries, VBA/XLM indicators and embedded-object paths |
| **OpenDocument metadata** | `.odt` `.ods` `.odp` `.odg` `.odf` `.ott` `.otp` | Generating application, author, title, creation date and editing statistics |
| **EPUB package** | `.epub` | Generating application, author, title and date |
| **RTF metadata** | `.rtf` | Generating application |
| **SVG metadata** | `.svg` | Generating application and author |
| **Jupyter notebook** | `.ipynb` | Kernel, language version and author |
| **PE header** | `.exe` `.dll` `.sys` `.scr` `.ocx` `.cpl` `.drv` `.efi` | Target machine, linker, link time, PDB path, Rich header records, company, product, original file name and version strings, and whether a signature is attached |
| **Font tables** | `.ttf` `.otf` `.ttc` `.otc` `.woff` | Family, designer, foundry, version, licence, creation and modification times, vendor identifier and variation axes |
| **Maker notes** | `.jpg` `.jpeg` `.jpe` `.tif` `.tiff` `.dng` `.nef` `.cr2` `.arw` `.orf` `.rw2` `.webp` `.heic` `.heif` `.avif` | The vendor block beside the EXIF, where most cameras write the identity standard EXIF leaves blank: body serial number, lens serial number and model, shutter count, firmware version, frame number, and the owner name typed into the camera. Apple adds the identifiers that tie a Live Photo's still and film together, and a trail camera the event and frame numbers that put a season of captures in order. A note holding a picture instead of a directory is read as a preview; one that only points at a preview is reported, including when the file no longer contains it. A block this reader cannot place is reported as present rather than guessed at |
| **Web document** | `.html` `.htm` `.xhtml` | Author, publisher, dates, canonical URL, Open Graph, Twitter Cards, JSON-LD, Microdata and RDFa |
| **C2PA** | `.3gp` `.arw` `.avi` `.avif` `.cr2` `.dng` `.heic` `.heif` `.jpeg` `.jpg` `.m4a` `.m4v` `.mov` `.mp3` `.mp4` `.nef` `.orf` `.png` `.qt` `.rmi` `.rw2` `.svg` `.tif` `.tiff` `.wav` `.wave` `.webp` | Producing application, creation data, digital source type such as a generative AI model, the recorded actions and ingredients, and whether the file still matches its manifest |

XMP, XMP history and IPTC are not tied to one format and are read wherever a supported file carries them.

| Block | Data extracted |
| --- | --- |
| **XMP** | Creating application, author, title, document IDs and derivation information |
| **XMP history** | Recorded editing steps and timestamps |
| **IPTC** | By-line, credit, source, copyright, headline, caption, keywords, place and creation date |

Presence of VBA storage, XLM macro sheets, JavaScript, a PDF action or another active-content indicator is reported as an observation. FileGrail does not classify a document as malicious.

### C2PA interpretation

A C2PA manifest is reported with the state of its hard binding:

- the asset still matches its manifest;
- the asset no longer matches its manifest;
- the binding could not be checked.

The claim signature is always marked as not verified. FileGrail does not validate the C2PA certificate chain and does not present the signer as trusted.

### Executables

PE/COFF files (`.exe` `.dll` `.sys` `.scr` `.ocx` `.cpl` `.drv` `.efi`) can yield:

- target machine and subsystem;
- linker version and link timestamp;
- CodeView/PDB path, PDB GUID and age;
- Rich header records;
- version-resource strings: company, product, original file name, file and product versions;
- presence of an Authenticode signature.

An attached Authenticode signature is reported as present. Its trust chain is not verified.

### Fonts

Font files (`.ttf` `.otf` `.ttc` `.otc` `.woff`) can yield:

- family and subfamily;
- designer, manufacturer and foundry;
- version;
- licence and licence, vendor and designer URLs;
- creation and modification times;
- vendor identifier;
- embedding rights;
- variable-font axes;
- WOFF metadata where present.

### Web documents

HTML and XHTML documents can yield author, publisher, publication and modification dates, canonical URL, Open Graph, Twitter Cards, JSON-LD, Microdata and RDFa.

FileGrail does not fetch linked resources.

---

## Email

Saved email is treated differently from ordinary document metadata because parts of the message record its transport.

### EML

FileGrail can read:

- `Received:` hops;
- connecting addresses;
- message identifiers;
- sender-provided headers;
- the message body, for content pivots.

The topmost `Received:` hop is kept distinct from lower hops: it was written by the receiving infrastructure, the rest travelled with the message.

### MSG

Outlook `.msg` files can expose:

- transport headers where present;
- selected MAPI message properties;
- OLE/CFB metadata;
- the message body;
- embedded compound-file structures.

Where an Exchange message does not contain internet transport headers, FileGrail does not invent a delivery route.

---

## Archives and containers

FileGrail uses archives in two ways:

1. supported files inside them are read as files of their own;
2. extracted files are connected back to the archive they likely came from.

Supported archive families: ZIP, JAR, WHL, TAR, TGZ, GZ, BZ2, XZ.

A member that carries evidence is reported as a file inside the archive, with its own size, time and evidence, the archive as its parent and the archive's origin inherited as its own. Nothing is unpacked to the scanned directory.

A member's metadata remains the member's. A photograph taken in 2018 does not make the ZIP containing it a 2018 archive, and the photograph's GPS fix is not the archive's location.

Extracted files are matched back to a member by file name and exact uncompressed size.

---

## Torrents

A `.torrent` file is treated as a provenance and container artifact.

FileGrail can extract:

- trackers;
- creating client;
- comment;
- member names and sizes;
- BitTorrent info hash;
- magnet link.

Torrent membership can also be recovered from qBittorrent, Transmission and Deluge client stores.

---

## Sidecars

`yt-dlp` `.info.json` sidecars can provide:

- page URL;
- uploader;
- channel;
- upload or publication date;
- extractor;
- fetch time.

The publication date and the local fetch event are kept separate because they describe different events.

---

## Supported formats

A format supported for metadata extraction is not automatically supported for content inspection, cleaning or every other operation.

| Family | Examples |
| --- | --- |
| **Images** | JPEG, PNG, APNG, TIFF, WebP, HEIC, HEIF, AVIF, PSD, PSB and supported RAW formats including DNG, NEF, CR2, ARW, ORF and RW2 |
| **Documents** | PDF, DOCX, DOCM, XLSX, XLSM, PPTX, PPTM, legacy Office, OpenDocument, RTF, EPUB, Jupyter notebooks |
| **Video and audio** | MP4, MOV, M4V, M4A, 3GP, MKV, WebM, WAV, AIFF, AVI, FLAC, OGG, Opus, MP3, APE, Musepack, WavPack |
| **Executables** | EXE, DLL, SYS, SCR, OCX, CPL, DRV, EFI |
| **Fonts** | TTF, OTF, TTC, OTC, WOFF |
| **Email** | EML, MSG |
| **Archives** | ZIP, JAR, WHL, TAR, TGZ, GZ, BZ2, XZ |
| **Text and structured data** | TXT, Markdown, reStructuredText, JSON, NDJSON, YAML, TOML, INI, CSV, TSV, HTML, XML |
| **Geospatial data** | GPX, KML, KMZ, GeoJSON |
| **Personal-information formats** | vCard, iCalendar |
| **Investigation and graph data** | GEXF, GraphML, XMind, FreeMind, JSON Canvas, Maltego MTGX |
| **Provenance artifacts** | `.torrent`, `yt-dlp` `.info.json` |

A complete mapping of formats, readers, metadata blocks, signature recognition and pivot-detection rules is maintained in [docs/FORMATS.md](docs/FORMATS.md).

### File signature checks

An extension is only a file-name claim.

For supported signatures, FileGrail compares the extension against the bytes actually present at the beginning or in the structure of the file, and reports a mismatch only where the two disagree.

Recognized families: JPEG, PNG, GIF, TIFF, WebP, PDF, RTF, ZIP, gzip, bzip2, XZ, Zstandard, 7-Zip, RAR, TAR, OLE Compound File, ISO Base Media, Matroska, Ogg, FLAC, MP3, WAV, AVI, SQLite, ELF, Windows PE, Mach-O, HTML, SVG, XML.

A format legitimately built on another container is not a mismatch: DOCX, EPUB and JAR are ZIP files. Unknown bytes are not treated as suspicious.

### Format identification

Every scanned file is identified from its bytes against [PRONOM](https://www.nationalarchives.gov.uk/PRONOM/), the file format registry of The National Archives (UK). The result is the format's PUID, name and version, for example `fmt/412 Microsoft Word for Windows 2007 onwards`. DROID, Siegfried and digital archives use the same identifiers, so a result can be compared with theirs directly.

- Office documents, OpenDocument files, EPUBs and other formats built on ZIP or OLE2 are named by what the container holds, not as a generic ZIP or compound file.
- The first and the last 64 KiB of each file are read, as in DROID's default settings.
- A file whose bytes match no signature gets no format. Nothing is guessed from the extension.
- Where the registry cannot tell two formats apart, both are listed.
- Files inside archives are not identified.

The report shows the format beside the type in the file details and in `compare`. JSON gives it as `formats` on each file, and `run.format_registry` names the registry release that was used.

The registry data contains public sector information licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).

---

## Document content

`--pivots` extracts pivots from the readable content of supported files as well as from provenance and metadata. `--content` narrows the search to the content, `--meta` to provenance and metadata.

```bash
filegrail ./case --pivots --content
```

The source text itself is not added to the report. Only detected identifiers and their locations are retained.

At most 1 MB of text is read from one file, and at most 64 parts of one document, such as slides or chapters.

| Extensions | Content read | Location reported as |
| --- | --- | --- |
| `.txt` `.text` `.md` `.markdown` `.rst` `.log` | Text | `line 12` |
| `.json` `.ndjson` `.jsonl` `.ipynb` `.yaml` `.yml` `.toml` `.ini` `.cfg` `.conf` `.vcf` `.ics` `.canvas` | Text | `line 12` |
| `.csv` `.tsv` | Each cell | `row 4 · column 3` |
| `.html` `.htm` `.xhtml` `.xml` `.svg` `.graphml` | Visible text and links | `line 12` |
| `.gpx` `.kml` | Names, links, named points and the start and end of every track | `line 12`, `waypoint 3`, `track 1 start`, `placemark 2` |
| `.geojson` | Text, every point and the start and end of every line | `line 12`, `feature 1`, `feature 1 end` |
| `.gexf` `.mm` | Visible text, links and node labels | `line 12` |
| `.pdf` | The text of each page | `page 7` |
| `.docx` `.docm` `.dotx` | Body, footnotes, endnotes and comments | `body`, `footnotes`, `endnotes`, `comments` |
| `.xlsx` `.xlsm` `.xltx` | Cell text | `cell text`, `sheet 2` |
| `.pptx` `.pptm` | Slide text and notes | `slide 4`, `slide 4 notes` |
| `.odt` `.ods` `.odp` `.odg` `.odf` `.ott` `.otp` | Document body, headers and footers | `body`, `headers and footers` |
| `.epub` | Chapters | chapter file name |
| `.kmz` | Embedded KML names, links and positions | `map`, `placemark 2` |
| `.xmind` | Map topics | `body` |
| `.mtgx` | Entities and their values from every graph | `graph 1` |
| `.eml` `.msg` | Message body, every text part | `body`, `body (html)` |

Encrypted PDFs are not treated as readable plaintext.

Scanned PDF pages contain images of text. FileGrail does not perform OCR.

---

## Investigative pivots

Values from metadata, provenance and content are normalized into identifiers that can be correlated across files.

```bash
filegrail ./case --pivots
```

Extracts pivots from metadata, provenance and supported document content.

```bash
filegrail ./case --pivots --meta
```

Metadata and provenance only, no document opened. `--content` is the opposite: document content only.

Each result can preserve:

- type;
- original value;
- normalized value;
- source file;
- evidence source;
- metadata field or document location;
- occurrence count;
- corpus;
- relationship to other graph entities.

Values found in more than one file are surfaced as shared pivots.

### Supported pivot classes

Network and web:

- `url`
- `domain`
- `hostname`
- `ipv4`
- `ipv6`
- `asn`
- `onion`
- `tracker`

Identity and accounts:

- `email`
- `person`
- `org`
- `handle`
- `message_id`

Cryptographic and security identifiers:

- `md5`
- `sha1`
- `sha256`
- `sha512`
- `cve`
- `cwe`
- `ghsa`

Host and Windows artifacts:

- `path`
- `registry`
- `sid`
- `executable`
- `mac`

Geographic and physical identifiers:

- `geo`
- `postcode`
- `vin`

Financial, tax and company identifiers:

- `iban`
- `bic`
- `aba`
- `vat`
- `nip`
- `regon`
- `ein`
- `crn`
- `cik`

Cryptocurrency:

- `btc`
- `bch`
- `ltc`
- `doge`
- `xmr`
- `eth`

Sensitive values:

- `secret`
- `ssn`

Secrets and US Social Security numbers are represented by type and fingerprint rather than being exposed as raw values.

Detectors apply validation and contextual filtering to reduce common false positives such as:

- software versions mistaken for IP addresses;
- file names mistaken for domains;
- arbitrary hexadecimal strings mistaken for hashes;
- unlabelled numeric identifiers;
- invalid cryptocurrency addresses.

Detection rules for every type are documented in [docs/FORMATS.md](docs/FORMATS.md).

---

## Analysis and correlation

### Timeline

```bash
filegrail ./case --timeline
```

Combines dated observations from:

- origin records;
- embedded metadata;
- local activity;
- XMP history;
- filesystem timestamps;
- mail;
- supported application records.

Timestamps with different UTC offsets are ordered by the instant they represent.

The original evidence source remains attached to each event.

### Corroboration

Independent records describing the same event or origin strengthen the investigative context.

Examples:

- browser history and `Zone.Identifier` naming the same source;
- several metadata blocks recording the same creator;
- the same camera serial appearing across multiple images;
- a URL in document content also appearing in provenance evidence.

FileGrail records the observations. It does not convert correlation into attribution.

### Conflicts

Where evidence disagrees, FileGrail keeps the disagreement visible.

Examples include:

- conflicting origin URLs;
- recorded size versus actual file-size mismatch;
- weak filename-only association;
- a file claiming creation after its arrival;
- creation and modification dates in impossible order;
- XMP editing steps out of chronological sequence;
- EXIF, IPTC or PDF metadata conflicting with XMP;
- C2PA hard-binding failure;
- file extension contradicting recognized file structure.

Conflict reporting identifies material worth reviewing. It does not decide which source is true.

---

## File relationships and lineage

### XMP document lineage

FileGrail uses XMP identifiers such as:

- `xmpMM:DocumentID`
- `xmpMM:InstanceID`
- `xmpMM:OriginalDocumentID`
- `xmpMM:DerivedFrom`

to connect files across editing, export, renaming and derived renditions.

Relationships are reported as:

- `derived from` and `source of`;
- `descends from` and `original of`;
- `same document`;
- `common ancestor`.

`derived from` and `source of`, like `descends from` and `original of`, are given from both ends, so a file names what it came from and a master names what came from it. `same document` and `common ancestor` read the same from either file, so each pair is connected once rather than twice.

A shared original identifier is not presented as direct derivation, because files generated from the same template legitimately share an ancestor.

### Clustering

```bash
filegrail ./photos --cluster
```

Files are grouped around the values they share:

- **camera body serial**: a shared serial indicates the same recorded physical camera;
- **lens serial**: a shared serial indicates the same recorded physical lens, which may have been mounted on more than one body;
- **camera model**: a shared make and model identifies a device class, not one device;
- **author**: a shared recorded author connects documents carrying the same metadata value, which does not prove that the same person created them.

### Compare

```bash
filegrail compare original.docx edited.docx
```

Compares two files across identifying metadata fields, origin route and capture-time interval.

Useful for examining edited copies, exports, renamed files, document revisions and sanitized versus original material.

### Explain

```bash
filegrail explain document.pdf
```

Shows the evidence behind the findings associated with one file: source, match basis, decoded fields, timestamps and associated paths or containers.

---

## Evidence graph

FileGrail turns a scan into a graph of files, identifiers, devices, authors and containers.

Relationships retain the evidence behind them.

```text
file
 ├── email
 │    └── domain
 ├── URL
 │    └── domain
 ├── camera serial
 ├── author
 ├── archive
 └── torrent
```

When hashing is enabled, identical files meet at the same SHA-256 node rather than requiring pairwise file-to-file relationships.

Graph edges preserve:

- relationship type;
- direction;
- evidence source;
- evidence category;
- match basis;
- location;
- occurrence count;
- timestamp where available.

### GraphML export

```bash
filegrail ./case --graphml -o graph.graphml
```

Each node carries a readable label and its type, and each relationship carries its type and its occurrence count as a weight, so Gephi, NetworkX and a Neo4j import read the graph without being configured first. yEd draws the shape but shows none of the values: it reads only its own attributes.

### CSV relationship export

```bash
filegrail ./case --graph-csv -o relationships.csv
```

Writes one relationship per row: both endpoints with their type and label, the kind of relationship, its occurrence count as a weight, and the evidence behind it. The evidence is given both as columns a tool can filter on and in full, so each ground keeps its own place, count and time.

What the scan itself was goes in `relationships.csv.meta.json` beside the table, because it belongs to the run and not to any one relationship. `--json` carries the same values.

For spreadsheets, Neo4j `LOAD CSV`, Gephi, Maltego and transformation into other link-analysis formats.

### CASE/UCO export

```bash
filegrail ./case --case-jsonld -o case.json
```

CASE is the exchange format built on the UCO ontology that digital forensic tools use to hand results to one another. It is the only format here with a place for the two things the evidence graph is made of: a relationship is an object that carries its own evidence, and the document records which tool produced it, from what and when.

A relationship supported by two independent grounds stays one relationship with two pieces of evidence, rather than being split or flattened. Where UCO has no class for something FileGrail found, the value is exported as a plain observable carrying the name FileGrail gave it, rather than being fitted into a class that would say something the tool did not find.

Identifiers are the same across runs and claim no more than the evidence supports. A file with a SHA-256 is identified by its content, so two scans anywhere agree on it. A file without one is identified by where it was found, which is a claim about that target only. A filename is never an identity.

The export makes no network request and needs no JSON-LD library. Output is validated against CASE 1.5.0.

FileGrail performs no network enrichment. External enrichment remains downstream of the evidence collection step.

---

## HTML investigation reports

`--html` creates a self-contained investigation report that loads no external assets and makes no network requests.

```bash
filegrail ./case --pivots --html -o report.html
```

The report can contain:

- investigation summary;
- key findings;
- evidence coverage;
- file index;
- decoded evidence for individual files;
- chronological timeline on a spine, grouped by day, with the silences between days named;
- investigative pivots;
- conflicts;
- XMP file relationships;
- evidence graph;
- graph pan and zoom;
- SVG graph export;
- node details;
- relationship explorer;
- graph search and filters;
- graph layouts, spacing and label control, and a full-screen view of the graph;
- sections that fold to their heading;
- sortable tables;
- copy-as-TSV tables;
- cross-links between files, findings, pivots and conflicts;
- full-report search;
- dark theme;
- print layout.

The complete report remains one portable HTML file.

[View the example report](https://osintshifu.github.io/filegrail/example-report.html).

---

## Digital image examination

`filegrail image` examines still images and writes its own report. It runs the same provenance and metadata scan as any other file, adds what the image's own structure records about how it was encoded, and, with the optional pixel extra installed, renders a set of diagnostic views of the picture.

```bash
filegrail image ./photos --out examination.html --case 2026/014 --examiner "J. Nowak"
```

The report is one HTML file that loads no external assets and makes no network requests. Working images and diagnostic renderings go to a directory beside it, so a browser loads only what is on screen.

### Report sections

| Section | What it answers |
| --- | --- |
| Summary | The collection in six figures: images examined, how many have a decodable working image and how many do not, conflicts, review signals and recorded values |
| Images | Every image with its analysis opened under the row it sits in: file facts, metadata fields, evidence coverage, JPEG structure and marker list |
| Findings | Numbered disagreements and review signals, each a link into the image it came from |
| Shared attributes | Images grouped by claimed make, body serial, lens and JPEG encoding fingerprint |
| Dates | Every recorded capture time on one axis, one dot per image |
| Locations | Recorded coordinates as an area map, a local plot and a table |
| Evidence | Every value read, with its category, its source and the basis it was matched on |

### What the structure records

The JPEG pass walks the marker stream to the end of the file: encoding and dimensions, component sampling, quantization and Huffman tables, restart interval, scan count, comments and any bytes after the end marker. Quantization quality is reported as an exact IJG table match or as the nearest estimate, and it describes the tables the file carries now, not its first save.

The EXIF pass walks IFD0, EXIF, GPS, Interoperability, SubIFDs and IFD1, and keeps a valid IFD1 thumbnail for the report.

Where two of those records disagree, the report numbers it as a finding: JPEG dimensions against the ones EXIF states, an embedded preview whose aspect ratio does not match the image, bytes appended after the end marker.

### Analytical outputs

`pip install 'filegrail[photo]'` adds Pillow and NumPy, and with them the pixel diagnostics. Without the extra the report states for each one that it was not evaluated.

| Output | What it makes visible |
| --- | --- |
| Working image | The picture decoded and scaled to a bounded size; every map below is measured from this decode |
| Embedded preview | The small copy the camera wrote inside the file, and the one in the vendor's own block |
| Preview comparison | The embedded preview against the image, where different framing or tone points at a later edit |
| Histogram | How often each value occurs, per channel and in luminance |
| Luminance gradient | How brightness changes from one pixel to the next, as a direction |
| Noise residual | What is left when the picture is taken away and only local variation remains |
| Bit planes | Single bits of the luminance channel, the highest and three of the lowest |
| Error level analysis | The image against itself saved again, at two declared qualities |

Each output states what it shows and what would be a mistake to conclude from it. No result is converted into an authenticity or manipulation score.

### Image options

| Option | Purpose |
| --- | --- |
| `-o`, `--out FILE` | Write the report here; working images and outputs go to a directory beside it |
| `--case REF` | Case reference for the report's title block |
| `--examiner NAME` | Examiner named in the report's title block |
| `--redact` | Redact text and omit every pixel-bearing preview and diagnostic |
| `--embed` | Carry the images inside the page instead of beside it |
| `--image-budget MB` | Megabytes of images one report may produce; default 512, or 16 with `--embed`, and `0` for no limit |
| `--no-recurse` | Do not descend into subdirectories |

An image past the budget keeps every fact read from it and loses only its pictures. SHA-256 is recorded for every image, and `filegrail photo` is accepted as an alias for the same command.

Which containers are selected, and what structural coverage each one gets, are in the [format reference](docs/FORMATS.md#digital-image-examination).

---

## Usage

```text
filegrail <path> [options]
filegrail <command> [options]
```

Running `filegrail` without arguments shows the command overview without starting a scan.

### Commands

| Command | Purpose |
| --- | --- |
| `filegrail PATH` | Analyze a file or directory |
| `filegrail scan PATH` | Explicit scan form |
| `filegrail image PATH --out FILE` | Build a digital image examination report |
| `filegrail explain FILE` | Show the evidence behind one file |
| `filegrail compare A B` | Compare two files |
| `filegrail doctor` | Inspect available local evidence sources |
| `filegrail clean PATH --out DIR` | Write metadata-cleaned copies |
| `filegrail clean PATH --check` | Check what supported metadata would remain |
| `filegrail menu` | Interactive command menu |
| `filegrail help COMMAND` | Command-specific help |
| `filegrail --version` | Print the version |

### Scan options

| Option | Purpose |
| --- | --- |
| `--brief` | Compact summary and file index |
| `-v`, `--verbose` | Expanded file details and decoded fields |
| `--pivots` | Extract investigative pivots from provenance, metadata and document content |
| `--meta` | Pivots from provenance and metadata only; enables pivots |
| `--content` | Pivots from supported document content only; enables pivots |
| `--timeline` | Build the chronological timeline |
| `--cluster` | Group files by supported shared attributes |
| `--unknown-only` | Show only files without evidence found |
| `--hash` | Compute SHA-256 |
| `--type NAME` | Filter by file family |
| `--ext LIST` | Filter by extension |
| `--limit N` | Limit selected result lists |
| `--home DIR` | Read local evidence from another user profile |
| `--redact` | Redact supported credentials before output |
| `-j`, `--json` | JSON output |
| `--html` | Self-contained HTML output |
| `--graphml` | Evidence graph as GraphML |
| `--graph-csv` | Evidence relationships as CSV |
| `--case-jsonld` | Evidence graph as CASE/UCO JSON-LD |
| `-o`, `--out FILE` | Write output to a file |
| `--no-recurse` | Disable recursive directory scanning |
| `--no-skip` | Include normally skipped build/cache/vendor directories |
| `--no-shell-history` | Exclude shell history |
| `--no-archives` | Leave files inside archives, documents and messages unread, and disable inherited archive-origin matching |
| `--color`, `--no-color` | Force or disable ANSI colour |

One output form at a time: `--timeline`, `--json`, `--html`, `--graphml`, `--graph-csv` and `--case-jsonld` exclude one another.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | The command ran successfully; for `clean` and `clean --check`, every copy came out clean |
| `1` | `clean` only: supported metadata remained, or would remain, in at least one copy |
| `2` | Invalid command input, such as a missing path, wrong argument count or unknown option |

---

## Common workflows

| Task | Command |
| --- | --- |
| Trace where a file came from | `filegrail download.pdf` |
| Inspect why a finding exists | `filegrail explain download.pdf` |
| Get a quick directory overview | `filegrail ./case --brief` |
| Extract investigative identifiers | `filegrail ./case --pivots` |
| Skip document content | `filegrail ./case --pivots --meta` |
| Build a timeline | `filegrail ./case --timeline` |
| Find photographs sharing camera metadata | `filegrail ./photos --cluster` |
| Analyze a copied profile | `filegrail /mnt/evidence --home /mnt/profile` |
| Hash every file | `filegrail ./case --hash --json > report.json` |
| Export GraphML | `filegrail ./case --graphml -o graph.graphml` |
| Export graph edges as CSV | `filegrail ./case --graph-csv -o relationships.csv` |
| Produce a shareable redacted report | `filegrail ./case --pivots --redact --html -o report.html` |
| Check metadata before publishing | `filegrail clean ./publish --check` |

---

## Metadata removal

```bash
filegrail clean ./publish --out ./clean
```

FileGrail writes cleaned copies. Original files are not modified.

### Cleanable formats

| Family | Extensions |
| --- | --- |
| **JPEG** | `.jpg` `.jpeg` `.jpe` |
| **PNG** | `.png` `.apng` |
| **SVG** | `.svg` |
| **ISO BMFF media** | `.mp4` `.m4v` `.m4a` `.mov` `.qt` `.3gp` |
| **Microsoft OOXML** | `.docx` `.docm` `.dotx` `.xlsx` `.xlsm` `.xltx` `.pptx` `.pptm` |
| **OpenDocument** | `.odt` `.ods` `.odp` `.odg` `.ott` `.otp` |

Removed: EXIF, XMP, IPTC, Content Credentials, text and comment blocks, document properties and the timestamps a container records about itself. Pixels, vector paths, audio and video streams are left as they are.

Check the expected result without writing files:

```bash
filegrail clean ./publish --check
```

After a copy is cleaned, FileGrail scans it again and reports supported metadata that remains.

### Cleaning options

| Option | Purpose |
| --- | --- |
| `--out DIR` | Destination for cleaned copies |
| `--check` | Analyze cleaning without writing files |
| `--overwrite` | Replace existing destination files |
| `--type NAME` | Filter by file family |
| `--ext LIST` | Filter by extension |
| `--no-recurse` | Disable recursive traversal |
| `-j`, `--json` | JSON output |
| `--color`, `--no-color` | Force or disable ANSI colour |

Metadata removal is **not anonymization**.

Information may remain in:

- document content;
- pixels;
- sensor characteristics;
- codec characteristics;
- unsupported metadata;
- embedded resources;
- file structure;
- identifiers outside known metadata blocks.

---

## Automation and exports

FileGrail works both interactively and inside analysis pipelines.

### JSON

```bash
filegrail ./case --json > report.json
```

Main commands support structured JSON output for `jq`, Python, notebooks, shell pipelines and ingestion into other analytical systems.

Origin URL for every file that has one:

```bash
filegrail ./case --json |
  jq -r '.files[] |
         .path as $file |
         .evidence[] |
         select(.category == "origin" and .url) |
         "\($file)\t\(.url)"'
```

Email addresses found in metadata and supported document content:

```bash
filegrail ./case --pivots --json |
  jq -r '.identifiers[] |
         select(.type == "email") |
         .normalized'
```

Files grouped by their PRONOM format:

```bash
filegrail ./case --json |
  jq -r '.files[] |
         select(.formats | length > 0) |
         "\(.formats[0].puid)\t\(.formats[0].name)\t\(.path)"' |
  sort
```

Pivots shared by more than one file:

```bash
filegrail ./case --pivots --json |
  jq -r '.identifiers[] |
         select(.files > 1) |
         "\(.type)\t\(.normalized)\t\(.files) files"'
```

The `identifiers` list is present when `--pivots`, `--meta`, `--content` or a graph export was requested.

### JSON schemas

Each major command identifies its schema version.

| Command | Schema |
| --- | --- |
| `scan` | `filegrail.scan/2` |
| `explain` | `filegrail.explain/2` |
| `compare` | `filegrail.compare/2` |
| `doctor` | `filegrail.doctor/1` |
| `clean` | `filegrail.clean/1` |

A schema version changes when the meaning or compatibility of the structured output changes, rather than for every implementation change.

Scan documents can contain:

- schema identifier;
- FileGrail version;
- scan root;
- run configuration;
- evidence coverage;
- file records, including the files read inside archives, documents and messages, each with its parent;
- evidence records, each with where in the file it was read from, where the reader knows;
- correlation results;
- investigative identifiers;
- graph nodes and relationships;
- cluster/shared-attribute results;
- XMP links;
- hashes.

The scan configuration and coverage accompany exported graph data, so downstream consumers retain the conditions under which relationships were produced.

---

## Local-first operation

FileGrail:

- makes no network requests during analysis;
- performs no OSINT enrichment itself;
- does not upload files;
- does not submit hashes;
- does not contact reputation services;
- does not require external metadata tools at runtime;
- can operate in offline analysis environments.

FileGrail collects and structures local evidence. Enrichment can then be performed explicitly in another tool or workflow.

---

## Read-only analysis

Normal scanning is read-only.

FileGrail does not modify:

- analyzed files;
- browser databases;
- shell histories;
- operating-system provenance attributes;
- archive contents;
- torrent stores.

Where an application database has to be opened, FileGrail reads its own copy.

`filegrail clean` is the explicit exception: it writes new sanitized copies to the requested output directory.

Files are treated as untrusted input. Malformed or unsupported input results in a partial or absent reading, never in a value invented from bytes FileGrail cannot interpret reliably.

---

## Privacy and redaction

Reports can contain sensitive investigative data, including:

- private URLs;
- filesystem paths;
- commands;
- account names;
- email addresses;
- names of people and organizations;
- IP addresses;
- hostnames;
- MAC addresses;
- GPS coordinates;
- bank and company identifiers;
- tax identifiers;
- vehicle identification numbers;
- cryptocurrency addresses;
- analytics IDs;
- secrets embedded in files or commands.

Use:

```bash
filegrail ./case --redact
```

to redact supported credentials before output.

Credentials in URLs, commands and recognized secret formats are replaced with fingerprints, so repeated values stay correlatable without being exposed.

Other personally identifiable or sensitive investigative values are not automatically hidden.

Review any report before sharing it.

---

## Limitations

FileGrail only analyzes evidence that still exists and that its readers understand.

- cleared browser records cannot be reconstructed from nothing;
- removed extended attributes cannot be recovered by FileGrail;
- missing shell history cannot be inferred;
- a sync root identifies account/folder context, not who uploaded a file;
- messenger file-name patterns do not identify a sender or conversation;
- archive or torrent matches are associations, not proof of authorship or intent;
- recorded author and organization metadata can be edited;
- camera model alone does not identify one physical device;
- a camera body serial is a stronger link but remains recorded metadata;
- filesystem timestamps can be altered;
- EXIF GPS can be modified;
- an embedded thumbnail may be stale, independently edited or produced by a different workflow stage;
- a JPEG quality estimate describes the observed quantization tables, not necessarily the image's first save;
- ELA, bit planes, gradients and residual maps are review aids, not manipulation detectors;
- C2PA hard binding is checked where supported, but certificate-chain and signer trust are not verified;
- Authenticode presence is reported but signer trust is not established;
- PDF signature dictionaries are reported as structures, not as proof of signature validity;
- scanned PDF pages require OCR and are not converted to text;
- unsupported or encrypted structures may remain unread;
- `clean` does not guarantee anonymity.

FileGrail is not:

- a chain-of-custody management system;
- a full disk-forensics suite;
- a malware sandbox;
- an automatic attribution engine;
- a monitoring agent;
- an OSINT enrichment service;
- a replacement for analyst judgment.

---

## Documentation

- [Format and detection reference](docs/FORMATS.md)
- [Roadmap](ROADMAP.md)
- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

---

## Development

Development dependencies are optional and separate from the runtime package.

```bash
pip install -e '.[dev]'
```

Run tests:

```bash
pytest
```

Lint:

```bash
ruff check .
```

Type checking:

```bash
mypy src/filegrail
```

FileGrail targets Python 3.10+.

---

## License

Apache-2.0.
