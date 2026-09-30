# Changelog

All notable changes to `filegrail` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

- The terminal report shows findings and file detail as trees, with both values of every conflict.
- The file index is a table in three groups: files to review, files with evidence and files with none.
- Evidence coverage is a table, and every recorded location is listed.
- Files that declare an AI-generated source have their own count in the summary.
- Cross-file pivots list every file that holds them.
- `-o FILE.html` writes the HTML report, prints the terminal report and ends with the saved path and a link to open it.
- Every `-o` says which file it wrote, and the output file is never scanned as evidence.
- A terminal report without `-o` ends with the command that writes it as HTML.
- The start screen and the terminal report open with the FileGrail logo mark.
- The report header says which report the run wrote: an HTML file, a text file or the terminal only.

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
