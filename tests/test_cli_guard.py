"""CLI guard: DOS_PGB_URL unset -> fail loud (exit 2) before any pg_dsn() call.

pg_dsn() (shared/config.py) silently falls back to a stale default password +
wrong DB when DOS_PGB_URL is absent. The guard in __main__.main() closes that
hole for non-systemd invocations (manual runs, tests) where EnvironmentFile
isn't loaded.
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
    # DOS_PGB_URL set -> guard passes; dispatch runs (may fail on DB/network,
    # but NOT on the guard). Assert only that the guard message is ABSENT.
    with patch.dict(os.environ, {"DOS_PGB_URL": "postgresql://x:x@localhost:6432/x"}):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            try:
                main(["anichin", "--max-new", "0"])
            except Exception:
                pass  # DB/network failure is fine — guard didn't fire
    assert "DOS_PGB_URL unset" not in err.getvalue()
