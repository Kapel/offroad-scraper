from __future__ import annotations

import html as html_lib
import re
from urllib.parse import urljoin, urlparse

import structlog

logger = structlog.get_logger(__name__)

_HREF_RE = re.compile(r'<a\s[^>]*?href\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_ASSET_SUFFIX_RE = re.compile(
    r"\.(?:css|js|png|jpe?g|gif|svg|webp|ico|pdf|woff2?|json|xml|zip|mp4|webm|rss|atom)"
    r"(?:[?#]|$)",
    re.IGNORECASE,
)

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


def extract_candidate_urls(
    html: str,
    base_url: str,
    *,
    exclude_paths: list[str] | tuple[str, ...] = (),
    max_urls: int = 20,
) -> list[str]:
    """Discover same-domain trip-detail links from a listing page.

    Only absolute http(s) URLs on the same host are considered; asset files,
    the root page, fragments, and a blocklist of common navigation paths are
    excluded. Relative URLs are resolved against ``base_url``.
    """
    base = urlparse(base_url)
    if base.scheme not in ("http", "https") or not base.netloc:
        logger.warning("invalid base url for link extraction", base_url=base_url)
        return []

    exclusions = tuple(p.lower() for p in (*DEFAULT_EXCLUDE_PATHS, *exclude_paths))
    seen: set[str] = set()
    result: list[str] = []

    for match in _HREF_RE.finditer(html):
        href = html_lib.unescape(match.group(1)).strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "data:", "#")):
            continue

        resolved = urljoin(base_url, href)
        parsed = urlparse(resolved)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc.lower() != base.netloc.lower():
            continue

        path = parsed.path
        if path in ("", "/"):
            continue
        if _ASSET_SUFFIX_RE.search(path):
            continue

        lowered = path.lower()
        if any(exclusion in lowered for exclusion in exclusions):
            continue

        clean = urlparse(resolved)._replace(fragment="").geturl()
        if clean in seen:
            continue
        seen.add(clean)
        result.append(clean)

        if len(result) >= max_urls:
            break

    return result
