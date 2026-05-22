-- Track applied schema migrations for soothe_checkpoints (AgentLoop persistence).
CREATE TABLE IF NOT EXISTS soothe_schema_migrations (
    version TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
