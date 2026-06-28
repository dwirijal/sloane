"""Real oploverz.fans scraper plugin. Fresh, no anti-bot (httpx works directly).

Spec ported from sloane-legacy-ref (selectors verified live 2026-06-28):
  list endpoint: /anime/list-mode/
  list selector: a.series -> href + title
  detail page:   synopsis / genres / status / year / episode links
No CDP needed (no CF challenge on this domain currently).

Emits CanonicalEntity per anime. Episodes go into payload. Detail fetch is
per-anime HTTP — ponytail: add concurrency (asyncio.gather) when 425 fetches
become slow; one-at-a-time is fine for smoke scope.
"""
from __future__ import annotations
import re
from collections.abc import Iterator

import httpx
from bs4 import BeautifulSoup

from shared.schema_contract import CanonicalEntity, KIND_ANIME
from sloane.sources.base import BaseSource, register

BASE_URL = "https://oploverz.fans"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
_EP_NUM = re.compile(r"(\d+(?:\.\d+)?)")


@register
class OploverzSource(BaseSource):
    slug = "oploverz"
    kind = KIND_ANIME

    def __init__(self, max_anime: int = 5) -> None:
        # ponytail: cap detail fetches; 425 full list is heavy for smoke.
        # Add a batch param when wiring 24/7 full ingest.
        self._max = max_anime

    def fetch(self) -> Iterator[CanonicalEntity]:
        with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as cx:
            html = cx.get(f"{BASE_URL}/anime/list-mode/").text
            for anime in self._parse_list(html)[: self._max]:
                detail_url = anime["url"]
                try:
                    detail_html = cx.get(detail_url).text
                    anime.update(self._parse_detail(detail_html))
                except Exception:
                    pass  # list-only entity still valid; detail enrich optional
                yield CanonicalEntity(
                    source=self.slug,
                    external_id=anime["slug"],
                    kind=self.kind,
                    title=anime["title"],
                    url=anime["url"],
                    payload={
                        "cover_url": anime.get("cover_url"),
                        "synopsis": anime.get("synopsis"),
                        "genres": anime.get("genres"),
                        "status": anime.get("status"),
                        "year": anime.get("year"),
                        "episodes": anime.get("episodes", []),
                    },
                )

    def _parse_list(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        out = []
        for a in soup.select("a.series"):
            href = a.get("href", "")
            if "/anime/" not in href:
                continue
            title = (a.get("title") or a.text or "").strip()
            slug = href.rstrip("/").split("/")[-1]
            if not title or not slug:
                continue
            url = href if href.startswith("http") else f"{BASE_URL}{href}"
            out.append({"slug": slug, "title": title, "url": url})
        return out

    def _parse_detail(self, html: str) -> dict:
        soup = BeautifulSoup(html, "lxml")
        data: dict = {"synopsis": None, "genres": None, "status": None,
                      "year": None, "episodes": []}
        desc = soup.select_one(
            ".sinopc, .desc, .description, .entry-content, [itemprop='description']"
        )
        if desc:
            data["synopsis"] = desc.text.strip()
        genres = [g.text.strip() for g in soup.select(
            ".genre a, .tag a, [itemprop='genre'] a, .genres a, span.genre a"
        ) if g.text.strip()]
        if genres:
            data["genres"] = list(dict.fromkeys(genres))  # dedup, preserve order
        # episodes
        seen = set()
        for link in soup.select("a[href*='episode']"):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            num_match = _EP_NUM.search(link.text)
            if num_match:
                data["episodes"].append({
                    "episode_number": float(num_match.group(1)),
                    "stream_url": href if href.startswith("http") else f"{BASE_URL}{href}",
                })
        data["episodes"].sort(key=lambda x: x["episode_number"] or 0, reverse=True)
        return data
