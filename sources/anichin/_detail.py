"""Parse an anichin series detail page (/anime/{slug}).

Metadata lives in .infox as <span><b>Label:</b> Value</span> pairs (verified live
2026-06-30). Labels are Indonesian: Tipe (type), Status, Studio, Season, Tanggal
rilis (released), Durasi, Negara (country). Genres are <a href*="/genres/"> links
in .infox. anichin has NO Score field. The synopsis is the longest <p> in
.entry-content. Episode links live at /{slug}-episode-{N}-subtitle-indonesia/.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from . import _http

_EP_NUM_RE = re.compile(r"-episode-(\d+)-subtitle")

# .infox <b>Label:</b> -> payload key. Case-insensitive, trailing colon stripped.
# Only the subset that matters for canonical merge/enrich; admin/noise dropped.
_FIELD_LABELS = {
    "tipe": "type",
    "status": "status",
    "studio": "studio",
    "season": "season",
    "tanggal rilis": "released",
    "durasi": "duration",
    "negara": "country",
}

def _value_after_b(b) -> str | None:
    """Text value of a <b>Label:</b> within its parent element.

    anichin wraps each field as <span><b>Status:</b> Ongoing</span> — the value
    is the tail text after <b>, not a following <span> sibling. Take the
    parent's full text and strip the label prefix.
    """
    parent = b.parent
    if parent is None:
        return None
    full = parent.get_text(" ", strip=True)
    label = b.get_text(" ", strip=True)
    # drop the leading "Label:" then trim.
    if full.startswith(label):
        full = full[len(label):]
    val = full.lstrip(":").strip()
    return val or None

def parse_detail(html: str, base: str = _http.BASE_URL) -> dict:
    """Series detail -> metadata + episode links (no stream_url yet).

    Returns {slug, title, cover_url, synopsis, infox:{...}, episodes:[{n,url}]}.
    Unknown infox labels tolerated (robust to markup drift).
    """
    soup = BeautifulSoup(html, "lxml")
    infox: dict = {"genres": []}

    # Metadata: .infox <span><b>Label:</b> Value</span>. Walk .infox <b> tags.
    box = soup.select_one(".infox")
    if box:
        for b in box.find_all("b"):
            label = b.get_text(strip=True).lower().rstrip(":").strip()
            key = _FIELD_LABELS.get(label)
            if key:
                infox[key] = _value_after_b(b)

        # Genres: <a> tags inside .infox that link to /genres/ (the trailing
        # unlabeled block). Collect their text, dedup, preserve order.
        ga = [g.get_text(strip=True) for g in box.select("a[href*='/genres/']")
              if g.get_text(strip=True)]
        if ga:
            infox["genres"] = list(dict.fromkeys(ga))

    # Title: first <h1> (entry-title or bare h1).
    h1 = soup.select_one("h1.entry-title, h1")
    title = h1.get_text(" ", strip=True) if h1 else None

    # Cover: .wp-post-image or itemprop=image img.
    img = soup.select_one("img.wp-post-image, [itemprop='image'] img, .thumb img")
    cover_url = img.get("src") if img else None

    # Synopsis: longest <p> in the description container.
    syn = soup.select_one(".entry-content, [itemprop='description']")
    synopsis = None
    if syn:
        paras = [p.get_text(" ", strip=True) for p in syn.select("p") if p.get_text(strip=True)]
        synopsis = max(paras, key=len) if paras else syn.get_text(" ", strip=True)

    # Slug: derive from canonical <link> path (anichin canonical is root-relative
    # /{slug}/, not /anime/{slug}/). Last path segment, minus trailing slash.
    slug = None
    canon = soup.select_one("link[rel='canonical']")
    if canon and canon.get("href"):
        path = urlparse(canon.get("href")).path.strip("/")
        if path:
            slug = path.split("/")[-1]

    # Episode links: /{slug}-episode-{N}-subtitle-indonesia/. Scope to THIS
    # series (slug prefix) so related/other-series episodes in .lastend etc.
    # don't leak in with colliding N. Dedup by N (an episode may have several
    # anchors incl. #comment fragments); sort ascending by N.
    seen_n: set[int] = set()
    episodes: list[dict] = []
    ep_prefix = f"/{slug}-episode-" if slug else "-episode-"
    for a in soup.select(f"a[href*='{ep_prefix}']"):
        href = a.get("href", "").strip()
        if not href or "/sharer" in href or "/share" in href:
            continue
        m = _EP_NUM_RE.search(urlparse(href).path)
        if not m:
            continue
        n = int(m.group(1))
        if n in seen_n:
            continue
        seen_n.add(n)
        # strip any fragment (#comment-...) — anchors may repeat with fragments.
        clean = href.split("#", 1)[0]
        if not clean.startswith("http"):
            clean = f"{base.rstrip('/')}/{clean.lstrip('/')}"
        episodes.append({"n": n, "url": clean})
    episodes.sort(key=lambda e: e["n"])

    return {
        "slug": slug,
        "title": title,
        "cover_url": cover_url,
        "synopsis": synopsis,
        "infox": infox,
        "episodes": episodes,
    }
