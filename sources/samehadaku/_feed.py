"""Parse samehadaku's WordPress RSS feed (/feed/) into recent posts.

/feed/ is the site's own change-notification primitive: a newest-first list of
recent posts (episode + batch pages ARE posts), each with a pubDate. Polling it
is how the ingest runner learns what changed since last run.

kind is inferred from the post URL slug: '-episode-' -> episode, '/batch/' ->
batch, else post. No anti-bot; same _http client as the rest of samehadaku.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from . import _http


def parse_feed(html: str) -> list[dict]:
    """RSS XML -> [{url, pubdate, kind}]. Empty list on malformed feed."""
    soup = BeautifulSoup(html, "xml")
    out: list[dict] = []
    for item in soup.find_all("item"):
        link = item.find("link")
        pub = item.find("pubDate")
        url = (link.get_text(strip=True) if link else "") or ""
        if not url:
            continue
        if "-episode-" in url:
            kind = "episode"
        elif "/batch/" in url:
            kind = "batch"
        else:
            kind = "post"
        out.append({
            "url": url,
            "pubdate": pub.get_text(strip=True) if pub else "",
            "kind": kind,
        })
    return out


def fetch_feed(cx) -> str:
    """Fetch /feed/ HTML via an existing httpx.Client (caller owns lifecycle)."""
    return cx.get(f"{_http.BASE_URL}/feed/").text


if __name__ == "__main__":
    # Live self-check (project convention — see store/merger.py:204).
    import httpx
    r = httpx.get(f"{_http.BASE_URL}/feed/", headers=_http.HEADERS,
                  timeout=20, follow_redirects=True)
    assert r.status_code == 200, f"feed fetch failed: {r.status_code}"
    items = parse_feed(r.text)
    assert items, "live feed returned no items"
    assert items[0]["kind"] in {"episode", "batch", "post"}
    print(f"samehadaku _feed self-check OK ({len(items)} items, "
          f"first={items[0]['kind']} {items[0]['url'][:50]})")
