"""Parse samehadaku list endpoints into series / batch discovery rows.

anime-terbaru + daftar-anime-2 share the same `.thumb > a[itemprop=url]` structure.
daftar-batch yields batch slugs only (no series). jadwal-rilis gives release_day.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from . import _http

_SLUG_RE = re.compile(r"/anime/([^/]+)/?$")


def parse_series_list(html: str) -> list[dict]:
    """List pages (anime-terbaru, daftar-anime-2) -> [{slug, title, cover_url}].

    Two layouts: anime-terbaru uses `.thumb a[itemprop=url]`; daftar-anime-2 uses
    `article.animpost a[href*=/anime/]` with cover `img.anmsa`. We match any
    anchor whose href is /anime/{slug}/ and resolve cover from the nearest img
    inside, so both (and any future variant) parse uniformly. Dedup by slug.
    """
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    seen: set[str] = set()
    for a in soup.select("a[href*='/anime/']"):
        href = a.get("href", "")
        m = _SLUG_RE.search(urlparse(href).path)
        if not m:
            continue
        slug = m.group(1)
        if slug in seen:
            continue
        # skip the /anime/ index itself and "category/anime" style
        seen.add(slug)
        img = (a.select_one("img.npws, img.anmsa, img.wp-post-image")
               or a.find("img"))
        title = (a.get("title") or a.get("alt")
                 or (img.get("alt") if img else None)
                 or a.get_text(strip=True)).strip()
        cover = img.get("src") if img else None
        out.append({"slug": slug, "title": title or slug, "cover_url": cover})
    return out


def walk_directory(cx) -> list[dict]:
    """Walk daftar-anime-2 pagination front-to-back, return ALL series.

    samehadaku's pagination is incremental (page N links up to N+2), so we walk
    page 1, 2, ... until a page returns no series. ~728 series / 25 pages.
    Sync (used by discover + backfill seeding). Caller owns cx lifecycle.
    """
    all_series: list[dict] = []
    seen: set[str] = set()
    page = 0
    while True:
        page += 1
        url = (f"{_http.BASE_URL}/daftar-anime-2/"
               if page == 1
               else f"{_http.BASE_URL}/daftar-anime-2/page/{page}/")
        try:
            html = cx.get(url).text
        except Exception:
            break  # network blip: stop where we are (resumable — re-run adds more)
        items = parse_series_list(html)
        if not items:
            break  # past the last page
        fresh = [it for it in items if it["slug"] not in seen]
        if not fresh:
            break  # page returned only dupes = end of list
        seen.update(it["slug"] for it in fresh)
        all_series.extend(fresh)
    return all_series


def parse_batch_list(html: str) -> list[str]:
    """daftar-batch page -> [batch_slug, ...]. Bare slugs for later detail fetch."""
    soup = BeautifulSoup(html, "lxml")
    slugs: list[str] = []
    seen: set[str] = set()
    for a in soup.select("a[href*='/batch/']"):
        path = urlparse(a.get("href", "")).path
        m = re.search(r"/batch/([^/]+)/?$", path)
        if not m:
            continue
        s = m.group(1)
        if s not in seen:
            seen.add(s)
            slugs.append(s)
    return slugs


def parse_schedule(html: str) -> dict[str, list[str]]:
    """jadwal-rilis -> {day: [series_slug, ...]}.

    Samehadaku groups by weekday headings. Metadata only — no downloads here.
    ponytail: structure is day-heading + .thumb anchors; if markup shifts, fall
    back to nearest preceding heading per anchor.
    """
    soup = BeautifulSoup(html, "lxml")
    schedule: dict[str, list[str]] = {}
    # Walk the schedule widget; each day is a heading, series anchors follow.
    for a in soup.select(".thumb a[itemprop='url'], a[href*='/anime/']"):
        path = urlparse(a.get("href", "")).path
        m = _SLUG_RE.search(path)
        if not m:
            continue
        # Find nearest preceding heading text as the day label.
        day = None
        for h in a.find_all_previous(["h2", "h3", "h4"]):
            txt = h.get_text(strip=True)
            if txt:
                day = txt
                break
        day = day or "Unknown"
        schedule.setdefault(day, [])
        slug = m.group(1)
        if slug not in schedule[day]:
            schedule[day].append(slug)
    return schedule
