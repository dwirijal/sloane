"""Real v2.samehadaku.how scraper source. No anti-bot (httpx works directly).

Discovery: /anime-terbaru/ (fresh) — full dir via /daftar-anime-2/ later.
Per series: /anime/{slug} detail -> .infox + synopsis + episode links + batch
links. Per episode + per batch: fetch detail, parse div.download-eps.

Emits ONE CanonicalEntity per anime SERIES (kind=anime); episodes + batches
go into payload. Matches oploverz/kusonime shape so the merger links same
titles (e.g. "One Piece" -> normalized "onepiece") without changes.

ponytail: one-at-a-time HTTP fetch. Add asyncio.gather for full-ingest
(all series x all episodes); smoke cap (max_anime + episode cap) is the
ceiling marked below.
"""
from __future__ import annotations

from collections.abc import Iterator

from shared.schema_contract import CanonicalEntity, KIND_ANIME
from sloane.sources.base import BaseSource, register

from . import _detail, _downloads, _http, _lists


@register
class SamehadakuSource(BaseSource):
    slug = "samehadaku"
    kind = KIND_ANIME

    # Smoke caps. Lift for 24/7 full-ingest (see ponytail above).
    _MAX_EPISODES_PER_SERIES = 3  # fetch first N + always latest (episode[0])
    _MAX_BATCHES_PER_SERIES = 2

    def __init__(self, max_anime: int = 5) -> None:
        self._max = max_anime

    def fetch(self) -> Iterator[CanonicalEntity]:
        with _http.client() as cx:
            # 1. discover series from the fresh list.
            html = cx.get(f"{_http.BASE_URL}/anime-terbaru/").text
            series = _lists.parse_series_list(html)[: self._max]
            for item in series:
                slug = item["slug"]
                # 2. series detail (metadata + episode/batch links).
                detail_url = f"{_http.BASE_URL}/anime/{slug}/"
                try:
                    dhtml = cx.get(detail_url).text
                except Exception:
                    continue  # skip unreachable series; don't abort the batch
                data = _detail.parse_series(dhtml, base=_http.BASE_URL)

                # 3. episode download links (capped).
                eps: list[dict] = []
                # slice first N + latest; series episodes are desc by number.
                pick = data["episodes"][: self._MAX_EPISODES_PER_SERIES]
                for ep in pick:
                    try:
                        ep_html = cx.get(ep["url"]).text
                    except Exception:
                        continue
                    eps.append({
                        "episode_number": ep["episode_number"],
                        "url": ep["url"],
                        "downloads": _downloads.parse_downloads(ep_html),
                    })

                # 4. batch download links (capped).
                batches: list[dict] = []
                for bhref in data["batch_links"][: self._MAX_BATCHES_PER_SERIES]:
                    try:
                        b_html = cx.get(bhref).text
                    except Exception:
                        continue
                    bslug = _downloads.slug_and_ep(bhref)[0]
                    batches.append({
                        "slug": bslug,
                        "url": bhref,
                        "downloads": _downloads.parse_downloads(b_html),
                    })

                yield CanonicalEntity(
                    source=self.slug,
                    external_id=slug,
                    kind=self.kind,
                    title=item["title"],
                    url=detail_url,
                    payload={
                        "cover_url": item["cover_url"],
                        "synopsis": data["synopsis"],
                        "genres": data["genres"],
                        "japanese": data["japanese"],
                        "english": data["english"],
                        "alt_title": data["alt_title"],
                        "status": data["status"],
                        "type": data["type"],
                        "studio": data["studio"],
                        "season": data["season"],
                        "released": data["released"],
                        "total_episode": data["total_episode"],
                        "duration": data["duration"],
                        "rating": data["rating"],
                        "source": data["source"],
                        "producers": data["producers"],
                        "episodes": eps,
                        "batches": batches,
                    },
                )
