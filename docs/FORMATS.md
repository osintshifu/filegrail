# Formats

What `filegrail` can read out of a file you point it at.

This is the reference list. The [README](../README.md) has the short version; this
one is complete, and it is checked against the code by
`tests/test_documented_formats.py` — a reader whose formats are missing here
fails a test, and so does a format listed here that nothing reads. It cannot
drift.

Two different questions get confused a lot, so to be clear about which one this
answers:

- **What the file says about itself** — EXIF, XMP, document properties, mail
  headers. That is this file.
- **What your machine remembers about the file** — browser history, OS origin
  attributes, quarantine records, shell history, Recent shortcuts. Different
  axis, and `filegrail doctor` tells you which of those are available.

---

## Metadata blocks

**93 file extensions** have a reader. Twenty-one named metadata blocks, plus three
that turn up in any container that will carry them.

The first column is the `block` value you get in `--json`. It is what to filter
on when you want the PDFs rather than everything a file said about itself.

| Block | Extensions | What comes out |
|:---|:---|:---|
| `exif` | `.jpg` `.jpeg` `.jpe` `.tif` `.tiff` `.dng` `.nef` `.cr2` `.arw` `.orf` `.rw2` `.webp` `.heic` `.heif` `.avif` | Camera, lens, software, capture time and GPS; IFD1 embedded-JPEG thumbnail descriptors; JPEG JFIF/JFXX and ICC profile metadata |
| `maker-notes` | `.jpg` `.jpeg` `.jpe` `.tif` `.tiff` `.dng` `.nef` `.cr2` `.arw` `.orf` `.rw2` `.webp` `.heic` `.heif` `.avif` | Camera body serial number, shutter count, owner name, firmware version, frame number and lens identity from the vendor block; the vendor, the entry count, how its offsets are addressed and whether its byte order matches the container |
| `photoshop-irb` | `.jpg` `.jpeg` `.jpe` `.tif` `.tiff` `.psd` `.psb` | Resolution, JPEG settings, embedded-thumbnail descriptors, paths, workflow URLs and version information |
| `png-text` | `.png` `.apng` | `tEXt` / `zTXt` / `iTXt` keywords: software, creation time, author, and whatever a generator wrote there; the EXIF tags of an `eXIf` chunk |
| `isobmff` | `.mp4` `.m4v` `.mov` `.qt` `.3gp` `.m4a` `.heic` `.heif` `.avif` | Encoder and recording device, creation time, ISO 6709 location, from the `udta` atoms and from `moov/meta` `mdta` keys such as `com.apple.quicktime.model`, with every other `mdta` key kept under its own name; each track's handler, sample format and `mdhd` language, and a `tmcd` track noted; GoPro `FIRM`, `LENS`, `CAME` and `MUID` atoms; a `gpmd` (GPMF) or `camm` track located through the sample tables and summarised: device, stream names, GPS point count, first and last fix, GPS clock start and end |
| `matroska` | `.mkv` `.mk3d` `.webm` `.mka` | Writing application and library, segment date, tag entries |
| `riff` | `.wav` `.wave` `.rmi` `.avi` | `LIST`/`INFO` fields, BWF `bext` recorder and coding history, an `id3 ` chunk where one is present |
| `vorbis-comment` | `.flac` `.ogg` `.oga` `.opus` `.spx` | Vendor string and every `NAME=value` comment |
| `aiff` | `.aif` `.aiff` `.aifc` | `NAME`, `AUTH`, `(c) ` and `ANNO` chunks, the `COMM` sound description, an `ID3 ` chunk where one is present |
| `ape-tag` | `.ape` `.mpc` `.wv` `.ofr` | APEv2 items at the end of the file: encoder, artist, title, year and every other text item |
| `id3` | `.mp3` `.aac` `.tta` | ID3v2 frames: encoding software, artist, title, date |
| `pdf-info` | `.pdf` | The `Info` dictionary, through compressed object streams and hex strings; incremental updates with the objects each replaced or added, trailer IDs, encryption, embedded files, JavaScript and launch actions, AcroForm/XFA, URI targets and signature dictionaries |
| `ooxml-properties` | `.docx` `.docm` `.dotx` `.xlsx` `.xlsm` `.xltx` `.pptx` `.pptm` | `app.xml` and `core.xml`: application, author, last editor, company, template, revision count, total editing time; every `.rels` relationship with `TargetMode="External"`, and DDE instructions from the field text of the document, headers, footers and notes |
| `ole-summary` | `.doc` `.dot` `.xls` `.xlt` `.ppt` `.pot` `.pps` `.msg` | Summary properties, storage metadata, orphaned entries, VBA/XLM indicators, and OLE Packager paths |
| `odf-meta` | `.odt` `.ods` `.odp` `.odg` `.odf` `.ott` `.otp` | `meta.xml`: generator, author, creation and editing metadata |
| `epub-package` | `.epub` | OPF package metadata |
| `rtf-generator` | `.rtf` | The `\generator` and `\info` groups |
| `svg-metadata` | `.svg` | Generator, plus an embedded RDF block where an editor left one |
| `notebook-kernel` | `.ipynb` | Kernel name and language runtime version |
| `pe-header` | `.exe` `.dll` `.sys` `.scr` `.ocx` `.cpl` `.drv` `.efi` | COFF and optional header: machine, subsystem, linker version, link time; CodeView PDB path, GUID and age; Rich header tool records; version resource strings; whether an Authenticode signature is attached |
| `font-tables` | `.ttf` `.otf` `.ttc` `.otc` `.woff` | `name`, `head`, `OS/2` and `fvar` tables: family, designer, manufacturer, version, licence and URLs, creation and modification times, vendor identifier, embedding rights, variation axes; the WOFF metadata block where one is present |
| `web-document` | `.html` `.htm` `.xhtml` | Declared author, publisher, dates, canonical URL, Open Graph, Twitter Cards, bounded JSON-LD, Microdata and RDFa |
| `c2pa` | `.3gp` `.arw` `.avi` `.avif` `.cr2` `.dng` `.heic` `.heif` `.jpeg` `.jpg` `.m4a` `.m4v` `.mov` `.mp3` `.mp4` `.nef` `.orf` `.png` `.qt` `.rmi` `.rw2` `.tif` `.tiff` `.wav` `.wave` `.webp` | JUMBF manifest: producing application, creation data, digital source type, actions, ingredients with their relationship, and whether the manifest's own hash still covers the file |

