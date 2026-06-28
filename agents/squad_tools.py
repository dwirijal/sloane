"""Processor + store squad tools. Processor enriches canonicals with registry
IDs (Jikan/MAL). Store enforces DB governance: lean ratio, retention flags.
"""
from __future__ import annotations
import psycopg
from google.adk.tools import FunctionTool

from shared.config import pg_dsn
from shared.migrations_runner import ensure_schema
from sloane.store.enricher import enrich_canonical


def enrich_pending_canonicals(limit: int = 5) -> dict:
    """Enrich canonicals that have no registry ID yet (resolve mal_id via Jikan).
    Returns counts. Processor squad's core job: give canonicals authoritative IDs.
    """
    dsn = pg_dsn(); ensure_schema(dsn)
    with psycopg.connect(dsn) as c, c.cursor() as cur:
        cur.execute(
            "SELECT c.id, c.title, c.kind FROM canonical_entities c "
            "WHERE NOT EXISTS (SELECT 1 FROM external_ids e WHERE e.canonical_id=c.id) "
            "ORDER BY c.id LIMIT %s", (limit,))
        pending = cur.fetchall()
    enriched = 0
    for cid, title, kind in pending:
        r = enrich_canonical(cid, title, kind, dsn=dsn)
        if r.get("resolved"):
            enriched += 1
    return {"pending": len(pending), "enriched": enriched, "mal_ids_added": enriched}


def store_health_check() -> dict:
    """Store squad governance: raw vs canonical ratio, orphans, lean flag.
    Lean = canonicals should be << raw (merge working). Orphan raw = no link.
    """
    dsn = pg_dsn()
    with psycopg.connect(dsn) as c, c.cursor() as cur:
        cur.execute("SELECT count(*) FROM raw_entities"); raw = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM canonical_entities"); canon = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM canonical_entities c WHERE NOT EXISTS (SELECT 1 FROM external_ids e WHERE e.canonical_id=c.id)"); no_id = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM raw_entities r WHERE NOT EXISTS (SELECT 1 FROM entity_source_links l WHERE l.raw_id=r.id)"); orphan = cur.fetchone()[0]
    ratio = (canon / raw) if raw else 0
    # lean: merge compressing (canon < raw*0.8 = healthy merge). ponytail: tune threshold with real scale.
    lean = 0 < ratio < 0.8 if raw else True
    return {"raw": raw, "canonical": canon, "ratio": round(ratio, 2),
            "canonicals_without_id": no_id, "orphan_raw": orphan, "lean": lean}


enrich_tool = FunctionTool(func=enrich_pending_canonicals)
store_health_tool = FunctionTool(func=store_health_check)
