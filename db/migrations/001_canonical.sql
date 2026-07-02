-- sloane canonical entity store. One row = one normalized entity.
-- Dedup enforced by UNIQUE(source, external_id). payload = JSONB for kind-specific fields.
CREATE TABLE IF NOT EXISTS canonical_entities (
    id            BIGSERIAL PRIMARY KEY,
    source        TEXT        NOT NULL,
    external_id   TEXT        NOT NULL,
    kind          TEXT        NOT NULL,
    title         TEXT        NOT NULL,
    url           TEXT        NOT NULL,
    payload       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    first_seen    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_canonical_kind ON canonical_entities (kind);
-- ponytail: guard payload GIN — post-003, canonical_entities is the NEW table
-- (no payload col; has best_payload). Re-running 001 against post-003 state
-- would error here. Only create if column exists; raw_entities gets its own
-- index via the 003 rename on a clean run.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='canonical_entities'
               AND column_name='payload') THEN
    CREATE INDEX IF NOT EXISTS idx_canonical_payload_gin ON canonical_entities USING gin (payload);
  END IF;
END $$;

-- Upsert: update payload + updated_at on conflict, keep first_seen.
-- ponytail: ON CONFLICT handles dedup atomically at DB layer (constraint > app code).