Mail is not in this table because a message's metadata is its delivery record
rather than a block inside a container; it has a section of its own further
down. Neither are XMP and IPTC, which are not tied to an extension at all.

### Why so many fields

Because you rarely know in advance which one matters. A body serial ties images
to one camera. GPS time is often more trustworthy than the camera clock. Office
properties expose the last editor, the company, the template and how long
somebody had the document open.

So decoded fields stay visible by default. `--brief` folds them down, `--json`
keeps all of them, and long values wrap instead of being cut.

## Photo-forensics analysis

`filegrail photo PATH --out REPORT.html` is a separate still-image workflow. It reuses the provenance and metadata scan, then adds structural facts and, when installed, optional bounded pixel diagnostics.

The native JPEG pass reads the marker stream through EOI, including SOF encoding and dimensions, component sampling, DQT and DHT summaries, DRI, SOS count, comments, restart markers and bytes after EOI. Quantization quality is labelled as either an exact IJG table match or the nearest heuristic estimate. It describes the current encoding tables, not the first save of the image.

The EXIF pass walks IFD0, EXIF, GPS, Interoperability, SubIFDs and IFD1 with bounds and cycle detection. A valid IFD1 JPEG thumbnail is retained only for the dedicated report and described in ordinary scan evidence by format, dimensions, byte count and SHA-256. The binary thumbnail never enters scan JSON.

