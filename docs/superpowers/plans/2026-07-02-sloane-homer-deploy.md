# sloane Homer-Deploy Plan

## Context

sloane currently runs (when run) from the dev machine, reaching the DB over an SSH tunnel to the homeserver's pgbouncer. The user wants to **push sloane to the homeserver and run it from there** — the DB is local on homer (Docker `DOS-pg`/`DOS-pgb`), so no tunnel is needed, which is cleaner for 24/7 timer operation. Constraint: **only touch the sloane repo** — don't modify dwizzyOS-HQ, `.secrets/`, or docker config.

Recon established:
- Homer has `~/dwizzyOS/.venv-adk` (httpx/bs4/psycopg ✓), `~/dwizzyOS-HQ` (shared/ ✓), Docker `DOS-pg`+`DOS-pgb` (DB local ✓). No tunnel needed.
- Homer's `~/sloane` is an empty 1-commit stub — sloane code must be cloned fresh to `~/dwizzyOS/sloane`.
- The `kultivasimusemangatku` password in CLAUDE.md/deploy units is **stale** — fails SASL auth on homer's `:6432` and `:5432`. The real password is a 32-char docker secret at `/run/secrets/dos_pg_password` inside `DOS-pg` (readable via `docker exec`). It goes into `~/.config/sloane/ingest.env` (out-of-tree, gitignored) — never into the repo.
- Homer's pgbouncer publishes on `192.168.100.6:6432` (not `127.0.0.1`).
- Dev has **no installed sloane timers** (both `inactive`, tunnel unit not found) — so editing the units to be homer-targeted breaks nothing on dev.
- Dev's 14 commits are not on GitHub yet (GitHub HEAD `7175300d` ≠ dev HEAD `1faa4d0`) — must push before homer pulls.

This deploy **supersedes the secret-removal plan** (`2026-07-02-sloane-secret-removal.md`): the unit edits here (remove inline password, required `EnvironmentFile`) accomplish that plan's Task 1 as a side effect, plus path-parameterization and dropping the tunnel dependency. The CLI guard (that plan's Task 2) is included here.

## Approach

