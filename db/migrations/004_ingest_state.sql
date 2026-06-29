-- Runner state. One row per (source, key); value is JSONB.
-- Used by the ingest runner to persist things like seen_feed_urls across
-- stateless cron runs. Survives restarts; DB is the single source of truth
-- (matches raw/canonical/external_ids pattern).
CREATE TABLE IF NOT EXISTS ingest_state (
    source      TEXT        NOT NULL,
    key         TEXT        NOT NULL,
    value       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, key)
);
