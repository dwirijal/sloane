"""Enrichment: resolve canonical title -> registry IDs (MAL via Jikan, OMDB, ...).

ID-first merge key: once a canonical has an authoritative mal_id, future raw
rows from any source carrying the same mal_id (or matching the resolved
canonical) merge exactly — no fuzzy title guesswork.

Jikan = free unofficial MAL API (no key). Rate-limited (~3 req/s); we throttle
to be safe. OMDB/tvdb added later when needed; interface is registry-agnostic.
"""
from __future__ import annotations
import time
import re

import httpx

JIKAN_BASE = "https://api.jikan.moe/v4"
# Jikan ~3 req/s sustained; sleep to respect. ponytail: real rate-limiter add when bulk.
_MIN_GAP = 0.4
_last_call = 0.0

_NORM_RE = re.compile(r"[^a-z0-9]+")
_NOISE_RE = re.compile(r"\b(season|cour|part|the|movie|hen|tan|s2)\b", re.IGNORECASE)
_ROMAN = {"ii": "2", "iii": "3", "iv": "4", "v": "5"}


def _throttle() -> None:
    global _last_call
    now = time.monotonic()
    wait = _MIN_GAP - (now - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def _normalize(s: str) -> str:
    s = s.lower()
    s = _NORM_RE.sub(" ", s)
    s = _NOISE_RE.sub("", s)
    return " ".join(s.split()).strip()


def _season_marker(s: str) -> str | None:
    """Extract a normalized season/part identifier from title.

    'season 2'/'s2'/'part 3' -> '2'/'2'/'3'; roman 'ii' -> '2'. None if base series.
    """
    s = s.lower()
    m = re.search(r"\b(?:season|part|s)\s*([0-9]+)\b", s)
    if m:
        return m.group(1)
    m = re.search(r"([0-9]+)(?:nd|rd|th|st)\s*season", s)
    if m:
        return m.group(1)
    for roman, digit in _ROMAN.items():
        if re.search(r"\b" + roman + r"\b", s):
            return digit
    return None


def resolve_mal_id(title: str) -> dict | None:
    """Resolve a title to a MAL entry via Jikan. Returns {mal_id, title, type} or None.

    Two tiers: (1) exact case-insensitive title match; (2) token-overlap >=0.8 with a
    season-suffix guard — query "X Season 2" only matches MAL entries carrying the same
    season marker, so we never map S2 raw onto a base-series S1 MAL id (wrong-id poison).
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
    # 1. exact title (case-insensitive) — strongest signal.
    exact = [a for a in data if a.get("title", "").strip().lower() == title.strip().lower()]
    if exact:
        best = exact[0]
        return {"mal_id": best["mal_id"], "title": best.get("title", title), "type": best.get("type")}
    # 2. tier-2: token-overlap >=0.8 + season-marker match.
    # No hard Movie/ONA filter: samehadaku lists movie arcs (Jujutsu Kaisen 0,
    # Chainsaw Man Reze-hen, SAO Progressive) as series — filtering them out loses
    # correct matches. Score + season-guard alone decide.
    q_words = set(_normalize(title).split())
    q_season = _season_marker(title)
    candidates = []
    for item in data:
        t_title = item.get("title") or ""
        t_words = set(_normalize(t_title).split())
        # Season guard: mismatching markers -> wrong season entry. Reject.
        if q_season != _season_marker(t_title):
            continue
        if not q_words:
            continue
        score = len(q_words & t_words) / len(q_words)
        if score >= 0.8:
            candidates.append((score, item))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0][1]
    return {"mal_id": best["mal_id"], "title": best.get("title", title), "type": best.get("type")}


def enrich_canonical(canonical_id: int, title: str,
                     dsn: str | None = None) -> dict:
    """Resolve + persist a mal_id for a canonical entity. Idempotent."""
    import psycopg
    from shared.config import pg_dsn
    dsn = dsn or pg_dsn()
    resolved = resolve_mal_id(title)
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
