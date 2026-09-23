# Contributing

Contributions are welcome.

## Development setup

```bash
git clone https://github.com/osintshifu/filegrail.git
cd filegrail

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

python -m pip install -e ".[dev]"
pytest
ruff check .
ruff format --check .
mypy
```

Those four are what CI runs on every push, on Linux, macOS and Windows. It runs
one more job on generated input, which needs the extra that carries Hypothesis:

```bash
python -m pip install -e ".[dev,fuzz]"
pytest tests/test_properties.py
```

`filegrail` has **no runtime dependencies** and that is a deliberate constraint,
not an accident. A change that adds one has to earn it; so far everything,
including the CBOR decoder needed for C2PA, has been reachable with the standard
library.

## Adding an evidence source

An evidence source produces one or more evidence records from an artifact, a
metadata block, an application database, a filesystem attribute or another
supported store. It does not have to answer "where did this come from" - EXIF
and Recent Documents are sources too, and they answer different questions.

Say five things about a new one, in code and in the tables it registers with:

| | |
|:---|:---|
| **category** | `origin`, `metadata` or `activity`, in `models.SOURCE_CATEGORIES`. `category()` raises for a source that is in neither table, on purpose: the old default classified by forgetting. |
| **source** | The artifact or block the record came from, named the way an analyst names it - `Chromium download history`, `Zone.Identifier`, `EXIF`. Not a person, a camera or a cluster key. |
| **match basis** | How the record was tied to *this* file, in `models.SOURCE_MATCH` or on the record. A path, a name, a name and size, membership of a container, or the file's own bytes. Where the tie is not direct, the record carries it. |
| **data produced** | The fields the record fills in, and nothing inferred from elsewhere. If a field is absent, leave it absent. |
| **limitations** | What the record cannot establish. A sync folder does not say which way the bytes travelled; a file name in a messenger's pattern is an association with a naming convention. |

Two more rules, unchanged:

- **Fail quietly when absent.** A missing profile, an unreadable file or a
  malformed container is ordinary, not an error. One bad file must never end a
  scan.
- **Never write.** The tool reads. It does not modify files, profiles or
  histories, and a live database is copied before being opened.

There is a presentation order in `models.SOURCE_PRIORITY`, used to decide which
record a one-row summary shows. It is not a confidence, it is never printed and
it is never exported. Do not reach for it to express how much a source is worth
believing - that is what the category and the match basis are for.

## Adding a format

Metadata is the substance of this tool, so a format that carries any is worth
reading. Put the reader in `src/filegrail/sources/embedded/`, one module per
container family, and add a test that builds a minimal valid file rather than
committing a sample.

Do not compute byte lengths by hand in a test. Encode the structure with a small
helper instead, so a miscounted length cannot silently produce a passing test on
malformed input.

Add the format to the table in [`FORMATS.md`](docs/FORMATS.md) in the same change.
That file is parsed by `tests/test_documented_formats.py` and held against the
readers, so a format you can read and did not document is a failing test rather
than a document that quietly stops being true.

The same change registers the reader everywhere else a test looks: its block
name in `BLOCK_LABELS` in `models.py`, the field naming a person in
`AUTHOR_FIELDS` in `overview.py` (or the block in `WITHOUT_AUTHOR` when it
names none), its extensions in a family in `filters.py` so `--type` can select
them, and a row in the README's embedded-metadata table. Each of these is held
against the readers by a test, so a missed one fails rather than drifts.

A reader arriving with a suffix set of its own also needs a specimen in
`tests/specimens.py`: one minimal file carrying values nothing could decode by
accident, and what has to come back. `tests/test_specimens.py` then writes it
under every extension the reader claims and checks that each one reads. An
extension added to a set that already has a specimen needs nothing: it is swept
under that specimen and fails there if the reader cannot really read it.

The same specimens are what `tools/build_corpus.py` writes out, with a manifest
giving each file's expected block, expected values and digest. That corpus is
how somebody outside the project checks these claims.

It is also what `tests/test_differential.py` hands to `exiftool`, in a job of
its own, because a fixture built from a specification and read by the parser it
was built for agrees with itself and proves little else. The readers here search
for payloads rather than walk container structure, which is the right choice
when evidence arrives truncated, and it means a malformed fixture passes in
silence. Build a specimen the way an encoder writes the file: the comparison has
already caught a PDF whose information dictionary the cross reference table did
not list, and an Ogg page with no checksum.

