"""Parse an anichin episode page (/{slug}-episode-{N}-subtitle-indonesia/).

anichin episodes are streaming-only: the page embeds a Dailymotion iframe. There
are NO download-host links on the page (the word "Download" appears only in the
JSON-LD meta description). We extract the episode number + the iframe stream src.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

_EP_NUM_RE = re.compile(r"episode[- ](\d+)[- ]subtitle", re.IGNORECASE)


def parse_episode(html: str) -> dict:
    """Episode page -> {n, stream_url}.

    n: int from the -episode-{N}-subtitle pattern (h1 or <title>), else None.
    stream_url: first iframe[src*="dailymotion"] src, else None (page may be
    JS-gated on some episodes — don't fail ingest for a missing iframe).
    """
    soup = BeautifulSoup(html, "lxml")

    # Episode number: prefer h1, fall back to <title>.
    n = None
    h1 = soup.select_one("h1.entry-title, h1")
    title_el = soup.select_one("title")
    for el in (h1, title_el):
        if el:
            m = _EP_NUM_RE.search(el.get_text(" ", strip=True))
            if m:
                n = int(m.group(1))
                break

    # Stream src: first Dailymotion iframe.
    iframe = soup.select_one("iframe[src*='dailymotion']")
    stream_url = iframe.get("src") if iframe else None

    return {"n": n, "stream_url": stream_url}
