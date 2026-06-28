"""Enrichment: resolve canonical title -> registry IDs (MAL via Jikan, OMDB, ...).

ID-first merge key: once a canonical has an authoritative mal_id, future raw
rows from any source carrying the same mal_id (or matching the resolved
canonical) merge exactly — no fuzzy title guesswork.

Jikan = free unofficial MAL API (no key). Rate-limited (~3 req/s); we throttle
to be safe. OMDB/tvdb added later when needed; interface is registry-agnostic.
"""
from __future__ import annotations
import time

import httpx

JIKAN_BASE = "https://api.jikan.moe/v4"
# Jikan ~3 req/s sustained; sleep to respect. ponytail: real rate-limiter add when bulk.
_MIN_GAP = 0.4
_last_call = 0.0


def _throttle() -> None:
    global _last_call
    now = time.monotonic()
    wait = _MIN_GAP - (now - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def resolve_mal_id(title: str, kind: str | None = None) -> dict | None:
    """Resolve a title to a MAL entry via Jikan. Returns {mal_id, title, type} or None.

    kind hint narrows: anime sources -> anime endpoint; movies filter by type.
    """
    _throttle()
    try:
        r = httpx.get(f"{JIKAN_BASE}/anime",
                      params={"q": title, "limit": 5, "sfw": True},
                      timeout=15, headers={"User-Agent": "sloane-enricher/1.0"})
    except Exception:
        return None
    if r.status_code != 200:
        return None
    data = r.json().get("data", [])
    if not data:
        return None
    # best match: exact title (case-insensitive), prefer non-movie for series kind
    exact = [a for a in data if a.get("title", "").strip().lower() == title.strip().lower()]
    pool = exact or data
    if kind in ("anime", "series", "comic", "novel"):
        non_movie = [a for a in pool if a.get("type") not in ("Movie", "ONA")]
        if non_movie:
            pool = non_movie
    best = pool[0]
    return {"mal_id": best["mal_id"], "title": best.get("title", title), "type": best.get("type")}


def enrich_canonical(canonical_id: int, title: str, kind: str,
                     dsn: str | None = None) -> dict:
    """Resolve + persist a mal_id for a canonical entity. Idempotent."""
    import psycopg
    from shared.config import pg_dsn
    dsn = dsn or pg_dsn()
    resolved = resolve_mal_id(title, kind)
    if not resolved:
        return {"canonical_id": canonical_id, "resolved": False}
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO external_ids (canonical_id, registry, external_id) "
            "VALUES (%s,'mal',%s) ON CONFLICT (registry, external_id) DO NOTHING "
            "RETURNING id", (canonical_id, str(resolved["mal_id"])))
        added = cur.fetchone() is not None
        conn.commit()
    return {"canonical_id": canonical_id, "resolved": True,
            "mal_id": resolved["mal_id"], "added": added}
