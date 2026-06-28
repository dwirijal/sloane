-- Hierarchical agent memory with group-based RBAC.
-- Groups: tribe, squad, chapter, guild. Memory rows tagged with a scope.
-- Access rule: squad/chapter/guild memory writable by group members;
--              tribe memory readable ONLY by tribe_lead + squad_lead roles.

CREATE TABLE IF NOT EXISTS agent_groups (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,          -- e.g. "squad-sloane", "chapter-backend", "guild-perf"
    kind        TEXT NOT NULL,                 -- tribe | squad | chapter | guild
    parent_id   BIGINT REFERENCES agent_groups(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_agent_groups_kind ON agent_groups (kind);

CREATE TABLE IF NOT EXISTS agent_memberships (
    id          BIGSERIAL PRIMARY KEY,
    agent_id    TEXT NOT NULL,                 -- agent name (ADK agent.name)
    group_id    BIGINT NOT NULL REFERENCES agent_groups(id) ON DELETE CASCADE,
    role        TEXT NOT NULL DEFAULT 'member',-- member | squad_lead | tribe_lead
    UNIQUE (agent_id, group_id)
);
CREATE INDEX IF NOT EXISTS idx_memberships_agent ON agent_memberships (agent_id);
CREATE INDEX IF NOT EXISTS idx_memberships_group ON agent_memberships (group_id);

CREATE TABLE IF NOT EXISTS agent_memory (
    id          BIGSERIAL PRIMARY KEY,
    group_id    BIGINT NOT NULL REFERENCES agent_groups(id) ON DELETE CASCADE,
    author      TEXT NOT NULL,                 -- agent_id that wrote it
    content     TEXT NOT NULL,
    embedding   vector(768) NULL,              -- pgvector; NULL until embedded
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_memory_group ON agent_memory (group_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_embed_gin ON agent_memory USING gin (metadata);

-- RBAC view: which agents can READ which memory rows.
-- tribe memory -> only tribe_lead + squad_lead of that tribe.
-- squad/chapter/guild memory -> any member of that group.
-- ponytail: RBAC as a SQL view (DB-enforced, not app code).
CREATE OR REPLACE VIEW v_memory_readable AS
SELECT m.id, m.group_id, g.kind, am.agent_id
FROM agent_memory m
JOIN agent_groups g ON g.id = m.group_id
JOIN agent_memberships am ON am.group_id = m.group_id
WHERE g.kind IN ('squad', 'chapter', 'guild')
   OR am.role IN ('tribe_lead', 'squad_lead');
