"""Metadata declared by a saved web document.

The page is read as a file, never fetched.  HTML metadata is useful precisely
because a saved article can keep its canonical URL, author, publisher and
publication date after browser history has expired.  Values are reported as
claims made by the document, not as facts verified against the live site.
"""

from __future__ import annotations

import codecs
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

SUFFIXES = {".html", ".htm", ".xhtml"}

_MAX_BYTES = 2 * 1024 * 1024
_MAX_VALUE = 4096
_MAX_JSON_LD = 16
_MAX_JSON_LD_CHARS = 256 * 1024
_MAX_SEMANTIC_CAPTURES = 256
_MAX_CAPTURE_CHARS = 4096

_CHARSET = re.compile(rb"charset\s*=\s*['\"]?\s*([a-z0-9._-]+)", re.IGNORECASE)

# Names are normalized only to decide what to keep.  The stable spelling on
# the right is retained in JSON and reports, so `datePublished` does not become
# a different field depending on whether HTML used `name`, `property` or
# `itemprop`.
_META_KEYS = {
    name.lower(): name
    for name in (
        "author",
        "publisher",
        "generator",
        "application-name",
        "description",
        "date",
        "datePublished",
        "dateModified",
        "article:author",
        "article:published_time",
        "article:modified_time",
        "og:title",
        "og:description",
        "og:url",
        "og:image",
        "og:video",
        "og:audio",
        "og:site_name",
        "og:type",
        "twitter:title",
        "twitter:description",
        "twitter:image",
        "twitter:player",
        "twitter:site",
        "twitter:creator",
        "citation_author",
        "citation_publication_date",
        "dc.creator",
        "dcterms.creator",
        "dcterms.date",
        "dcterms.issued",
        "dcterms.modified",
    )
}

_JSON_LD_KEYS = (
    "@type",
    "headline",
    "name",
    "url",
    "datePublished",
    "dateModified",
    "author",
    "publisher",
    "image",
    "video",
    "audio",
    "mainEntityOfPage",
    "contentUrl",
    "embedUrl",
)

_SEMANTIC_KEYS = {
    name.casefold(): name
    for name in (
        "author",
        "creator",
        "publisher",
        "copyrightHolder",
        "copyrightYear",
        "license",
        "headline",
        "name",
        "url",
        "datePublished",
        "dateModified",
        "dateCreated",
        "uploadDate",
        "image",
        "video",
        "audio",
        "contentUrl",
        "embedUrl",
        "mainEntityOfPage",
    )
}


@dataclass(slots=True)
class _Capture:
    tag: str
    prefix: str
    names: tuple[str, ...]
    parts: list[str] = field(default_factory=list)
    size: int = 0


@dataclass(slots=True)
class WebDocument:
    """The bounded set of provenance-relevant declarations in one page."""

    fields: dict[str, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.fields)


def read_web_document(path: Path) -> WebDocument | None:
    """Read metadata from a local HTML document without any network access."""
    try:
        with path.open("rb") as handle:
            raw = handle.read(_MAX_BYTES + 1)
    except OSError:
        return None
    utf16 = raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE))
    if not raw or (b"\x00" in raw[:8192] and not utf16):
        return None

    parser = _WebMetadata()
    try:
        parser.feed(_decode(raw[:_MAX_BYTES]))
        parser.close()
    except (ValueError, AssertionError):
        return None

    parser.finish()
    return WebDocument(parser.fields) if parser.fields else None


def _decode(raw: bytes) -> str:
    for mark, encoding in (
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    ):
        if raw.startswith(mark):
            return raw.decode(encoding, "replace")

    match = _CHARSET.search(raw[:16384])
    if match:
        encoding = match.group(1).decode("ascii", "ignore")
        try:
            codecs.lookup(encoding)
        except LookupError:
            pass
        else:
            return raw.decode(encoding, "replace")
    return raw.decode("utf-8", "replace")


