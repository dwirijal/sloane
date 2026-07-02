# sloane Secret-Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the hardcoded DB password (`kultivasimusemangatku`) from all tracked sloane files; move it to an out-of-tree `ingest.env` the systemd units already reference; add a CLI guard so non-systemd runs fail loud instead of silently hitting the wrong DB.

**Architecture:** Minimal env-file fix (judge-panel winner, 88/100). `DOS_PGB_URL` moves from 4 inline `Environment=` lines into `~/.config/sloane/ingest.env` (already referenced via `EnvironmentFile`, currently optional+absent). Flip `EnvironmentFile=-` → `EnvironmentFile=` (required → systemd refuses start if missing). One-line guard in `__main__.py` after `parse_args` catches non-systemd invocations where `pg_dsn()` would silently fall back to Docker `:5432` + the leaked default password. Docs redacted to placeholders.

**Tech Stack:** systemd user units, Python 3.12 stdlib (`os`, `argparse`, `sys`), shell builtins (`set -a`/`.`).

## Global Constraints

- **No hardcoded secrets in tracked files** (CLAUDE.md). The password `kultivasimusemangatku` must not appear in any tracked file after this plan — verify with `git grep -n "kultivasimusemangatku"` → 0 matches.
- **Tests run via stdlib harness, NOT pytest** (no pip/pytest in venv). Harness: `cd /home/dwirijal/Projects/dwizzyOS && PYTHONPATH=...:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ .venv-adk/bin/python -c "import importlib,inspect,sys,glob; ..."` (see CLAUDE.md Tests section).
- **Run env:** `python=/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python`, `PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ`.
- **DB DSN via `from shared.config import pg_dsn` — NEVER hardcode.** `pg_dsn()` reads `DOS_PGB_URL` env first (this is the var we're moving to `ingest.env`).
- **YAGNI extremist:** no tracked `ingest.env` template (would duplicate README or leak the secret). No deploy-time `test -f` check (required `EnvironmentFile` IS the check).
- **Conventional Commits:** `type(scope): description` + `Co-Authored-By: Claude <noreply@anthropic.com>` trailer.
- **Spec:** `docs/superpowers/specs/2026-07-02-sloane-secret-removal-design.md` (read for rationale; this plan is the executable version).

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `deploy/sloane-anichin-ingest.service` | systemd unit | Remove inline `DOS_PGB_URL`; flip `EnvironmentFile` to required |
| `deploy/sloane-anichin-discover.service` | systemd unit | Same |
| `deploy/sloane-samehadaku-ingest.service` | systemd unit | Same |
| `deploy/sloane-samehadaku-discover.service` | systemd unit | Same |
| `.gitignore` | VCS ignores | Add `ingest.env` (defensive — real file is out-of-tree) |
| `ingest/__main__.py` | CLI entry | Add `DOS_PGB_URL`-unset guard after `parse_args` |
| `tests/test_cli_guard.py` | NEW test | Assert guard fires (exit 2) when `DOS_PGB_URL` unset |
| `CLAUDE.md` | agent guidelines | Redact `:35` DSN → placeholder + pointer |
| `deploy/README.md` | deploy docs | Redact inline DSNs; extend `ingest.env` creation; `set -a` sourcing for one-offs |

---

### Task 1: Remove inline `DOS_PGB_URL` from deploy units + require `EnvironmentFile` + gitignore

**Files:**
- Modify: `deploy/sloane-anichin-ingest.service:15,19`
- Modify: `deploy/sloane-anichin-discover.service:12,14`
- Modify: `deploy/sloane-samehadaku-ingest.service:15,18-19`
- Modify: `deploy/sloane-samehadaku-discover.service:12,14`
- Modify: `.gitignore` (append)

**Interfaces:**
- Consumes: none (config files).
- Produces: 4 `.service` files with no inline password; required `EnvironmentFile` pointing at `~/.config/sloane/ingest.env`.

- [ ] **Step 1: Edit `deploy/sloane-anichin-ingest.service`**

Delete line 15 (the inline `DOS_PGB_URL`). Update the comment block (lines 12-18) so it documents that `DOS_PGB_URL` now lives in `ingest.env`. Flip `EnvironmentFile` to required. The full `[Service]` section after edit:

```ini
[Service]
Type=oneshot
User=dwizzy
WorkingDirectory=/home/dwirijal/Projects/dwizzyOS/sloane
Environment=PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ
# DOS_PGB_URL (DB password) + ROUTER_API_KEY live in ingest.env (not committed):
EnvironmentFile=%h/.config/sloane/ingest.env
# 9router (LLM for merge fuzzy + enrich) lives on the homeserver too:
Environment=ROUTER_BASE_URL=http://192.168.100.6:20128/v1
ExecStart=/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest anichin
```

- [ ] **Step 2: Edit `deploy/sloane-anichin-discover.service`**

Delete line 12 (inline `DOS_PGB_URL`). Flip line 14 `EnvironmentFile`. Full `[Service]` after edit:

```ini
[Service]
Type=oneshot
User=dwizzy
WorkingDirectory=/home/dwirijal/Projects/dwizzyOS/sloane
Environment=PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ
Environment=ROUTER_BASE_URL=http://192.168.100.6:20128/v1
EnvironmentFile=%h/.config/sloane/ingest.env
ExecStart=/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest anichin --discover
```

- [ ] **Step 3: Edit `deploy/sloane-samehadaku-ingest.service`**

Same pattern as anichin-ingest (Step 1): delete line 15, update comment, flip `EnvironmentFile`. Full `[Service]` after edit:

```ini
[Service]
Type=oneshot
User=dwizzy
WorkingDirectory=/home/dwirijal/Projects/dwizzyOS/sloane
Environment=PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ
# DOS_PGB_URL (DB password) + ROUTER_API_KEY live in ingest.env (not committed):
EnvironmentFile=%h/.config/sloane/ingest.env
# 9router (LLM for merge fuzzy + enrich) lives on the homeserver too:
Environment=ROUTER_BASE_URL=http://192.168.100.6:20128/v1
ExecStart=/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest samehadaku
```

- [ ] **Step 4: Edit `deploy/sloane-samehadaku-discover.service`**

Same pattern as anichin-discover (Step 2): delete line 12, flip `EnvironmentFile`. Full `[Service]` after edit:

```ini
[Service]
Type=oneshot
User=dwizzy
WorkingDirectory=/home/dwirijal/Projects/dwizzyOS/sloane
Environment=PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ
Environment=ROUTER_BASE_URL=http://192.168.100.6:20128/v1
EnvironmentFile=%h/.config/sloane/ingest.env
ExecStart=/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest samehadaku --discover
```

- [ ] **Step 5: Append `ingest.env` to `.gitignore`**

Add after the existing `.env` line (line 4):

```
ingest.env
# ponytail: real file is out-of-tree at ~/.config/sloane/; catches accidental in-repo copy only.
```

- [ ] **Step 6: Verify no inline password remains in deploy units**

Run:
```bash
git grep -n "kultivasimusemangatku" -- 'deploy/*.service'
```
Expected: no output (0 matches). Also verify `EnvironmentFile` has no `-` prefix:
```bash
grep -n "EnvironmentFile" deploy/sloane-*.service
```
Expected: 4 lines, all `EnvironmentFile=%h/.config/sloane/ingest.env` (no `-`).

- [ ] **Step 7: Commit**

```bash
git add deploy/sloane-anichin-ingest.service deploy/sloane-anichin-discover.service \
        deploy/sloane-samehadaku-ingest.service deploy/sloane-samehadaku-discover.service \
        .gitignore
git commit -m "fix(sloane/deploy): move DOS_PGB_URL to ingest.env, require EnvironmentFile

Remove the inline DB password from all 4 ingest/discover .service files.
Move DOS_PGB_URL into ~/.config/sloane/ingest.env (already referenced,
was optional+absent). Flip EnvironmentFile=- to required (no '-') so a
missing file fails loud at systemd start instead of silently degrading.
gitignore ingest.env (defensive — real file is out-of-tree).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: `DOS_PGB_URL`-unset guard in `ingest/__main__.py` (TDD)

**Files:**
- Create: `tests/test_cli_guard.py`
- Modify: `ingest/__main__.py:17,46-47` (add `import os`; insert guard after `parse_args`)

**Interfaces:**
- Consumes: `os.environ.get("DOS_PGB_URL")`.
- Produces: `main()` returns `2` + stderr message when `DOS_PGB_URL` is unset, before any `pg_dsn()` call. `--help` still works (guard is after `parse_args`).

**Why after `parse_args`, not before (spec refinement):** The spec showed the guard before `argparse`. That breaks `--help` (argparse never runs). Placing it after `parse_args` means `--help` and invalid-arg errors still work normally; the guard only fires on a valid parse that would proceed to dispatch.

- [ ] **Step 1: Write the failing test `tests/test_cli_guard.py`**

```python
"""CLI guard: DOS_PGB_URL unset -> fail loud (exit 2) before any pg_dsn() call.

pg_dsn() (shared/config.py) silently falls back to Docker :5432 + a leaked
default password when DOS_PGB_URL is absent — wrong DB, no error. The guard
in __main__.main() closes that hole for non-systemd invocations.
"""
import contextlib
import io
import os
from unittest.mock import patch

from sloane.ingest.__main__ import main


def test_main_guard_fires_when_dsn_unset():
    # DOS_PGB_URL absent -> guard fires before any DB/network call.
    env = {k: v for k, v in os.environ.items() if k != "DOS_PGB_URL"}
    with patch.dict(os.environ, env, clear=True):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = main(["anichin", "--max-new", "1"])
    assert rc == 2
    assert "DOS_PGB_URL unset" in err.getvalue()


def test_main_guard_does_not_fire_when_dsn_set():
    # DOS_PGB_URL set -> guard passes, dispatch runs (will fail on DB/network,
    # but NOT on the guard). Use --help path isn't viable (argparse exits);
    # instead set a dummy DSN and expect either a result dict or a non-2
    # non-guard error (connection refused etc). We only assert the guard
    # message is ABSENT.
    with patch.dict(os.environ, {"DOS_PGB_URL": "postgresql://x:x@localhost:6432/x"}):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            try:
                main(["anichin", "--max-new", "0"])
            except Exception:
                pass  # DB/network failure is fine — we only care the guard didn't fire
    assert "DOS_PGB_URL unset" not in err.getvalue()
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `/home/dwirijal/Projects/dwizzyOS`):
```bash
PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ \
/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -c "import importlib,inspect,sys
mn='sloane.tests.test_cli_guard'
mod=importlib.import_module(mn)
p=f=0
for n,fn in inspect.getmembers(mod,inspect.isfunction):
    if not n.startswith('test_'): continue
    try: fn(); p+=1; print(f'  ok {n}')
    except Exception as e: f+=1; print(f'FAIL {n}: {e}')
print(f'{p} passed, {f} failed')"
```
Expected: `FAIL test_main_guard_fires_when_dsn_unset: AssertionError` (guard doesn't exist yet, `main` proceeds to dispatch) + `test_main_guard_does_not_fire_when_dsn_set` may pass or fail depending on DB. The first FAIL is the spec.

- [ ] **Step 3: Add `import os` to `ingest/__main__.py`**

In the import block (after `import sys`, line 17), add:

```python
import os
```

So lines 14-17 become:
```python
from __future__ import annotations
import argparse
import json
import os
import sys
```

- [ ] **Step 4: Add the guard after `parse_args` in `main()`**

Insert between `args = p.parse_args(argv)` (line 46) and `if args.source == "samehadaku":` (line 48):

```python
    # DOS_PGB_URL guard: pg_dsn() (shared/config.py) silently falls back to
    # Docker :5432 + a leaked default password when this is unset — wrong DB,
    # no error. Fail loud at the CLI entry instead. After parse_args so --help
    # still works.
    # ponytail: lift to shared/config.py when upstream drops the hardcoded default.
    if not os.environ.get("DOS_PGB_URL"):
        sys.stderr.write("DOS_PGB_URL unset; set in ~/.config/sloane/ingest.env\n")
        return 2
```

- [ ] **Step 5: Run test to verify it passes**

Run the same harness command as Step 2.
Expected: `2 passed, 0 failed`.

- [ ] **Step 6: Verify `--help` still works (guard is after parse_args)**

```bash
PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ \
/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest anichin --help
```
Expected: prints usage mentioning `anichin`, exit 0 (guard not reached — `--help` exits in `parse_args`).

Also verify the guard fires on a valid parse without the env var:
```bash
env -u DOS_PGB_URL PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ \
/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest anichin --max-new 1
```
Expected: stderr `DOS_PGB_URL unset; set in ~/.config/sloane/ingest.env`, exit 2.

- [ ] **Step 7: Run full anichin suite to confirm no regressions**

```bash
cd /home/dwirijal/Projects/dwizzyOS
PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ \
/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -c "import importlib,inspect,sys,glob;p=f=0
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
Expected: all pass except `test_state.*` (needs DB tunnel — pre-existing, unrelated).

- [ ] **Step 8: Commit**

```bash
git add ingest/__main__.py tests/test_cli_guard.py
git commit -m "fix(sloane): guard DOS_PGB_URL at CLI entry, fail loud not silent

pg_dsn() (shared/config.py) silently falls back to Docker :5432 + a leaked
default password when DOS_PGB_URL is unset — wrong DB, no error. Required
EnvironmentFile (Task 1) catches systemd-start absence; this guard catches
non-systemd runs (manual python -m, tests, future HQ callers) and
empty-but-present ingest.env (falsy ''). After parse_args so --help works.

ponytail: lift to shared/config.py when upstream drops the hardcoded default.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Redact DSN from `CLAUDE.md` + `deploy/README.md`

**Files:**
- Modify: `CLAUDE.md:35`
- Modify: `deploy/README.md:27-32,73-76,80-83,90`

**Interfaces:**
- Consumes: none.
- Produces: no tracked doc carries the literal password; README instructs creating `ingest.env` with `DOS_PGB_URL` + `chmod 600`; manual one-offs source the env file instead of inlining the DSN.

- [ ] **Step 1: Redact `CLAUDE.md:35`**

Replace:
```
DOS_PGB_URL: postgresql://dwizzy:kultivasimusemangatku@localhost:6432/dwizzyos
```
With:
```
DOS_PGB_URL: postgresql://dwizzy:<DB_PASSWORD>@localhost:6432/dwizzyos  # set in ~/.config/sloane/ingest.env (not committed)
```

- [ ] **Step 2: Extend README Prerequisites step 2 (lines 27-32)**

Replace the current step 2:
```markdown
2. **ROUTER_API_KEY** (LLM for merge fuzzy-match + Jikan-free enrich). Create:
   ```
   mkdir -p ~/.config/sloane
   echo "ROUTER_API_KEY=your-9router-key" > ~/.config/sloane/ingest.env
   ```
   (The 9router base URL is set in the service: `http://192.168.100.6:20128/v1`.)
```
With:
```markdown
2. **`~/.config/sloane/ingest.env`** (DB password + LLM key — not committed). Create:
   ```
   mkdir -p ~/.config/sloane
   cat > ~/.config/sloane/ingest.env <<'EOF'
   DOS_PGB_URL=postgresql://dwizzy:<DB_PASSWORD>@localhost:6432/dwizzyos
   ROUTER_API_KEY=your-9router-key
   EOF
   chmod 600 ~/.config/sloane/ingest.env
   ```
   (The 9router base URL is set inline in the service: `http://192.168.100.6:20128/v1`.
   The `.service` files require this file — missing it, systemd refuses to start.)
```

- [ ] **Step 3: Redact README manual one-off (samehadaku, lines 73-76)**

Replace:
```
PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ \
DOS_PGB_URL=postgresql://dwizzy:kultivasimusemangatku@localhost:6432/dwizzyos \
/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest samehadaku --max-new 1
```
With:
```
set -a; . ~/.config/sloane/ingest.env; set +a
PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ \
/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest samehadaku --max-new 1
```
(`set -a`/`.` are shell builtins — no new dep, robust against special chars in values.)

- [ ] **Step 4: Redact README manual one-off (anichin, lines 80-83)**

Replace:
```
PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ \
DOS_PGB_URL=postgresql://dwizzy:kultivasimusemangatku@localhost:6432/dwizzyos \
/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest anichin --max-new 1
```
With:
```
set -a; . ~/.config/sloane/ingest.env; set +a
PYTHONPATH=/home/dwirijal/Projects/dwizzyOS:/home/dwirijal/Projects/dwizzyOS/dwizzyOS-HQ \
/home/dwirijal/Projects/dwizzyOS/.venv-adk/bin/python -m sloane.ingest anichin --max-new 1
```

- [ ] **Step 5: Redact README homeserver alt-path (line 90)**

Replace:
```
+ drop the tunnel dependency. Cleaner for 24/7 (no SSH tunnel to babysit).
```
The sentence before it (line 90 start) currently says:
```
bs4/httpx/psycopg, and change the service `Environment=DOS_PGB_URL=...@127.0.0.1:6432/...`
```
Replace that fragment with:
```
bs4/httpx/psycopg, and edit `DOS_PGB_URL` in `~/.config/sloane/ingest.env` to `@127.0.0.1:6432/...`
```

- [ ] **Step 6: Verify no password remains in any tracked file**

```bash
git grep -n "kultivasimusemangatku"
```
Expected: no output (0 matches across all tracked files). This is the load-bearing verification for the whole plan.

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md deploy/README.md
git commit -m "docs(sloane): redact DB password from CLAUDE.md + README

Replace the literal DSN with placeholders + pointers to
~/.config/sloane/ingest.env. Manual one-off commands now source the env
file (set -a; . ingest.env; set +a) instead of inlining the password.
README Prerequisites step 2 extended to create ingest.env with
DOS_PGB_URL + ROUTER_API_KEY + chmod 600.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review Notes

**Spec coverage:** Every spec file-change section maps to a task step — 4 `.service` files (Task 1 steps 1-4), `ingest.env` creation (Task 3 step 2 — README template, not a tracked file per YAGNI), `.gitignore` (Task 1 step 5), `CLAUDE.md:35` (Task 3 step 1), `README` (Task 3 steps 2-5), `__main__.py` guard (Task 2). Out-of-scope items (history purge, password rotation, `shared/config.py`) are not tasks — correct, they're separate follow-ups.

**Spec refinement:** Guard placement moved from before-`argparse` (spec) to after-`parse_args` (Task 2 step 4) — noted in the task's "Why" block. `--help` regression test is Step 6.

**Type consistency:** `main(argv) -> int` — guard returns `2`, matching the existing `p.error(...); return 2` pattern at line 64. `os` imported in Step 3, used in Step 4. No signature changes.

**Verification:** Task 1 step 6 + Task 3 step 6 both run `git grep -n "kultivasimusemangatku"` → 0 matches. This is the single most important assertion: the password is gone from the working tree.
