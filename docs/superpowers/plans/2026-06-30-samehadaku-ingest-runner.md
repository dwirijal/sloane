# samehadaku Incremental Ingest Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A cron-driven runner that incrementally ingests new samehadaku episode/batch posts via the site's RSS feed, plus a daily discovery sweep for new series.

**Architecture:** Two systemd timers fire a stateless CLI runner (`sloane-ingest samehadaku` every 2h, `--discover` daily). The 2h job fetches `/feed/`, deltas new post URLs against an `ingest_state` DB row, fetches only new post pages, parses downloads, and load-mutate-upserts the parent series `raw_entities` row through the existing `write_entities` → `merge_raw` → `enrich` pipeline. State lives in Postgres, not in process memory.

**Tech Stack:** Python 3.12, httpx, BeautifulSoup4 (`lxml`), psycopg, Postgres (dwizzyOS `DOS-pg`), systemd user units. The shared contract + config come from `dwizzyOS-HQ/shared/` (`schema_contract.py`, `config.py`) on `PYTHONPATH`.

## Global Constraints

- **Run env:** Python at `/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python` has `bs4`+`httpx`+`psycopg`. `PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ` (sloane root + parent so `import sloane.*` and `import shared.*` both resolve).
- **HTTP client:** reuse `sources/samehadaku/_http.py` — `BASE_URL = "https://v2.samehadaku.how"`, browser UA, `httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True)`. No anti-bot; no CDP.
- **DB access:** `shared.config.pg_dsn()` for the DSN. All DB ops use `psycopg.connect(dsn)`. Migrations live in `db/migrations/` as versioned SQL (`004_...` next).
- **CanonicalEntity contract:** `from shared.schema_contract import CanonicalEntity, KIND_ANIME`. `write_entities(dsn, entities)` validates + UPSERTs raw rows (replaces `payload` wholesale — load-mutate-upsert, NOT a SQL per-field patch). `merge_raw_to_canonical(raw_id, title, kind, payload, registry_ids=None, dsn=None)` links raw→canonical. `enrich_canonical(canonical_id, title, kind, dsn=None)` resolves MAL id.
- **Self-check convention:** each parser module has an `if __name__ == "__main__":` block asserting real behavior against the live site (see `store/merger.py:204`, `sources/samehadaku/_downloads.py:98`).
- **YAGNI:** no concurrency, no per-post transactions, no other sources wired in. `ponytail:` comments mark every deliberate ceiling + upgrade path.
- **Commit messages** end with `Co-Authored-By: Claude <noreply@anthropic.com>`.
- **No commits on `main`.** All work on `feat/samehadaku-ingest-runner`.

---

## File Structure

| File | Responsibility |
|---|---|
| `sources/samehadaku/_feed.py` (new) | Parse `/feed/` XML → `[{url, pubdate, kind}]`. Kind inferred from URL. + live self-check. |
| `db/migrations/004_ingest_state.sql` (new) | `ingest_state(source, key, value jsonb, updated_at)` table. UNIQUE(source,key). |
| `store/state.py` (new) | `get_state` / `set_state` / `add_seen` over `ingest_state`. + round-trip self-check. |
| `ingest/__init__.py` (new) | empty package marker. |
| `ingest/samehadaku.py` (new) | `ingest_feed()` (2h job) + `discover_new_series()` (daily job). Load-mutate-upsert series payload. |
| `ingest/__main__.py` (new) | CLI: `sloane-ingest samehadaku [--discover] [--max-new N]`. Prints JSON result. |
| `tests/test_feed.py` (new) | Unit tests for `_feed.parse` + kind inference (fixture). |
| `tests/test_state.py` (new) | Round-trip + dedup tests for `store.state` (uses real DB via `pg_dsn`). |
| `tests/test_ingest.py` (new) | Delta + idempotency tests for `ingest_feed`/`discover_new_series` (mocked http). |
| `deploy/sloane-samehadaku-ingest.service` (new) | systemd user service: 2h ingest. |
| `deploy/sloane-samehadaku-ingest.timer` (new) | systemd user timer: every 2h. |
| `deploy/sloane-samehadaku-discover.service` (new) | systemd user service: daily discover. |
| `deploy/sloane-samehadaku-discover.timer` (new) | systemd user timer: daily 05:00. |

