"""Pipeline tools exposed to sloane agents.

Agents orchestrate; tools do deterministic work. 3-layer flow:
  fetch_source -> write raw -> merge raw->canonical -> assert both layers.
LLM never touches DB directly; tools return counts so agents report status.
"""
from __future__ import annotations
from google.adk.tools import FunctionTool

from shared.config import pg_dsn
from shared.migrations_runner import ensure_schema
from shared.schema_contract import CanonicalEntity
from sloane.db.writer import write_entities
from sloane.store.merger import merge_raw_to_canonical
import sloane.sources  # noqa: F401  register plugins
from sloane.sources.registry import REGISTRY


def fetch_source(source_slug: str) -> list[dict]:
    """Fetch all entities from a registered source slug."""
    cls = REGISTRY.get(source_slug)
    if cls is None:
        raise ValueError(f"unknown source {source_slug!r}; known: {list(REGISTRY)}")
    out = []
    for e in cls().fetch():
        e.validate()
        out.append({"source": e.source, "external_id": e.external_id, "kind": e.kind,
                    "title": e.title, "url": e.url, "payload": e.payload})
    return out


def write_entities_tool(entities: list[dict]) -> dict:
    """Write raw entities + merge each into canonical. Returns raw/canonical counts."""
    dsn = pg_dsn(); ensure_schema(dsn)
    keep = {"source", "external_id", "kind", "title", "url", "payload"}
    ents = []
    for e in entities:
        fields = {k: e[k] for k in keep if k in e}
        extra = {k: v for k, v in e.items() if k not in keep}
        if extra:
            fields["payload"] = {**(fields.get("payload") or {}), **extra}
        ents.append(CanonicalEntity(**fields))
    r = write_entities(dsn, ents)
    # merge each raw -> canonical. Sources carrying registry_ids (e.g. jikan mal_id)
    # merge ID-first; scrapers merge by cleaned title then LLM fuzzy.
    merged_new = 0
    methods: dict[str, int] = {}
    for rid, ent in zip(r.raw_ids, ents):
        reg = (ent.payload or {}).get("registry_ids")
        m = merge_raw_to_canonical(rid, ent.title, ent.kind, ent.payload,
                                   registry_ids=reg, dsn=dsn)
        methods[m["method"]] = methods.get(m["method"], 0) + 1
        merged_new += 1 if m["merged"] else 0
    return {"raw_inserted": r.inserted, "raw_updated": r.updated,
            "canonical_new": merged_new, "canonical_total": len(r.raw_ids),
            "merge_methods": methods}


def assert_quality(source_slug: str, expected: int | None = None) -> dict:
    """Quality gate: verify raw rows for source + canonical merge happened."""
    import psycopg
    dsn = pg_dsn()
    with psycopg.connect(dsn) as c, c.cursor() as cur:
        cur.execute(
            "SELECT external_id, kind, title FROM raw_entities WHERE source=%s ORDER BY title",
            (source_slug,))
        rows = cur.fetchall()
        cur.execute(
            "SELECT count(*) FROM entity_source_links l "
            "JOIN raw_entities r ON r.id=l.raw_id WHERE r.source=%s", (source_slug,))
        links = cur.fetchone()[0]
    checks = {
        "raw_rows_present": len(rows) > 0,
        "no_null_title": all(r[2] for r in rows),
        "no_null_kind": all(r[1] for r in rows),
        "no_null_external_id": all(r[0] for r in rows),
        "count_ok": expected is None or len(rows) == expected,
        "merged_to_canonical": links == len(rows),
    }
    return {"source": source_slug, "raw_count": len(rows), "links": links,
            "passed": all(checks.values()), "checks": checks}


fetch_tool = FunctionTool(func=fetch_source)
write_tool = FunctionTool(func=write_entities_tool)
assert_tool = FunctionTool(func=assert_quality)
