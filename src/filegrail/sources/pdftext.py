"""The text a PDF shows, page by page, for the detectors to be pointed at.

A PDF does not store its text. It stores instructions for drawing glyphs, and
the bytes those instructions carry are indices into whatever encoding the font
happens to use. Two documents that look identical can hold entirely different
bytes, which is why pulling the string literals out and hoping is not a reader
but a guess - and a guess here produces an address nobody ever wrote.

So every run of text is decoded through the font that draws it, and a font
whose mapping cannot be established is not decoded at all. What a reader does
with the result is find identifiers in it, so the failure that matters is not
unreadable prose: it is a plausible address assembled out of the wrong glyphs.
Dropping a run costs a lead. Inventing one costs the investigation.

Three mappings are established, in this order:

* `/ToUnicode`, a CMap the writer supplies precisely so that the text can be
  recovered. Where it exists it is the answer and nothing else is consulted.
* `/Encoding`, either one of the named encodings or a base with `/Differences`
  naming glyphs one at a time. Glyph names are resolved through a table of the
  Latin names and the `uniXXXX` form.
* Nothing, for a font that states neither. Then only the printable ASCII range
  is taken and every other byte is dropped, because a subset font's own
  encoding agrees with ASCII for those positions far more often than not, and
  the values this tool looks for are written in them.

Before any of them comes what the writer says outright. A span marked with
`/ActualText` reads as that text whatever its glyphs map to, because it is how
a writer names a glyph no map can: the alternate hyphen a browser draws inside
a number is mapped to nothing, and stated there as a hyphen.

What is refused: an encrypted document, a stream under a filter this module
does not undo, a font whose glyphs resolve to nothing, and a file whose page
tree cannot be walked. A page number is a fact a PDF really does record - it
is structure, not pagination invented at render time - so it is reported, and
a document whose pages cannot be ordered is not reported on at all.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, replace
from itertools import pairwise
from typing import NamedTuple

from .compression import decompress_zlib


class Font(NamedTuple):
    """What a font's bytes mean, how many make one character, and how far each
    one moves the pen.

    The width is not decoration. A composite font is shown two bytes at a
    time, and reading those bytes singly looks up two codes that are not the
    one drawn - which does not fail, it returns whatever those positions hold.
    A glyph index above 255 is ordinary in any subset font, so this is the
    difference between reading a document and reporting letters from the
    wrong places in it.

    `advances` is each code's width in ems, and `missing` the width of a code
    the font does not list. `missing` is `None` for a font that states no
    widths at all, and then where its glyphs end cannot be said.
    """

    width: int
    table: dict[int, str]
    advances: dict[int, float]
    missing: float | None


#: The largest document this reader opens. It is read whole - see `_whole` in
#: `content.py` - so the bound is on the file rather than on a prefix of it.
MAX_FILE_BYTES = 64 * 1024 * 1024

#: How many pages are read from one document. A report names the page it found
#: a value on, so the number has to mean something; past this many the reader
#: stops rather than paginating for hours.
MAX_PAGES = 512

#: How much text is taken before the reader stops walking pages. The caller
#: bounds the result too - this stops the work, not just the output.
MAX_TEXT_BYTES = 1024 * 1024

#: The most one decoded PDF stream may occupy. Page contents, CMaps and object
#: streams are normally far smaller; the bound prevents a tiny Flate stream
#: from expanding until the process runs out of memory.
MAX_STREAM_BYTES = 4 * 1024 * 1024

#: How many objects one document may hold. A malformed or hostile file can
#: name millions; the table is built once and this is what it costs at most.
MAX_OBJECTS = 200_000

#: How wide a gap, in ems, is a space the writer chose not to draw. Kerning
#: inside a word stays under it, and a space between two words stays over it
#: even squeezed to fill a line. Joining across a space glues two words into
#: an address that was never in the document.
_WORD_GAP = 0.15

#: How far, in ems, the next glyph may sit off the line the last one ended on,
#: or start back over it, and still be read as continuing it. A writer rounds
#: where it puts a glyph, and a word broken at every rounding reports its
#: pieces: `example.co` is a domain too.
_SAME_LINE = 0.5
_OVERLAP = 0.2

#: How deep `q` saves are kept. A stream of saves nothing restores would
#: otherwise grow without bound.
_MAX_DEPTH = 256

#: How many glyph widths one composite font may list. Its ranges are expanded,
#: and a range over every code there is is ordinary; a million of them is not.
_MAX_WIDTHS = 4 * 0x10000

_OBJECT = re.compile(rb"(\d+)\s+\d+\s+obj\b(.*?)\bendobj", re.S)
_ROOT = re.compile(rb"/Root\s+(\d+)\s+\d+\s+R")
_REFERENCE = re.compile(rb"(\d+)\s+\d+\s+R")
_STREAM = re.compile(rb"stream\r?\n", re.S)
_TYPE_PAGE = re.compile(rb"/Type\s*/Page(?![sA-Za-z])")


def read_pages(raw: bytes) -> list[tuple[int, str]]:
    """Every page's text, numbered the way the document numbers its pages."""
    if b"/Encrypt" in raw[-2048:] or re.search(rb"/Encrypt\s+\d+\s+\d+\s+R", raw) is not None:
        return []  # the strings are ciphertext; decoding them would be invention
    objects = _objects(raw)
    if not objects:
        return []

    pages = list(_pages(raw, objects))
    if not pages:
        return []

    found: list[tuple[int, str]] = []
    budget = MAX_TEXT_BYTES
    for number, page in enumerate(pages[:MAX_PAGES], 1):
        fonts = _fonts(page, objects)
        content = b"".join(_contents(page, objects))
        if not content:
            continue
        text = _show(content, fonts)
        if not text.strip():
            continue
        found.append((number, text))
        budget -= len(text)
        if budget <= 0:
            break
    return found


