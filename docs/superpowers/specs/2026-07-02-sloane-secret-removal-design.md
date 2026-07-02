# sloane secret-removal design

## Problem (the secret surface, from the audit)

DB password `kultivasimusemangatku` is hardcoded in 6 tracked locations:

1. `CLAUDE.md:35` — run-env doc block.
2. `deploy/README.md:74` — manual samehadaku one-off command.
3. `deploy/README.md:81` — manual anichin one-off command.
4. `deploy/sloane-anichin-ingest.service:15` — inline `Environment=DOS_PGB_URL=...`.
5. `deploy/sloane-anichin-discover.service:12` — same.
6. `deploy/sloane-samehadaku-ingest.service:15` — same (pre-existing).
7. `deploy/sloane-samehadaku-discover.service:12` — same (pre-existing).

(Root cause #7 lives in `shared/config.py` of **dwizzyOS-HQ**, not sloane: `pg_dsn()` line ~44 `os.environ.get("DOS_PG_PASSWORD", "kultivasimusemangatku")` — hardcoded fallback default. Different repo, out of scope here.)

Compounding risk: `pg_dsn()` precedence is `DOS_PGB_URL` env → container IP `:5432` → `localhost:5432` fallback. A missing `DOS_PGB_URL` **silently** degrades to Docker `:5432` (which CLAUDE.md:39 says is NOT sloane's DB) using the leaked default → silent wrong-DB writes. The 4 units today use `EnvironmentFile=-%h/.config/sloane/ingest.env` (the `-` = optional), and `~/.config/sloane/ingest.env` does **not** exist yet, so the fallback path is currently reachable.

## Approach (the winner + grafts, one paragraph)

Winner = minimal working-tree removal: drop the inline `DOS_PGB_URL` line from all 4 `.service` files, move it into the (already-precedented) `~/.config/sloane/ingest.env`, flip `EnvironmentFile` from optional (`-`) to **required** (drop `-`) so a missing env file fails loud at `systemctl --user start`. Keep `PYTHONPATH` and `ROUTER_BASE_URL` **inline** — they are not secrets (repo path + LAN IP); moving `ROUTER_BASE_URL` adds a router-break failure mode (config.py defaults to `localhost:20128`, wrong on homeserver) for zero secret-removal. Graft exactly two things from runners-up: (1) a one-line `DOS_PGB_URL`-set guard at the top of `ingest/__main__.py main()` — the **only** thing that closes the verified `config.py:44` silent-fallback hole for non-systemd invocations (manual runs, tests, future HQ callers); it doubles as empty-file validation since `os.environ.get` returns falsy `''`. (2) explicit `README:90` homeserver alt-path redaction (no inline DSN). Reject: `ROUTER_BASE_URL` move (not a secret, adds router-break risk); `test -f` preflight (required EnvironmentFile + the `__main__` guard already cover absent-file and empty-file — a third check is redundant). No code beyond the one-line guard, no new deps, no config.py edit.

## File-by-file changes

### `deploy/sloane-anichin-ingest.service` (lines 12-19)

- **Delete** line 15: `Environment=DOS_PGB_URL=postgresql://dwizzy:...`.
- **Keep** lines 12-14 comment block (tunnel explanation, documents WHY).
- **Keep** line 17: `Environment=ROUTER_BASE_URL=http://192.168.100.6:20128/v1` (inline, not secret).
- **Keep** line 19 `EnvironmentFile` — but flip optional → required.
- Line 19: `EnvironmentFile=-%h/.config/sloane/ingest.env` → `EnvironmentFile=%h/.config/sloane/ingest.env` (drop `-`).
- Net `[Service]`: `PYTHONPATH` line + tunnel comment + `ROUTER_BASE_URL` line + router comment + required `EnvironmentFile` + `ExecStart`.

### `deploy/sloane-anichin-discover.service` (lines 12-14)

- **Delete** line 12: `Environment=DOS_PGB_URL=...`.
- Line 14: drop `-` → `EnvironmentFile=%h/.config/sloane/ingest.env`.
- Keep `ROUTER_BASE_URL` (line 13) + `PYTHONPATH` inline.

### `deploy/sloane-samehadaku-ingest.service` (lines 12-19)

- Same edits as anichin-ingest: delete line 15 DSN, flip line 19 `-` → required, keep `ROUTER_BASE_URL` line 17 + comment block lines 12-14 inline.

### `deploy/sloane-samehadaku-discover.service` (lines 12-14)

- Same edits as anichin-discover: delete line 12 DSN, flip line 14 `-` → required, keep `ROUTER_BASE_URL` line 13 inline.

### `~/.config/sloane/ingest.env` (NEW, user-created, NOT committed)

Lives out-of-tree. Extend the existing `ROUTER_API_KEY`-only file (README:27-30 precedent) with the DSN:

```
ROUTER_API_KEY=<your-9router-key>
DOS_PGB_URL=postgresql://dwizzy:<DB_PASSWORD>@localhost:6432/dwizzyos
```

`chmod 600` (file holds a live DB password — perms matter).

### `.gitignore` (currently empty/nonexistent)

Append:

```
ingest.env
# ponytail: real file is out-of-tree at ~/.config/sloane/; catches accidental in-repo copy only.
```

### `CLAUDE.md:35`

Replace literal DSN → placeholder + pointer:

```
DOS_PGB_URL: postgresql://dwizzy:<DB_PASSWORD>@localhost:6432/dwizzyos  # set in ~/.config/sloane/ingest.env (not committed)
```

### `deploy/README.md`

- **Prerequisites step 2 (lines 27-31)**: extend the `ingest.env` creation snippet to include `DOS_PGB_URL` alongside `ROUTER_API_KEY`; add `chmod 600`. Full-line comments only (systemd `EnvironmentFile` parses `#` full-line reliably, trailing inline comments less so).
- **Lines 73-76 (samehadaku manual one-off)**: replace inline `DOS_PGB_URL=...` arg with sourced env file:
  ```
  set -a; . ~/.config/sloane/ingest.env; set +a
  PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ \
  /home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest samehadaku --max-new 1
  ```
  (`set -a`/`.` are shell builtins, no new dep, robust against special chars in values. Keep `PYTHONPATH` inline — not in env file.)
- **Lines 80-83 (anichin manual one-off)**: same sourcing pattern, `anichin` source arg.
- **Line 90 (homeserver alt-path)**: redact inline DSN → `edit DOS_PGB_URL in ~/.config/sloane/ingest.env to @127.0.0.1:6432` (no inline DSN in instructions).

### `ingest/__main__.py` (line 34, top of `main()`)

Add `import os` (line ~17, alongside `import sys`). Guard at top of `main()`, before `argparse` dispatch — fires before any downstream `pg_dsn()` call (all 6 call sites are downstream of `main()`):

```python
def main(argv: list[str] | None = None) -> int:
    if not os.environ.get("DOS_PGB_URL"):
        sys.stderr.write("DOS_PGB_URL unset; set in ~/.config/sloane/ingest.env\n")
        return 2
    p = argparse.ArgumentParser(prog="sloane-ingest")
    ...
```

`# ponytail: guard at CLI entry, not each pg_dsn() call site — single chokepoint, 6 callers covered. Lift to shared/config.py when upstream drops the hardcoded default.`

## Out of scope (with WHY)

1. **Git history purge** (filter-repo/BFG). Working-tree clean ≠ secret revoked. Verified: 5 commits contain `kultivasimusemangatku` (`git log -S`). The password is recoverable from history by any clone. Heavy, rewrites history, breaks downstream clones — separate follow-up, not a deploy-unit redaction.

2. **DB password rotation** at homeserver pgbouncer/Postgres role. The leaked-in-history password remains a **live** DB credential until rotated. Without rotation, working-tree redaction is cosmetic. Meaningful only after history purge (else rotated-then-releaked from history). Separate ops task.

3. **`shared/config.py` hardcoded `DOS_PG_PASSWORD` default** (dwizzyOS-HQ repo, line ~44). The actual root cause of the silent wrong-DB fallback. sloane cannot edit a file in another repo. The `__main__` guard is the **only** sloane-side mitigation; a future caller invoking `pg_dsn()` outside `__main__` (test, manual `python -c`, HQ agent) still hits the fallback. Follow-up = open issue in dwizzyOS-HQ to drop the default (`os.environ["DOS_PG_PASSWORD"]`, KeyError) or `if not (pw := os.environ.get("DOS_PG_PASSWORD")): raise RuntimeError(...)`.

4. **No tracked `ingest.env` template**. Would either leak the secret or duplicate the README snippet — YAGNI.

5. **No `test -f` preflight** in README. Required `EnvironmentFile` + the `__main__` guard cover absent-file and empty-file; a third check is redundant.

6. **No moving `PYTHONPATH` or `ROUTER_BASE_URL`** into env file. Not secrets; moving `ROUTER_BASE_URL` adds a router-break failure mode (config.py defaults to `localhost:20128`) for zero secret-removal benefit.

## Open questions

1. Does the homeserver alt-path (`README:90`) also need `chmod 600` called out in its instruction? (Trivial — yes, same file holds the password there.)

2. Should the `__main__` guard also check `ROUTER_BASE_URL`? No — router calls degrade loudly (HTTP error) without it via config.py default; only `DOS_PGB_URL` silently miswrites. Scope: guard covers the silent-wrong-DB hole only.

## Verification (how to confirm the secret is gone from working tree + units still boot)

**Secret gone from working tree:**

```
git grep -n "kultivasimusemangatku"   # expect: 0 matches in tracked files
```

(Also confirm the placeholder is in place: `git grep -n "DB_PASSWORD"` should hit CLAUDE.md + the guard comment context only.)

**Units still boot (fail-loud path):**

```
# missing env file → systemd refuses to start:
systemctl --user start sloane-anichin-ingest.service   # expect: failure, "Failed to load environment files"
# create env file per README Prerequisites step 2 (with the real DSN) → starts:
mkdir -p ~/.config/sloane && $EDITOR ~/.config/sloane/ingest.env   # per README template
chmod 600 ~/.config/sloane/ingest.env
systemctl --user start sloane-anichin-ingest.service   # expect: runs (or fails on tunnel, NOT on env)
```

**`__main__` guard (non-systemd path):**

```
# unset → guard fires, exit 2, no pg_dsn() call:
env -u DOS_PGB_URL PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ \
  /home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest anichin --max-new 1
# expect stderr: "DOS_PGB_URL unset; set in ~/.config/sloane/ingest.env", exit 2
```

**Empty-but-present env file (guard catches falsy `''`):**

```
printf 'DOS_PGB_URL=\n' > ~/.config/sloane/ingest.env
# run the same env -u-free command → expect same guard fire, exit 2
```
