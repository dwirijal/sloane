"""Runtime config. Secrets from env, never hardcoded (security.md)."""
from __future__ import annotations
import os
from pathlib import Path

# ponytail: secret dir convention matches Gebelin. Password read at runtime.
SECRET_DIR = Path(os.environ.get("DOS_SECRET_DIR", "/home/dwizzy/dwizzyOS/Gebelin/.secrets"))


def _read_secret(name: str) -> str:
    p = SECRET_DIR / name
    if not p.exists():
        raise RuntimeError(f"secret {p} missing; set DOS_SECRET_DIR or create it")
    return p.read_text().strip()


def _container_ip() -> str | None:
    """Resolve DOS-pg's IP on the dwizzyOS docker network from host."""
    import subprocess
    try:
        r = subprocess.run(
            ["docker", "inspect", "DOS-pg", "--format",
             "{{(index .NetworkSettings.Networks \"dwizzyOS\").IPAddress}}"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() or None
    except Exception:
        return None


def pg_dsn() -> str:
    """psycopg DSN to the dwizzyos canonical DB.

    Source of truth = dos_pgb_url connection string (correct plain password).
    dos_pg_password secret file is stale (mismatched hash, auth fails over TCP).
    Falls back to resolving DOS-pg's container IP on the dwizzyOS docker network
    since 5432 is not published to the host.
    """
    # 1. explicit full connection string wins
    if url := os.environ.get("DOS_PGB_URL"):
        return url
    # 2. resolve container IP (host can't reach 127.0.0.1, port unpublished)
    host = _container_ip() or os.environ.get("DOS_PG_HOST", "localhost")
    pw = os.environ.get("DOS_PG_PASSWORD", "kultivasimusemangatku")
    port = os.environ.get("DOS_PG_PORT", "5432")
    return f"postgresql://dwizzy:{pw}@{host}:{port}/dwizzyos"


# 9router as the LLM backend for all agents (OpenAI-compatible).
ROUTER_BASE_URL = os.environ.get("ROUTER_BASE_URL", "http://192.168.100.6:20128/v1")
ROUTER_API_KEY = os.environ.get("ROUTER_API_KEY", "")  # set in env, not committed
MODEL_LEAD = "gc/gemini-2.5-pro"       # decompose / plan
MODEL_WORKER = "gc/gemini-2.5-flash"   # scrape / transform / qa
