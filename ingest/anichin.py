"""anichin incremental ingest runner.

2h job (ingest_updates): fetch /anime/?order=update, and for each listed series
diff the detail page's max episode number against the DB payload's max. Fetch
ONLY the new episode pages (n > old_max), parse their Dailymotion stream_url,
and load-mutate-upsert the parent series raw_entities row (write_entities replaces
payload wholesale, so we SELECT the existing payload, append new eps with
stream_url, UPSERT the full entity). Then merge_raw. No RSS feed (disabled) —
ep-number diff is the delta primitive.

daily job (discover_new_series): A-Z directory walk -> slugs absent from
raw_entities -> full series fetch -> write_entities -> merge -> enrich. Stores
episodes WITHOUT stream_url (deferred — full-eps fetch is too heavy for a daily
sweep; stream_url filled later by ingest_updates for new eps or by backfill).

backfill (backfill_all): full historical ingest of every series from the A-Z
directory (~700), each with ALL episode pages parsed for stream_url. Concurrent
(httpx.AsyncClient + N workers) because the scale (~50k episode pages for the
long donghua runners) makes sequential impractical. Resumable via ingest_state
backfill_done slug set.

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
from sloane.store.state import get_state, set_state
from sloane.sources.anichin import _detail, _episodes, _http, _lists

SOURCE = "anichin"
BACKFILL_KEY = "backfill_done"


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


def _max_ep(payload: dict) -> int:
    """Highest episode number in payload['episodes'], or 0 if none."""
    eps = payload.get("episodes") or []
    return max((e.get("n") or 0 for e in eps), default=0)


def _merge_episodes(old: list, new: list) -> list:
    """Union old + new episode dicts, dedup by n (new wins), sorted ascending."""
    by_n = {e["n"]: e for e in old if "n" in e}
    for e in new:
        if "n" in e:
            by_n[e["n"]] = e
    return sorted(by_n.values(), key=lambda e: e["n"])


def ingest_updates(dsn: str | None = None, max_new: int | None = None) -> dict:
    """2h job: latest-update-list delta ingest of new episodes.

    Returns {fetched, updated_series, new_episodes, skipped}.
    """
    dsn = dsn or pg_dsn()
    updated = skipped = new_eps_total = 0

    with _http.client() as cx:
        list_html = cx.get(f"{_http.BASE_URL}/anime/?status=&type=&order=update").text
        series = _lists.parse_update_list(list_html)
        if max_new is not None:
            series = series[:max_new]

        for item in series:
            slug = item["slug"]
            existing = load_series_payload(dsn, slug)
            if existing is None:
                # series not yet in DB; discover job will add it. skip.
                skipped += 1
                continue
            try:
                detail_html = cx.get(f"{_http.BASE_URL}/anime/{slug}/").text
                detail = _detail.parse_detail(detail_html, base=_http.BASE_URL)
            except Exception:
                skipped += 1
                continue

            old_max = _max_ep({"episodes": existing.get("episodes", [])})
            new_eps = [e for e in detail["episodes"] if e["n"] > old_max]
            if not new_eps:
                continue  # up to date

            # Fetch only new episode pages -> parse stream_url.
            for ep in new_eps:
                try:
                    ep_html = cx.get(ep["url"]).text
                    parsed = _episodes.parse_episode(ep_html)
                    ep["stream_url"] = parsed.get("stream_url")
                except Exception:
                    ep["stream_url"] = None

            title = existing.get("title") or item["title"]
            payload = {k: v for k, v in existing.items() if k != "title"}
            payload["episodes"] = _merge_episodes(
                payload.get("episodes", []),
                [{"n": e["n"], "url": e["url"], "stream_url": e.get("stream_url")} for e in new_eps],
            )
            # carry detail metadata forward if missing (first delta after discover)
            payload.setdefault("cover_url", detail.get("cover_url"))
            payload.setdefault("synopsis", detail.get("synopsis"))
            payload.setdefault("infox", detail.get("infox"))

            raw_id = patch_series(dsn, slug, title, f"{_http.BASE_URL}/anime/{slug}/", payload)
            merge_raw_to_canonical(raw_id, title, KIND_ANIME, payload, dsn=dsn)
            # No enrich here: canonical + mal_id already resolved at discover time.
            updated += 1
            new_eps_total += len(new_eps)

    return {"fetched": len(series), "updated_series": updated,
            "new_episodes": new_eps_total, "skipped": skipped}


def discover_new_series(dsn: str | None = None, max_new: int | None = None) -> dict:
    """daily job: A-Z directory walk -> slugs absent from raw_entities -> full fetch.

    Stores episodes WITHOUT stream_url (deferred to ingest_updates / backfill).
    Returns {discovered, ingested}.
    """
    dsn = dsn or pg_dsn()
    discovered = ingested = 0
    with _http.client() as cx:
        all_series = _lists.walk_directory(cx)
        if max_new is not None:
            all_series = all_series[:max_new]
        for item in all_series:
            slug = item["slug"]
            if load_series_payload(dsn, slug) is not None:
                continue  # already in DB
            discovered += 1
            try:
                detail_html = cx.get(f"{_http.BASE_URL}/anime/{slug}/").text
                detail = _detail.parse_detail(detail_html, base=_http.BASE_URL)
                payload = {
                    "cover_url": detail.get("cover_url"),
                    "synopsis": detail.get("synopsis"),
                    "infox": detail.get("infox"),
                    "episodes": detail["episodes"],  # [{n,url}] — no stream_url yet
                }
                raw_id = patch_series(dsn, slug, item["title"],
                                      f"{_http.BASE_URL}/anime/{slug}/", payload)
                mr = merge_raw_to_canonical(raw_id, item["title"], KIND_ANIME,
                                            payload, dsn=dsn)
                enrich_canonical(mr["canonical_id"], item["title"], dsn=dsn)
                ingested += 1
            except Exception:
                continue
    return {"discovered": discovered, "ingested": ingested}


# ---------------------------------------------------------------------------
# Backfill: full historical ingest (all series + all episode stream_urls).
# ---------------------------------------------------------------------------

# Episode page fetches are the cost driver (Martial Master alone = 720). Cap
# concurrency to respect the site. ponytail: raise to 12-16 once a run confirms
# no rate-limit 429s.
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


async def _fetch_series_full(cx, sem, slug: str, title: str) -> dict | None:
    """Fetch a series detail + ALL its episode pages concurrently.

    Returns the full payload dict (episodes with stream_url) for one series,
    or None if the detail page itself failed.
    """
    series_url = f"{_http.BASE_URL}/anime/{slug}/"
    detail_html = await _fetch_one(cx, series_url, sem)
    if not detail_html:
        return None
    detail = _detail.parse_detail(detail_html, base=_http.BASE_URL)

    ep_urls = [e["url"] for e in detail["episodes"]]
    ep_htmls = await asyncio.gather(*[_fetch_one(cx, u, sem) for u in ep_urls])
    episodes = []
    for ep, html in zip(detail["episodes"], ep_htmls):
        stream_url = None
        if html:
            stream_url = _episodes.parse_episode(html).get("stream_url")
        episodes.append({"n": ep["n"], "url": ep["url"], "stream_url": stream_url})

    return {
        "cover_url": detail.get("cover_url"),
        "synopsis": detail.get("synopsis"),
        "infox": detail.get("infox"),
        "episodes": episodes,
    }


async def _backfill_async(dsn, series, workers, log) -> dict:
    sem = asyncio.Semaphore(workers)
    ingested = failed = 0
    done: set[str] = set(get_state(dsn, SOURCE, BACKFILL_KEY, default=[]) or [])
    async with httpx.AsyncClient(headers=_http.HEADERS, follow_redirects=True) as cx:
        BATCH = 10
        for i in range(0, len(series), BATCH):
            chunk = [s for s in series[i:i + BATCH] if s["slug"] not in done]
            if not chunk:
                continue
            results = await asyncio.gather(
                *[_fetch_series_full(cx, sem, s["slug"], s["title"]) for s in chunk]
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
                    enrich_canonical(mr["canonical_id"], s["title"], dsn=dsn)
                    ingested += 1
                    done.add(slug)
                except Exception:
                    failed += 1
            # persist progress so a crash resumes past completed slugs
            set_state(dsn, SOURCE, BACKFILL_KEY, sorted(done))
            log(f"backfill: {min(i + BATCH, len(series))}/{len(series)} "
                f"(ingested {ingested}, failed {failed})")
    return {"total": len(series), "ingested": ingested, "failed": failed}


def backfill_all(dsn: str | None = None, workers: int = BACKFILL_WORKERS,
                 limit: int | None = None, log=print) -> dict:
    """Full historical ingest: every series from A-Z + all episode stream_urls.

    Resumable via ingest_state backfill_done slug set — a crash + re-run skips
    completed series. `limit` caps the series count (smoke).
    """
    dsn = dsn or pg_dsn()
    with _http.client() as cx:
        all_series = _lists.walk_directory(cx)
    if limit is not None:
        all_series = all_series[:limit]

    done: set[str] = set(get_state(dsn, SOURCE, BACKFILL_KEY, default=[]) or [])
    new_series = [s for s in all_series if s["slug"] not in done]
    log(f"backfill: {len(all_series)} series in directory, "
        f"{len(new_series)} new ({len(all_series) - len(new_series)} already done)")

    if not new_series:
        return {"total": 0, "ingested": 0, "failed": 0,
                "skipped_existing": len(all_series)}

    return asyncio.run(_backfill_async(dsn, all_series, workers, log))
