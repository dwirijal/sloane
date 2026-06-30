# samehadaku Incremental Ingest Runner — Design

**Date:** 2026-06-30
**Status:** Approved (brainstorm → design)
**Supersedes:** schedule-driven + sleep-loop daemon (dropped — see "Why not schedule-driven")

## Context

sloane is a scraper. The `samehadaku` parser package (added 2026-06-29) emits one
`CanonicalEntity` per anime series, with episodes + batches parsed into `payload`.
Currently there is no runner: only `db/writer.write_entities`, `store/merger.merge_raw_to_canonical`,
and `store/enricher.enrich_canonical` exist as functions, plus `__main__` self-checks.

The user needs four update flows:
1. **Episode baru** — ongoing anime drop new episodes (delayed uploads common).
2. **Season baru** — new series/season appear in `anime-terbaru`.
3. **Batch baru** — batch posts appear.
4. **Jadwal rilis** — weekly release schedule (used only as metadata, not as a trigger).

## Why RSS + cron (the recommendation that won)

samehadaku is WordPress. `/feed/` is the site's own change-notification primitive:
a timestamped, newest-first list of recent posts (episode + batch pages are posts).
Polling the feed is the site *telling us* what changed — cheaper (1 small page),
exact (one `pubDate` per post), and authoritative. Inferring from `jadwal-rilis`
weekday maps + grace windows is us guessing; the feed is the ground truth.

Cron (systemd timer) beats a sleep-loop daemon because a 2-hour poll has no
resident state worth keeping: each run is fetch feed → delta → ingest → exit.
No process supervision, no in-memory timing logic, no memory leaks. systemd
(on this CachyOS/Arch host) gives restart-on-crash, boot-start, and journald
logging for free.

## Architecture

```
systemd timer (every 2h)  ─►  sloane ingest samehadaku
                                   │
                                   ▼
   ┌─ runner: sloane/ingest/samehadaku.py ──────────────────────┐
   │                                                              │
   │  1. FETCH FEED   GET /feed/ → parse → [{url, pubdate, kind}] │
   │     (kind = episode | batch, inferred from URL slug)         │
   │                                                              │
   │  2. DELTA        seen = ingest_state(seen_feed_urls)         │
   │     new = feed − seen.  Empty → exit (nothing changed).      │
   │                                                              │
   │  3. INGEST       per new post:                               │
   │       _downloads.parse(post_url) → downloads                │
   │       series_slug = _downloads.slug_and_ep(url)[0]          │
   │       LOAD existing raw_entities row (series payload),       │
   │       MUTATE payload.episodes/.batches (append new),         │
   │       UPSERT full entity via write_entities (idempotent)     │
   │       → merge_raw → enrich                                   │
   │                                                              │
   │  4. REMEMBER     append new urls → ingest_state              │
   └──────────────────────────────────────────────────────────────┘

   daily sweep (separate systemd timer, 05:00)  ─►  sloane ingest samehadaku --discover
       anime-terbaru → _lists.parse_series_list → slugs absent from raw_entities
       → full fetch (series detail + latest episodes) → write_entities → merge → enrich
```

## Components

### `sources/samehadaku/_feed.py` (new)
Parse `/feed/` XML → `[{url, pubdate, kind}]`.
- `kind` inferred from URL: `-episode-` → `"episode"`, `/batch/` → `"batch"`, else `"post"`.
- WordPress `/feed/` defaults to 10 items; samehadaku releases < 10 posts per 2h window.
- Uses the existing `_http` client (same browser UA, no anti-bot).

### `db/migrations/004_ingest_state.sql` (new)
```sql
CREATE TABLE IF NOT EXISTS ingest_state (
    source      TEXT        NOT NULL,
    key         TEXT        NOT NULL,
    value       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, key)
);
```
One row per (source, key). `samehadaku` + `seen_feed_urls` → JSONB array of post URLs.
Survives runner restarts; DB is the single source of truth (matches raw/canonical/external_ids pattern).

### `store/state.py` (new)
Thin helpers over `ingest_state`:
- `get_state(dsn, source, key, default) -> Any` — read JSONB value.
- `set_state(dsn, source, key, value) -> None` — UPSERT value (replaces).
- `add_seen(dsn, source, key, new_urls) -> None` — atomic append to a JSONB array,
  dedup preserved by the ingest delta logic in Python (set difference).

`ponytail: if seen_feed_urls grows past ~10k, swap JSONB array for a dedicated
seen_urls table. At 2h cadence + <10 posts/run, this won't happen for years.`

### `ingest/samehadaku.py` (new — the runner)
Two entry points, both write through the existing `db/writer` + `store/merger` + `store/enricher`:

**`ingest_feed(dsn, max_new=None) -> dict`** — the 2h job:
1. Fetch `/feed/`, parse via `_feed.parse`.
2. `seen = get_state(dsn, "samehadaku", "seen_feed_urls", [])`
3. `new = [p for p in feed if p.url not in seen]`
4. If `max_new`: cap `new` (smoke ceiling for first runs).
5. For each new post: fetch post page, `_downloads.parse`, resolve series slug,
   **load the series' existing `raw_entities` row** (SELECT payload), **mutate**:
   append `{episode_number, url, downloads}` to `payload.episodes` (or to
   `payload.batches` for batch posts), dedup by episode URL, then **UPSERT the
   full entity** via `write_entities` (the writer replaces payload wholesale —
   load-mutate-upsert, not a per-field SQL patch). Then `merge_raw_to_canonical`
   + `enrich_canonical`.
6. `add_seen(dsn, "samehadaku", "seen_feed_urls", [p.url for p in new])`
7. Return `{fetched, ingested, skipped, new_urls}`.

