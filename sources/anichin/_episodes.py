"""Parse an anichin episode page (/{slug}-episode-{N}-subtitle-indonesia/).

anichin episodes are streaming-only: the page embeds a single player iframe in
a .player-embed container. Hosts vary per-series (Dailymotion, ok.ru, ...) —
the fixture (Martial Master 670) is Dailymotion but e.g. aliens-among-immortals
uses ok.ru, so we capture the first .player-embed iframe src regardless of host.
There are NO download-host links (the word "Download" appears only in JSON-LD
meta description).
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

_EP_NUM_RE = re.compile(r"episode[- ](\d+)[- ]subtitle", re.IGNORECASE)


def parse_episode(html: str) -> dict:
    """Episode page -> {n, stream_url}.

    n: int from the -episode-{N}-subtitle pattern (h1 or <title>), else None.
    stream_url: first .player-embed iframe[src], else None (page may be
    JS-gated on some episodes — don't fail ingest for a missing iframe).
    Host-agnostic: anichin uses Dailymotion, ok.ru, and others per-series.
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

    # Stream src: the single .player-embed iframe. Host-agnostic — anichin
    # uses Dailymotion, ok.ru, and others per-series.
    iframe = soup.select_one(".player-embed iframe[src]")
    stream_url = iframe.get("src") if iframe else None

    return {"n": n, "stream_url": stream_url}