Parameterize the 4 ingest/discover `.service` files with `%h`-relative paths (matching homer's `~/dwizzyOS` layout), remove the stale inline `DOS_PGB_URL`, require `EnvironmentFile` (fail-loud if `ingest.env` missing), and drop the `Requires=sloane-db-tunnel.service` (homer's DB is local). Add the `DOS_PGB_URL`-unset guard in `__main__.py` (catches manual runs that bypass the unit's `EnvironmentFile`). Redact the stale password from `CLAUDE.md` + README. Push to GitHub, clone on homer, create `ingest.env` with the real docker-secret password, install + enable timers, smoke-test live.

## File Changes (sloane repo only)

### `deploy/sloane-anichin-ingest.service` + `sloane-samehadaku-ingest.service` (2 ingest units)

Pattern (anichin shown; samehadaku identical except `anichin`→`samehadaku` in `ExecStart` + `Description`):
- `WorkingDirectory=/home/dwirijal/Projects/dwizzyOS/sloane` → `WorkingDirectory=%h/dwizzyOS/sloane`
- `Environment=PYTHONPATH=...Projects/dwizzyOS:...Projects/dwizzyOS/dwizzyOS-HQ` → `Environment=PYTHONPATH=%h/dwizzyOS:%h/dwizzyOS-HQ`
- `ExecStart=/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python ...` → `ExecStart=%h/dwizzyOS/.venv-adk/bin/python ...`
- **Delete** the `Environment=DOS_PGB_URL=postgresql://dwizzy:kultivasimusemangatku@localhost:6432/dwizzyos` line (stale password leaves the repo).
- `EnvironmentFile=-%h/.config/sloane/ingest.env` → `EnvironmentFile=%h/.config/sloane/ingest.env` (drop `-` → required; missing file = systemd start failure).
- `[Unit]`: `After=network-online.target sloane-db-tunnel.service` → `After=network-online.target docker.service`; **delete** `Requires=sloane-db-tunnel.service` (homer DB is local; tunnel is a dev-machine concern). Keep `Wants=network-online.target`.
- Keep `Environment=ROUTER_BASE_URL=http://192.168.100.6:20128/v1` (9router on homer; reachable from homer via its own LAN IP).
- Update the comment block: `DOS_PGB_URL` now lives in `ingest.env`, DB is local Docker (no tunnel).

### `deploy/sloane-anichin-discover.service` + `sloane-samehadaku-discover.service` (2 discover units)

Same pattern (shorter units — no `--discover` flag confusion: discover units already pass `--discover`). Same path/EnvironmentFile/tunnel edits.

### `ingest/__main__.py`

Add `import os`; insert after `args = p.parse_args(argv)` (before dispatch):
```python
# DOS_PGB_URL guard: pg_dsn() silently falls back to a stale default password
# + wrong DB when unset. Fail loud at CLI entry. After parse_args so --help works.
# ponytail: lift to shared/config.py when upstream drops the hardcoded default.
if not os.environ.get("DOS_PGB_URL"):
    sys.stderr.write("DOS_PGB_URL unset; set in ~/.config/sloane/ingest.env\n")
    return 2
```
+ new `tests/test_cli_guard.py` (TDD: asserts exit 2 + stderr when unset; guard absent when set).

### `CLAUDE.md:35`

`DOS_PGB_URL: postgresql://dwizzy:kultivasimusemangatku@localhost:6432/dwizzyos` → `DOS_PGB_URL: postgresql://dwizzy:<DB_PASSWORD>@192.168.100.6:6432/dwizzyos  # set in ~/.config/sloane/ingest.env (not committed)`. Also update the "reached via sloane-db-tunnel.service SSH tunnel" line to note homer runs local (no tunnel).

### `deploy/README.md`

- Prerequisites step 2: extend `ingest.env` creation to include `DOS_PGB_URL` (placeholder) + `ROUTER_API_KEY` + `chmod 600`.
- Manual one-offs (lines 73-83): replace inline `DOS_PGB_URL=...` with `set -a; . ~/.config/sloane/ingest.env; set +a` sourcing.
- "Alternative: run timers on the homeserver" section (85-91): flesh out with the concrete homer steps (clone to `~/dwizzyOS/sloane`, `ingest.env` with `192.168.100.6:6432` + real password, install user units, enable timers). This is now the primary deploy target, not just an alternative.

### `.gitignore`

Append `ingest.env` (defensive — real file is out-of-tree at `~/.config/sloane/`).

## Homer Deploy Steps (after repo edits + push)

1. `git push origin main` from dev (gets the 14 commits to GitHub).
2. On homer (`ssh dwizzy@192.168.100.6`): `rm -rf ~/sloane` (empty stub) → `git clone git@github.com:dwirijal/sloane.git ~/dwizzyOS/sloane` (matches `%h/dwizzyOS/sloane`).
3. Create `~/.config/sloane/ingest.env` on homer — password read from the docker secret, never typed in transcript:
   ```bash
   PW=$(docker exec DOS-pg cat /run/secrets/dos_pg_password)
   printf 'DOS_PGB_URL=postgresql://dwizzy:%s@192.168.100.6:6432/dwizzyos\nROUTER_API_KEY=%s\n' "$PW" "${ROUTER_API_KEY:-}" > ~/.config/sloane/ingest.env
   chmod 600 ~/.config/sloane/ingest.env
   ```
4. Install user units on homer: `cp ~/dwizzyOS/sloane/deploy/sloane-*.service ~/dwizzyOS/sloane/deploy/sloane-*.timer ~/.config/systemd/user/` → `systemctl --user daemon-reload` → `systemctl --user enable --now sloane-anichin-ingest.timer sloane-anichin-discover.timer sloane-samehadaku-ingest.timer sloane-samehadaku-discover.timer`.
5. Homer uses `bash -lc` for all SSH commands (homer's login shell is fish).

## Verification

1. **Unit edit correctness** (dev, pre-push): `git grep -n "kultivasimusemangatku"` → 0 matches. `grep EnvironmentFile deploy/sloane-*.service` → 4× required (no `-`). `grep Requires=sloane-db-tunnel deploy/sloane-*.service` → 0 matches.
2. **CLI guard** (dev): `env -u DOS_PGB_URL ... python -m sloane.ingest anichin --max-new 1` → stderr "DOS_PGB_URL unset...", exit 2. `--help` → exit 0. Full anichin suite green (13 tests).
3. **Homer clone + import**: `ssh homer 'bash -lc "cd ~/dwizzyOS/sloane && git log --oneline -1"'` → matches dev HEAD. `ssh homer 'bash -lc "PYTHONPATH=%h/dwizzyOS:%h/dwizzyOS-HQ ~/dwizzyOS/.venv-adk/bin/python -c \"from sloane.ingest.anichin import ingest_updates; print(\\\"ok\\\")\""'` → `ok`.
4. **Homer DB via ingest.env**: `ssh homer 'bash -lc "set -a; . ~/.config/sloane/ingest.env; set +a; ~/dwizzyOS/.venv-adk/bin/python -c \"import psycopg; from shared.config import pg_dsn; c=psycopg.connect(pg_dsn()); print(c.execute(\\\\\\\"select count(*) from raw_entities where source=\\\\\\\\\\\\\\\"anichin\\\\\\\\\\\\\\\"\\\\\\\").fetchone())\""'` → connects, returns a count (0 if fresh).
5. **Homer live smoke**: `ssh homer 'bash -lc "set -a; . ~/.config/sloane/ingest.env; set +a; cd ~/dwizzyOS/sloane; PYTHONPATH=$HOME/dwizzyOS:$HOME/dwizzyOS-HQ ~/dwizzyOS/.venv-adk/bin/python -m sloane.ingest anichin --max-new 1"'` → exits 0, prints JSON `{fetched:1, skipped:1}` (no series in DB yet) or `updated_series`/`new_episodes` if seeding.
6. **Timers scheduled**: `ssh homer 'bash -lc "systemctl --user list-timers | grep -E \"anichin|samehadaku\""'` → 4 timers listed.
7. **Cleanup**: remove any smoke-test rows from `raw_entities`/`canonical_entities`/`entity_source_links` where `source='anichin'` after the smoke (don't leave test data).

## Out of Scope

- **dwizzyOS-HQ `shared/config.py`** — the stale hardcoded `DOS_PG_PASSWORD` default lives here; not sloane's to edit. The `__main__` guard mitigates; root-cause fix is a dwizzyOS-HQ follow-up.
- **Git history purge / password rotation** — the stale password is in history; rotation is an ops task. (Note: since the password is stale/auth-fails, rotation urgency is lower than a live leaked secret, but still a follow-up.)
- **Dev-machine timers** — dev has none installed; the parameterized units target homer's layout. If dev later wants timers, clone/symlink sloane to `~/dwizzyOS/sloane` on dev too (or re-add a dev-specific unit).
