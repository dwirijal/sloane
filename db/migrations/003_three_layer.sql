-- 3-layer data model: raw (evidence) -> canonical (truth) -> links (traceability).
-- raw_entities: 1 row per (source, external_id), what the scraper saw. Purgeable.
-- canonical_entities: 1 row per real-world title. Lean, consumer-facing, forever.
-- entity_source_links: N raw -> 1 canonical. external_ids: multi-registry IDs (MAL/AniList/OMDB/TVDB).

-- 1. rename existing table to raw (was canonical_entities, holds raw per-source rows)
ALTER TABLE canonical_entities RENAME TO raw_entities;
ALTER INDEX IF EXISTS idx_canonical_kind RENAME TO idx_raw_kind;
ALTER INDEX IF EXISTS idx_canonical_payload_gin RENAME TO idx_raw_payload_gin;

-- 2. canonical (merged truth). dedup by kind+normalized_title.
CREATE TABLE IF NOT EXISTS canonical_entities (
    id              BIGSERIAL PRIMARY KEY,
    kind            TEXT NOT NULL,
    title           TEXT NOT NULL,
    normalized_title TEXT NOT NULL,             -- lowercased/depunctuated for fuzzy match
    best_payload    JSONB NOT NULL DEFAULT '{}'::jsonb,  -- merged best fields across sources
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (kind, normalized_title)
);
CREATE INDEX IF NOT EXISTS idx_canonical_norm ON canonical_entities (normalized_title);

-- 3. external registry IDs (OTORITATIF merge key). canonical can have many.
CREATE TABLE IF NOT EXISTS external_ids (
    id          BIGSERIAL PRIMARY KEY,
    canonical_id BIGINT NOT NULL REFERENCES canonical_entities(id) ON DELETE CASCADE,
    registry    TEXT NOT NULL,                  -- mal | anilist | omdb | tvdb | jikan
    external_id TEXT NOT NULL,                  -- the ID in that registry
    UNIQUE (registry, external_id),
    UNIQUE (canonical_id, registry)
);
CREATE INDEX IF NOT EXISTS idx_extids_lookup ON external_ids (registry, external_id);

-- 4. links: which raw rows back this canonical (traceability + re-merge support)
CREATE TABLE IF NOT EXISTS entity_source_links (
    canonical_id BIGINT NOT NULL REFERENCES canonical_entities(id) ON DELETE CASCADE,
    raw_id       BIGINT NOT NULL REFERENCES raw_entities(id) ON DELETE CASCADE,
    is_primary   BOOLEAN NOT NULL DEFAULT false,  -- best source for display
    PRIMARY KEY (canonical_id, raw_id)
);
CREATE INDEX IF NOT EXISTS idx_links_raw ON entity_source_links (raw_id);

-- ponytail: raw retains UNIQUE(source, external_id) from rename. canonical dedup
-- by normalized_title. Two sources saying "One Piece" -> 1 canonical + 2 links.
