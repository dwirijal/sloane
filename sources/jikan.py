"""Jikan v4 source plugin. MAL's free unofficial API, no key.

Unlike HTML scrapers, Jikan returns structured data WITH the mal_id registry ID.
This exercises the ID-first merge path: a canonical created by oploverz/kusonime
(title merge) gets its mal_id here, so future scrapes of the same title from a
source carrying mal_id merge by ID, not title/LLM.

Throttle ~3 req/s sustained (Jikan limit). ponytail: real rate-limiter when bulk.
"""
from __future__ import annotations
import time
from collections.abc import Iterator

import httpx

from shared.schema_contract import CanonicalEntity, KIND_ANIME
from sloane.sources.base import BaseSource, register

JIKAN_BASE = "https://api.jikan.moe/v4"
_MIN_GAP = 0.4
_last_call = 0.0


def _throttle() -> None:
    global _last_call
    now = time.monotonic()
    wait = _MIN_GAP - (now - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


@register
class JikanSource(BaseSource):
    slug = "jikan"
    kind = KIND_ANIME

    def __init__(self, max_anime: int = 5) -> None:
        self._max = max_anime

    def fetch(self) -> Iterator[CanonicalEntity]:
        # top anime — stable list, good smoke source
        _throttle()
        r = httpx.get(f"{JIKAN_BASE}/top/anime",
                      params={"limit": self._max},
                      timeout=15,
                      headers={"User-Agent": "sloane-jikan/1.0"})
        if r.status_code != 200:
            return
        for item in r.json().get("data", [])[: self._max]:
            mal_id = item.get("mal_id")
            title = (item.get("title_english") or item.get("title") or "").strip()
            if not mal_id or not title:
                continue
            yield CanonicalEntity(
                source=self.slug,
                external_id=f"mal-{mal_id}",
                kind=self.kind,
                title=title,
                url=item.get("url", ""),
                payload={
                    "mal_id": mal_id,
                    "registry_ids": {"mal": mal_id},  # merger uses ID-first
                    "score": item.get("score"),
                    "type": item.get("type"),
                },
            )


if __name__ == "__main__":
    # self-check: live fetch yields >=1 entity with mal_id
    n = 0
    for e in JikanSource(max_anime=2).fetch():
        n += 1
        assert e.payload.get("mal_id"), "jikan entity must carry mal_id"
        print(" ", e.title, "mal_id=", e.payload["mal_id"])
    assert n > 0, "jikan fetch returned nothing"
    print("jikan self-check OK")