Build the fixture the way a real encoder writes the file, not the way the
specification reads. The two differ, and where they differ is where the bugs
are: a HEIC names an `Exif` item in its item table long before the payload
appears, so a reader that stops at the first marker decodes the table and
reports nothing — on a green suite, because no synthetic fixture had a table.

## Adding a relationship to the graph

The graph is only worth reading if every claim in it means one stated thing.
Two keys and one table hold that still.

**A node is keyed by what it is, not by what it is called.** A file's key is the
path it was found at, which identifies it inside one scan and nowhere else: a
name identifies nothing, because two directories each holding a `report.pdf`
hold two files. An identifier's key is its type together with its normalized
value, since the same text is not always the same thing - `example.org` is a
domain in one file and the tail of an address in another. Across scans a path
means nothing at all, which is why `--case-jsonld` re-identifies a file by its
SHA-256 where one was computed, and scopes it to the scan target where none was.

**A relationship is keyed by its two ends and its kind**, direction included.
Everything else - how many occurrences, which field carried them, when - is
evidence hanging on that one edge. A document naming one person in `creator`
and again in `lastModifiedBy` is therefore one `author` edge resting on two
grounds, and that is a decision rather than a side effect of merging: the
fields that name a person differ across every format that has any, and one kind
per field is a list of fields, not a taxonomy. What the edge claims is narrowed
to match. It says the file names this person in a field meant to name a person,
and explicitly not that they wrote it; which field it was is in the evidence,
and in a filterable column of the CSV export.

**Every kind declares its meaning** in `TAXONOMY` in `graph.py`, and a kind that
is not in the table cannot reach an export: every edge is keyed through it, so
an undeclared kind ends the scan instead of arriving in a case file undefined.
Say four things about a new one:

| | |
|:---|:---|
| **direction** | `DIRECTED` where the two ends are not interchangeable, which is nearly always: a file has an identifier and the identifier does not have the file. `SYMMETRIC` where the claim reads the same from either end. |
| **claim** | What an edge of this kind asserts, in one line. If it takes two, it is probably two kinds. |
| **limits** | Where the assertion stops. A make and model names a product thousands of people own, never which camera; an XMP link is unsigned text that copying a file copies. |
| **inverse** | The kind that is this one read backwards, where the graph carries both halves under their own names, as `derived from` and `source of` do. |

Direction is the part that is easy to get wrong, because a scan meets a
symmetric claim from both files and will happily store both halves. That is one
finding reported twice, counted twice and drawn twice, so `SYMMETRIC` kinds are
ordered by node key before they are stored and merged into one edge. Its weight
is not the sum of the halves either: one occurrence seen from two ends is one
occurrence. Declare the direction deliberately - `uco-core:isDirectional` in
the CASE export is written straight off this field, so a kind declared wrongly
tells a recipient that a rendition of a document is its parent.

## Updating the format registry

`src/filegrail/data/pronom.json` is compiled from two files The National
Archives publishes on the DROID signature page: the signature file and the
container signature file. Download both, then compile them:

```bash
python tools/build_pronom.py DROID_SignatureFile_V125.xml \
    container-signature-20260119.xml src/filegrail/data/pronom.json
```

The compiler stops on any syntax it does not understand rather than drop a
signature. Change the two file names in the `differential` job and in
`tests/test_commands.py` to the new release, then run
`tests/test_pronom_differential.py` against DROID locally:

```bash
DROID=/path/to/droid.sh PRONOM_SOURCES=/folder/with/both/files \
    python -m pytest tests/test_pronom_differential.py
```

It checks that the shipped file is exactly what the two sources compile to, and
that DROID names every file of the validation corpus as this project does.

## The local corpus

`tests/test_corpus.py` reads whatever real files you have put in `test-data/`,
which is deliberately not committed. It asserts one invariant: a file holding a
payload the TIFF parser can decode must not come back empty. That catches the
class of bug a synthetic fixture cannot, without third-party binaries entering
the tree.

It skips when the directory is absent, so it is a local net rather than a CI
gate. Point it at a directory of real photographs and documents before sending a
change that touches a reader.

## Pull requests

Keep changes focused and include tests for behaviour changes.

Priorities, in order: correctness, honesty about what a source does and does not
prove, privacy, portability, and only then breadth.

Commit messages describe what changed and why, in prose. No trailers.
