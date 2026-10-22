from __future__ import annotations

from offroad_scraper.link_extractor import extract_candidate_urls

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
