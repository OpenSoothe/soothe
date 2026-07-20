-- soothe_vectors: pgvector extension (collection tables are created per config at runtime).

CREATE TABLE IF NOT EXISTS soothe_schema_migrations (
    version TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE EXTENSION IF NOT EXISTS vector;
