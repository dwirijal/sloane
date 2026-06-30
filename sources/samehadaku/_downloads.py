"""Parse download-link blocks from episode + batch detail pages.

Structure (verified 2026-06-29, episode 1168):
    div.download-eps
      <p><b>MKV</b></p>           # format group header
      <ul>
        <li><strong>360p</strong> # quality
          <span><a href=URL>Host</a></span>   # one host per <span>
          ...
        </li>
        <li><strong>720p</strong> ...</li>
      </ul>
      <p><b>MP4</b></p> ...        # next format group

Shared by episode ({slug-episode-N}) and batch ({/batch/slug}) pages.
No JS gating — links are static HTML.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from . import _http

# File-extension fallback when <p><b> format header is absent.
_EXT_RE = re.compile(r"\.(mkv|mp4|avi|webm|m4a)(?:[^/?\s]*)?($|[/?\s])", re.I)


def _format_for(block: Tag, li: Tag) -> str:
    """Resolve the format (MKV/MP4) for a quality <li>.

    Walk backwards from <li> to the nearest <p><b> header inside the block.
    If none, infer from any href filename extension in the <li>.
    """
    node = li
    while node is not None and node is not block:
        prev = node.find_previous_sibling(["p", "ul", "li"])
        if prev is None:
            node = node.parent
            if node is block or node is None:
                break
            continue
        if prev.name == "p":
            b = prev.find(["b", "strong"])
            txt = (b or prev).get_text(strip=True)
            if txt:
                return txt.upper()
        node = prev
    # Fallback: extension from any download href in this <li>.
    for a in li.select("a[href]"):
        m = _EXT_RE.search(a["href"])
        if m:
            return m.group(1).upper()
    return "UNKNOWN"


def parse_downloads(html: str) -> list[dict]:
    """Episode/batch page -> [{format, quality, hosts:[{host, url}]}].

    Multiple quality rows may share one format group; format is attached per
    row by scanning back to the nearest <p><b> header.
    """
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    for block in soup.select(_http.SEL_DOWNLOAD_BLOCK):
        for li in block.select("li"):
            strong = li.find("strong")
            quality = strong.get_text(strip=True) if strong else None
            if not quality:
                continue
            hosts = []
            for a in li.select("a[href]"):
                host = a.get_text(strip=True)
                url = a["href"].strip()
                if host and url and not url.startswith("#"):
                    hosts.append({"host": host, "url": url})
            if hosts:
                out.append({
                    "format": _format_for(block, li),
                    "quality": quality,
                    "hosts": hosts,
                })
    return out


def slug_and_ep(url: str) -> tuple[str, str | None]:
    """Episode URL -> (series_slug, episode_number_str_or_None).

    /one-piece-episode-1168/ -> ('one-piece', '1168')
    /one-piece-batch-part-2/ -> ('one-piece', None)  (batch, no ep num)
    """
    m = re.search(r"/([^/]+?)(?:-episode-(\d+(?:\.\d+)?))?(?:-batch[^/]*)?/?$", url.rstrip("/"))
    if not m:
        return url.rstrip("/").split("/")[-1], None
    return m.group(1), m.group(2)


if __name__ == "__main__":
    # Self-check (project convention — see store/merger.py:206). Hits the live
    # site; no DB. Asserts the load-bearing parser returns real download data.
    import httpx
    r = httpx.get("https://v2.samehadaku.how/one-piece-episode-1168/",
                  headers=_http.HEADERS, timeout=20, follow_redirects=True)
    assert r.status_code == 200, f"fetch failed: {r.status_code}"
    dl = parse_downloads(r.text)
    assert dl, "no downloads parsed from episode page"
    assert any(d["quality"] for d in dl), "no quality labels"
    assert any(d["hosts"] for d in dl), "no host links"
    assert any(d["format"] != "UNKNOWN" for d in dl), "format not resolved"
    slug, ep = slug_and_ep("https://v2.samehadaku.how/one-piece-episode-1168/")
    assert slug == "one-piece" and ep == "1168", f"slug/ep wrong: {slug}/{ep}"
    slug2, ep2 = slug_and_ep("https://v2.samehadaku.how/batch/one-piece-batch-part-2/")
    assert slug2 == "one-piece" and ep2 is None, f"batch slug/ep wrong: {slug2}/{ep2}"
    print(f"samehadaku _downloads self-check OK ({len(dl)} quality rows, "
          f"{sum(len(d['hosts']) for d in dl)} host links)")