---

### Task 1: Feed parser (`_feed.py`)

**Files:**
- Create: `sources/samehadaku/_feed.py`
- Create: `tests/test_feed.py`

**Interfaces:**
- Consumes: `sources/samehadaku/_http.py` (`BASE_URL`, `HEADERS`, `client()`).
- Produces: `parse_feed(html: str) -> list[dict]` where each dict is `{"url": str, "pubdate": str, "kind": str}`; `kind ∈ {"episode","batch","post"}`. `fetch_feed(cx) -> str` returns raw feed HTML.

- [ ] **Step 1: Save the feed fixture for tests**

```bash
/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python - <<'PY'
import httpx
from pathlib import Path
r = httpx.get("https://v2.samehadaku.how/feed/",
              headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
              timeout=20, follow_redirects=True)
Path("tests/fixtures/samehadaku_feed.xml").write_text(r.text)
print("saved", len(r.text), "bytes")
PY
```
Ensure `tests/fixtures/` dir exists first (`mkdir -p tests/fixtures`).

- [ ] **Step 2: Write the failing test**

`tests/test_feed.py`:
```python
from pathlib import Path
from sloane.sources.samehadaku._feed import parse_feed

FIXTURE = Path(__file__).parent / "fixtures" / "samehadaku_feed.xml"

def test_parse_feed_returns_items():
    items = parse_feed(FIXTURE.read_text())
    assert items, "feed parsed no items"
    first = items[0]
    assert "url" in first and "pubdate" in first and "kind" in first
    assert first["url"].startswith("https://v2.samehadaku.how/")

def test_kind_inference_episode_and_batch():
    items = parse_feed(FIXTURE.read_text())
    kinds = {i["kind"] for i in items}
    assert "episode" in kinds  # -episode- URLs dominate the feed
    # batch posts may or may not be present; at least episode + valid kinds
    assert kinds <= {"episode", "batch", "post"}
    # an episode URL must classify as episode
    ep = next(i for i in items if "-episode-" in i["url"])
    assert ep["kind"] == "episode"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /home/dwirijal/Projects/dwizzyOS && PYTHONPATH="/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ" /home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m pytest tests/test_feed.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sloane.sources.samehadaku._feed'`

- [ ] **Step 4: Write minimal implementation**

