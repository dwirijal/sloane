# anichin Incremental Ingest Runner — Design

**Date:** 2026-06-30
**Status:** Approved (brainstorm → design)
**Supersedes:** none (new source)

## Context

sloane is a scraper. anichin.moe is a **donghua (Chinese anime) streaming-only** site:
WordPress, but with the RSS feed disabled (`/feed/` returns 500 "No feed available").
Content is sub-Indo donghua with high episode volume (Martial Master = 670+ eps,
Against the Sky Supreme = 527+ eps). Episodes are **streaming-only** (Dailymotion
iframe); there are **no download host links** on episode pages.

This differs from samehadaku (which has a working RSS feed + download-host links) in
two load-bearing ways:
1. **No RSS** → delta cannot be feed-delta. "New" = episode-number increased per series.
2. **Streaming, not downloads** → store the stream iframe `src`, not download-host links.

The user wants: store series + episodes (number + ep-page URL + stream_url), merge
into canonical, enrich MAL id. Delta via latest-updated list poll. Cadence = 2h ingest
+ daily discover (parity with samehadaku timers).

## Site map (verified live 2026-06-30)

```
https://anichin.moe
├── /                                          # home (latest eps grid)
├── /anime/?status=&type=&order=update&page=N  # latest-updated series list (30/pg, body after stripping sidebar .subSchh)
├── /az-lists/?show=A..Z&page=N                # full A-Z directory (series body = root /{slug}/ anchors w/ title attr)
├── /anime/{slug}/                             # series detail: h1 title, .wp-post-image cover, .entry-content synopsis, .infox meta, ~748 ep anchors
└── /{slug}-episode-{NNN}-subtitle-indonesia/  # episode page: h1, Dailymotion iframe (stream src), NO download links
```

Key parsing facts (verified):
- `/anime/?order=update` body lists 30 series/page; **strip `.subSchh` sidebar first** (it appears on every page, 6 latest series).
- A-Z directory body uses **root-slug anchors** `<a href="/{slug}/" title="...">`, NOT `/anime/{slug}/` anchors (those are sidebar).
- Episode URL pattern: `/{slug}-episode-{NNN}-subtitle-indonesia/`. Slug + ep number extractable via regex.
- Episode page: Dailymotion iframe `iframe[src*="dailymotion"]`; no download block in body (only in JSON-LD meta description).
- Browser UA is sufficient (no Cloudflare/JS gating observed).

## Architecture

```
sources/anichin/
  _http.py      — BASE_URL, HEADERS (browser UA), client() [mirrors sources/samehadaku/_http.py]
  _lists.py     — parse_update_list(html) -> [{slug, title}]    # /anime/?order=update body (sidebar stripped)
                  walk_directory(cx) -> [{slug, title}]         # /az-lists/?show=0-9,A..Z paginated (backfill seed)
  _detail.py    — parse_detail(html) -> {slug, title, cover_url, synopsis, infox: {type, status, score}, episodes: [{n, url}]}
  _episodes.py  — parse_episode(html) -> {n, stream_url}        # Dailymotion iframe src

ingest/anichin.py + ingest/__main__.py
  ingest_updates(dsn, max_new=None) -> dict      # 2h job: poll update list, diff ep-numbers, fetch new ep pages
  discover_new_series(dsn, max_new=None) -> dict # daily job: A-Z walk, new slugs only, series row + ep list (no stream_url)
  backfill(dsn, workers=6, max_new=None) -> dict # concurrent A-Z walk + full detail + all ep pages (stream_url for every ep), resumable
```

Source name: `"anichin"`. One process per source. Same 3-layer model
(raw → canonical → links) and same `write_entities` / `merge_raw_to_canonical` /
`enrich_canonical` as samehadaku. `CanonicalEntity.kind = KIND_ANIME`.

`payload` shape:
```jsonc
{
  "cover_url": "...",
  "synopsis": "...",
  "infox": {
    "type": "Donghua",
    "status": "Ongoing",
    "studio": "Ruo Hong Culture",
    "season": "Spring 2020",
    "released": "Mar 08, 2020",
    "duration": "7 min per. ep",
    "country": "China",
    "genres": ["Action", "Fantasy", "Martial Arts", "Reincarnation"]
  },
  "episodes": [{"n": 670, "url": "/martial-master-episode-670-subtitle-indonesia/", "stream_url": "https://geo.dailymotion.com/..."}]
}
```

## Components

### `_lists.parse_update_list(html) -> [{slug, title}]`
Strip sidebar `.subSchh`. Select `<a href^="/">` with non-empty `title` attr matching
`^/[a-z0-9-]+/$` (root-slug anchors). Dedup by slug. ~30/page.

