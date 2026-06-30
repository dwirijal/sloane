"""Parse an anime series detail page (/anime/{slug}).

Metadata lives in .spe spans: <span><b>Label</b> value</span> (Japanese,
Synonyms, Status, Type, Studio, ...). Genres are <a itemprop='genre'>. The
synopsis is the longest <p> in .entry-content. Episode links live at
/{slug-episode-N}/; batch links at /batch/{slug}. Download links themselves
are on the episode/batch pages (parsed by _downloads).
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from . import _http

_EP_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")

# Labels samehadaku uses inside .spe spans as <b>Label</b> value.
# Map label text -> payload key. Order-insensitive; case-insensitive.
_FIELD_LABELS = {
    "japanese": "japanese",
    "synonyms": "alt_title",
    "english": "english",
    "status": "status",
    "type": "type",
    "studio": "studio",
    "season": "season",
    "released": "released",
    "total episode": "total_episode",
    "total episodes": "total_episode",
    "duration": "duration",
    "rating": "rating",
    "score": "rating",
    "source": "source",
    "producers": "producers",
}


def parse_series(html: str, base: str = _http.BASE_URL) -> dict:
    """Series detail -> metadata + episode links + batch links (no downloads yet).

    Returns dict with keys: synopsis, genres, japanese, english, alt_title,
    status, type, studio, season, released, total_episode, duration, rating,
    episodes:[{episode_number,url}], batch_links:[url]. Unknown fields
    tolerated (robust to markup drift).
    """
    soup = BeautifulSoup(html, "lxml")
    data: dict = {
        "synopsis": None, "genres": [], "japanese": None, "english": None,
        "alt_title": None, "status": None, "type": None, "studio": None,
        "season": None, "released": None, "total_episode": None,
        "duration": None, "rating": None, "source": None,
        "producers": None, "episodes": [], "batch_links": [],
    }

    # Metadata: .spe > span, each <b>Label</b> value. .spe is unique per page;
    # don't depend on which .infox wraps it (two .infox exist, only one has .spe).
    for span in soup.select(".spe span"):
        b = span.find("b")
        if not b:
            continue
        label = b.get_text(strip=True).lower().rstrip(":").strip()
        # value = span text with the label node removed.
        val = span.get_text(" ", strip=True)[len(b.get_text(strip=True)):].strip(" :")
        key = _FIELD_LABELS.get(label)
        if key:
            data[key] = val or None

    # Genres: <a itemprop='genre'> inside .infox — most reliable.
    ga = [g.get_text(strip=True) for g in soup.select(".infox a[itemprop='genre'], .genre a") if g.get_text(strip=True)]
    if ga:
        data["genres"] = list(dict.fromkeys(ga))

    # Synopsis: longest <p> in the description container.
    syn = soup.select_one(_http.SEL_SYNOPSIS)
    if syn:
        paras = [p.get_text(" ", strip=True) for p in syn.select("p") if p.get_text(strip=True)]
        data["synopsis"] = max(paras, key=len) if paras else syn.get_text(" ", strip=True)

    # Episode links: /{slug-episode-N}/. Dedup by href; desc by episode number.
    seen: set[str] = set()
    for a in soup.select("a[href*='-episode-']"):
        href = a.get("href", "").strip()
        if not href or href in seen:
            continue
        seen.add(href)
        if not href.startswith("http"):
            href = f"{base.rstrip('/')}/{href.lstrip('/')}"
        nm = _EP_NUM_RE.search(a.get_text(" ", strip=True) + " " + urlparse(href).path)
        data["episodes"].append({
            "episode_number": float(nm.group(1)) if nm else None,
            "url": href,
        })
    data["episodes"].sort(key=lambda e: e["episode_number"] or 0, reverse=True)

    # Batch links on the series page.
    seen_b: set[str] = set()
    for a in soup.select("a[href*='/batch/']"):
        href = a.get("href", "").strip()
        if href and href not in seen_b:
            seen_b.add(href)
            if not href.startswith("http"):
                href = f"{base.rstrip('/')}/{href.lstrip('/')}"
            data["batch_links"].append(href)

    return data