**`discover_new_series(dsn, max_new=None) -> dict`** — the daily `--discover` job:
1. Fetch `anime-terbaru`, `_lists.parse_series_list`.
2. Filter to slugs whose `(source='samehadaku', external_id=slug)` is absent in `raw_entities`.
3. For each: full series fetch via `SamehadakuSource`-style flow (reuse the source's
   `_detail` + `_downloads`), `write_entities` → `merge_raw` → `enrich`.
4. Return `{discovered, ingested}`.

### `ingest/__main__.py` (new — CLI entry)
```
sloane-ingest samehadaku              # → ingest_feed (2h job)
sloane-ingest samehadaku --discover   # → discover_new_series (daily job)
sloane-ingest samehadaku --max-new 5  # smoke cap
```
Console-script entry point in `pyproject.toml` (or plain `python -m sloane.ingest`).
Prints the result dict as JSON to stdout (journald captures it).

### `deploy/sloane-samehadaku-ingest.{service,timer}` (new)
- `sloane-samehadaku-ingest.timer`: `OnCalendar=*-*-* 00/2:00:00` (every 2h), `Persistent=true`.
- `sloane-samehadaku-ingest.service`: `ExecStart=sloane-ingest samehadaku`, `User=dwizzy`,
  env for `DOS_SECRET_DIR` / `ROUTER_API_KEY` from the systemd unit's environment.
- `sloane-samehadaku-discover.timer`: `OnCalendar=daily` (05:00), separate service running `--discover`.
- Units are templates the user copies to `~/.config/systemd/user/` (user units — no root).

## Data flow

```
/feed/  ──► _feed.parse ──► delta vs ingest_state
                                 │ (new posts only)
                                 ▼
              _downloads.parse ─► patch raw_entities.payload (UPSERT)
                                 │
                                 ▼
                   merge_raw_to_canonical ──► canonical_entities + external_ids
                                 │
                                 ▼
                          enrich_canonical (Jikan mal_id)
```

No new entity kind. Series stay one `CanonicalEntity` (kind=anime). Episodes + batches
remain in `payload`. The 3-layer model + merger are untouched.

## Restart resilience

Every run reads `ingest_state` from DB on start, writes on finish. A crash mid-run
means some new posts were ingested but not marked seen — the next run re-processes
them. `write_entities` UPSERT is idempotent (`ON CONFLICT (source, external_id)`),
`merge_raw` links idempotently (`ON CONFLICT (canonical_id, raw_id)`), and
`enrich_canonical` is idempotent. So a mid-run crash costs only redundant work,
never duplicate data. The `seen_feed_urls` append happens *after* successful ingest
of each batch, so a crash before append = re-do (safe); a crash after = done (correct).

`ponytail: for true per-post atomicity, wrap each post's (patch + add_seen) in one
DB transaction. Defer until cadence proves it matters — idempotency already protects.`

## Error handling

- Feed fetch fails (network/5xx) → runner exits non-zero; systemd retries next tick.
  No partial `seen` update (we only append seen after a successful ingest batch).
- A post page 404s (deleted between feed and fetch) → skip that post, log, mark seen
  (don't retry a dead URL forever).
- `merge_raw` / `enrich` exceptions → caught per-post, logged; that post skipped but
  others proceed. One bad episode doesn't abort the batch.
- LLM/router down → `merge_raw` falls back to title_exact + created (merger.py already
  returns False on error). Enrich skips. Ingest continues; canonicals still written.

## Testing

- `_feed.parse`: assert parse of a captured `/feed/` XML fixture returns ≥1 item with
  url + pubdate + kind; assert kind inference (`-episode-`→episode, `/batch/`→batch).
- `store/state`: round-trip get/set/add_seen against a temp/throwaway DSN; assert
  dedup on add_seen.
- `ingest_feed`: mock the `_http` client + `_downloads.parse`, assert delta logic
  (only unseen posts ingested), assert idempotency (re-run ingests 0 new).
- `discover_new_series`: assert slugs already in `raw_entities` are skipped.
- Live self-check (`if __name__ == "__main__"` in `_feed.py`, matching `_downloads.py`
  convention): fetch real `/feed/`, assert ≥1 item.
- Integration smoke: run `ingest samehadaku --max-new 1` against the real DB +
  site; assert one `raw_entities` row patched, `seen_feed_urls` grew.

## Why not schedule-driven (dropped design)

Original brainstorm picked: jadwal-rilis weekday map + daily tick for due anime +
pending/retry queue + grace window for delayed uploads + sleep-loop daemon.
That re-implements (badly) what `/feed/` gives for free. RSS is the site's own
"what's new" signal; the schedule is a *plan*, the feed is *reality*. Delayed
uploads need no special handling under RSS — the post appears in the feed when
uploaded, whenever that is. One 2h poll + a `seen` set replaces weekday maps,
grace windows, retry queues, and a resident daemon. YAGNI applied hard.

## Skipped (add when)

- **Concurrency** (`asyncio.gather` over new posts) — add when a single 2h run's
  new-post count makes sequential fetch slow; <10/run makes it pointless now.
- **Per-post transactional ingest** — add if mid-run crashes cause visible
  redundant re-work at scale; idempotency makes this a perf concern, not correctness.
- **Other sources** — add when needed as `sources/<site>/` + `ingest/<site>.py`
  runners on this same pattern. The old source-plugin/REGISTRY machinery was deleted
  as dead code; sloane is scraper + ingestion, not an agent orchestrator.
- **`daftar-anime-2` full-directory pagination** — add for historical backfill;
  `anime-terbaru` covers fresh series discovery for the daily sweep.
- **Feed pagination** (`/feed/?paged=2`) — add only if samehadaku ever exceeds
  10 posts per 2h window (it won't); the daily `--discover` sweep is the
  belt-and-suspenders recovery for anything aged off `/feed/`.