`sources/samehadaku/_feed.py`:
```python
"""Parse samehadaku's WordPress RSS feed (/feed/) into recent posts.

/feed/ is the site's own change-notification primitive: a newest-first list of
recent posts (episode + batch pages ARE posts), each with a pubDate. Polling it
is how the ingest runner learns what changed since last run.

kind is inferred from the post URL slug: '-episode-' -> episode, '/batch/' ->
batch, else post. No anti-bot; same _http client as the rest of samehadaku.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from . import _http


def parse_feed(html: str) -> list[dict]:
    """RSS XML -> [{url, pubdate, kind}]. Empty list on malformed feed."""
    soup = BeautifulSoup(html, "xml")
    out: list[dict] = []
    for item in soup.find_all("item"):
        link = item.find("link")
        pub = item.find("pubDate")
        url = (link.get_text(strip=True) if link else "") or ""
        if not url:
            continue
        if "-episode-" in url:
            kind = "episode"
        elif "/batch/" in url:
            kind = "batch"
        else:
            kind = "post"
        out.append({
            "url": url,
            "pubdate": pub.get_text(strip=True) if pub else "",
            "kind": kind,
        })
    return out


def fetch_feed(cx) -> str:
    """Fetch /feed/ HTML via an existing httpx.Client (caller owns lifecycle)."""
    return cx.get(f"{_http.BASE_URL}/feed/").text


if __name__ == "__main__":
    # Live self-check (project convention — see store/merger.py:204).
    import httpx
    r = httpx.get(f"{_http.BASE_URL}/feed/", headers=_http.HEADERS,
                  timeout=20, follow_redirects=True)
    assert r.status_code == 200, f"feed fetch failed: {r.status_code}"
    items = parse_feed(r.text)
    assert items, "live feed returned no items"
    assert items[0]["kind"] in {"episode", "batch", "post"}
    print(f"samehadaku _feed self-check OK ({len(items)} items, "
          f"first={items[0]['kind']} {items[0]['url'][:50]})")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/dwirijal/Projects/dwizzyOS && PYTHONPATH="/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ" /home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m pytest tests/test_feed.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run the live self-check**

Run: `cd /home/dwirijal/Projects/dwizzyOS && PYTHONPATH="/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ" /home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.sources.samehadaku._feed`
Expected: `samehadaku _feed self-check OK (N items, first=episode https://v2.samehadaku.how/...)`

- [ ] **Step 7: Commit**

```bash
git add sources/samehadaku/_feed.py tests/test_feed.py tests/fixtures/samehadaku_feed.xml
git commit -m "feat(sloane): samehadaku RSS feed parser

parse_feed splits /feed/ into {url,pubdate,kind} items; kind inferred from
URL slug. Foundation for the 2h incremental ingest runner.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: `ingest_state` table + state helpers

**Files:**
- Create: `db/migrations/004_ingest_state.sql`
- Create: `store/state.py`
- Create: `tests/test_state.py`

**Interfaces:**
- Consumes: `shared.config.pg_dsn()` (DSN). `psycopg`.
- Produces:
  - `get_state(dsn, source, key, default=None) -> Any` — read `value` JSONB, decoded; return `default` if row missing.
  - `set_state(dsn, source, key, value) -> None` — UPSERT, replaces `value`.
  - `add_seen(dsn, source, key, new_urls) -> None` — atomic append of `new_urls` (list[str]) to the JSONB array at `key`; dedup handled by callers via set-diff (this fn just persists what it's given, deduping against existing for safety).

- [ ] **Step 1: Write the migration**

`db/migrations/004_ingest_state.sql`:
```sql
-- Runner state. One row per (source, key); value is JSONB.
-- Used by the ingest runner to persist things like seen_feed_urls across
-- stateless cron runs. Survives restarts; DB is the single source of truth
-- (matches raw/canonical/external_ids pattern).
CREATE TABLE IF NOT EXISTS ingest_state (
    source      TEXT        NOT NULL,
    key         TEXT        NOT NULL,
    value       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, key)
);
```

- [ ] **Step 2: Apply the migration to the live DB**

Run:
```bash
cd /home/dwirijal/Projects/dwizzyOS && PYTHONPATH="/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ" /home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python - <<'PY'
from pathlib import Path
from shared.config import pg_dsn
import psycopg
sql = Path("sloane/db/migrations/004_ingest_state.sql").read_text()
with psycopg.connect(pg_dsn()) as conn, conn.cursor() as cur:
    cur.execute(sql)
    conn.commit()
    cur.execute("SELECT count(*) FROM ingest_state")
    print("ingest_state ready, rows:", cur.fetchone()[0])
PY
```
Expected: `ingest_state ready, rows: 0`

- [ ] **Step 3: Write the failing test**

`tests/test_state.py`:
```python
import json
from sloane.store.state import get_state, set_state, add_seen
from shared.config import pg_dsn

DSN = pg_dsn()
S, K = "test-samehadaku", "seen_feed_urls"

def _clear():
    import psycopg
    with psycopg.connect(DSN) as c, c.cursor() as cur:
        cur.execute("DELETE FROM ingest_state WHERE source=%s AND key=%s", (S, K))
        c.commit()

def test_set_get_roundtrip():
    _clear()
    set_state(DSN, S, K, ["a", "b"])
    assert get_state(DSN, S, K, default=[]) == ["a", "b"]
    _clear()

def test_get_default_when_missing():
    _clear()
    assert get_state(DSN, S, K, default=["x"]) == ["x"]
    _clear()

def test_add_seen_appends_and_dedups():
    _clear()
    set_state(DSN, S, K, ["a"])
    add_seen(DSN, S, K, ["a", "b", "c"])
    assert sorted(get_state(DSN, S, K, default=[])) == ["a", "b", "c"]
    # adding existing again does not duplicate
    add_seen(DSN, S, K, ["a"])
    assert sorted(get_state(DSN, S, K, default=[])) == ["a", "b", "c"]
    _clear()
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd /home/dwirijal/Projects/dwizzyOS && PYTHONPATH="/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ" /home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m pytest tests/test_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sloane.store.state'`

