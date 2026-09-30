# Changelog

All notable changes to `filegrail` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

## 1.1.0 - 2026-09-30

- Terminal report layout update.
- Clearer report saving with `-o`.
- New logo in the terminal.

## 1.0.0 - 2026-09-29

First stable release.

- Provenance from browser history, operating-system origin and quarantine records, shell history, archives, torrents, sidecars and mail transport.
- Embedded metadata from images, documents, media, email, executables and fonts, with PRONOM format identification.
- Investigative pivots from metadata, provenance and document content, each with the place it was found.
- Timeline, conflicts, clusters and evidence-backed relationships between files, including XMP lineage.
- A self-contained HTML investigation report with an evidence graph.
- FileGrail Image: image forensics with a separate HTML report, from EXIF and JPEG structure to error level analysis.
- Exports as JSON, GraphML, CSV relationships and CASE/UCO JSON-LD.
- Metadata removal into cleaned copies, checked by the same readers.
- A read-only MCP server for AI agents.
- Runs locally and makes no network requests; the core has no runtime dependencies.
