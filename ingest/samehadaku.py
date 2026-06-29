"""samehadaku incremental ingest runner.

2h job (ingest_feed): fetch /feed/, delta new post URLs vs ingest_state, fetch
only new post pages, parse downloads, and load-mutate-upsert the parent series
raw_entities row (write_entities replaces payload wholesale, so we SELECT the
existing payload, append the new episode/batch, UPSERT the full entity). Then
merge_raw + enrich. State in DB; runner otherwise stateless.

daily job (discover_new_series): anime-terbaru -> slugs absent from raw_entities
-> full series fetch -> write_entities -> merge -> enrich.

No concurrency, no per-post transactions. Idempotency (write_entities ON
CONFLICT + merge_raw ON CONFLICT) protects a mid-run crash: redundant work at
worst, never duplicate data.
"""
from __future__ import annotations

import psycopg

from shared.config import pg_dsn
from shared.schema_contract import CanonicalEntity, KIND_ANIME
from sloane.db.writer import write_entities
from sloane.store.merger import merge_raw_to_canonical
from sloane.store.enricher import enrich_canonical
from sloane.store.state import get_state, add_seen
from sloane.sources.samehadaku import _downloads, _feed, _http, _lists

SOURCE = "samehadaku"
SEEN_KEY = "seen_feed_urls"


def load_series_payload(dsn: str, slug: str) -> dict | None:
    """SELECT existing raw_entities.payload for this series slug. None if absent."""
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        row = cur.execute(
            "SELECT payload, title FROM raw_entities WHERE source=%s AND external_id=%s",
            (SOURCE, slug),
        ).fetchone()
    if not row:
        return None
    return {"title": row[1], **(row[0] or {})}


def patch_series(dsn: str, slug: str, title: str, url: str, payload: dict) -> int:
    """Build + UPSERT the series CanonicalEntity. Returns raw_id."""
    res = write_entities(dsn, [
        CanonicalEntity(
            source=SOURCE, external_id=slug, kind=KIND_ANIME,
            title=title, url=url, payload=payload,
        )
    ])
    return res.raw_ids[0]


def _patch_episode_into(payload: dict, post_url: str, downloads: list[dict]) -> None:
    """Append {episode_number,url,downloads} to payload['episodes'], dedup by url."""
    eps = payload.setdefault("episodes", [])
    _series_slug, ep_num = _downloads.slug_and_ep(post_url)
    eps[:] = [e for e in eps if e.get("url") != post_url]
    eps.append({
        "episode_number": float(ep_num) if ep_num else None,
        "url": post_url,
        "downloads": downloads,
    })
    eps.sort(key=lambda e: e.get("episode_number") or 0, reverse=True)


def _patch_batch_into(payload: dict, post_url: str, downloads: list[dict]) -> None:
    """Append {slug,url,downloads} to payload['batches'], dedup by url."""
    bts = payload.setdefault("batches", [])
    series_slug, _ = _downloads.slug_and_ep(post_url)
    bts[:] = [b for b in bts if b.get("url") != post_url]
    bts.append({"slug": series_slug, "url": post_url, "downloads": downloads})


def ingest_feed(dsn: str | None = None, max_new: int | None = None) -> dict:
    """2h job: feed-delta ingest of new episode/batch posts.

    Returns {fetched, ingested, skipped, new_urls}.
    """
    dsn = dsn or pg_dsn()
    seen = set(get_state(dsn, SOURCE, SEEN_KEY, default=[]) or [])
    ingested = skipped = 0
    new_urls: list[str] = []

    with _http.client() as cx:
        feed_html = _feed.fetch_feed(cx)
        items = _feed.parse_feed(feed_html)
        new = [it for it in items if it["url"] not in seen]
        if max_new is not None:
            new = new[:max_new]

        for post in new:
            post_url = post["url"]
            try:
                page_html = cx.get(post_url).text
                downloads = _downloads.parse_downloads(page_html)
            except Exception:
                # post 404'd or fetch failed: mark seen so we don't retry forever.
                skipped += 1
                new_urls.append(post_url)
                continue

            series_slug, _ = _downloads.slug_and_ep(post_url)
            series_url = f"{_http.BASE_URL}/anime/{series_slug}/"
            existing = load_series_payload(dsn, series_slug)
            if existing is None:
                # series not yet in DB; discover job will add it. mark seen, skip.
                skipped += 1
                new_urls.append(post_url)
                continue
            title = existing.get("title") or series_slug
            payload = {k: v for k, v in existing.items() if k != "title"}
            if post["kind"] == "batch":
                _patch_batch_into(payload, post_url, downloads)
            else:
                _patch_episode_into(payload, post_url, downloads)

            raw_id = patch_series(dsn, series_slug, title, series_url, payload)
            merge_raw_to_canonical(raw_id, title, KIND_ANIME, payload, dsn=dsn)
            # No enrich here: feed job only patches episodes/batches into an
            # existing series whose canonical + mal_id are already resolved (the
            # discover job enriches when it first creates the series). MAL id
            # does not change because an episode was added.
            ingested += 1
            new_urls.append(post_url)

    if new_urls:
        add_seen(dsn, SOURCE, SEEN_KEY, new_urls)

    return {"fetched": len(items), "ingested": ingested, "skipped": skipped,
            "new_urls": new_urls}


def discover_new_series(dsn: str | None = None, max_new: int | None = None) -> dict:
    """daily job: anime-terbaru -> slugs absent from raw_entities -> full fetch.

    Returns {discovered, ingested}.
    """
    dsn = dsn or pg_dsn()
    discovered = ingested = 0
    with _http.client() as cx:
        html = cx.get(f"{_http.BASE_URL}/anime-terbaru/").text
        series = _lists.parse_series_list(html)
        if max_new is not None:
            series = series[:max_new]
        for item in series:
            slug = item["slug"]
            if load_series_payload(dsn, slug) is not None:
                continue  # already in DB
            discovered += 1
            try:
                detail = cx.get(f"{_http.BASE_URL}/anime/{slug}/").text
                from sloane.sources.samehadaku._detail import parse_series
                data = parse_series(detail, base=_http.BASE_URL)
                payload = {
                    "cover_url": item["cover_url"], "synopsis": data["synopsis"],
                    "genres": data["genres"], "japanese": data["japanese"],
                    "english": data["english"], "alt_title": data["alt_title"],
                    "status": data["status"], "type": data["type"],
                    "studio": data["studio"], "season": data["season"],
                    "released": data["released"], "total_episode": data["total_episode"],
                    "duration": data["duration"], "rating": data["rating"],
                    "source": data["source"], "producers": data["producers"],
                    "episodes": [], "batches": [],
                }
                raw_id = patch_series(dsn, slug, item["title"],
                                      f"{_http.BASE_URL}/anime/{slug}/", payload)
                mr = merge_raw_to_canonical(raw_id, item["title"], KIND_ANIME,
                                            payload, dsn=dsn)
                enrich_canonical(mr["canonical_id"], item["title"], KIND_ANIME, dsn=dsn)
                ingested += 1
            except Exception:
                continue
    return {"discovered": discovered, "ingested": ingested}
