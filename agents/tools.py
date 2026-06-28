"""Pipeline tools exposed to sloane agents.

Agents orchestrate (decide what/when); tools do the deterministic work
(fetch, validate, write, assert). LLM never touches DB directly — it calls
these functions via ADK's FunctionTool. Keeps the 24/7 loop reproducible and
budget-capped: each tool call is one bounded step.

Tool names = function names (ADK convention). Instructions reference the
exact names so the LLM doesn't hallucinate variants.
"""
from __future__ import annotations
from google.adk.tools import FunctionTool

from shared.config import pg_dsn
from shared.migrations_runner import ensure_schema
from sloane.db.writer import write_entities
from shared.memory_service import GroupMemoryService
import sloane.sources  # noqa: F401  register plugins
from sloane.sources.registry import REGISTRY
from shared.schema_contract import CanonicalEntity


def fetch_source(source_slug: str) -> list[dict]:
    """Fetch all entities from a registered source slug. Returns a list of dicts."""
    cls = REGISTRY.get(source_slug)
    if cls is None:
        raise ValueError(f"unknown source {source_slug!r}; known: {list(REGISTRY)}")
    out = []
    for e in cls().fetch():
        e.validate()
        out.append({
            "source": e.source, "external_id": e.external_id, "kind": e.kind,
            "title": e.title, "url": e.url, "payload": e.payload,
        })
    return out


def write_entities_tool(entities: list[dict]) -> dict:
    """Upsert entities to PG (dedup by source+external_id). Returns {inserted,updated}.

    Extra LLM-added keys are folded into payload, never crash the pipeline.
    """
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
    return {"inserted": r.inserted, "updated": r.updated}


def assert_quality(source_slug: str, expected: int | None = None) -> dict:
    """Quality gate: verify rows for source in DB. Returns {passed, checks, rows}."""
    import psycopg
    dsn = pg_dsn()
    with psycopg.connect(dsn) as c, c.cursor() as cur:
        cur.execute(
            "SELECT source, external_id, kind, title, payload->>'episodes' AS eps "
            "FROM canonical_entities WHERE source=%s ORDER BY title",
            (source_slug,),
        )
        rows = cur.fetchall()
    checks = {
        "rows_present": len(rows) > 0,
        "no_null_title": all(r[3] for r in rows),
        "no_null_kind": all(r[2] for r in rows),
        "no_null_external_id": all(r[1] for r in rows),
        "count_ok": expected is None or len(rows) == expected,
    }
    return {"source": source_slug, "row_count": len(rows),
            "passed": all(checks.values()), "checks": checks, "rows": rows}


fetch_tool = FunctionTool(func=fetch_source)
write_tool = FunctionTool(func=write_entities_tool)
assert_tool = FunctionTool(func=assert_quality)
