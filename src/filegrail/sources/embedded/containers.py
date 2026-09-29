"""Zip-based and text-based document containers.

Each of these keeps its provenance in a well-known place, and each is reachable
with nothing but the standard library:

    ODF     meta.xml: meta:generator, dc:creator, meta:creation-date
    EPUB    the OPF package: dc:creator, dc:date, the generator meta
    RTF     the \\*\\generator group
    SVG     inkscape:version, an Illustrator comment, or Dublin Core
    IPYNB   the kernel and language recorded by Jupyter
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ElementTree
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .parts import read_part

ODF_SUFFIXES = {".odt", ".ods", ".odp", ".odg", ".odf", ".otp", ".ott"}
EPUB_SUFFIXES = {".epub"}
RTF_SUFFIXES = {".rtf"}
SVG_SUFFIXES = {".svg"}
NOTEBOOK_SUFFIXES = {".ipynb"}
SUFFIXES = ODF_SUFFIXES | EPUB_SUFFIXES | RTF_SUFFIXES | SVG_SUFFIXES | NOTEBOOK_SUFFIXES

_OFFICE_META = "urn:oasis:names:tc:opendocument:xmlns:meta:1.0"
_OFFICE = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
_DC = "http://purl.org/dc/elements/1.1/"
_OPF = "http://www.idpf.org/2007/opf"
_CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
_INKSCAPE = "http://www.inkscape.org/namespaces/inkscape"

_TEXT_SCAN_BYTES = 256 * 1024
_RTF_GENERATOR = re.compile(rb"\{\\\*\\generator ([^;}]{1,200})")
_SVG_COMMENT = re.compile(r"<!--\s*(?:Generator|Created with)\s*:?\s*([^\n]{3,120}?)\s*-->", re.I)


@dataclass(slots=True)
class Document:
    """What a container says about its own creation."""

    tool: str | None = None
    author: str | None = None
    created: str | None = None
    title: str | None = None

    #: Which of the five standards this came from. One reader serves all of
    #: them, and a caller comparing a self-description against its mirror has
    #: to know whether it is holding an ODF `meta.xml` or an OPF package.
    block: str | None = None

    #: Everything else the container declared. ODF records how many times a
    #: document was edited and for how long; an OPF package records identifiers,
    #: publisher and language. None of it fits a four-field summary.
    fields: dict[str, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return any((self.tool, self.author, self.created, self.title))


def read_container(path: Path) -> Document | None:
    suffix = path.suffix.lower()
    for suffixes, read, block in (
        (ODF_SUFFIXES, _read_odf, "odf-meta"),
        (EPUB_SUFFIXES, _read_epub, "epub-package"),
        (RTF_SUFFIXES, _read_rtf, "rtf-generator"),
        (SVG_SUFFIXES, _read_svg, "svg-metadata"),
        (NOTEBOOK_SUFFIXES, _read_notebook, "notebook-kernel"),
    ):
        if suffix not in suffixes:
            continue
        try:
            found = read(path)
        except (OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError, KeyError):
            return None
        if not found:
            return None
        found.block = block
        return found
    return None


#: ODF keeps arbitrary document properties here, one element per property.
_USER_DEFINED = f"{{{_OFFICE_META}}}user-defined"


def _read_odf(path: Path) -> Document:
    with zipfile.ZipFile(path) as archive:
        if "meta.xml" not in archive.namelist():
            return Document()
        meta_xml = read_part(archive, "meta.xml")
        if meta_xml is None:
            return Document()
        root = ElementTree.fromstring(meta_xml)

    meta = root.find(f"{{{_OFFICE}}}meta")
    if meta is None:
        meta = root
    return Document(
        fields=_declared(meta),
        tool=_text(meta.findtext(f"{{{_OFFICE_META}}}generator")),
        author=_text(meta.findtext(f"{{{_DC}}}creator"))
        or _text(meta.findtext(f"{{{_OFFICE_META}}}initial-creator")),
        created=_text(meta.findtext(f"{{{_OFFICE_META}}}creation-date")),
        title=_text(meta.findtext(f"{{{_DC}}}title")),
    )


def _declared(element: ElementTree.Element) -> dict[str, str]:
    """Every child element that carries text, by local name.

    Attributes are included because the statistics element keeps its page, table
    and word counts in them and nowhere else.

    `meta:user-defined` is the exception, and it needs its own reading. It is a
    *list* of properties whose names live in an attribute rather than in the tag,
    so treating it like every other child collapses the whole list into one
    field: the first value wins, the rest are dropped, and the attribute names of
    the others scatter into fields of their own - a document reporting `name
    AppVersion` and `value-type float`, neither of which anybody wrote. The
    developer's corpus has a spreadsheet with six of them where three fields came
    out and five properties went missing.

    They are collected apart and merged afterwards so that a real element always
    wins the name: a user-defined property may legitimately be called `creator`,
    and it does not get to answer for `dc:creator`.
    """
    found: dict[str, str] = {}
    defined: dict[str, str] = {}

    for child in element:
        if child.tag == _USER_DEFINED:
            name = _text(child.get(f"{{{_OFFICE_META}}}name"))
            value = (child.text or "").strip()
            if name and value:
                defined.setdefault(name, value)
            continue

        name = child.tag.rsplit("}", 1)[-1]
        value = (child.text or "").strip()
        if value and name not in found:
            found[name] = value
        for key, attribute in child.attrib.items():
            found.setdefault(key.rsplit("}", 1)[-1], attribute)

    for name, value in defined.items():
        found.setdefault(name, value)
    return found


def _read_epub(path: Path) -> Document:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        opf_name = None
        if "META-INF/container.xml" in names:
            declaration = read_part(archive, "META-INF/container.xml")
            if declaration is not None:
                container = ElementTree.fromstring(declaration)
                root_file = container.find(f".//{{{_CONTAINER_NS}}}rootfile")
                if root_file is not None:
                    opf_name = root_file.get("full-path")
        if opf_name is None:
            opf_name = next((name for name in names if name.endswith(".opf")), None)
        if opf_name is None or opf_name not in names:
            return Document()
        opf = read_part(archive, opf_name)
        if opf is None:
            return Document()
        package = ElementTree.fromstring(opf)

    generator = None
    for meta in package.iter(f"{{{_OPF}}}meta"):
        if (meta.get("name") or "").lower() in ("generator", "calibre:timestamp"):
            generator = generator or _text(meta.get("content"))
    return Document(
        tool=generator,
        author=_text(package.findtext(f".//{{{_DC}}}creator")),
        created=_text(package.findtext(f".//{{{_DC}}}date")),
        title=_text(package.findtext(f".//{{{_DC}}}title")),
    )


def _read_rtf(path: Path) -> Document:
    with path.open("rb") as handle:
        head = handle.read(_TEXT_SCAN_BYTES)
    match = _RTF_GENERATOR.search(head)
    if not match:
        return Document()
    return Document(tool=match.group(1).decode("latin-1", "replace").strip())


def _read_svg(path: Path) -> Document:
    with path.open("rb") as handle:
        head = handle.read(_TEXT_SCAN_BYTES)
    text = head.decode("utf-8", "replace")

    tool = None
    comment = _SVG_COMMENT.search(text)
    if comment:
        tool = comment.group(1).strip()

    author = None
    try:
        root = ElementTree.fromstring(text) if text.rstrip().endswith(">") else None
    except ElementTree.ParseError:
        root = None
    if root is not None:
        version = root.get(f"{{{_INKSCAPE}}}version")
        if version:
            tool = tool or f"Inkscape {version}"
        author = _text(root.findtext(f".//{{{_DC}}}creator"))
    elif "inkscape:version" in text:
        found = re.search(r'inkscape:version="([^"]{1,60})"', text)
        if found:
            tool = tool or f"Inkscape {found.group(1)}"

    return Document(tool=tool, author=author)


def _read_notebook(path: Path) -> Document:
    with path.open("rb") as handle:
        payload = json.loads(handle.read(_TEXT_SCAN_BYTES * 8).decode("utf-8", "replace"))
    if not isinstance(payload, dict):
        return Document()
    metadata = payload.get("metadata") or {}
    kernel = (metadata.get("kernelspec") or {}).get("display_name")
    language = metadata.get("language_info") or {}
    name = _text(language.get("name"))
    version = _text(language.get("version"))

    runtime = f"{name} {version}".strip() if name else None
    parts = [part for part in (_text(kernel), runtime) if part]
    tool = f"Jupyter ({', '.join(parts)})" if parts else "Jupyter notebook"

    authors = metadata.get("authors")
    author = _text(authors[0].get("name")) if isinstance(authors, list) and authors else None
    return Document(tool=tool, author=author)


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