# --- the objects ---------------------------------------------------------------


def _objects(raw: bytes) -> dict[int, bytes]:
    """Every object body, including the ones packed into an object stream.

    Read by pattern rather than through the cross-reference table on purpose:
    a table that disagrees with the file is ordinary in a document something
    has appended to, and the bodies are what is wanted either way.
    """
    found: dict[int, bytes] = {}
    for match in _OBJECT.finditer(raw):
        if len(found) >= MAX_OBJECTS:
            break
        found.setdefault(int(match.group(1)), match.group(2))
    for body in list(found.values()):
        if b"/ObjStm" in body:
            found.update(_packed(body, found))
    return found


def _packed(body: bytes, objects: dict[int, bytes]) -> dict[int, bytes]:
    """The objects inside one object stream: a header of pairs, then the bodies."""
    data = _stream(body, objects)
    if data is None:
        return {}
    count = _integer(body, b"/N")
    first = _integer(body, b"/First")
    if count is None or first is None or first > len(data):
        return {}
    numbers = data[:first].split()
    found: dict[int, bytes] = {}
    for index in range(min(count, len(numbers) // 2)):
        try:
            number = int(numbers[index * 2])
            start = first + int(numbers[index * 2 + 1])
        except ValueError:
            break
        end = len(data)
        if index * 2 + 3 < len(numbers):
            try:
                end = first + int(numbers[index * 2 + 3])
            except ValueError:
                pass
        found[number] = data[start:end]
    return found


def _integer(body: bytes, key: bytes) -> int | None:
    match = re.search(re.escape(key) + rb"\s+(\d+)", body)
    return int(match.group(1)) if match else None


def _stream(body: bytes, objects: dict[int, bytes]) -> bytes | None:
    """An object's stream, undone where every filter on it is one done here."""
    opening = _STREAM.search(body)
    if opening is None:
        return None
    end = body.rfind(b"endstream")
    data = body[opening.end() : end if end != -1 else len(body)]
    header = body[: opening.start()]

    filters = re.findall(rb"/([A-Za-z0-9]+Decode)", header)
    for name in filters:
        if name == b"FlateDecode":
            inflated = decompress_zlib(data, MAX_STREAM_BYTES)
            if inflated is None:
                # A writer that miscounted /Length can leave a short tail. The
                # old reader accepted what could be decoded, so preserve that
                # tolerance while applying the same output limit.
                inflated = decompress_zlib(data, MAX_STREAM_BYTES, require_eof=False)
            if inflated is None:
                return None
            data = inflated
        else:
            return None  # an image codec, or a filter nothing here undoes
    if filters and (predictor := _integer(header, b"/Predictor")) and predictor >= 10:
        data = _unpredict(data, _integer(header, b"/Columns") or 1)
    return data


def _unpredict(data: bytes, columns: int) -> bytes:
    """Undo the PNG row filters a writer may put in front of Flate."""
    width = columns + 1
    out = bytearray()
    previous = bytearray(columns)
    for start in range(0, len(data) - 1, width):
        row = bytearray(data[start + 1 : start + width])
        if len(row) < columns:
            break
        kind = data[start]
        if kind == 2:  # up, the only one a writer uses for a table of numbers
            for index in range(columns):
                row[index] = (row[index] + previous[index]) & 0xFF
        elif kind == 1:  # sub
            for index in range(1, columns):
                row[index] = (row[index] + row[index - 1]) & 0xFF
        out += row
        previous = row
    return bytes(out)


def _resolve(value: bytes, objects: dict[int, bytes]) -> bytes:
    """A reference followed to the object it names; anything else unchanged."""
    match = _REFERENCE.fullmatch(value.strip())
    if match is None:
        return value
    return objects.get(int(match.group(1)), b"")


# --- the pages -----------------------------------------------------------------


def _pages(raw: bytes, objects: dict[int, bytes]) -> Iterator[bytes]:
    """The page objects in the order the document puts them in.

    Walked from the root rather than collected by type, because the order is
    the page number and a number read off the wrong sequence is a false place.
    """
    root = _ROOT.search(raw)
    if root is None:
        return
    catalogue = objects.get(int(root.group(1)))
    if catalogue is None:
        return
    tree = re.search(rb"/Pages\s+(\d+)\s+\d+\s+R", catalogue)
    if tree is None:
        return
    yield from _leaves(int(tree.group(1)), objects, set(), b"")


def _leaves(
    number: int, objects: dict[int, bytes], seen: set[int], inherited: bytes
) -> Iterator[bytes]:
    """Every page under one node, depth first, with what it inherits attached.

    The tree is walked with a stack of its own: a chain of nodes deeper than
    the interpreter's recursion limit is malformed, and must be cut, not raised.
    """
    stack = [(number, inherited)]
    while stack:
        number, inherited = stack.pop()
        if number in seen or len(seen) > MAX_OBJECTS:
            continue  # a tree that points at itself is malformed, not infinite work
        seen.add(number)
        body = objects.get(number)
        if body is None:
            continue
        # Resources are inherited down the tree, so a page that states none is
        # drawn with its parent's fonts and has to be read with them.
        resources = _entry(body, b"/Resources") or inherited
        kids = re.search(rb"/Kids\s*\[(.*?)\]", body, re.S)
        if kids is not None:
            children = [int(child.group(1)) for child in _REFERENCE.finditer(kids.group(1))]
            stack.extend((child, resources) for child in reversed(children))
            continue
        if _TYPE_PAGE.search(body):
            yield body + b"\n/filegrail-resources " + resources


def _entry(body: bytes, key: bytes) -> bytes:
    """One dictionary entry's raw value: a reference, a name, a number, an
    array or a `<<...>>`.

    The key has to end where a name ends. `/W` is not the start of `/WMode`,
    nor of the `/WILIOO+Raleway` a subset font is called.
    """
    at = re.search(re.escape(key) + rb"(?=[\s/\[\]<>()%]|$)", body)
    if at is None:
        return b""
    rest = body[at.end() :].lstrip()
    if rest.startswith(b"<<"):
        depth, index = 0, 0
        while index < len(rest) - 1:
            if rest[index : index + 2] == b"<<":
                depth += 1
                index += 2
                continue
            if rest[index : index + 2] == b">>":
                depth -= 1
                index += 2
                if depth == 0:
                    return rest[:index]
                continue
            index += 1
        return rest
    if rest.startswith(b"["):  # a composite font's widths nest one array in another
        depth = 0
        for bracket in re.finditer(rb"[\[\]]", rest):
            depth += 1 if bracket.group() == b"[" else -1
            if depth == 0:
                return rest[: bracket.end()]
        return rest
    match = re.match(rb"(\d+\s+\d+\s+R|/[^\s/\[\]<>]+|[-+]?(?:\d+\.?\d*|\.\d+))", rest)
    return match.group(1) if match else b""


def _contents(page: bytes, objects: dict[int, bytes]) -> Iterator[bytes]:
    """The content streams of one page, in the order they are drawn."""
    value = _entry(page, b"/Contents")
    references = [int(match.group(1)) for match in _REFERENCE.finditer(value)]
    for number in references:
        body = objects.get(number)
        if body is None:
            continue
        data = _stream(body, objects)
        if data is not None:
            yield data


# --- the fonts -----------------------------------------------------------------


def _fonts(page: bytes, objects: dict[int, bytes]) -> dict[bytes, Font]:
    """Every font the page names, with what each one's bytes mean."""
    resources = _resolve(_entry(page, b"/filegrail-resources"), objects)
    if resources.lstrip().startswith(b"<<") is False:
        resources = _resolve(resources, objects)
    table = _resolve(_entry(resources, b"/Font"), objects)
    found: dict[bytes, Font] = {}
    for match in re.finditer(rb"(/[^\s/\[\]<>]+)\s+(\d+)\s+\d+\s+R", table):
        body = objects.get(int(match.group(2)))
        if body is not None:
            found[match.group(1)[1:]] = _mapping(body, objects)
    return found


def _mapping(font: bytes, objects: dict[int, bytes]) -> Font:
    """What each code this font is shown draws, and how wide those codes are.

    An empty table means the run is dropped: a font whose glyphs cannot be
    established says nothing this tool is willing to repeat.
    """
    # A composite font is shown two bytes at a time unless its own CMap says
    # otherwise, which the `/ToUnicode` codespace below is allowed to correct.
    # A simple font is shown one byte at a time whatever its map declares: a
    # writer that gives one a two-byte codespace has not changed what it draws.
    composite = b"/Type0" in font
    width = 2 if composite else 1
    advances, missing = _widths(font, objects)

    unicode_map = _entry(font, b"/ToUnicode")
    if unicode_map:
        body = _resolve(unicode_map, objects)
        data = _stream(body, objects)
        if data:
            decoded, stated = _cmap(data)
            if decoded:
                return Font((stated or width) if composite else 1, decoded, advances, missing)

    if composite:
        # An identity encoding names glyphs, not letters.
        return Font(width, {}, advances, missing)

    encoding = _entry(font, b"/Encoding")
    if encoding.startswith(b"/"):
        return Font(1, dict(_named(encoding)), advances, missing)
    if encoding:
        block = _resolve(encoding, objects) if not encoding.startswith(b"<<") else encoding
        base = _entry(block, b"/BaseEncoding") or b"/StandardEncoding"
        table = dict(_named(base))
        differences = re.search(rb"/Differences\s*\[(.*?)\]", block, re.S)
        if differences is not None:
            table.update(_differences(differences.group(1)))
        return Font(1, table, advances, missing)
    return Font(1, {}, advances, missing)


def _widths(font: bytes, objects: dict[int, bytes]) -> tuple[dict[int, float], float | None]:
    """How far each code the font is shown moves the pen, in ems.

    A simple font lists its widths from `/FirstChar` on. A composite font lists
    them by glyph in its descendant's `/W`, and only an identity encoding shows
    glyphs by the codes it is drawn with. A font that states neither has no
    widths to measure with, and `None` says so.
    """
    if b"/Type0" in font:
        if _entry(font, b"/Encoding") != b"/Identity-H":
            return {}, None  # vertical, or codes that are not glyph numbers
        descendants = _resolve(_entry(font, b"/DescendantFonts"), objects)
        reference = _REFERENCE.search(descendants)
        if reference is None:
            return {}, None
        descendant = objects.get(int(reference.group(1)), b"")
        table = _cid_widths(_resolve(_entry(descendant, b"/W"), objects))
        default = _float(_resolve(_entry(descendant, b"/DW"), objects))
        if table is None:
            return {}, None
        return table, (1000.0 if default is None else default) / 1000

    widths = _resolve(_entry(font, b"/Widths"), objects)
    first = _integer(font, b"/FirstChar")
    if not widths or first is None:
        return {}, None  # one of the fonts every viewer carries, which states none
    scale = 0.001
    if b"/Type3" in font:  # its glyphs are drawn in a space of its own choosing
        matrix = _numbers(_entry(font, b"/FontMatrix"))
        if len(matrix) != 6:
            return {}, None
        scale = matrix[0]
    descriptor = _resolve(_entry(font, b"/FontDescriptor"), objects)
    missing = _float(_resolve(_entry(descriptor, b"/MissingWidth"), objects)) or 0.0
    table = {first + index: value * scale for index, value in enumerate(_numbers(widths))}
    return table, missing * scale


def _cid_widths(array: bytes) -> dict[int, float] | None:
    """A composite font's `/W`: a glyph and the widths from it on, or a range
    of glyphs sharing one width. An absent array leaves every glyph at the
    default, and one too large to expand is not guessed at."""
    table: dict[int, float] = {}
    if not array.lstrip().startswith(b"["):
        return table
    numbers: list[float] = []
    work = 0
    for match in re.finditer(rb"\[([^\[\]]*)\]|([-+]?(?:\d+\.?\d*|\.\d+))", array.lstrip()[1:]):
        if match.group(1) is not None:
            values = _numbers(match.group(1))
            work += len(values)
            if work > _MAX_WIDTHS:
                return None
            if numbers:
                start = _glyph_number(numbers[-1])
                table.update((start + offset, value / 1000) for offset, value in enumerate(values))
            numbers = []
            continue
        numbers.append(float(match.group(2)))
        if len(numbers) == 3:
            low, high = _glyph_number(numbers[0]), _glyph_number(numbers[1])
            work += max(high - low + 1, 0)
            if work > _MAX_WIDTHS:
                return None
            table.update((code, numbers[2] / 1000) for code in range(low, high + 1))
            numbers = []
    return table


def _glyph_number(value: float) -> int:
    """A glyph number as a composite font can have one: two bytes, never less
    than none. Twenty digits of one are a malformed file, not an overflow."""
    return int(min(max(value, 0.0), 0xFFFF))


def _numbers(value: bytes) -> list[float]:
    return [float(number) for number in re.findall(rb"[-+]?(?:\d+\.?\d*|\.\d+)", value)]


def _float(value: bytes) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _named(encoding: bytes) -> Iterator[tuple[int, str]]:
    """One of the encodings a font may name instead of describing.

    Only the positions these three agree on are taken: the printable ASCII
    range, which is where every address, host and hash is written. The upper
    halves differ between them and a wrong guess there writes an accent into
    the middle of a value.
    """
    if encoding.strip() not in (
        b"/WinAnsiEncoding",
        b"/MacRomanEncoding",
        b"/StandardEncoding",
        b"/PDFDocEncoding",
    ):
        return
    for code in range(0x20, 0x7F):
        yield code, chr(code)


def _differences(body: bytes) -> dict[int, str]:
    """A `/Differences` array: a code, then the glyphs that follow it."""
    table: dict[int, str] = {}
    code = 0
    for token in re.findall(rb"\d+|/[^\s/\[\]<>]+", body):
        if token.isdigit():
            code = int(token)
            continue
        letter = _glyph(token[1:].decode("latin-1"))
        if letter is not None:
            table[code] = letter
        code += 1
    return table


#: The glyph names that carry a value. Names outside this table - a subset
#: font's `g42`, a symbol, a logo - resolve to nothing and their code is left
#: out of the map, so the byte is dropped rather than guessed at.
_GLYPHS = {
    "space": " ", "exclam": "!", "quotedbl": '"', "numbersign": "#", "dollar": "$",
    "percent": "%", "ampersand": "&", "quotesingle": "'", "quoteright": "'",
    "quoteleft": "'", "parenleft": "(", "parenright": ")", "asterisk": "*",
    "plus": "+", "comma": ",", "hyphen": "-", "period": ".", "slash": "/",
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "colon": ":",
    "semicolon": ";", "less": "<", "equal": "=", "greater": ">", "question": "?",
    "at": "@", "bracketleft": "[", "backslash": "\\", "bracketright": "]",
    "asciicircum": "^", "underscore": "_", "grave": "`", "braceleft": "{",
    "bar": "|", "braceright": "}", "asciitilde": "~", "endash": "-", "emdash": "-",
    "hyphenchar": "-", "fi": "fi", "fl": "fl", "ff": "ff", "ffi": "ffi", "ffl": "ffl",
}  # fmt: skip


#: How a glyph name spells an accent, in the words Unicode uses for one. A name
#: like `aogonek` is a letter and a mark, and what it draws is the character
#: Unicode calls `LATIN SMALL LETTER A WITH OGONEK` - so what is kept here is
#: the marks, and the several thousand letters they make are derived. Without
#: this a Polish document loses every accented letter it has, and `Łódź` comes
#: back as `d`: not a letter missing but a word that reads as another one.
_MARKS = {
    "acute": "ACUTE", "grave": "GRAVE", "circumflex": "CIRCUMFLEX",
    "dieresis": "DIAERESIS", "tilde": "TILDE", "ring": "RING ABOVE",
    "cedilla": "CEDILLA", "ogonek": "OGONEK", "caron": "CARON",
    "breve": "BREVE", "macron": "MACRON", "slash": "STROKE", "bar": "STROKE",
    "dotaccent": "DOT ABOVE", "hungarumlaut": "DOUBLE ACUTE",
    "commaaccent": "COMMA BELOW", "stroke": "STROKE",
}  # fmt: skip


def _glyph(name: str) -> str | None:
    """What a glyph name draws, where this module can say."""
    if len(name) == 1 and name.isascii() and name.isprintable():
        return name
    if name in _GLYPHS:
        return _GLYPHS[name]
    accented = re.fullmatch(r"([A-Za-z])([a-z]+)", name)
    if accented is not None and accented.group(2) in _MARKS:
        letter, mark = accented.group(1), _MARKS[accented.group(2)]
        case = "CAPITAL" if letter.isupper() else "SMALL"
        try:
            return unicodedata.lookup(f"LATIN {case} LETTER {letter.upper()} WITH {mark}")
        except KeyError:
            return None
    match = re.fullmatch(r"uni([0-9A-Fa-f]{4})|u([0-9A-Fa-f]{4,6})", name)
    if match is not None:
        try:
            return chr(int(match.group(1) or match.group(2), 16))
        except ValueError:
            return None
    return None


def _cmap(data: bytes) -> tuple[dict[int, str], int]:
    """A `/ToUnicode` CMap: single codes, ranges of them, and how wide a code is.

    The width comes from the codespace the CMap declares, and failing that from
    the codes it writes - four hex digits is a two-byte code. Guessing it wrong
    in either direction reads the document through the wrong positions.
    """
    table: dict[int, str] = {}
    widths = {
        len(low) // 2
        for block in re.findall(rb"begincodespacerange(.*?)endcodespacerange", data, re.S)
        for low, _ in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block)
    }
    for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
        for source, target in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            letter = _utf16(target)
            if letter is not None:
                table[int(source, 16)] = letter
    for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
        for low, high, target in re.findall(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block
        ):
            start, end = int(low, 16), int(high, 16)
            first = _utf16(target)
            if first is None or end < start or end - start > 0xFFFF:
                continue
            for offset in range(end - start + 1):
                table[start + offset] = chr(ord(first[0]) + offset) + first[1:]
    if not widths:
        widths = {
            len(source) // 2
            for block in re.findall(rb"beginbf(?:char|range)(.*?)endbf(?:char|range)", data, re.S)
            for source in re.findall(rb"<([0-9A-Fa-f]+)>", block)[:1]
        }
    return table, max(widths) if widths else 0


def _utf16(target: bytes) -> str | None:
    """A CMap's value, which is UTF-16BE however many code units it holds."""
    try:
        letter = bytes.fromhex(target.decode("ascii")).decode("utf-16-be")
    except (ValueError, UnicodeDecodeError):
        return None
    return letter or None


# --- what the page draws ---------------------------------------------------------


_Matrix = tuple[float, float, float, float, float, float]

_IDENTITY: _Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

#: Where a piece of text is on the page: a point, the unit direction its line
#: runs in, and how large an em is there - all in the page's own units.
_Place = tuple[float, float, float, float, float]


@dataclass
class _Pen:
    """Where the next glyph is drawn, and what decides how far it moves.

    `q` and `Q` save and restore all of it but the text position, which the
    format keeps apart from the rest of the graphics state. `lost` is set when
    a run moved the pen by widths its font does not state, and cleared by the
    next instruction that puts the pen somewhere of its own accord.
    """

    ctm: _Matrix = _IDENTITY
    matrix: _Matrix = _IDENTITY
    line: _Matrix = _IDENTITY
    font: Font | None = None
    size: float = 0.0
    spacing: float = 0.0
    words: float = 0.0
    scale: float = 1.0
    leading: float = 0.0
    rise: float = 0.0
    lost: bool = False


def _show(content: bytes, fonts: dict[bytes, Font]) -> str:
    """The text the drawing instructions put on one page.

    Where the break goes decides what gets reported, and the instructions say
    where glyphs go rather than where words end. So the gap is measured, from
    the right side of one glyph to the left side of the next: joined when
    there is none, a space when it is a word's, a line of its own when the
    next glyph is somewhere else. A writer that places every glyph itself - a
    browser printing to PDF does - is read as the words it drew rather than as
    one letter a line.

    A gap that cannot be measured is a break. A font that states no widths
    gives no side to measure from, and joining across a move anyway was tried
    on real documents: a table whose columns share a baseline turns `0` and
    `works` into a domain, and that reported more values nobody wrote than
    breaking there did.
    """
    out: list[str] = []
    pen = _Pen()
    saved: list[_Pen] = []
    last: _Drawn | None = None  # the run drawn before, while nothing has moved the pen
    end: _Place | None = None  # where that run's last glyph ended, if it can be said
    marked = 0  # how many marked spans are open
    stated: str | None = None  # what the writer says the open span shows
    stated_at = 0  # how many were open when that span began
    said = False  # whether what it shows has been reported
    pending: list[tuple[bytes, str]] = []
    for token, kind in _tokens(content):
        if kind in ("string", "hex", "number", "name"):
            pending.append((token, kind))
            continue
        if kind != "operator":
            continue
        numbers = [_number(value) for value, sort in pending if sort == "number"]
        if token in (b"Tj", b"'", b'"', b"TJ"):
            if token in (b"'", b'"'):
                if token == b'"' and len(numbers) >= 2:
                    pen.words, pen.spacing = numbers[-2], numbers[-1]
                _move(pen, 0.0, -pen.leading)
                last = None
            strings = [item for item in pending if item[1] in ("string", "hex")]
            drawn = _draw(pen, pending if token == b"TJ" else strings[-1:])
            text = drawn.text
            if stated is not None:
                # The span's first run reports what the writer says it shows,
                # and the rest report nothing but are still drawn where they are.
                text = "" if said else stated
                said = True
            if text and out:
                if last is not None:  # the pen is where the run before left it
                    gap = last.trail + drawn.lead
                    em = max(last.em, drawn.em)
                    out.append(" " if em > 0 and gap >= _WORD_GAP * em else "")
                else:
                    out.append(_between(end, _place(pen, drawn.lead)))
            out.append(text)
            # A run that draws nothing readable still stands between its
            # neighbours, so it leaves nothing to join the next one to.
            readable = bool(drawn.text if stated is None else stated)
            end = _place(pen, drawn.edge) if readable and drawn.edge is not None else None
            last = drawn if readable else None
            if drawn.advance is None:
                pen.lost = True
            else:
                pen.matrix = _multiply((1.0, 0.0, 0.0, 1.0, drawn.advance, 0.0), pen.matrix)
        elif token in (b"BMC", b"BDC"):
            marked += 1
            if stated is None and token == b"BDC":
                stated, stated_at, said = _actual_text(pending), marked, False
        elif token == b"EMC":
            if stated is not None and marked == stated_at:
                stated = None
            marked = max(marked - 1, 0)
        elif token == b"q":
            if len(saved) < _MAX_DEPTH:
                saved.append(replace(pen))
        elif token == b"Q":
            if saved:
                pen = replace(saved.pop(), matrix=pen.matrix, line=pen.line, lost=pen.lost)
                last = None
        elif token == b"cm" and len(numbers) >= 6:
            pen.ctm = _multiply(_matrix(numbers), pen.ctm)
            last = None
        elif token == b"BT":
            pen.matrix = pen.line = _IDENTITY
            pen.lost = False
            last = None
        elif token == b"Tf":
            names = [value for value, sort in pending if sort == "name"]
            if names:
                pen.font = fonts.get(names[-1][1:])
            if numbers:
                pen.size = numbers[-1]
        elif token in (b"Td", b"TD") and len(numbers) >= 2:
            if token == b"TD":
                pen.leading = -numbers[-1]
            _move(pen, numbers[-2], numbers[-1])
            last = None
        elif token == b"T*":
            _move(pen, 0.0, -pen.leading)
            last = None
        elif token == b"Tm" and len(numbers) >= 6:
            pen.matrix = pen.line = _matrix(numbers)
            pen.lost = False
            last = None
        elif numbers and token in _STATE:
            setattr(pen, _STATE[token], numbers[-1] / 100 if token == b"Tz" else numbers[-1])
        pending = []
    return "".join(out)


#: The text state set by a single number, and the name it has on the pen.
_STATE = {b"Tc": "spacing", b"Tw": "words", b"Tz": "scale", b"TL": "leading", b"Ts": "rise"}


def _actual_text(operands: list[tuple[bytes, str]]) -> str | None:
    """What a marked span's glyphs show, where the writer states it.

    A writer states it for a glyph no map can name: a browser draws the hyphen
    in a number with an alternate shape of it and maps that shape to nothing.
    The statement is a text string - UTF-16 behind a byte order mark, UTF-8
    behind one, and one byte a character otherwise.
    """
    for (key, sort), (value, kind) in pairwise(operands):
        if sort == "name" and key == b"/ActualText" and kind in ("string", "hex"):
            raw = _hex(value) if kind == "hex" else _literal(value)
            if raw.startswith(b"\xfe\xff"):
                return raw[2:].decode("utf-16-be", "replace")
            if raw.startswith(b"\xef\xbb\xbf"):
                return raw[3:].decode("utf-8", "replace")
            return raw.decode("latin-1")
    return None


class _Drawn(NamedTuple):
    """One showing instruction, measured along its line from where it starts.

    `edge` is the right side of the last glyph and `advance` where the pen is
    left, both `None` when the font gives no widths. `lead` and `trail` are
    the gaps before the first glyph and after the last, which need none: they
    are kerning and spacing, stated in the instruction itself.
    """

    text: str
    em: float
    lead: float
    trail: float
    edge: float | None
    advance: float | None


def _draw(pen: _Pen, drawn: list[tuple[bytes, str]]) -> _Drawn:
    """What one showing instruction draws, glyph by glyph.

    The gap after a glyph is the spacing the text state adds to it, and in a
    `TJ` array the kerning numbers too, so the gaps inside a run are known
    whatever the font. A document that draws `exam` `ple.com` a hair apart has
    written one address. One that sets its words out with character spacing,
    as a typesetter filling a line does, has written several.
    """
    font = pen.font
    em = abs(pen.size * pen.scale)
    text: list[str] = []
    lead, trail = 0.0, 0.0
    drawing = False  # whether a glyph has been drawn yet, so a gap is between two
    edge: float | None = None
    advance: float | None = 0.0
    for value, sort in drawn:
        if sort == "number":
            move = -_number(value) / 1000 * pen.size * pen.scale
            advance = None if advance is None else advance + move
            if drawing:
                trail += move
            else:
                lead += move
            continue
        raw = _hex(value) if sort == "hex" else _literal(value)
        for code, letter in _glyphs(raw, font):
            if drawing and em > 0 and trail >= _WORD_GAP * em:
                text.append(" ")
            text.append(letter)
            drawing = True
            width = None if font is None else font.advances.get(code, font.missing)
            if advance is None or width is None:
                advance = edge = None
            else:
                advance += width * pen.size * pen.scale
                edge = advance
            trail = pen.spacing * pen.scale
            if code == 32 and (font is None or font.width == 1):
                trail += pen.words * pen.scale  # word spacing is for a one-byte space only
            advance = None if advance is None else advance + trail
    return _Drawn("".join(text), em, lead, trail, edge, advance)


def _glyphs(raw: bytes, font: Font | None) -> Iterator[tuple[int, str]]:
    """Each code a string is drawn with, and what it reads as through its font."""
    for code in _codes(raw, 1 if font is None else font.width):
        if font is not None and font.table:
            yield code, font.table.get(code, "")
        elif font is not None and font.width > 1:
            yield code, ""  # a composite font whose codes mean nothing without its map
        else:
            # A font that states no encoding is read as ASCII and nothing else:
            # see the module docstring. Anything outside that range is dropped.
            yield code, chr(code) if 0x20 <= code <= 0x7E else ""


def _between(end: _Place | None, start: _Place | None) -> str:
    """What separates a run from the one before it, measured on the page."""
    if end is None or start is None:
        return "\n"
    x, y, run_x, run_y, before = end
    next_x, next_y, next_run_x, next_run_y, after = start
    em = max(before, after)
    if not em > 0 or run_x * next_run_x + run_y * next_run_y < 0.99:
        return "\n"  # nothing to measure with, or a line turned another way
    along = ((next_x - x) * run_x + (next_y - y) * run_y) / em
    off = ((next_y - y) * run_x - (next_x - x) * run_y) / em
    if not (abs(off) <= _SAME_LINE and along >= -_OVERLAP):
        return "\n"
    return " " if along >= _WORD_GAP else ""


def _place(pen: _Pen, offset: float) -> _Place | None:
    """A point this far along the pen's line, which way the line runs, and its
    em - on the page, where runs drawn under different matrices can be compared."""
    if pen.lost:
        return None
    a, b, c, d, e, f = _multiply((1.0, 0.0, 0.0, 1.0, offset, 0.0), _multiply(pen.matrix, pen.ctm))
    length = (a * a + b * b) ** 0.5
    if not length > 0:
        return None
    em = abs(pen.size) * (c * c + d * d) ** 0.5
    return pen.rise * c + e, pen.rise * d + f, a / length, b / length, em


def _move(pen: _Pen, x: float, y: float) -> None:
    """Start the next line this far from the start of the current one."""
    pen.line = _multiply((1.0, 0.0, 0.0, 1.0, x, y), pen.line)
    pen.matrix = pen.line
    pen.lost = False


def _multiply(first: _Matrix, second: _Matrix) -> _Matrix:
    a, b, c, d, e, f = first
    p, q, r, s, t, u = second
    return (
        a * p + b * r,
        a * q + b * s,
        c * p + d * r,
        c * q + d * s,
        e * p + f * r + t,
        e * q + f * s + u,
    )


def _matrix(numbers: list[float]) -> _Matrix:
    a, b, c, d, e, f = numbers[-6:]
    return (a, b, c, d, e, f)


def _number(value: bytes) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0


def _codes(raw: bytes, width: int) -> Iterator[int]:
    """The string's bytes as the codes the font is shown, however wide."""
    if width <= 1:
        yield from raw
        return
    for at in range(0, len(raw) - width + 1, width):
        yield int.from_bytes(raw[at : at + width], "big")


def _hex(value: bytes) -> bytes:
    digits = re.sub(rb"[^0-9A-Fa-f]", b"", value)
    if len(digits) % 2:
        digits += b"0"
    try:
        return bytes.fromhex(digits.decode("ascii"))
    except ValueError:
        return b""


_ESCAPES = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}
_OCTAL = set(b"01234567")


