from __future__ import annotations

from offroad_scraper.link_extractor import extract_candidate_urls, parse_rss_links

BASE = "https://example.com/trips"


def test_extracts_same_domain_links() -> None:
    html = '<a href="/trip-a">A</a> <a href="https://example.com/trip-b">B</a>'
    assert extract_candidate_urls(html, BASE) == [
        "https://example.com/trip-a",
        "https://example.com/trip-b",
    ]


def test_resolves_relative_links() -> None:
    html = '<a href="subpage">x</a>'
    assert extract_candidate_urls(html, "https://example.com/dir/") == [
        "https://example.com/dir/subpage"
    ]


def test_excludes_external_domains() -> None:
    html = '<a href="https://other.com/x">x</a> <a href="/local">y</a>'
    assert extract_candidate_urls(html, BASE) == ["https://example.com/local"]


def test_excludes_root_and_fragment() -> None:
    html = '<a href="/">home</a> <a href="/#foo">frag</a> <a href="/trip">t</a>'
    assert extract_candidate_urls(html, BASE) == ["https://example.com/trip"]


def test_excludes_assets() -> None:
    html = (
        '<a href="/style.css">css</a> <a href="/img.png">png</a> '
        '<a href="/doc.pdf">pdf</a> <a href="/trip">t</a>'
    )
    assert extract_candidate_urls(html, BASE) == ["https://example.com/trip"]


def test_excludes_blocklist_and_custom_paths() -> None:
    html = (
        '<a href="/contact">c</a> <a href="/post/hello">blog</a> '
        '<a href="/reserveer-je-avontuur">nav</a> <a href="/trip">t</a>'
    )
    urls = extract_candidate_urls(html, BASE, exclude_paths=["/reserveer"])
    assert urls == ["https://example.com/trip"]


def test_deduplicates() -> None:
    html = '<a href="/trip">a</a> <a href="/trip">b</a>'
    assert extract_candidate_urls(html, BASE) == ["https://example.com/trip"]


def test_ignores_non_http_schemes() -> None:
    html = (
        '<a href="javascript:void(0)">js</a> <a href="mailto:x@y.com">mail</a> '
        '<a href="tel:123">tel</a> <a href="/trip">t</a>'
    )
    assert extract_candidate_urls(html, BASE) == ["https://example.com/trip"]


def test_caps_at_max_urls() -> None:
    links = "".join(f'<a href="/trip-{i}">x</a>' for i in range(10))
    assert len(extract_candidate_urls(links, BASE, max_urls=3)) == 3


RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>A</title><link>https://example.com/trip-a</link></item>
  <item><title>B</title><link>https://example.com/trip-b</link></item>
  <item><title>C</title><link>https://other.com/x</link></item>
</channel></rss>
"""


def test_parse_rss_links_extracts_item_links() -> None:
    assert parse_rss_links(RSS, BASE) == [
        "https://example.com/trip-a",
        "https://example.com/trip-b",
    ]


def test_parse_rss_links_excludes_blocked_paths() -> None:
    rss = """<rss version="2.0"><channel>
      <item><link>https://example.com/contact</link></item>
      <item><link>https://example.com/trip-a</link></item>
    </channel></rss>"""
    assert parse_rss_links(rss, BASE) == ["https://example.com/trip-a"]


def test_parse_rss_links_atom() -> None:
    atom = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>A</title><link href="https://example.com/trip-a"/></entry>
    </feed>"""
    assert parse_rss_links(atom, BASE) == ["https://example.com/trip-a"]


def test_parse_rss_links_invalid_xml() -> None:
    assert parse_rss_links("not xml", BASE) == []