The command selects JPEG, TIFF and supported camera-raw EXIF containers, WebP, HEIC, HEIF, AVIF, PNG, APNG, BMP, DIB and GIF. Structural coverage varies by container. JPEG marker analysis applies only to JPEG; EXIF directory analysis applies only where the native EXIF reader supports the container. Pixel decoding depends on Pillow's codec support on the installed system.

Installing `filegrail[photo]` adds Pillow and NumPy for a bounded main preview, RGB and luminance histogram, luminance gradient, selected bit planes, median noise residual, ELA at two declared qualities and embedded-thumbnail comparison. Without the extra, the report explicitly says those methods were not evaluated. No result is converted into an authenticity or manipulation score.

---

## Blocks with no format

Three readers do not care what the container is. They look for the block and
read it wherever it turns up.

| Block | Where it is found | What comes out |
|:---|:---|:---|
| `xmp` | Any file carrying an XMP packet — JPEG, TIFF and raw, PNG, PDF, MP4, HEIC, SVG, InDesign output, and containers nobody thought to list | Creating application, author, title, `xmpMM` derivation identifiers |
| `xmp-history` | The same packet | Every recorded editing step. A step with a timestamp becomes its own dated claim and lands on `--timeline`; one without stays a field, because inventing a time for it would be worse than leaving it undated. The sequence is also held against itself: a step dated before the one it follows is reported |
| `iptc` | Any Photoshop image-resource block — JPEG, TIFF, PSD — plus TIFF tag 33723 | By-line, credit, source, copyright, headline, caption, keywords, place and date of creation |

XMP identifiers are also what links the scanned files to each other:
`xmpMM:DocumentID`, `OriginalDocumentID` and `DerivedFrom` let a master, its
export and a rendition of that export be reported as a chain. A shared
*original* is only ever reported as a common ancestor — a template carries its
XMP into everything made from it, and those files share an ancestor and nothing
else. The reasoning is in
[`docs/specs/2026-09-01-derivation-lineage.md`](specs/2026-09-01-derivation-lineage.md).

---

## Mail

A saved message is the one file type where the metadata *is* the provenance.
`Received:` headers are the only part of an email the sender did not write.

| Extension | What comes out |
|:---|:---|
| `.eml` | Every `Received:` hop as its own claim, the connecting address each server saw, and the sender's own headers kept separate from them |
| `.msg` | The same header block, out of the `PR_TRANSPORT_MESSAGE_HEADERS` MAPI stream. Where an Exchange delivery never wrote internet headers, the message's own MAPI properties are reported and no delivery record is invented |

The hops are not ranked alike. The topmost was written by the recipient's own
server and is the one hop nobody else could have forged; everything below it
was written by a machine the sender may control.

A `.msg` also goes through the `ole-summary` reader, because it is a compound
document and its Office-style properties sit exactly where a `.doc`'s do.
Directory timestamps are reported only for storage entries. CFB stream entries
do not define meaningful creation or modification times. `VBAStorage=present`
means that the container has a VBA storage, not that its code was executed or
is malicious. XLM is reported only when a BIFF `BoundSheet` record explicitly
identifies a macro sheet, not from the presence of a `Workbook` stream alone.
Allocated entries outside the root directory tree are reported as orphaned and
are not treated as active metadata or automation indicators.

---

## Torrents

A torrent is a container in the same sense an archive is: it lists its members
by name and exact size, so a file matching both was very likely one of them.
Unlike an archive it carries an origin of its own rather than one to inherit.

| File | What comes out |
|:---|:---|
| `.torrent` | The trackers it was announced to, the client that wrote it, any comment, and a magnet address built from the info hash |

Torrents are read from the scanned tree and from the stores the clients keep -
qBittorrent's `BT_backup`, Transmission's `torrents`, Deluge's `state` - which
is the ordinary case, since a downloaded file rarely has a `.torrent` beside it
and the client has kept one all along. `filegrail doctor` says whether any such
store was found.

