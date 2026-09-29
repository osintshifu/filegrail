# Roadmap

Planned work, in the order it will be done. Released changes are listed in [CHANGELOG.md](CHANGELOG.md).

## Evidence depth

The next round deepens what a scan knows about a file before widening the list of formats. Formats come last, and only the ones that turn up in real material.

### Real files behind every reader

Readers written against a specification alone are checked against files produced by the software the specification describes, and the defects those files reveal are fixed. The corpus test runs over a local `test-data/` directory that is not part of the repository. Files still wanted: an Outlook MSG, a Windows LNK, a WOFF from a foundry, a GoPro MP4 and a WAV with an `id3` chunk.

### Where a value was found

Naming the metadata namespace and path, the logical place such as a page or a slide, and the byte
range where one is reliable.

### Files inside files

Reading what a carried file itself carries, beyond the first level.

### Deeper Office and PDF evidence

The original name and path of embedded objects.

### What a media file says about how it was made

The timecode value itself, the language of Matroska tracks and the encoder chain in RIFF.
Codec profiles, colour and bit rates are left out; they describe the picture, not where it came from.

### Format identification from the bytes

Identifying the files carried inside archives and documents.

### Formats that turn up in real material

Canon CR3 and Fujifilm RAF, TNEF `winmail.dat`, and the member list of 7z and RAR archives without unpacking them. Each is added only once a real file is available to check it against.

## FileGrail Image

### Two images side by side

One report comparing two images across the same methods, for the case where the question is
whether one came from the other.

### A scan and an examination as one case

The two reports stay separate workflows. An explicit mapping between the files of a scan and
the images of an examination would let a finding in one open the other.

### Values behind a shifted maker note

The footer a Canon note ends with separates legitimate padding from a shifted note base. Reading
it would recover the values that are currently skipped rather than risk inventing them.

## Later

### Comparing two scans

Two saved scans compared by their nodes and relationships: what appeared and what disappeared, for example after a new batch of material arrives.

## Not planned

- Relationships inferred only because two values appear in the same document, such as a name and an email address on one page. Both values are connected to the file, with their places.
- Enrichment, or any other lookup that needs the network.
- A case database and incremental scans.
- Pseudonymized reports and exports.
