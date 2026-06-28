"""Raw-layer writer. Upserts into raw_entities (per-source evidence).

3-layer model: scrapers write RAW here; the merger resolves raw -> canonical.
write_entities returns raw_ids so the merger can link immediately.
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
    raw_ids: list  # ids of inserted/updated raw rows, in order


UPSERT_SQL = """
INSERT INTO raw_entities (source, external_id, kind, title, url, payload)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (source, external_id)
DO UPDATE SET
    title     = EXCLUDED.title,
    url       = EXCLUDED.url,
    payload   = EXCLUDED.payload,
    updated_at = now()
RETURNING id, (xmax = 0) AS was_inserted
"""


def write_entities(dsn: str, entities: Iterable[CanonicalEntity]) -> WriteResult:
    """Validate + upsert raw entities. Returns counts + raw_ids."""
    inserted = updated = 0
    raw_ids: list = []
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for e in entities:
            e.validate()
            row = cur.execute(
                UPSERT_SQL,
                (e.source, e.external_id, e.kind, e.title, e.url, json.dumps(e.payload)),
            ).fetchone()
            raw_id, was_inserted = row[0], row[1]
            raw_ids.append(raw_id)
            if was_inserted:
                inserted += 1
            else:
                updated += 1
        conn.commit()
    return WriteResult(inserted=inserted, updated=updated, raw_ids=raw_ids)