The info hash is taken over the `info` value exactly as its author wrote it,
not over a re-encoding of what was decoded: the two differ wherever the author
was not canonical, and that is precisely where a hash computed from the
re-encoding would name the wrong content. The decoder refuses non-canonical
bencode for the same reason.

The claim is not dated. A torrent's creation date says when the torrent was
made, which can be years before anything in it was fetched, so the date is
reported as what it is rather than as an arrival.

---

## Sidecars

Not metadata either, and not inside the file at all. A download tool can be
asked to write what it knows beside what it fetched, and that record names the
page the bytes came from.

| File | What comes out |
|:---|:---|
| `<name>.info.json` | `yt-dlp --write-info-json`: the page URL, the uploader and channel, the publication date, the extractor, and the moment the fetch ran |

The moment reported is the fetch, not the publication. `epoch` is when the tool
wrote the document; `upload_date` is when the video became available and can be
years earlier, so reading it as the arrival would place the file on this
machine before it was.

The estimated size is deliberately not carried. `filesize_approx` is an
estimate for the format that was chosen, and reported as a byte count it would
contradict the file on disk and be reported as a size mismatch nothing is
actually wrong about.

A sidecar is paired to its media by file name alone, which is why it ranks
below the attributes an operating system attaches to the file itself: a copy
that brings one and not the other, or a rename, breaks that pairing in a way an
extended attribute cannot be broken.

---

## Archives

Not metadata. These are read so that a file extracted from one can inherit the
archive's origin, when the member name and uncompressed size both match.

| Extensions | What filegrail does with them |
|:---|:---|
| `.zip` `.jar` `.whl` | Member names and uncompressed sizes |
| `.tar` `.tgz` `.gz` `.bz2` `.xz` | The same, through the compression |

The files inside are also read, one at a time, without unpacking the archive:
a photograph in a zip has the same EXIF it would have on disk. A member that
carries evidence becomes a file of its own in the report, with the archive as
its parent, the archive's origin inherited as its own, and its member path in
`where`. What it says stays its own - a photograph taken in 2008 inside a zip
written last week does not date the zip, and a zip has never been anywhere.
A `.gz`, `.bz2` or `.xz` that is not a tar holds one file, named by the
archive's own name without the compression suffix.

For the same reason the readers that sweep raw bytes for a block, XMP and IPTC,
are not run on an archive at all. What they would find there belongs to a
member, and a zip is not made by Photoshop because a photograph inside it was.

The archive is considered whether or not it is inside the scanned tree — a case
directory is usually the *result* of unpacking something that lives elsewhere.

## Files inside documents and messages

Read the way an archive's members are: each becomes a file of its own in the
report, with the carrier as its parent, the carrier's origin inherited as its
own under the `embedded-file` source, and an `embedded in` relationship in
the graph.

| Carrier | What is read |
|:---|:---|
| PDF | Files attached to the document, named by their file specification |
| `.eml` | Attachments, under the name the message gives them |
| `.msg` | Attachments, under the name the message gives them; a message attached to a message is not opened |
| Office packages (`.docx`, `.xlsx`, `.pptx` and their macro and template variants) | Files under `embeddings/`; an OLE Packager object is read as the file it packages, under its original file name |
| Legacy Office (`.doc`, `.xls`, `.ppt` and their template variants) | OLE Packager objects, named by their storage and original file name |

The budget is the archive's: a bounded number of files opened per carrier and
a bounded size per file, and a carrier over a size of its own is not opened.
A carried file is read one level deep: a zip attached to a message is
reported, and what is inside that zip is not.

---

## Text a document holds

A different axis from everything above. The tables so far are what a file
records *about itself*; this is what it *says*, and it is read only when
`--pivots` asks for it. The identifier detectors are then pointed at the text
as well as at the metadata, and every value carries which of the two it came
from, and where in the document it was.

Nothing here is a claim about provenance. A body is not evidence of arrival.
The point of reading it is the correlation: a name a document carries that the
record of the file's *arrival* also carries was written down twice, by two
separate acts, and neither half says that alone.