- [ ] **Step 5: Write minimal implementation**

`store/state.py`:
```python
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
import json
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
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /home/dwirijal/Projects/dwizzyOS && PYTHONPATH="/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ" /home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m pytest tests/test_state.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Commit**

```bash
git add db/migrations/004_ingest_state.sql store/state.py tests/test_state.py
git commit -m "feat(sloane): ingest_state table + state helpers

ingest_state(source,key,value jsonb) persists runner state across cron
runs (seen_feed_urls etc). get_state/set_state/add_seen over psycopg.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: `ingest_feed` runner (the 2h job)

**Files:**
- Create: `ingest/__init__.py` (empty)
- Create: `ingest/samehadaku.py`
- Create: `tests/test_ingest.py`

**Interfaces:**
- Consumes:
  - `sources/samehadaku/_feed.py` → `parse_feed(html)`, `fetch_feed(cx)`.
  - `sources/samehadaku/_downloads.py` → `parse_downloads(html)`, `slug_and_ep(url) -> (series_slug, ep_num_str|None)`.
  - `sources/samehadaku/_http.py` → `client()`, `BASE_URL`, `HEADERS`.
  - `store/state.py` → `get_state`, `add_seen`.
  - `db/writer.py` → `write_entities(dsn, entities) -> WriteResult` (has `.raw_ids`).
  - `shared.schema_contract.py` → `CanonicalEntity`, `KIND_ANIME`.
  - `store/merger.py` → `merge_raw_to_canonical(raw_id, title, kind, payload, registry_ids=None, dsn=None)`.
  - `store/enricher.py` → `enrich_canonical(canonical_id, title, kind, dsn=None)`.
  - `shared.config.py` → `pg_dsn()`.
- Produces:
  - `ingest_feed(dsn=None, max_new=None) -> dict` returning `{"fetched": int, "ingested": int, "skipped": int, "new_urls": list[str]}`.
  - `load_series_payload(dsn, slug) -> dict | None` — SELECT existing `payload` for `(source='samehadaku', external_id=slug)`; None if absent.
  - `patch_series(dsn, slug, title, url, payload) -> int` — build `CanonicalEntity`, UPSERT via `write_entities`, return raw_id.

- [ ] **Step 1: Write the failing test**

