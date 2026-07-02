"""Parse anichin list endpoints into series discovery rows.

anichin series anchors are ROOT-slug (`/<slug>/`) with a `title` attr — NOT
`/anime/<slug>/` (those are the sidebar .subSchh, which appears on every page).
walk_directory paginates /az-lists/?show=<LETTER> front-to-back for the full
series set (backfill + discover seed). parse_update_list reads the latest-updated
list body (used by the 2h delta job).
"""
from __future__ import annotations

import re
import urllib.parse

from bs4 import BeautifulSoup

from . import _http

# Root-slug anchor: href exactly "/<slug>/" with non-empty title attr.
# Excludes /anime/, /az-lists/, /genres/, episode URLs, bare "/".
_SLUG_RE = re.compile(r"^/([a-z0-9][a-z0-9-]+)/?$")

# Paths that look like slugs but are site sections, not series.
_SECTIONS = {"anime", "az-lists", "genres", "page"}

# /az-lists/?show= walks 0-9 then A..Z.
_SHOWS = ["0-9"] + [chr(c) for c in range(ord("A"), ord("Z") + 1)]


def _strip_sidebar(soup: BeautifulSoup) -> None:
    """Remove .subSchh (latest-series sidebar) so it doesn't pollute parsing."""
    for sb in soup.select(_http.SEL_SIDEBAR):
        sb.decompose()


def _series_anchors(soup: BeautifulSoup) -> list[dict]:
    """Root-slug anchors with title attrs -> [{slug, title}]. Dedup."""
    out: list[dict] = []
    seen: set[str] = set()
    for a in soup.find_all("a", title=True):
        href = a.get("href", "")
        m = _SLUG_RE.match(urllib.parse.urlparse(href).path)
        if not m:
            continue
        slug = m.group(1)
        if slug in seen or slug in _SECTIONS:
            continue
        title = a.get("title", "").strip()
        seen.add(slug)
        out.append({"slug": slug, "title": title})
    return out


def parse_update_list(html: str) -> list[dict]:
    """/anime/?order=update body -> [{slug, title}]. Strips sidebar first."""
    soup = BeautifulSoup(html, "lxml")
    _strip_sidebar(soup)
    return _series_anchors(soup)


def walk_directory(cx) -> list[dict]:
    """Walk /az-lists/ A-Z, following the .next pagination link per letter.

    anichin serves stale content on out-of-range page numbers (page 50 of a
    4-page letter still returns items), so blind page++ never terminates —
    we follow the Next » link instead and stop when it disappears. cx is an
    httpx.Client-like with .get(url).text; caller owns lifecycle.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for show in _SHOWS:
        url = f"{_http.BASE_URL}/az-lists/page/1/?show={show}"
        while url:
            soup = BeautifulSoup(cx.get(url).text, "lxml")
            _strip_sidebar(soup)
            for it in _series_anchors(soup):
                if it["slug"] not in seen:
                    seen.add(it["slug"])
                    out.append(it)
            # Next page link (.next a.page-numbers); absent on the last page.
            nxt = soup.select_one("a.next.page-numbers, .pagination a.next")
            href = nxt.get("href") if nxt else None
            url = f"{_http.BASE_URL}{href}" if href and href.startswith("/") else href
    return out
