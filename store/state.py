"""Runner state persistence over the ingest_state table.

Stateless cron runs need to remember things across invocations (e.g. which
feed URLs were already ingested). That state lives in Postgres, not in process
memory — every run reads on start, writes on finish. A crash mid-run costs
redundant work (write_entities/merge_raw are idempotent), never duplicate data.

ponytail: value is a JSONB array for seen_feed_urls. If a key's value grows
past ~10k entries, swap to a dedicated table. At <10 posts/run this won't
happen for years.
"""
from __future__ import annotations
from typing import Any

import psycopg
from psycopg.types.json import Json


def get_state(dsn: str, source: str, key: str, default: Any = None) -> Any:
    """Read the JSONB value for (source, key). Return default if absent."""
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        row = cur.execute(
            "SELECT value FROM ingest_state WHERE source=%s AND key=%s",
            (source, key),
        ).fetchone()
    return row[0] if row else default


def set_state(dsn: str, source: str, key: str, value: Any) -> None:
    """UPSERT, replacing the value wholesale."""
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingest_state (source, key, value) VALUES (%s,%s,%s) "
            "ON CONFLICT (source, key) DO UPDATE SET value=EXCLUDED.value, "
            "updated_at=now()",
            (source, key, Json(value)),
        )
        conn.commit()


def add_seen(dsn: str, source: str, key: str, new_urls: list[str]) -> None:
    """Append new_urls to the JSONB array at (source,key), deduping.

    Loads existing, unions with new_urls (preserving order), UPSERTs back.
    Caller already computes the delta via set-diff; this dedups defensively so
    a double-call never inflates the array.
    """
    existing = get_state(dsn, source, key, default=[]) or []
    if not isinstance(existing, list):
        existing = []
    seen = set(existing)
    merged = list(existing) + [u for u in new_urls if u not in seen]
    set_state(dsn, source, key, merged)
