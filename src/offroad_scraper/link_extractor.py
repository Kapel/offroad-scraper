from __future__ import annotations

import html as html_lib
import re
from urllib.parse import urljoin, urlparse

import structlog
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

logger = structlog.get_logger(__name__)

_HREF_RE = re.compile(r'<a\s[^>]*?href\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_ASSET_SUFFIX_RE = re.compile(
    r"\.(?:css|js|png|jpe?g|gif|svg|webp|ico|pdf|woff2?|json|xml|zip|mp4|webm|rss|atom)"
    r"(?:[?#]|$)",
    re.IGNORECASE,
)

_ATOM_NS = "{http://www.w3.org/2005/Atom}"

# Common navigation / utility paths that are never trip offers. Matching is a
# case-insensitive substring test against the URL path.
DEFAULT_EXCLUDE_PATHS = (
    "/contact",
    "/about",
    "/login",
    "/logout",
    "/register",
    "/signup",
    "/blog",
    "/news",
    "/cart",
    "/checkout",
    "/account",
    "/privacy",
    "/terms",
    "/cookie",
    "/faq",
    "/shop",
    "/winkel",
    "/impressum",
    "/post/",
    "/author",
    "/category/",
    "/tag/",
    "/page/",
)


def _resolve_and_keep(
    href: str,
    base_url: str,
    exclusions: tuple[str, ...],
) -> str | None:
    """Resolve ``href`` against ``base_url`` and return the cleaned URL if it is
    a same-domain, non-asset, non-nav http(s) link, else ``None``."""
    base = urlparse(base_url)
    resolved = urljoin(base_url, href)
    parsed = urlparse(resolved)
    if parsed.scheme not in ("http", "https"):
        return None
    if parsed.netloc.lower() != base.netloc.lower():
        return None
    path = parsed.path
    if path in ("", "/"):
        return None
    if _ASSET_SUFFIX_RE.search(path):
        return None
    if any(exclusion in path.lower() for exclusion in exclusions):
        return None
    return urlparse(resolved)._replace(fragment="").geturl()


def _dedupe(links: list[str], max_urls: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for link in links:
        if link in seen:
            continue
        seen.add(link)
        result.append(link)
        if len(result) >= max_urls:
            break
    return result


def extract_candidate_urls(
    html: str,
    base_url: str,
    *,
    exclude_paths: list[str] | tuple[str, ...] = (),
    max_urls: int = 20,
) -> list[str]:
    """Discover same-domain trip-detail links from an HTML listing page."""
    base = urlparse(base_url)
    if base.scheme not in ("http", "https") or not base.netloc:
        logger.warning("invalid base url for link extraction", base_url=base_url)
        return []

    exclusions = tuple(p.lower() for p in (*DEFAULT_EXCLUDE_PATHS, *exclude_paths))
    links: list[str] = []
    for match in _HREF_RE.finditer(html):
        href = html_lib.unescape(match.group(1)).strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "data:", "#")):
            continue
        kept = _resolve_and_keep(href, base_url, exclusions)
        if kept is not None:
            links.append(kept)
        if len(_dedupe(links, max_urls)) >= max_urls:
            break
    return _dedupe(links, max_urls)


def parse_rss_links(
    xml_text: str,
    base_url: str,
    *,
    exclude_paths: list[str] | tuple[str, ...] = (),
    max_urls: int = 20,
) -> list[str]:
    """Discover trip links from an RSS 2.0 or Atom feed."""
    base = urlparse(base_url)
    if base.scheme not in ("http", "https") or not base.netloc:
        logger.warning("invalid base url for rss parsing", base_url=base_url)
        return []

    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, DefusedXmlException, ValueError) as exc:
        logger.error("failed to parse rss feed", base_url=base_url, error=str(exc))
        return []

    exclusions = tuple(p.lower() for p in (*DEFAULT_EXCLUDE_PATHS, *exclude_paths))
    raw: list[str] = []

    # RSS 2.0
    for item in root.iter("item"):
        link = item.findtext("link")
        if link:
            raw.append(link.strip())

    # Atom (only used if no RSS items were found)
    if not raw:
        for entry in root.iter(f"{_ATOM_NS}entry"):
            link = entry.find(f"{_ATOM_NS}link")
            href = link.get("href") if link is not None else None
            if href:
                raw.append(href.strip())

    links: list[str] = []
    for href in raw:
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "data:", "#")):
            continue
        kept = _resolve_and_keep(href, base_url, exclusions)
        if kept is not None:
            links.append(kept)
    return _dedupe(links, max_urls)
