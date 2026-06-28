"""PG writer for canonical entities. Dedup via ON CONFLICT (source, external_id).

Immutability: upsert returns a new EntityWrite result, never mutates input.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Iterable

import psycopg
from shared.schema_contract import CanonicalEntity


@dataclass(frozen=True)
class WriteResult:
    inserted: int
    updated: int


UPSERT_SQL = """
INSERT INTO canonical_entities (source, external_id, kind, title, url, payload)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (source, external_id)
DO UPDATE SET
    title     = EXCLUDED.title,
    url       = EXCLUDED.url,
    payload   = EXCLUDED.payload,
    updated_at = now()
RETURNING (xmax = 0) AS was_inserted
"""


def write_entities(dsn: str, entities: Iterable[CanonicalEntity]) -> WriteResult:
    """Validate + upsert entities. Returns counts. Raises on validation failure."""
    inserted = updated = 0
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for e in entities:
            e.validate()  # trust boundary: reject malformed before touching DB
            was_inserted = cur.execute(
                UPSERT_SQL,
                (e.source, e.external_id, e.kind, e.title, e.url, json.dumps(e.payload)),
            ).fetchone()[0]
            if was_inserted:
                inserted += 1
            else:
                updated += 1
        conn.commit()
    return WriteResult(inserted=inserted, updated=updated)