| Extensions | What is read |
|:---|:---|
| `.txt` `.text` `.md` `.markdown` `.rst` `.log` | The file, a line at a time, and the line is what a value is reported against |
| `.json` `.ndjson` `.jsonl` `.ipynb` `.yaml` `.yml` `.toml` `.ini` `.cfg` `.conf` `.vcf` `.ics` `.canvas` | The same. Data formats are text, and an export out of an application is exactly the sort of file an examiner is handed |
| `.csv` `.tsv` | A cell at a time rather than a line, because a row read whole runs its columns together and a value at the end of one takes the separator and the next column with it. The place names the row and the column, which is where a reader can go and look |
| `.html` `.htm` `.xhtml` `.xml` `.svg` `.graphml` | The text, and the addresses in `href`, `src` and their kin, by the line of the file. `<script>` and `<style>` are left out - a colour is a short hex digest and a bundler writes hosts nobody typed - and a namespace declaration is markup rather than something the document said |
| `.gpx` `.kml` | The text and the links as markup, and then the positions the file carries as structure: every named point, and the start and the end of every track or line, each written as a `geo:` URI so the coordinate detector takes it on its own and a bare pair of decimals is still never believed. KML puts the longitude first; the reader turns it around. Not read: `gx:Track`, polygons and multi-geometries |
| `.geojson` | By line like any data, and a second time for the features: every `Point`, and the start and the end of every `LineString`, longitude first there too. A file the budget cuts short keeps its lines and contributes no positions |
| `.gexf` `.mm` | As markup, plus the text a node keeps in an attribute - `label` in a Gephi graph, `TEXT` in a FreeMind map - where a reader that keeps only addresses never looks. The rule is per format: `value` would be every form field in HTML |
| `.pdf` | The text of each page, reported against the page the document itself numbers. A PDF stores instructions rather than text: the bytes it draws are indices into whatever encoding each font uses, so every run is decoded through its font. A font whose glyphs resolve to nothing - a subset naming `g1`, `g2` - is skipped rather than read as bytes, an encrypted document is refused, and a scanned page holds a picture rather than text |
| `.docx` `.docm` `.dotx` `.xlsx` `.xlsm` `.xltx` `.pptx` `.pptm` | The body, footnotes, endnotes and comments of a Word file; every slide and its notes; a workbook's shared strings and its inline cell text. Reported as `body`, `footnotes`, `slide 4`, `sheet 2` - the terms the format has. There is no page number: pagination happens when something renders the file, which does not record where the breaks fell |
| `.odt` `.ods` `.odp` `.odg` `.odf` `.ott` `.otp` | `content.xml` as the body, `styles.xml` as headers and footers |
| `.kmz` | The `.kml` at the root, read as a `.kml` is: its names and links as `map`, its positions under their own placemarks |
| `.xmind` | `content.json` as the body, or `content.xml` in the older format |
| `.mtgx` | Every `Graphs/GraphN.graphml` of a Maltego export as `graph N`. An entity's value sits in `<mtg:Value>` as text, so the markup reader takes it without a rule of its own |
| `.epub` | Each chapter, under the name the book gives it |
| `.eml` `.msg` | The message body, decoded first - quoted-printable and base64 both hide an address from anything reading the bytes as they lie. The headers are not taken again here: they are already read as evidence of delivery, and counting them twice would file the second copy under the wrong axis |

No dependency comes with any of this. The formats where a text search fails
hardest are zip archives of XML, and the reader that already opens them for
their properties opens them for this, under the same bound on what one member
may cost.

---

## The name against the bytes

An extension is a claim, and renaming a file is one command. Every scanned file
whose extension appears below is read a few bytes deep, and the format written
there is held against the format the name claims. Where the two disagree the
file carries a `file signature` record saying which is which, and the files it
happened in are named together under the key findings.

Three things are not a disagreement. A format written under several names: a
`.docx`, an `.epub` and a `.jar` are all zip archives, and every one of those
carries it legitimately. Bytes that match no row below: what the file is was
not established, which is not the same as establishing that it is misnamed. An
extension no row below names: there is no claim to contradict.

