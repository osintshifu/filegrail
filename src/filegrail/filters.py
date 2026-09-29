"""Narrowing a scan to particular file types.

A case directory is rarely homogeneous. Someone chasing camera provenance does
not want forty spreadsheets in the report, and reading their metadata is work
the scan did not need to do in the first place - the filter is applied while
walking, before any file is opened.

Families are named after what an analyst asks for. Nobody thinks "jpg, jpeg,
jpe, tif, tiff, dng, nef, cr2, arw, orf, rw2, webp, heic, heif, avif, png,
apng"; they think "the images". Wherever a reader already knows the extensions
for a family, that set is reused rather than restated, so adding a format to a
reader also adds it here.
"""

from __future__ import annotations

from .sources import mail
from .sources.archives import ARCHIVE_SUFFIXES
from .sources.embedded import (
    aiff,
    ape,
    containers,
    documents,
    exif,
    fonts,
    id3,
    matroska,
    ole,
    pe,
    photoshop,
    png,
    riff,
    vorbis,
    web,
)


class UnknownType(ValueError):
    """A family name that does not exist, reported with the ones that do."""


#: Extensions an ISO base media file uses for moving pictures. `isobmff.SUFFIXES`
#: cannot be reused wholesale: it also claims `.heic` and `.avif`, which are
#: still images and belong under `image`. `riff.SUFFIXES` and
#: `matroska.SUFFIXES` are split for the same reason - one container each, and
#: neither a WAV nor an MKA is a film.
_VIDEO = (
    {".mp4", ".m4v", ".mov", ".qt", ".3gp", ".wmv", ".flv"}
    | riff.AVI_SUFFIXES
    | matroska.VIDEO_SUFFIXES
)

#: Formats no reader claims yet, listed so a filter still selects them - a file
#: this tool cannot read is exactly the sort a report should be able to include.
_EXTRA_IMAGE = {".gif", ".bmp", ".ico", ".raf", ".srw", ".pef"}
_EXTRA_AUDIO = {".m4a", ".wma"}
_EXTRA_TEXT = {
    ".txt",
    ".md",
    ".csv",
    ".tsv",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".log",
} | web.SUFFIXES

FAMILIES: dict[str, frozenset[str]] = {
    "image": frozenset(
        exif.SUFFIXES | png.SUFFIXES | photoshop.SUFFIXES | containers.SVG_SUFFIXES | _EXTRA_IMAGE
    ),
    "video": frozenset(_VIDEO),
    "audio": frozenset(
        id3.SUFFIXES
        | riff.WAVE_SUFFIXES
        | matroska.AUDIO_SUFFIXES
        | vorbis.SUFFIXES
        | aiff.SUFFIXES
        | ape.SUFFIXES
        | _EXTRA_AUDIO
    ),
    "document": frozenset(
        documents.PDF_SUFFIXES
        | documents.OOXML_SUFFIXES
        | ole.SUFFIXES
        | containers.ODF_SUFFIXES
        | containers.EPUB_SUFFIXES
        | containers.RTF_SUFFIXES
        | containers.NOTEBOOK_SUFFIXES
    ),
    "archive": frozenset(ARCHIVE_SUFFIXES),
    # `.msg` is in `document` as well: it is a compound document that happens
    # to hold a message, and an analyst asking for either should get it.
    # `.mbox` is listed but not read: a mailbox is many messages and a record
    # is one file, so asking for it selects nothing this can answer yet.
    "mail": frozenset(mail.SUFFIXES | mail.OUTLOOK_SUFFIXES | {".mbox"}),
    "text": frozenset(_EXTRA_TEXT),
    "executable": frozenset(pe.SUFFIXES),
    "font": frozenset(fonts.SUFFIXES),
}


def selection(families: list[str], extensions: list[str]) -> set[str] | None:
    """The suffixes to keep, or None when nothing was asked for.

    None rather than "every suffix": a scan with no filter must include files
    whose extension nobody listed, and an empty set would silently exclude them.
    """
    if not families and not extensions:
        return None

    chosen: set[str] = set()
    for name in families:
        for part in _split(name):
            if part not in FAMILIES:
                raise UnknownType(f"unknown type {part!r}; try one of: {', '.join(FAMILIES)}")
            chosen |= FAMILIES[part]

    for value in extensions:
        for part in _split(value):
            chosen.add(part if part.startswith(".") else f".{part}")
    return chosen


def _split(value: str) -> list[str]:
    """Accept `--type image,video` as readily as two separate flags."""
    return [part.strip().lower() for part in value.split(",") if part.strip()]


def describe(families: list[str], extensions: list[str]) -> str:
    """How the filter reads in a report, so an empty result can name its cause.

    It describes what was *asked for*, not what that resolved to. Someone who
    typed `--type image` wants to be told the report covers images, not to read
    back the twenty-five extensions the word stands for.
    """
    parts = [f"{name}s" for name in _flatten(families)]
    parts.extend(value.lstrip(".") for value in _flatten(extensions))

    if len(parts) > 6:
        return f"{', '.join(parts[:6])} and {len(parts) - 6} more"
    return ", ".join(parts)


def _flatten(values: list[str]) -> list[str]:
    return [part for value in values for part in _split(value)]
