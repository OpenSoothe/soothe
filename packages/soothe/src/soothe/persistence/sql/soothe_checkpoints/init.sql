-- soothe_checkpoints: StrangeLoop persistence, Context Engine, hot/cold checkpoint split.
-- Idempotent bootstrap via init.sql; incremental changes use NNN_name.sql migrations.

CREATE TABLE IF NOT EXISTS soothe_schema_migrations (
    version TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agentloop_checkpoints (
    loop_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    checkpoint_data JSONB NOT NULL,
    checkpoint_index JSONB,
    client_workspace TEXT,
    detached_at TIMESTAMPTZ,
    user_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_agentloop_checkpoints_thread_id
    ON agentloop_checkpoints(thread_id);
CREATE INDEX IF NOT EXISTS idx_agentloop_checkpoints_status
    ON agentloop_checkpoints(status);
CREATE INDEX IF NOT EXISTS idx_agentloop_checkpoints_updated_at
    ON agentloop_checkpoints(updated_at DESC);

CREATE TABLE IF NOT EXISTS agentloop_checkpoint_blobs (
    loop_id TEXT PRIMARY KEY REFERENCES agentloop_checkpoints(loop_id) ON DELETE CASCADE,
    cold_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agentloop_checkpoint_blobs_updated_at
    ON agentloop_checkpoint_blobs(updated_at DESC);

CREATE TABLE IF NOT EXISTS goal_records (
    goal_id TEXT PRIMARY KEY,
    loop_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    status TEXT NOT NULL,
    duration_ms INTEGER DEFAULT 0,
    tokens_used INTEGER DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    FOREIGN KEY (loop_id) REFERENCES agentloop_checkpoints(loop_id)
);

CREATE INDEX IF NOT EXISTS idx_goals_loop ON goal_records(loop_id);
CREATE INDEX IF NOT EXISTS idx_goals_thread ON goal_records(thread_id);

CREATE TABLE IF NOT EXISTS ce_dag (
    loop_id TEXT PRIMARY KEY,
    dag_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ce_ledger (
    loop_id TEXT PRIMARY KEY,
    ledger_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