| What the bytes are | Extensions that carry it |
|:---|:---|
| JPEG | `.jfif` `.jpe` `.jpeg` `.jpg` |
| PNG | `.png` |
| GIF | `.gif` |
| TIFF | `.tif` `.tiff` |
| WebP | `.webp` |
| PDF | `.pdf` |
| RTF | `.rtf` |
| ZIP | `.apk` `.docm` `.docx` `.epub` `.jar` `.kmz` `.odg` `.odp` `.ods` `.odt` `.pptm` `.pptx` `.xlsm` `.xlsx` `.xpi` `.zip` |
| gzip | `.gz` `.svgz` `.tgz` |
| bzip2 | `.bz2` `.tbz2` |
| XZ | `.txz` `.xz` |
| Zstandard | `.tzst` `.zst` |
| 7-Zip | `.7z` |
| RAR | `.rar` |
| tar | `.tar` |
| OLE compound file | `.doc` `.msg` `.msi` `.ppt` `.xls` |
| ISO base media (MP4, MOV, HEIC) | `.3g2` `.3gp` `.avif` `.heic` `.heif` `.m4a` `.m4b` `.m4v` `.mov` `.mp4` |
| Matroska (MKV, WebM) | `.mka` `.mks` `.mkv` `.webm` |
| Ogg | `.oga` `.ogg` `.ogv` `.opus` |
| FLAC | `.flac` |
| MP3 | `.mp3` |
| WAV | `.wav` |
| AVI | `.avi` |
| SQLite database | `.sqlite` `.sqlite3` |
| ELF binary | `.elf` `.ko` `.so` |
| Windows executable | `.cpl` `.dll` `.exe` `.ocx` `.scr` `.sys` |
| Mach-O binary | `.bundle` `.dylib` |
| HTML | `.htm` `.html` `.xhtml` |
| SVG | `.svg` |
| XML | `.atom` `.htm` `.html` `.plist` `.rss` `.svg` `.xhtml` `.xml` |

---

## Investigative pivots

What each pivot type takes from metadata and document text, and the look-alike values it leaves out.