### `_lists.walk_directory(cx) -> [{slug, title}]`
Loop `show` over `["0-9", "A", ..., "Z"]`. For each, paginate
`/az-lists/page/N/?show=X` (N=1..) until a page returns zero root-slug anchors.
Root-slug anchor pattern (same as `parse_update_list`). ~700 series total.

### `_detail.parse_detail(html) -> dict`
- `title`: `h1.entry-title` (or first `h1`) stripped.
- `cover_url`: `img.wp-post-image` (or `[itemprop=image] img`) `src`.
- `synopsis`: `.entry-content` (or `[itemprop=description]`) stripped.
- `infox`: `.infox` block is `<b>Label:</b><span> Value</span>` pairs (verified live).
  Parse label→value by walking the `<b>`/`<span>` siblings. Keep the subset that
  matters for canonical merge/enrich: `Tipe` (type — e.g. "Donghua"), `Status`
  (e.g. "Ongoing"), `Studio`, `Season` (e.g. "Spring 2020"), `Tanggal rilis`
  (release date), `Durasi`, `Negara` (country). Drop `Network/Subber/Episode-count/
  Diposting/Ditambahkan/Diperbarui` (admin/noise; ep count is redundant with the
  episodes list). No "Score" field exists on anichin (do not store one).
- `genres`: trailing unlabeled text after the `<b>`/`<span>` pairs in `.infox`
  (e.g. "Action", "Fantasy", "Martial Arts", "Reincarnation"). Collect as
  `payload.infox.genres: list[str]`.
- `episodes`: select `a[href*="-episode-"]`, extract `n` via
  `-episode-(\d+)-subtitle`, dedup by `n` (keep first/highest-priority URL),
  return `[{n, url}]`. Sorted by `n` ascending. (URL only; `stream_url` filled
  later by `parse_episode` for new eps.)

### `_episodes.parse_episode(html) -> {n, stream_url}`
- `n`: regex `-episode-(\d+)-subtitle` on `h1` (or `<title>`).
- `stream_url`: first `iframe[src*="dailymotion"]` `src`. If none, `stream_url=None`
  (ep row still stored with `n` + `url`).

### `store/state.py` (existing, reused)
`ingest_state` table already exists (migration 004). Keys:
- `("anichin", "backfill_done")` — JSONB slug set (resume backfill).
- Delta does NOT need a seen-set (ep-number diff is the dedup).

## Data flow

### Delta — `ingest_updates(dsn, max_new=None)` (2h systemd timer)
1. Fetch `/anime/?order=update` page 1, `parse_update_list` → `[{slug}]`.
2. For each slug (cap at `max_new` if set):
   a. `SELECT payload FROM raw_entities WHERE source='anichin' AND external_id=slug`.
   b. Fetch `/anime/{slug}/`, `parse_detail` → `detail`, `max_ep = max(detail.episodes[].n)`.
   c. `old_max = max(payload.episodes[].n) or 0` (0 if series not yet in DB — treat as discover).
   d. `new_eps = [ep for ep in detail.episodes if ep.n > old_max]`.
   e. For each ep in `new_eps`: fetch `ep.url`, `parse_episode` → fill `ep.stream_url`.
   f. Mutate `payload.episodes` (append `new_eps`, dedup by `n`), keep sorted by `n`.
   g. `write_entities([CanonicalEntity(...)])` (idempotent UPSERT, replaces `payload` wholesale).
   h. `merge_raw_to_canonical` → `enrich_canonical`.
3. Return `{fetched, updated_series, new_episodes, skipped}`.

### Discover — `discover_new_series(dsn, max_new=None)` (daily 05:00 systemd timer)
1. `walk_directory(cx)` → `[{slug}]`.
2. Filter slugs absent in `raw_entities` (`source='anichin', external_id=slug`).
3. For each new slug: fetch `/anime/{slug}/`, `parse_detail` → upsert series row with
   `episodes: [{n, url}]` (NO `stream_url` — deferred). `merge_raw` → `enrich`.
4. Return `{discovered, ingested}`.

Stream_url deferred on discover because full-eps fetch (748 pages/series) is too heavy
for a daily sweep. Stream_url is filled lazily by `ingest_updates` (new eps only) or by
a dedicated `backfill` pass.

### Backfill — `backfill(dsn, workers=6, max_new=None)` (manual / one-shot)
Concurrent `walk_directory` + full detail + ALL ep pages (stream_url for every ep).
Resumable per-slug via `ingest_state` key `("anichin", "backfill_done")` JSONB slug set.
`asyncio.Semaphore(workers)`, `httpx.AsyncClient` (same pattern as samehadaku backfill).
On resume, skip slugs in the done-set; on success append slug to set.

## Error handling