`tests/test_ingest.py`:
```python
from unittest.mock import patch, MagicMock
from sloane.ingest.samehadaku import ingest_feed, patch_series, load_series_payload

# Captured feed HTML: 2 episode posts for a known series.
FEED_HTML = """<?xml version="1.0"?>
<rss><channel>
<item><link>https://v2.samehadaku.how/one-piece-episode-9999/</link><pubDate>Mon, 30 Jun 2026</pubDate></item>
<item><link>https://v2.samehadaku.how/one-piece-episode-9998/</link><pubDate>Sun, 29 Jun 2026</pubDate></item>
</channel></rss>"""

EP_PAGE_HTML = '<div class="download-eps"><ul><li><strong>720p</strong>' \
    '<span><a href="https://pixeldrain.com/u/x">Pixeldrain</a></span></li></ul></div>'

DSN = "postgresql://test:test@localhost/test"  # mocked; no real connect

def _mock_client():
    cx = MagicMock()
    # fetch_feed calls cx.get("/feed/").text; patch_series fetches post pages.
    feed_resp = MagicMock(); feed_resp.text = FEED_HTML
    ep_resp = MagicMock(); ep_resp.text = EP_PAGE_HTML
    # /feed/ first, then episode pages.
    cx.get.side_effect = [feed_resp, ep_resp, ep_resp]
    return cx

def test_ingest_feed_deltas_and_ingests(monkeypatch):
    # seen already has ep-9998 -> only ep-9999 is new.
    monkeypatch.setattr("sloane.store.state.get_state", lambda *a, default=None, **k: ["https://v2.samehadaku.how/one-piece-episode-9998/"])
    calls = {"add_seen": []}
    monkeypatch.setattr("sloane.store.state.add_seen", lambda d, s, k, urls: calls["add_seen"].extend(urls))
    monkeypatch.setattr("sloane.ingest.samehadaku._http.client", _mock_client)
    # existing series payload has no episodes yet.
    monkeypatch.setattr("sloane.ingest.samehadaku.load_series_payload", lambda d, s: {"title": "One Piece", "episodes": [], "batches": []})
    patched = {}
    monkeypatch.setattr("sloane.ingest.samehadaku.patch_series", lambda d, slug, title, url, p: patched.update(slug=slug, payload=p) or 1)
    monkeypatch.setattr("sloane.store.merger.merge_raw_to_canonical", lambda *a, **k: {"canonical_id": 1})
    monkeypatch.setattr("sloane.store.enricher.enrich_canonical", lambda *a, **k: {})

    r = ingest_feed(dsn=DSN)
    assert r["ingested"] == 1, r
    assert "one-piece-episode-9999" in calls["add_seen"][0]
    # the new episode was appended to payload.episodes
    assert any(e["url"].endswith("episode-9999/") for e in patched["payload"]["episodes"])

def test_ingest_feed_idempotent_re_run(monkeypatch):
    # both eps already seen -> ingested 0, no patch calls.
    seen = ["https://v2.samehadaku.how/one-piece-episode-9999/",
            "https://v2.samehadaku.how/one-piece-episode-9998/"]
    monkeypatch.setattr("sloane.store.state.get_state", lambda *a, default=None, **k: seen)
    add = []; monkeypatch.setattr("sloane.store.state.add_seen", lambda *a, **k: add.append(1))
    monkeypatch.setattr("sloane.ingest.samehadaku._http.client", _mock_client)
    monkeypatch.setattr("sloane.ingest.samehadaku.patch_series", MagicMock())
    r = ingest_feed(dsn=DSN)
    assert r["ingested"] == 0
    assert add == []  # nothing new, no seen update
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/dwirijal/Projects/dwizzyOS && PYTHONPATH="/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ" /home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m pytest tests/test_ingest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sloane.ingest'`

- [ ] **Step 3: Write minimal implementation**

`ingest/__init__.py`: (empty file)

