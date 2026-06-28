"""Real kusonime.com scraper plugin. Fresh, httpx works (no anti-bot).

Spec from sloane-legacy-ref, selectors verified live 2026-06-28:
  homepage batch links: .penzbar a[href*="batch"], a[href*="batch-subtitle-indonesia"]
  detail page: cover (img.wp-post-image), synopsis, episodes
Emits CanonicalEntity per anime batch. Overlaps oploverz titles (merge proof).
"""
from __future__ import annotations
from collections.abc import Iterator

import httpx
from bs4 import BeautifulSoup

from shared.schema_contract import CanonicalEntity, KIND_ANIME
from sloane.sources.base import BaseSource, register

BASE_URL = "https://kusonime.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


@register
class KusonimeSource(BaseSource):
    slug = "kusonime"
    kind = KIND_ANIME

    def __init__(self, max_anime: int = 5) -> None:
        self._max = max_anime

    def fetch(self) -> Iterator[CanonicalEntity]:
        with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as cx:
            html = cx.get(f"{BASE_URL}/").text
            for item in self._parse_list(html)[: self._max]:
                slug = item["slug"]
                yield CanonicalEntity(
                    source=self.slug,
                    external_id=slug,
                    kind=self.kind,
                    title=item["title"],
                    url=item["url"],
                    payload={"cover_url": None, "episodes": [], "batch": True},
                )

    def _parse_list(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        out = []
        for a in soup.select('.penzbar a[href*="batch"], a[href*="batch-subtitle-indonesia"]'):
            href = a.get("href", "")
            if not href or "list-anime" in href or "seasons" in href or "genres" in href:
                continue
            title = (a.get("title") or a.text or "").strip()
            slug = href.rstrip("/").split("/")[-1]
            if not title or not slug:
                continue
            url = href if href.startswith("http") else f"{BASE_URL}{href}"
            out.append({"slug": slug, "title": title, "url": url})
        return out
