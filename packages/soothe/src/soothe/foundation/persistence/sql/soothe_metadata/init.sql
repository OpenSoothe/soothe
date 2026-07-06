-- soothe_metadata: namespace-isolated JSONB key-value persistence (durability, autopilot, etc.).

CREATE TABLE IF NOT EXISTS soothe_schema_migrations (
    version TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS soothe_persistence (
    key TEXT NOT NULL,
    namespace TEXT NOT NULL,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (namespace, key)
);

CREATE INDEX IF NOT EXISTS idx_persistence_updated
    ON soothe_persistence(updated_at);
