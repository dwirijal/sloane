"""Merge layer: raw_entities -> canonical_entities + links.

Two-phase merge (per the agreed key):
  1. ID-first: if a raw row carries a registry ID (mal/anilist/omdb/tvdb),
     match canonical via external_ids table. Otoritatif.
  2. Title fallback: normalized_title + kind match. Fuzzy later via pgvector;
     exact normalized for now (good enough for proof: oploverz & kusonime both
     say "One Piece").

Emits: new canonical row OR links raw to existing canonical. Always inserts
a link. raw_id -> canonical_id is 1:1 (one raw backs one canonical).
"""
from __future__ import annotations
import re
import json
import psycopg
from psycopg.types.json import Json

from shared.config import pg_dsn

_NORM = re.compile(r"[^a-z0-9]+")


def normalize_title(title: str) -> str:
    """Lowercase, strip punctuation/whitespace. 'One Piece' -> 'onepiece'."""
    return _NORM.sub("", title.lower()).strip()


def merge_raw_to_canonical(raw_id: int, title: str, kind: str,
                           payload: dict, registry_ids: dict | None = None,
                           dsn: str | None = None) -> dict:
    """Resolve + write canonical for one raw row. Returns {canonical_id, merged}.

    merged=True if a NEW canonical was created; False if linked to existing.
    """
    dsn = dsn or pg_dsn()
    norm = normalize_title(title)
    if not norm:
        raise ValueError(f"empty normalized title for raw_id={raw_id}")
    reg = registry_ids or {}

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        canonical_id = None

        # 1. ID-first: any registry ID hits an existing canonical?
        for registry, ext_id in reg.items():
            row = cur.execute(
                "SELECT canonical_id FROM external_ids WHERE registry=%s AND external_id=%s",
                (registry, str(ext_id)),
            ).fetchone()
            if row:
                canonical_id = row[0]
                break

        # 2. title fallback
        if canonical_id is None:
            row = cur.execute(
                "SELECT id FROM canonical_entities WHERE kind=%s AND normalized_title=%s",
                (kind, norm),
            ).fetchone()
            if row:
                canonical_id = row[0]

        merged = False
        if canonical_id is None:
            # create new canonical
            canonical_id = cur.execute(
                "INSERT INTO canonical_entities (kind, title, normalized_title, best_payload) "
                "VALUES (%s,%s,%s,%s) RETURNING id",
                (kind, title, norm, Json(payload)),
            ).fetchone()[0]
            merged = True
        else:
            # merge payload: best non-null wins (naive; LLM refines later)
            cur.execute(
                "UPDATE canonical_entities SET best_payload = best_payload || %s::jsonb, updated_at=now() WHERE id=%s",
                (Json(payload), canonical_id),
            )

        # registry IDs (if new canonical gained authoritative IDs)
        for registry, ext_id in reg.items():
            cur.execute(
                "INSERT INTO external_ids (canonical_id, registry, external_id) "
                "VALUES (%s,%s,%s) ON CONFLICT (registry, external_id) DO NOTHING",
                (canonical_id, registry, str(ext_id)),
            )

        # link raw -> canonical (first link is primary)
        cur.execute(
            "INSERT INTO entity_source_links (canonical_id, raw_id, is_primary) "
            "VALUES (%s,%s, true) "
            "ON CONFLICT (canonical_id, raw_id) DO UPDATE SET is_primary=true",
            (canonical_id, raw_id),
        )
        # only one primary per canonical: demote others
        cur.execute(
            "UPDATE entity_source_links SET is_primary=false "
            "WHERE canonical_id=%s AND raw_id<>%s",
            (canonical_id, raw_id),
        )
        conn.commit()
    return {"canonical_id": canonical_id, "merged": merged}