- **Update-list fetch fails (network/5xx):** runner exits non-zero; systemd retries next
  tick. No partial state written.
- **Detail page 404 (series deleted between list fetch + detail fetch):** skip slug,
  log, continue. Don't retry dead URLs.
- **Ep page 404:** skip ep, log. Series row + other eps still upserted.
- **No Dailymotion iframe on ep page:** `stream_url=None`, ep row still stored (`n`+`url`).
  Streaming may be JS-gated on some pages; don't fail ingest for it.
- **`merge_raw` / `enrich` exception:** caught per-series, logged; series skipped, others
  proceed. LLM/router down → merger falls back to `title_exact` (existing merger behavior);
  enrich skips. Canonical rows still written.
- **Rate-limit / 403:** httpx 429/403 → log and skip. No anti-bot observed yet (browser UA
  sufficient). `ponytail:` add exponential backoff + retry only if 429s appear in production.

## Restart resilience

Every run reads `ingest_state` from DB on start, writes on finish. Crash mid-`ingest_updates`
means some new eps were upserted but the series wasn't fully processed — next run re-diffs
ep-numbers and re-fetches only still-new eps. `write_entities` UPSERT is idempotent
(`ON CONFLICT (source, external_id)`), `merge_raw` links idempotently
(`ON CONFLICT (canonical_id, raw_id)`), `enrich_canonical` idempotent. Mid-run crash costs
only redundant work, never duplicate data.

Backfill resume: crash mid-backfill = done-set not updated for in-progress slug →
re-do that slug (idempotent). Done-set written after each slug's full ep-page fetch.

`ponytail:` per-ep atomicity (wrap each ep's fetch+mutate+upsert in one DB transaction)
deferred until cadence proves it matters — idempotency already protects correctness.

## Testing

Same stdlib harness (no pytest in venv; importlib + `inspect.getmembers`). Mock shim
`tests/_monkeypatch.py`. Fixtures saved from live probes (already in `/tmp/anichin_*.html`):

- `tests/fixtures/anichin_update.html` — `/anime/?order=update` page 1.
- `tests/fixtures/anichin_detail.html` — `/anime/martial-master/`.
- `tests/fixtures/anichin_episode.html` — `/martial-master-episode-670-subtitle-indonesia/`.
- `tests/fixtures/anichin_az.html` — `/az-lists/?show=A` page 1.

Tests:
- `tests/test_anichin_lists.py` — `parse_update_list` returns ≥1 `{slug,title}` and strips
  sidebar; `walk_directory` paginates `show` + `page` (mocked fetch, assert call sequence).
- `tests/test_anichin_detail.py` — `parse_detail` returns title/cover/synopsis/infox +
  episodes `[{n,url}]` deduped by `n`.
- `tests/test_anichin_episodes.py` — `parse_episode` extracts `n` from h1 + Dailymotion
  iframe `stream_url`; returns `stream_url=None` when no iframe.
- `tests/test_anichin_ingest.py` — `ingest_updates` diff: mock DB `old_max=5`, detail gives
  eps 1–10 → assert ep-page fetch count = 5 (only 6–10), not 10. Monkeypatch `_http` +
  `db.writer` + `store.state`.
- `tests/test_state.py` (existing) covers `ingest_state` CRUD; reused as-is.

Integration smoke (manual, not in auto-suite): `python -m sloane.ingest anichin --max-new 1`
against live DB + site; assert one `raw_entities` row patched, new ep appended.

## Why not feed-delta (the dropped design)

samehadaku uses WordPress `/feed/` as its delta primitive. anichin's `/feed/` is disabled
(server returns 500 "No feed available"). The next-best delta primitive is the
`/anime/?order=update` latest-updated list — it tells us *which* series changed, and the
detail page's ep-anchor list tells us *how many* eps exist. Diffing max-ep per listed
series is exact (no inference, no schedule guessing), reuses the load-mutate-upsert +
`ingest_state` pattern, and costs ~30 detail fetches per 2h (negligible). Sidebar scrape
(6 latest eps) was rejected as too lossy for a 700-series catalog.

## Skipped (add when)

- **Stream_url backfill for historical eps** — `ingest_updates` only fills `stream_url`
  for *new* eps; discover stores ep list without `stream_url`. Add a dedicated
  `--backfill-eps` pass (or fold into `backfill`) when DOS needs stream URLs for old eps.
- **Per-ep transactional ingest** — add if mid-run crashes cause visible redundant
  re-work at scale; idempotency makes this a perf concern, not correctness.
- **Retry/backoff on 429/403** — add only if anichin adds anti-bot; browser UA suffices now.
- **A-Z directory cache** — `walk_directory` hits ~28 letter-pages daily; cheap now.
  Add a daily cache if the directory grows past ~2000 series.
