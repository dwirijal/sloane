"""Apply SQL migrations idempotently. ponytail: plain psycopg, no Alembic yet."""
from __future__ import annotations
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def ensure_schema(dsn: str) -> None:
    """Run all .sql migrations in order. Idempotent (CREATE IF NOT EXISTS)."""
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")  # pgvector, used by memory
        for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            cur.execute(sql_file.read_text())
        conn.commit()
