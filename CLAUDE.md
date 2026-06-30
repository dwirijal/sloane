# sloane

AI agent guidelines for ALL agents (Claude, Cursor, Copilot, GitHub Agents) in this repo.

## Purpose

sloane is a **scraper + data-ingestion service**. It fetches anime sources (currently
samehadaku), parses them into `CanonicalEntity` rows, and merges/enriches them into the
3-layer model (raw → canonical → links) stored in the shared DOS-pg database.

sloane is **NOT an agent orchestrator**. No `agents/` dir, no agent/RBAC code, no
source-plugin/REGISTRY machinery — those were deleted as dead. Adding a new site =
a `sources/<site>/` parser package + an `ingest/<site>.py` runner on the same pattern as
samehadaku, **not** a `.fetch()` source plugin.

## Architecture

- `sources/<site>/` — per-site parsers: `_http` (client+HEADERS), `_lists`, `_detail`,
  `_downloads`, `_feed` (RSS).
- `ingest/<site>.py` + `ingest/__main__.py` — runners. RSS feed-delta (2h), daily
  discovery, concurrent resumable backfill. `python -m sloane.ingest <site>
  [--discover|--backfill] [--workers N] [--max-new N]`.
- `store/` — `merger.py` (raw→canonical: ID-first → title_exact → LLM-fuzzy),
  `enricher.py` (MAL id via Jikan; tier-2 token-overlap + season-suffix guard),
  `state.py` (`ingest_state` table, seen-urls dedup).
- `db/writer.py` — `write_entities` UPSERTs raw.
- `db/migrations/` — `001_canonical`, `003_three_layer`, `004_ingest_state`. (Agent RBAC
  lives in dwizzyOS-HQ, not here.)

## Run environment

```
python:   /home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python
PYTHONPATH: /home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ
DOS_PGB_URL: postgresql://dwizzy:kultivasimusemangatku@localhost:6432/dwizzyos
```

DB is the homeserver pgbouncer (`192.168.100.6`, localhost-only `:6432`), reached via the
`sloane-db-tunnel.service` SSH tunnel. Local Docker `:5432` is **NOT** sloane's DB.

## Tests

No pytest in the venv (no pip either). Run via stdlib harness:

```
.venv-adk/bin/python -c "import importlib,inspect,sys,glob;
p=f=0
import glob
for tf in sorted(glob.glob('sloane/tests/test_*.py')):
    mn='sloane.tests.'+tf.split('/')[-1][:-3]
    for m in list(sys.modules):
        if mn.split('.')[-1] in m: del sys.modules[m]
    mod=importlib.import_module(mn)
    for n,fn in inspect.getmembers(mod,inspect.isfunction):
        if not n.startswith('test_'): continue
        try: fn(); p+=1
        except Exception as e: f+=1; print(f'FAIL {mn}.{n}: {e}')
print(f'{p} passed, {f} failed')"
```

Mock shim: `tests/_monkeypatch.py`. `test_state.py` needs the tunnel + `DOS_PGB_URL` env.

## Deploy

`deploy/` systemd user units:
- `sloane-samehadaku-ingest.timer` — every 2h, feed-delta ingest.
- `sloane-samehadaku-discover.timer` — daily 05:00, new-series sweep.
- `sloane-db-tunnel.service` — persistent SSH tunnel.

See `deploy/README.md`.

## Style

- Ultra-terse. Telegraphic. Code, not essays.
- Conventional Commits: `type(scope): description` (feat/fix/chore/refactor/docs/test).
- stdlib-first. No new dependency for what a few lines can do. Deletion before addition.
- No hardcoded secrets — use env vars. Never commit `.env` / `.pem` / key stores.
- YAGNI extremist: no interface with one impl, no factory for one product, no config for
  a value that never changes. Mark deliberate simplifications with a `ponytail:` comment.
- Non-trivial logic leaves ONE runnable check (assert-based self-check or one small test
  file; no frameworks). Trivial one-liners need no test.