| Type | Taken | Not taken |
|:---|:---|:---|
| `url` | `http` and `https` addresses, normalized | |
| `domain` | Every host behind a URL, an address or a UNC path, and bare names whose TLD is a real one | Anything shaped like a file name, and onion names, which are their own type |
| `hostname` | Machine and server names that are not public domains: the machine a Windows shortcut was created on, the server in a UNC path and the hosts a `Received:` header names | IP addresses, public names, which are `domain`, and placeholders such as `localhost` or `server` |
| `email` | Addresses whose TLD is a real one | The address inside a message ID; its host is still kept |
| `message_id` | Message IDs from the `Message-ID`, `In-Reply-To` and `References` headers, so a reply and the message it answers share a value | The `Content-ID` of an attachment |
| `ipv4` | Dotted quads, with private and reserved ranges marked as such | Version numbers, and digits in a field naming software |
| `ipv6` | Addresses with all eight groups written out, or any form inside the brackets a URL places around one | A compressed address standing bare, which can resemble a scope operator in code |
| `geo` | Coordinates written with a hemisphere letter, a degree sign, a `geo:` URI, a map URL or an explicit latitude label | A bare pair of decimals |
| `md5` `sha1` `sha256` `sha512` | 32, 40, 64 and 128 hexadecimal digits, bare, and all but the longest also as colon-separated pairs; a digest of an address seen in the same scan is named for it | Digests in a field naming software, which may be build IDs |
| `cve` | Vulnerability identifiers, case-insensitive | |
| `cwe` | Weakness identifiers such as `CWE-79`, case-insensitive | |
| `ghsa` | GitHub security advisory identifiers, normalized to lowercase after the prefix | |
| `registry` | Windows Registry keys under any hive, long name or short, as one key | |
| `path` | Windows paths using a drive letter, environment variable or UNC share | POSIX paths; a bare drive or variable |
| `executable` | Bare names of Windows executables, scripts, installers or shortcuts, alone or inside a path or URL | Names with spaces, source files and anything ending in `com` |
| `btc` | Bitcoin addresses whose checksum holds, including legacy and `bc1`; Bech32 values are normalized to lowercase | Mixed-case `bc1` spelling |
| `bch` | Bitcoin Cash addresses in CashAddr form whose checksum holds, with or without the `bitcoincash:` prefix, normalized with it | Legacy Bitcoin Cash addresses, which are written the same as Bitcoin ones |
| `ltc` `doge` | Litecoin and Dogecoin addresses whose checksum holds and whose version byte names the chain, including `ltc1`; Bech32 values are normalized to lowercase | A `3` address, which Litecoin once shared with Bitcoin and which is a `btc` |
| `xmr` | Monero standard, integrated and subaddresses whose Keccak-256 checksum holds | |
| `eth` | Ethereum addresses, mixed-case ones validated using EIP-55 and one-case values by shape, normalized to lowercase | Transaction hashes |
| `vin` | Vehicle identification numbers when the North American check digit holds, and values beside a `VIN` label regardless | Other arbitrary seventeen-character strings |
| `iban` | Account numbers whose country, length and mod-97 check agree, with spaces removed | |
| `nip` `regon` | Polish tax and statistical numbers beside their label, or NIP behind an EU `PL` prefix | The same digits standing bare |
| `onion` | Tor v3 addresses whose checksum holds, normalized to lowercase | |
| `mac` | Hardware addresses in supported notations, normalized with colons | All-zero and broadcast addresses |
| `sid` | Windows account and group SIDs such as `S-1-5-21-…` with a relative ID | Short well-known SIDs such as `S-1-5-18` |
| `bic` | Bank identifier codes beside a `BIC` or `SWIFT` label, 8 or 11 characters, with a valid country code | The same code standing bare |
| `secret` | Vendor-prefixed API keys and tokens, JWTs and private-key blocks; reported as type and fingerprint, never as the secret value | Credentials detected only because of a nearby field name |
| `person` | Names in fields identifying who made a file - author, by-line, artist or mail display name - and names in text when preceded by supported honorifics | Arbitrary names in document text and common application placeholders |
| `org` | Company or credit fields and names in text ending with supported legal forms such as `Sp. z o.o.`, `GmbH`, `Ltd`, `Inc` or `LLC` | Ambiguous `Source` fields |
| `handle` | Accounts referenced through known-platform profile URLs, the owner in a GitHub repository or raw-file URL, and user-directory logins from the originating machine | Platform-owned pages and common system directories |
| `postcode` | Polish postcode with town context and UK postcodes recognized by shape | Bare ambiguous postal-looking values and US ZIP codes |
| `ssn` | US Social Security numbers beside their label and matching valid issuance shape; represented as a fingerprint, never the number | Bare values and ranges that were never issued |
| `ein` | US Employer Identification Numbers beside their label and using an assigned prefix | The same digits standing bare |
| `aba` | US bank routing numbers beside their label whose checksum and prefix are valid | Bare nine-digit values |
| `crn` | UK company registration numbers beside a Companies House or company-number label | Bare ambiguous values |
| `cik` | SEC filer identifiers beside a `CIK` label, normalized regardless of zero padding | |
| `vat` | EU VAT identifiers beside a `VAT` label and using a recognized country | Polish VAT values, which are represented as `nip` |
| `asn` | Autonomous system numbers such as `ASN 3356` or `AS3356` | Ambiguous uses of `AS` in normal text |
| `tracker` | Analytics, tag-manager, advertising and affiliate identifiers recognized by prefix or provider context, including values found in loader and pixel URLs | Numbers without a known prefix or provider context |

---

## Written from the specification

These readers have never been run against a file the originating software
produced, because nothing on the developer's machine writes one. They are built
to the specification and tested against fixtures assembled from it, with every
offset computed rather than counted by hand.