`ingest/samehadaku.py`:
```python
"""samehadaku incremental ingest runner.

2h job (ingest_feed): fetch /feed/, delta new post URLs vs ingest_state, fetch
only new post pages, parse downloads, and load-mutate-upsert the parent series
raw_entities row (write_entities replaces payload wholesale, so we SELECT the
existing payload, append the new episode/batch, UPSERT the full entity). Then
merge_raw + enrich. State in DB; runner otherwise stateless.

daily job (discover_new_series): anime-terbaru -> slugs absent from raw_entities
-> full series fetch -> write_entities -> merge -> enrich.

No concurrency, no per-post transactions. Idempotency (write_entities ON
CONFLICT + merge_raw ON CONFLICT) protects a mid-run crash: redundant work at
worst, never duplicate data.
"""
from __future__ import annotations
import json
from typing import Any

import psycopg

from shared.config import pg_dsn
from shared.schema_contract import CanonicalEntity, KIND_ANIME
from sloane.db.writer import write_entities
from sloane.store.merger import merge_raw_to_canonical
from sloane.store.enricher import enrich_canonical
from sloane.store.state import get_state, add_seen
from sloane.sources.samehadaku import _downloads, _feed, _http, _lists

SOURCE = "samehadaku"
SEEN_KEY = "seen_feed_urls"


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


def _patch_episode_into(payload: dict, post_url: str, downloads: list[dict]) -> None:
    """Append {episode_number,url,downloads} to payload['episodes'], dedup by url."""
    eps = payload.setdefault("episodes", [])
    series_slug, ep_num = _downloads.slug_and_ep(post_url)
    # dedup: drop any existing entry with this exact url
    eps[:] = [e for e in eps if e.get("url") != post_url]
    eps.append({
        "episode_number": float(ep_num) if ep_num else None,
        "url": post_url,
        "downloads": downloads,
    })
    eps.sort(key=lambda e: e.get("episode_number") or 0, reverse=True)


def _patch_batch_into(payload: dict, post_url: str, downloads: list[dict]) -> None:
    """Append {slug,url,downloads} to payload['batches'], dedup by url."""
    bts = payload.setdefault("batches", [])
    series_slug, _ = _downloads.slug_and_ep(post_url)
    bts[:] = [b for b in bts if b.get("url") != post_url]
    bts.append({"slug": series_slug, "url": post_url, "downloads": downloads})


def ingest_feed(dsn: str | None = None, max_new: int | None = None) -> dict:
    """2h job: feed-delta ingest of new episode/batch posts.

    Returns {fetched, ingested, skipped, new_urls}.
    """
    dsn = dsn or pg_dsn()
    seen = set(get_state(dsn, SOURCE, SEEN_KEY, default=[]) or [])
    ingested = skipped = 0
    new_urls: list[str] = []

    with _http.client() as cx:
        feed_html = _feed.fetch_feed(cx)
        items = _feed.parse_feed(feed_html)
        new = [it for it in items if it["url"] not in seen]
        if max_new is not None:
            new = new[:max_new]

        for post in new:
            post_url = post["url"]
            try:
                page_html = cx.get(post_url).text
                downloads = _downloads.parse_downloads(page_html)
            except Exception:
                skipped += 1
                new_urls.append(post_url)  # mark seen even on failure (dead link)
                continue

            series_slug, _ = _downloads.slug_and_ep(post_url)
            series_url = f"{_http.BASE_URL}/anime/{series_slug}/"
            existing = load_series_payload(dsn, series_slug)
            if existing is None:
                # series not yet in DB (discover job will add it); skip for now.
                skipped += 1
                new_urls.append(post_url)
                continue
            title = existing.get("title") or series_slug
            payload = {k: v for k, v in existing.items() if k != "title"}
            if post["kind"] == "batch":
                _patch_batch_into(payload, post_url, downloads)
            else:
                _patch_episode_into(payload, post_url, downloads)

            raw_id = patch_series(dsn, series_slug, title, series_url, payload)
            merge_raw_to_canonical(raw_id, title, KIND_ANIME, payload, dsn=dsn)
            # No enrich here: the feed job only patches episodes/batches into an
            # existing series whose canonical + mal_id are already resolved (the
            # discover job does enrich when it first creates the series). MAL id
            # does not change because an episode was added.
            ingested += 1
            new_urls.append(post_url)

    if new_urls:
        add_seen(dsn, SOURCE, SEEN_KEY, new_urls)

    return {"fetched": len(items), "ingested": ingested, "skipped": skipped,
            "new_urls": new_urls}


def discover_new_series(dsn: str | None = None, max_new: int | None = None) -> dict:
    """daily job: anime-terbaru -> slugs absent from raw_entities -> full fetch."""
    dsn = dsn or pg_dsn()
    discovered = ingested = 0
    with _http.client() as cx:
        html = cx.get(f"{_http.BASE_URL}/anime-terbaru/").text
        series = _lists.parse_series_list(html)
        if max_new is not None:
            series = series[:max_new]
        for item in series:
            slug = item["slug"]
            if load_series_payload(dsn, slug) is not None:
                continue  # already in DB
            discovered += 1
            try:
                detail = cx.get(f"{_http.BASE_URL}/anime/{slug}/").text
                # reuse the source's detail parser + a minimal episode fetch
                from sloane.sources.samehadaku._detail import parse_series
                data = parse_series(detail, base=_http.BASE_URL)
                payload = {"cover_url": item["cover_url"], "synopsis": data["synopsis"],
                           "genres": data["genres"], "japanese": data["japanese"],
                           "english": data["english"], "alt_title": data["alt_title"],
                           "status": data["status"], "type": data["type"],
                           "studio": data["studio"], "season": data["season"],
                           "released": data["released"], "total_episode": data["total_episode"],
                           "duration": data["duration"], "rating": data["rating"],
                           "source": data["source"], "producers": data["producers"],
                           "episodes": [], "batches": []}
                raw_id = patch_series(dsn, slug, item["title"],
                                      f"{_http.BASE_URL}/anime/{slug}/", payload)
                mr = merge_raw_to_canonical(raw_id, item["title"], KIND_ANIME, payload, dsn=dsn)
                enrich_canonical(mr["canonical_id"], item["title"], KIND_ANIME, dsn=dsn)
                ingested += 1
            except Exception:
                continue
    return {"discovered": discovered, "ingested": ingested}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/dwirijal/Projects/dwizzyOS && PYTHONPATH="/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ" /home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m pytest tests/test_ingest.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add ingest/__init__.py ingest/samehadaku.py tests/test_ingest.py
git commit -m "feat(sloane): samehadaku feed-delta ingest runner

ingest_feed: 2h RSS-feed-delta ingest (load-mutate-upsert series payload).
discover_new_series: daily new-series sweep. Idempotent via write_entities
ON CONFLICT + merge_raw ON CONFLICT.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: CLI entry (`__main__.py`)

**Files:**
- Create: `ingest/__main__.py`

**Interfaces:**
- Consumes: `ingest.samehadaku.ingest_feed`, `ingest.samehadaku.discover_new_series`.
- Produces: runnable as `python -m sloane.ingest samehadaku [--discover] [--max-new N]`.

- [ ] **Step 1: Write the CLI**

`ingest/__main__.py`:
```python
"""CLI entry for sloane ingest runners.

Usage:
  python -m sloane.ingest samehadaku              # 2h feed-delta ingest
  python -m sloane.ingest samehadaku --discover   # daily new-series sweep
  python -m sloane.ingest samehadaku --max-new 5  # smoke cap

Prints JSON result to stdout (journald captures it under systemd).
"""
from __future__ import annotations
import argparse
import json
import sys