def _literal(value: bytes) -> bytes:
    """A `(...)` string with its escapes undone, still as the font's own bytes."""
    out = bytearray()
    index = 0
    while index < len(value):
        char = value[index]
        if char != 0x5C:  # backslash
            out.append(char)
            index += 1
            continue
        index += 1
        if index >= len(value):
            break
        nxt = value[index]
        if nxt in _OCTAL:
            octal = bytearray()
            while len(octal) < 3 and index < len(value) and value[index] in _OCTAL:
                octal.append(value[index])
                index += 1
            out.append(int(octal, 8) & 0xFF)
            continue
        if nxt in _ESCAPES:
            out.append(_ESCAPES[nxt])
        elif nxt not in (10, 13):  # a line continuation draws nothing
            out.append(nxt)
        index += 1
    return bytes(out)


def _tokens(content: bytes) -> Iterator[tuple[bytes, str]]:
    """The content stream's tokens, with strings scanned rather than matched.

    A PDF string nests its parentheses, which no regular expression can follow,
    so the one construct that needs a scanner gets one and everything else is
    matched around it.
    """
    index, length = 0, len(content)
    while index < length:
        char = content[index]
        if char in b" \t\r\n\x00":
            index += 1
            continue
        if char == 0x28:  # (
            start = index + 1
            depth, index = 1, index + 1
            while index < length and depth:
                if content[index] == 0x5C:
                    index += 2
                    continue
                if content[index] == 0x28:
                    depth += 1
                elif content[index] == 0x29:
                    depth -= 1
                index += 1
            yield content[start : index - 1], "string"
            continue
        if char == 0x3C and index + 1 < length and content[index + 1] != 0x3C:  # <
            end = content.find(b">", index)
            if end == -1:
                return
            yield content[index + 1 : end], "hex"
            index = end + 1
            continue
        match = re.compile(rb"<<|>>|/[^\s/\[\]<>(){}]*|[-+.\d][-+.\d]*|[A-Za-z'\"*]+").match(
            content, index
        )
        if match is None:
            index += 1
            continue
        token = match.group(0)
        if token[:1] == b"/":
            yield token, "name"
        elif token[:1].isdigit() or token[:1] in b"-+.":
            yield token, "number"
        elif token in (b"<<", b">>"):
            pass
        else:
            yield token, "operator"
        index = match.end()
