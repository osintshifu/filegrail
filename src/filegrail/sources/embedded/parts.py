"""One member of a zip-based container, read with a bound.

ODF, OOXML and EPUB all keep what they say about themselves in a named part
inside a zip, and all three are read here with `zipfile`. What a member costs
to read is not what the file costs on disk: the uncompressed size is whatever
the member's header declares, and `ZipFile.read` returns as much as it is
asked for. XML deflates at around fifteen hundred to one, so a document under
a megabyte can name a property part of six hundred, and reading it allocates
that much twice - once as bytes, once as the tree parsed from them.

Every real property part is kilobytes. The bound is set far above anything a
writer produces, because the point is not to be tight; it is that there be a
number at all.
"""

from __future__ import annotations

import zipfile

#: The most a property part is read. Deliberately the same figure the PDF
#: reader allows itself for inflated object streams: four megabytes is what
#: this project treats as the most decompressed text worth looking at.
MAX_PART_BYTES = 4 * 1024 * 1024


def read_part(archive: zipfile.ZipFile, name: str, limit: int = MAX_PART_BYTES) -> bytes | None:
    """The member's bytes, or None where it is larger than `limit`.

    Read through `open` rather than `read` so the bound holds on the
    decompressed stream itself. Nothing here trusts the size the header
    declares - one byte past the limit is fetched and the answer refused,
    which needs no agreement between what the archive claims and what it
    actually contains.
    """
    try:
        with archive.open(name) as handle:
            payload = handle.read(limit + 1)
    except RuntimeError:
        # `zipfile` uses RuntimeError, rather than a dedicated exception, when
        # a member is encrypted and no password was supplied. FileGrail never
        # guesses or prompts for credentials, so that part is simply unreadable.
        return None
    return None if len(payload) > limit else payload