from sloane.ingest.samehadaku import ingest_feed, discover_new_series


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sloane-ingest")
    p.add_argument("source", choices=["samehadaku"])
    p.add_argument("--discover", action="store_true", help="run new-series discovery instead of feed ingest")
    p.add_argument("--max-new", type=int, default=None, help="cap new items ingested (smoke)")
    args = p.parse_args(argv)

    if args.source == "samehadaku":
        if args.discover:
            result = discover_new_series(max_new=args.max_new)
        else:
            result = ingest_feed(max_new=args.max_new)
    else:
        p.error(f"unknown source {args.source}")
        return 2

    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify the CLI parses (dry run, no DB)**

Run: `cd /home/dwirijal/Projects/dwizzyOS && PYTHONPATH="/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ" /home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest --help`
Expected: help text listing `samehadaku`, `--discover`, `--max-new`.

- [ ] **Step 3: Commit**

```bash
git add ingest/__main__.py
git commit -m "feat(sloane): ingest CLI entrypoint

python -m sloane.ingest samehadaku [--discover] [--max-new N]. Prints JSON
result for journald.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: systemd user units

**Files:**
- Create: `deploy/sloane-samehadaku-ingest.service`
- Create: `deploy/sloane-samehadaku-ingest.timer`
- Create: `deploy/sloane-samehadaku-discover.service`
- Create: `deploy/sloane-samehadaku-discover.timer`

**Interfaces:**
- Consumes: the `python -m sloane.ingest samehadaku` / `--discover` commands from Task 4.

- [ ] **Step 1: Write the four unit files**

`deploy/sloane-samehadaku-ingest.service`:
```ini
[Unit]
Description=sloane samehadaku 2h feed-delta ingest
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=dwizzy
WorkingDirectory=/home/dwirijal/Projects/dwizzyOS/sloane
Environment=PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ
Environment=DOS_SECRET_DIR=/home/dwizzy/dwizzyOS/Gebelin/.secrets
# ROUTER_API_KEY read from a systemd environment file if LLM enrich is needed:
# EnvironmentFile=-%h/.config/sloane/ingest.env
ExecStart=/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest samehadaku
```

`deploy/sloane-samehadaku-ingest.timer`:
```ini
[Unit]
Description=Run sloane samehadaku ingest every 2h

[Timer]
OnCalendar=*-*-* 00/2:00:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

`deploy/sloane-samehadaku-discover.service`:
```ini
[Unit]
Description=sloane samehadaku daily new-series discovery
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=dwizzy
WorkingDirectory=/home/dwirijal/Projects/dwizzyOS/sloane
Environment=PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ
Environment=DOS_SECRET_DIR=/home/dwizzy/dwizzyOS/Gebelin/.secrets
ExecStart=/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest samehadaku --discover
```

