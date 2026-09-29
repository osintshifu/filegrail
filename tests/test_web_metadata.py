from pathlib import Path

from filegrail.identify import extract
from filegrail.models import FileRecord
from filegrail.sources.embedded import read_embedded_metadata


def test_reads_declared_web_document_metadata(tmp_path: Path):
    page = tmp_path / "article.html"
    page.write_text(
        """<!doctype html>
<html lang="pl">
<head>
  <title>Investigation notes</title>
  <meta name="author" content="Anna Nowak">
  <meta name="generator" content="Hugo 0.148.2">
  <meta property="og:site_name" content="Example News">
  <meta property="article:published_time" content="2026-09-18T11:20:00+02:00">
  <meta property="og:image" content="https://cdn.example.org/lead.jpg">
  <link rel="canonical" href="https://example.org/article/123">
</head>
<body>Visible text is content, not metadata.</body>
</html>""",
        encoding="utf-8",
    )

    found = read_embedded_metadata(page)

    assert found is not None
    assert found.source == "document-metadata"
    assert found.block == "web-document"
    assert found.tool == "Hugo 0.148.2"
    assert found.at == "2026-09-18T09:20:00Z"
    assert found.note == "author Anna Nowak; publisher Example News; title Investigation notes"
    assert found.fields == {
        "lang": "pl",
        "title": "Investigation notes",
        "author": "Anna Nowak",
        "generator": "Hugo 0.148.2",
        "og:site_name": "Example News",
        "article:published_time": "2026-09-18T11:20:00+02:00",
        "og:image": "https://cdn.example.org/lead.jpg",
        "canonical": "https://example.org/article/123",
    }

    record = FileRecord(
        path=str(page), size=page.stat().st_size, mtime="2026-09-18T10:00:00Z", evidence=[found]
    )
    pivots = {(pivot.type, pivot.normalized) for pivot in extract([record])}
    assert ("url", "https://example.org/article/123") in pivots
    assert ("domain", "cdn.example.org") in pivots


def test_reads_bounded_json_ld_into_named_fields(tmp_path: Path):
    page = tmp_path / "story.xhtml"
    page.write_text(
        """<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@graph": [{
    "@type": "NewsArticle",
    "headline": "A recorded headline",
    "url": "https://example.net/story",
    "datePublished": "2026-08-09T07:06:05Z",
    "dateModified": "2026-08-10T08:00:00Z",
    "author": {"@type": "Person", "name": "Maria Wolf"},
    "publisher": {"@type": "Organization", "name": "Example Press"},
    "image": {"url": "https://img.example.net/story.webp"}
  }]
}
</script>
</head><body>text after the script must not become part of JSON-LD</body></html>""",
        encoding="utf-8",
    )

    found = read_embedded_metadata(page)

    assert found is not None
    assert found.at == "2026-08-09T07:06:05Z"
    assert found.note == "author Maria Wolf; publisher Example Press; title A recorded headline"
    assert found.fields["jsonld:@type"] == "NewsArticle"
    assert found.fields["jsonld:author"] == "Maria Wolf"
    assert found.fields["jsonld:publisher"] == "Example Press"
    assert found.fields["jsonld:url"] == "https://example.net/story"
    assert found.fields["jsonld:image"] == "https://img.example.net/story.webp"
    assert found.fields["jsonld:dateModified"] == "2026-08-10T08:00:00Z"


def test_meta_values_take_precedence_over_json_ld_fallbacks(tmp_path: Path):
    page = tmp_path / "article.htm"
    page.write_text(
        """<html><head>
<meta name="author" content="Declared Author">
<meta property="og:title" content="Declared title">
<script type="application/ld+json">
{"headline":"Fallback title","author":{"name":"Fallback Author"}}
</script>
</head></html>""",
        encoding="utf-8",
    )

    found = read_embedded_metadata(page)

    assert found is not None
    assert found.note == "author Declared Author; title Declared title"
    assert found.fields["author"] == "Declared Author"
    assert found.fields["jsonld:author"] == "Fallback Author"


def test_malformed_or_content_only_html_does_not_invent_metadata(tmp_path: Path):
    malformed = tmp_path / "broken.html"
    malformed.write_text(
        '<html><head><script type="application/ld+json">{not json}</script></head></html>',
        encoding="utf-8",
    )
    plain = tmp_path / "plain.html"
    plain.write_text("<html><body>Anna wrote this page.</body></html>", encoding="utf-8")

    assert read_embedded_metadata(malformed) is None
    assert read_embedded_metadata(plain) is None


def test_declared_charset_is_used_for_web_metadata(tmp_path: Path):
    page = tmp_path / "legacy.html"
    page.write_bytes(
        '<html><head><meta charset="windows-1250"><meta name="author" '
        'content="Małgorzata Żak"></head></html>'.encode("windows-1250")
    )

    found = read_embedded_metadata(page)

    assert found is not None
    assert found.fields["author"] == "Małgorzata Żak"


def test_utf16_bom_is_not_mistaken_for_a_binary_file(tmp_path: Path):
    page = tmp_path / "unicode.html"
    page.write_text(
        '<html><head><meta name="author" content="李明"></head></html>',
        encoding="utf-16",
    )

    found = read_embedded_metadata(page)

    assert found is not None
    assert found.fields["author"] == "李明"


def test_microdata_and_rdfa_values_are_read_from_body_elements(tmp_path: Path):
    page = tmp_path / "post.html"
    page.write_text(
        """<html><head>
<meta property="og:image" content="https://cdn.example.org/lead.jpg">
</head><body>
<article itemscope itemtype="https://schema.org/BlogPosting">
  <h1 itemprop="headline">Field <em>notes</em></h1>
  <span itemprop="author">Jan Kowalski</span>
  <time itemprop="datePublished" datetime="2026-09-18T08:00:00Z">18 Sept</time>
  <a itemprop="url" href="https://example.org/post/7">permalink</a>
</article>
<div vocab="https://schema.org/" typeof="Article">
  <span property="publisher">Example Press</span>
  <link property="license" href="https://creativecommons.org/licenses/by/4.0/">
</div>
</body></html>""",
        encoding="utf-8",
    )

    found = read_embedded_metadata(page)

    assert found is not None
    assert found.note == "author Jan Kowalski; publisher Example Press; title Field notes"
    assert found.at == "2026-09-18T08:00:00Z"
    assert found.fields["microdata:@type"] == "https://schema.org/BlogPosting"
    assert found.fields["microdata:headline"] == "Field notes"
    assert found.fields["microdata:datePublished"] == "2026-09-18T08:00:00Z"
    assert found.fields["microdata:url"] == "https://example.org/post/7"
    assert found.fields["rdfa:@type"] == "Article"
    assert found.fields["rdfa:license"] == "https://creativecommons.org/licenses/by/4.0/"
    assert "rdfa:image" not in found.fields
