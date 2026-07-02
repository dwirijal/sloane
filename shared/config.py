"""Runtime config. Secrets from env, never hardcoded (security.md).

ponytail: vendored trim of dwizzyOS-HQ/shared/config.py — only the 4 names
sloane imports (pg_dsn, ROUTER_BASE_URL, ROUTER_API_KEY, MODEL_WORKER).
Dropped: hardcoded password fallback (kultivasimusemangatku leak),
_container_ip/localhost:5432 silent-wrong-DB path, MODEL_LEAD/
EMBEDDING_MODELS/MODELS_HIGH/is_high_capability (unused in sloane).
Upstream: dwizzyOS-HQ/shared/config.py — re-sync if sloane needs more.
"""
from __future__ import annotations
import os
from pathlib import Path

SECRET_DIR = Path(os.environ.get("DOS_SECRET_DIR", "/home/dwizzy/dwizzyOS/Gebelin/.secrets"))


def _read_secret(name: str) -> str:
    p = SECRET_DIR / name
    if not p.exists():
        raise RuntimeError(f"secret {p} missing; set DOS_SECRET_DIR or create it")
    return p.read_text().strip()


def pg_dsn() -> str:
    """psycopg DSN to dwizzyos. Source of truth = DOS_PGB_URL env. No fallback."""
    if url := os.environ.get("DOS_PGB_URL"):
        return url
    raise RuntimeError("DOS_PGB_URL unset; set via env_file (dos_pgb_url)")


ROUTER_BASE_URL = os.environ.get("ROUTER_BASE_URL", "http://192.168.100.6:20128/v1")
ROUTER_API_KEY = os.environ.get("ROUTER_API_KEY", "")
MODEL_WORKER = os.environ.get("MODEL_WORKER", "AGENTS")