| Reader | Specification | Why it is untested against reality |
|:---|:---|:---|
| Outlook `.msg` transport headers | [MS-OXMSG] | No Outlook here. The container walk underneath is not in this position — real `.doc` files exercise it |
| Windows `.lnk` shortcuts | [MS-SHLLINK] | No Windows desktop writing Recent entries |
| The `id3 ` chunk inside a WAV | ID3v2 in RIFF | Nothing available writes one; the rest of the RIFF reader is exercised by real files |
| AIFF chunks | AIFF-C 1.0 | No AIFF here; the ID3 tag inside one goes through the same reader MP3 files exercise |
| APEv2 tags | APEv2 (Monkey's Audio) | No Monkey's Audio, Musepack or WavPack file here |
| WOFF tables and metadata | WOFF 1.0 | No WOFF here; the tables underneath are the same ones real TrueType, CFF and collection fonts exercise |
| PDF attachments, signature dictionaries and JavaScript | ISO 32000 | Real PDFs here exercise updates, trailer IDs, link targets and open actions, but none is signed, carries an attachment or a script |
| GPMF and CAMM telemetry tracks | GoPro GPMF, Google CAMM | No action-camera or phone recording with a metadata track here; the sample tables that locate it are read from real MP4 files |

That is worth knowing before you rely on one of them in something that matters.

---

## Deliberately not read

| What | Why |
|:---|:---|
| Who put a file in a synced folder | Dropbox encrypts its file cache, and for every client read here the answer lives on the server rather than on this machine. The folder and the account it syncs with are read; **who added the file is not** |
| Messaging-app stores | Telegram Desktop encrypts `tdata` and keeps no chat history in it. Signal Desktop's `db.sqlite` is SQLCipher behind a key the operating system wraps, and opening it needs a crypto library this tool does not carry. Discord and Slack keep no local message database. **No claim here names a sender or a conversation** - only the file names those clients write, which is a much weaker thing and is ranked as one |
| Vendor maker notes | Every manufacturer encodes them differently and each needs its own parser. The rest of EXIF is decoded |
| C2PA signatures | The certificate chain is **not** verified; that needs a crypto library and a trust list that changes over time. The *hard binding* is checked, which is a different question - whether the manifest describes these bytes, not whether its signer is anyone you should trust |
| `.mbox` | Many messages, one record per file. There is no honest single claim to make about a mailbox |
| Jump Lists (`.automaticDestinations-ms`) | In the Recent folder beside the shortcuts, and a different format. Shortcuts first |
| Fixed-length MAPI properties | Delivery and submit times live in `__properties_version1.0`, not a `__substg1.0_` stream. Left unread rather than guessed at, with no real `.msg` to check the layout against |
| Source code as text | A checkout is thousands of files whose identifiers are dependency hosts and licence URLs. `SKIP_DIRECTORIES` keeps a scan out of `node_modules` on the same principle |
| RTF text | Text under a layer of control words and hex escapes. It needs a parser to read honestly and yields noise without one. RTF **metadata** is read |
| PNG `Creation Time` in RFC 1123 form | Read as a moment, like the ISO form |

Anything else is still scanned. A format `filegrail` does not understand is
reported as not understood, rather than guessed at.

---

## Filtering by any of this

```bash
filegrail . --type image          # image, video, audio, document, archive, mail, text
filegrail . --ext jpg,pdf         # exactly these
filegrail . --json | jq '.files[].evidence[] | select(.block == "pdf-info")'
```

The `--type` families are derived from the readers themselves, so a format
added to a reader becomes selectable in the same commit. A test enforces that
too.

---

## Adding one

[`CONTRIBUTING.md`](../CONTRIBUTING.md) has the bar for a new reader. The short
version: one module per container family under `src/filegrail/sources/embedded/`,
a test that builds a minimal valid file rather than committing a sample, and no
byte length counted by hand.

Then add the row here. A missing row is a failing test, so you will not forget.
