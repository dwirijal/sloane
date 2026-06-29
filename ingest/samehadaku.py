"""samehadaku incremental ingest runner.

2h job (ingest_feed): fetch /feed/, delta new post URLs vs ingest_state, fetch
only new post pages, parse downloads, and load-mutate-upsert the parent series
raw_entities row (write_entities replaces payload wholesale, so we SELECT the
existing payload, append the new episode/batch, UPSERT the full entity). Then
merge_raw + enrich. State in DB; runner otherwise stateless.

daily job (discover_new_series): anime-terbaru -> slugs absent from raw_entities
-> full series fetch -> write_entities -> merge -> enrich.

backfill (backfill_all): full historical ingest of every series from
daftar-anime-2 (~728), each with ALL episodes + batches parsed for download
links. Concurrent (httpx.AsyncClient + N workers, rate-capped) because the
scale (~36k episode pages for the long runners) makes sequential impractical.
Resumable: skips series already in raw_entities, so a crash + re-run continues.

Idempotency (write_entities ON CONFLICT + merge_raw ON CONFLICT) protects a
mid-run crash: redundant work at worst, never duplicate data.
"""
from __future__ import annotations

import asyncio

import httpx
import psycopg

from shared.config import pg_dsn
from shared.schema_contract import CanonicalEntity, KIND_ANIME
from sloane.db.writer import write_entities
from sloane.store.merger import merge_raw_to_canonical
from sloane.store.enricher import enrich_canonical
from sloane.store.state import get_state, add_seen
from sloane.sources.samehadaku import _detail, _downloads, _feed, _http, _lists

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


# ---------------------------------------------------------------------------
# Backfill: full historical ingest (all series + episodes + batches).
# ---------------------------------------------------------------------------

# Episode page fetches are the cost driver (One Piece alone = 1166). Cap
# concurrency to respect the site (no anti-bot today, but 36k reqs needs a
# leash). ponytail: raise to 12-16 once a run confirms no rate-limit 429s.
BACKFILL_WORKERS = 6


async def _fetch_one(cx: httpx.AsyncClient, url: str, sem: asyncio.Semaphore) -> str | None:
    """Fetch one page under the concurrency semaphore. None on failure."""
    async with sem:
        try:
            r = await cx.get(url, timeout=20)
            r.raise_for_status()
            return r.text
        except Exception:
            return None


async def _fetch_series_full(cx, sem, slug: str, title: str, cover_url) -> dict | None:
    """Fetch a series detail + ALL its episode + batch pages concurrently.

    Returns the full payload dict (episodes+downloads, batches+downloads) for
    one series, or None if the detail page itself failed.
    """
    series_url = f"{_http.BASE_URL}/anime/{slug}/"
    detail_html = await _fetch_one(cx, series_url, sem)
    if not detail_html:
        return None
    data = _detail.parse_series(detail_html, base=_http.BASE_URL)

    # Fetch every episode page + every batch page concurrently.
    ep_urls = [e["url"] for e in data["episodes"]]
    ep_htmls = await asyncio.gather(*[_fetch_one(cx, u, sem) for u in ep_urls])
    episodes = []
    for ep, html in zip(data["episodes"], ep_htmls):
        if not html:
            continue  # dead episode page — keep its number/url, skip downloads
        episodes.append({
            "episode_number": ep["episode_number"],
            "url": ep["url"],
            "downloads": _downloads.parse_downloads(html),
        })

    bt_htmls = await asyncio.gather(*[_fetch_one(cx, u, sem) for u in data["batch_links"]])
    batches = []
    for bhref, html in zip(data["batch_links"], bt_htmls):
        if not html:
            continue
        bslug, _ = _downloads.slug_and_ep(bhref)
        batches.append({"slug": bslug, "url": bhref,
                        "downloads": _downloads.parse_downloads(html)})

    return {
        "cover_url": cover_url, "synopsis": data["synopsis"],
        "genres": data["genres"], "japanese": data["japanese"],
        "english": data["english"], "alt_title": data["alt_title"],
        "status": data["status"], "type": data["type"], "studio": data["studio"],
        "season": data["season"], "released": data["released"],
        "total_episode": data["total_episode"], "duration": data["duration"],
        "rating": data["rating"], "source": data["source"],
        "producers": data["producers"], "episodes": episodes, "batches": batches,
    }


async def _backfill_async(dsn, series, workers, log) -> dict:
    sem = asyncio.Semaphore(workers)
    ingested = failed = 0
    async with httpx.AsyncClient(headers=_http.HEADERS, follow_redirects=True) as cx:
        # Process series in small batches so DB writes (sync) interleave with
        # fetches (async) — bounded memory, steady progress.
        BATCH = 10
        for i in range(0, len(series), BATCH):
            chunk = series[i:i + BATCH]
            results = await asyncio.gather(
                *[_fetch_series_full(cx, sem, s["slug"], s["title"], s.get("cover_url"))
                  for s in chunk]
            )
            for s, payload in zip(chunk, results):
                slug = s["slug"]
                if payload is None:
                    failed += 1
                    continue
                try:
                    raw_id = patch_series(dsn, slug, s["title"],
                                          f"{_http.BASE_URL}/anime/{slug}/", payload)
                    mr = merge_raw_to_canonical(raw_id, s["title"], KIND_ANIME,
                                                payload, dsn=dsn)
                    enrich_canonical(mr["canonical_id"], s["title"], KIND_ANIME, dsn=dsn)
                    ingested += 1
                except Exception:
                    failed += 1
            log(f"backfill: {min(i + BATCH, len(series))}/{len(series)} "
                f"(ingested {ingested}, failed {failed})")
    return {"total": len(series), "ingested": ingested, "failed": failed}


def backfill_all(dsn: str | None = None, workers: int = BACKFILL_WORKERS,
                 limit: int | None = None, log=print) -> dict:
    """Full historical ingest: every series from daftar-anime-2 + all eps/batches.

    Resumable: series already in raw_entities are skipped, so a crash + re-run
    continues from where it stopped. `limit` caps the series count (smoke).
    """
    dsn = dsn or pg_dsn()
    # 1. seed the full directory (sync, ~25 pages).
    with _http.client() as cx:
        all_series = _lists.walk_directory(cx)
    if limit is not None:
        all_series = all_series[:limit]

    # 2. filter to series not yet in DB (resumable).
    new_series = [s for s in all_series if load_series_payload(dsn, s["slug"]) is None]
    log(f"backfill: {len(all_series)} series in directory, "
        f"{len(new_series)} new ({len(all_series) - len(new_series)} already in DB)")

    if not new_series:
        return {"total": 0, "ingested": 0, "failed": 0, "skipped_existing": len(all_series)}

    # 3. concurrent fetch + sync write.
    return asyncio.run(_backfill_async(dsn, new_series, workers, log))