class _WebMetadata(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fields: dict[str, str] = {}
        self._title = 0
        self._title_parts: list[str] = []
        self._json_ld: list[list[str]] = []
        self._json_ld_active: list[str] | None = None
        self._json_ld_size = 0
        self._captures: list[_Capture] = []
        self._capture_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = {name.lower(): value for name, value in attrs if value is not None}

        if tag == "html":
            self._keep("lang", values.get("lang"))
        elif tag == "title":
            self._title += 1
        elif tag == "meta":
            key = values.get("name") or values.get("property") or values.get("itemprop")
            canonical = _META_KEYS.get(key.strip().lower()) if key else None
            if canonical:
                self._keep(canonical, values.get("content"))
        elif tag == "link" and "canonical" in _tokens(values.get("rel")):
            self._keep("canonical", values.get("href"))
        elif (
            tag == "script"
            and values.get("type", "").split(";", 1)[0].strip().lower() == "application/ld+json"
            and len(self._json_ld) < _MAX_JSON_LD
        ):
            self._json_ld_active = []
            self._json_ld_size = 0
            self._json_ld.append(self._json_ld_active)

        self._semantic_start(tag, values)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title" and self._title:
            self._title -= 1
            if not self._title:
                self._keep("title", "".join(self._title_parts))
                self._title_parts.clear()
        elif tag.lower() == "script":
            self._json_ld_active = None
        self._semantic_end(tag.lower())

    def handle_data(self, data: str) -> None:
        if self._title:
            self._title_parts.append(data)
        if self._json_ld_active is not None:
            remaining = _MAX_JSON_LD_CHARS - self._json_ld_size
            if remaining > 0:
                kept = data[:remaining]
                self._json_ld_active.append(kept)
                self._json_ld_size += len(kept)
        for capture in self._captures:
            remaining = _MAX_CAPTURE_CHARS - capture.size
            if remaining > 0:
                kept = data[:remaining]
                capture.parts.append(kept)
                capture.size += len(kept)

    def finish(self) -> None:
        for parts in self._json_ld:
            raw = "".join(parts)
            if not raw.strip() or len(raw) > _MAX_JSON_LD_CHARS:
                continue
            try:
                value = json.loads(raw)
            except (json.JSONDecodeError, RecursionError):
                continue
            for key, item in _jsonld_fields(value).items():
                self._keep(f"jsonld:{key}", item)

    def _keep(self, name: str, value: str | None) -> None:
        if not value or name in self.fields:
            return
        collapsed = " ".join(value.split())
        if collapsed:
            self.fields[name] = collapsed[:_MAX_VALUE]

    def _semantic_start(self, tag: str, values: dict[str, str]) -> None:
        itemtype = values.get("itemtype")
        if itemtype:
            self._keep("microdata:@type", itemtype)
        rdftype = values.get("typeof")
        if rdftype:
            self._keep("rdfa:@type", rdftype)

        for attribute, prefix in (("itemprop", "microdata"), ("property", "rdfa")):
            names = _semantic_names(values.get(attribute))
            if not names:
                continue
            direct = _semantic_value(tag, values)
            if direct is not None:
                for name in names:
                    self._keep(f"{prefix}:{name}", direct)
            elif self._capture_count < _MAX_SEMANTIC_CAPTURES:
                self._capture_count += 1
                self._captures.append(_Capture(tag, prefix, names))

    def _semantic_end(self, tag: str) -> None:
        for index in range(len(self._captures) - 1, -1, -1):
            capture = self._captures[index]
            if capture.tag != tag:
                continue
            self._captures.pop(index)
            value = "".join(capture.parts)
            for name in capture.names:
                self._keep(f"{capture.prefix}:{name}", value)
            return


def _tokens(value: str | None) -> set[str]:
    return {token.lower() for token in value.split()} if value else set()


# Open Graph and its extensions use `property` too.  Those names are kept under
# their own spelling by `_META_KEYS`; they are not RDFa vocabulary terms.
_SOCIAL_PREFIXES = {
    "og",
    "article",
    "book",
    "profile",
    "music",
    "video",
    "fb",
    "twitter",
    "al",
    "place",
    "product",
}


def _semantic_names(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    found = []
    for raw in value.split():
        local = raw.rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        if ":" in local:
            prefix, local = local.rsplit(":", 1)
            if prefix.lower() in _SOCIAL_PREFIXES:
                continue
        if canonical := _SEMANTIC_KEYS.get(local.casefold()):
            found.append(canonical)
    return tuple(dict.fromkeys(found))


def _semantic_value(tag: str, values: dict[str, str]) -> str | None:
    for attribute in ("content", "resource", "href", "src", "datetime", "data", "value"):
        if value := values.get(attribute):
            return value
    if tag in {"meta", "link", "img", "audio", "video", "source", "object", "time", "data"}:
        return ""
    return None


def _jsonld_fields(value: object) -> dict[str, str]:
    found: dict[str, str] = {}
    for node in _jsonld_nodes(value):
        for key in _JSON_LD_KEYS:
            if key in found:
                continue
            text = _jsonld_value(node.get(key))
            if text:
                found[key] = text
    return found


def _jsonld_nodes(value: object) -> list[dict[str, Any]]:
    """Top-level entities and `@graph` members, never an unbounded walk."""
    roots = value if isinstance(value, list) else [value]
    nodes: list[dict[str, Any]] = []
    for root in roots[:256]:
        if not isinstance(root, dict):
            continue
        graph = root.get("@graph")
        if isinstance(graph, list):
            nodes.extend(item for item in graph[:256] if isinstance(item, dict))
        if any(key in root for key in _JSON_LD_KEYS):
            nodes.append(root)

    # Article/page entities carry the evidence sought here.  Put them before a
    # publisher or breadcrumb entity if a graph happened to list those first.
    return sorted(nodes[:256], key=_jsonld_rank, reverse=True)


def _jsonld_rank(node: dict[str, Any]) -> int:
    kind = _jsonld_value(node.get("@type")) or ""
    score = 2 if any(word in kind.lower() for word in ("article", "page", "posting")) else 0
    return score + sum(key in node for key in ("headline", "datePublished", "author"))


def _jsonld_value(value: object) -> str | None:
    if isinstance(value, str):
        return " ".join(value.split())[:_MAX_VALUE] or None
    if isinstance(value, list):
        values = [text for item in value[:32] if (text := _jsonld_value(item))]
        return ", ".join(dict.fromkeys(values))[:_MAX_VALUE] or None
    if isinstance(value, dict):
        for key in ("name", "headline", "url", "contentUrl", "embedUrl", "@id"):
            if text := _jsonld_value(value.get(key)):
                return text
    return None
