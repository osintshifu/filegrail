"""Minimal PDFs, assembled here rather than committed as samples.

Every offset in the cross-reference table is computed from the bodies as they
are written, because a length counted by hand is a length that can be wrong in
a way a passing test will not notice.
"""

from __future__ import annotations


def stream(body: bytes, entries: bytes = b"") -> bytes:
    """One stream object, with the length the body actually has."""
    return b"<< /Length " + str(len(body)).encode() + b" " + entries + b" >>\nstream\n" + body


def tounicode(mapping: dict[int, str], width: int = 1) -> bytes:
    """A `/ToUnicode` CMap naming what each code draws.

    `width` is how many bytes a code takes, written the way a real encoder
    writes it: the codespace range says so, and every code is spelled to the
    full width. A composite font uses two, and spelling those codes short is
    how a fixture comes to pass for the wrong reason.
    """
    digits = width * 2
    rows = b"".join(
        b"<%s> <%s>\n"
        % (
            f"{code:0{digits}X}".encode(),
            letter.encode("utf-16-be").hex().upper().encode(),
        )
        for code, letter in mapping.items()
    )
    high = b"F" * digits
    return (
        b"/CIDInit /ProcSet findresource begin\n"
        b"begincmap\n"
        b"1 begincodespacerange\n<%s> <%s>\nendcodespacerange\n"
        % (b"0" * digits, high)
        + b"%d beginbfchar\n" % len(mapping)
        + rows
        + b"endbfchar\n"
        b"endcmap\nend\n"
    )


def document(
    pages: list[bytes],
    font: bytes = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    extra: bytes | list[bytes] = b"",
    catalogue: bytes = b"",
    info: bytes = b"",
) -> bytes:
    """A PDF drawing `pages`, one content stream each, with one font.

    `extra` is an object appended after the font, for the tests that need the
    font to point at one - a `/ToUnicode` CMap is an object of its own. A
    composite font points at two, and names the second `{extra2}`.

    `info` is a document information dictionary. It goes in here rather than
    being bolted on afterwards because an object added after the cross
    reference table is built is an object the table does not list: `qpdf`
    calls such a file damaged and rebuilds the table before reading it, and a
    reader that follows the table properly finds no dictionary at all. A
    fixture like that tests whether a payload can be found by searching, which
    is not the same question as whether a PDF can be read.
    """
    extras = [extra] if isinstance(extra, bytes) else extra
    count = len(pages)
    # 1 catalogue, 2 page tree, then a page each, a content stream each, the
    # font, and whatever the caller appended.
    first_page, first_content, font_number = 3, 3 + count, 3 + count * 2
    kids = b" ".join(b"%d 0 R" % (first_page + index) for index in range(count))

    bodies = [
        b"<< /Type /Catalog /Pages 2 0 R " + catalogue + b">>",
        b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % count,
    ]
    for index in range(count):
        bodies.append(
            b"<< /Type /Page /Parent 2 0 R /Contents %d 0 R " % (first_content + index)
            + b"/Resources << /Font << /F1 %d 0 R >> >> >>" % font_number
        )
    bodies.extend(stream(page) + b"\nendstream" for page in pages)
    bodies.append(
        font.replace(b"{extra}", b"%d 0 R" % (font_number + 1)).replace(
            b"{extra2}", b"%d 0 R" % (font_number + 2)
        )
    )
    bodies.extend(body for body in extras if body)
    if info:
        bodies.append(info)

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(bodies, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"

    start = len(out)
    out += b"xref\n0 %d\n" % (len(bodies) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    trailer = b"<< /Size %d /Root 1 0 R" % (len(bodies) + 1)
    if info:
        trailer += b" /Info %d 0 R" % len(bodies)
    out += b"trailer\n" + trailer + b" >>\n"
    out += b"startxref\n%d\n%%%%EOF\n" % start
    return bytes(out)