`deploy/sloane-samehadaku-discover.timer`:
```ini
[Unit]
Description=Run sloane samehadaku discovery daily

[Timer]
OnCalendar=*-*-* 05:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

- [ ] **Step 2: Document install (no auto-copy — user installs into user units)**

Append to `deploy/README.md` (create if absent):
```markdown
# sloane deploy units

Copy to user systemd units and enable:

    mkdir -p ~/.config/systemd/user
    cp deploy/sloane-samehadaku-*.service deploy/sloane-samehadaku-*.timer ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now sloane-samehadaku-ingest.timer
    systemctl --user enable --now sloane-samehadaku-discover.timer

Check: `systemctl --user list-timers | grep samehadaku`
Logs: `journalctl --user -u sloane-samehadaku-ingest.service -f`
```

- [ ] **Step 3: Validate unit syntax (offline)**

Run: `systemd-analyze verify deploy/sloane-samehadaku-ingest.service deploy/sloane-samehadaku-ingest.timer deploy/sloane-samehadaku-discover.service deploy/sloane-samehadaku-discover.timer 2>&1 | head`
Expected: no errors (empty or only `Ignored` lines for the ExecStart path under a non- systemd-analyze context — any real syntax error like a bad key would surface here).

- [ ] **Step 4: Commit**

```bash
git add deploy/
git commit -m "feat(sloane): systemd user units for samehadaku ingest

2h feed-delta timer + daily discover timer. User units (no root). Install
doc in deploy/README.md.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Integration smoke (live, end-to-end)

**Files:**
- No new files. Runs the built runner against the real site + DB.

- [ ] **Step 1: Confirm the migration + tables exist**

Run: `cd /home/dwirijal/Projects/dwizzyOS && PYTHONPATH="/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ" /home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -c "import psycopg; from shared.config import pg_dsn; c=psycopg.connect(pg_dsn()); cur=c.cursor(); cur.execute('select count(*) from ingest_state'); print('ingest_state rows', cur.fetchone()[0]); cur.execute(\"select count(*) from raw_entities where source='samehadaku'\"); print('samehadaku raw rows', cur.fetchone()[0])"`
Expected: both counts print (ingest_state likely 0, samehadaku raw likely 0 if never ingested).

- [ ] **Step 2: Run a capped feed ingest**

Run: `cd /home/dwirijal/Projects/dwizzyOS && PYTHONPATH="/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ" /home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest samehadaku --max-new 1`
Expected: JSON like `{"fetched": 14, "ingested": 0, "skipped": 1, "new_urls": ["..."]}` — `ingested:0` if the series isn't in DB yet (expected on first run; discover adds it). `skipped:1` means the runner saw a new post but had no series row → correct behavior.

- [ ] **Step 3: Run discover to seed a series**

Run: `cd /home/dwirijal/Projects/dwizzyOS && PYTHONPATH="/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ" /home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest samehadaku --discover --max-new 1`
Expected: `{"discovered": 1, "ingested": 1}` — one new series written to `raw_entities`.

- [ ] **Step 4: Re-run feed ingest — now the series exists**

Run: `cd /home/dwirijal/Projects/dwizzyOS && PYTHONPATH="/home/dwirijal/Projects/dwizzyOS/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ" /home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest samehadaku --max-new 1`
Expected: this time `ingested >= 1` (if a feed post's series slug matches the discovered series) OR `ingested:0` if the feed's first post belongs to a different series than the one discovered. Either is correct behavior. Verify the `seen_feed_urls` row grew:
```bash
cd /home/dwirijal/Projects/dwizzyOS && PYTHONPATH="/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ" /home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -c "from sloane.store.state import get_state; from shared.config import pg_dsn; print(get_state(pg_dsn(),'samehadaku','seen_feed_urls',default=[]))"
```
Expected: a non-empty list of URLs.

- [ ] **Step 5: Re-run feed ingest — idempotency**

Run the Step 4 ingest command again.
Expected: `{"fetched": 14, "ingested": 0, "skipped": 0, "new_urls": []}` — nothing new, no seen update. This proves idempotency.

- [ ] **Step 6: No commit (smoke only, no code change)**

If all steps behaved as expected, the feature is verified end-to-end. If a step revealed a bug, fix in the relevant task's file and re-run.
