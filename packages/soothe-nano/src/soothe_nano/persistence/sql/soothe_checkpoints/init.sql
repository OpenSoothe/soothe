-- soothe_checkpoints: shared LangGraph checkpoint storage.
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

CREATE TABLE IF NOT EXISTS checkpoint_anchors (
    anchor_id SERIAL PRIMARY KEY,
    loop_id TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    thread_id TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    checkpoint_ns TEXT DEFAULT '',
    anchor_type TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    iteration_status TEXT,
    next_action_summary TEXT,
    tools_executed JSONB,
    reasoning_decision TEXT,
    FOREIGN KEY (loop_id) REFERENCES agentloop_checkpoints(loop_id),
    UNIQUE(loop_id, iteration, anchor_type)
);

CREATE INDEX IF NOT EXISTS idx_anchors_loop_iteration
    ON checkpoint_anchors(loop_id, iteration);
CREATE INDEX IF NOT EXISTS idx_anchors_thread
    ON checkpoint_anchors(thread_id);
CREATE INDEX IF NOT EXISTS idx_anchors_loop_thread
    ON checkpoint_anchors(loop_id, thread_id);

CREATE TABLE IF NOT EXISTS failed_branches (
    branch_id TEXT PRIMARY KEY,
    loop_id TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    thread_id TEXT NOT NULL,
    root_checkpoint_id TEXT NOT NULL,
    failure_checkpoint_id TEXT NOT NULL,
    failure_reason TEXT NOT NULL,
    execution_path JSONB NOT NULL,
    failure_insights JSONB,
    avoid_patterns JSONB,
    suggested_adjustments JSONB,
    created_at TIMESTAMPTZ NOT NULL,
    analyzed_at TIMESTAMPTZ,
    pruned_at TIMESTAMPTZ,
    FOREIGN KEY (loop_id) REFERENCES agentloop_checkpoints(loop_id)
);

CREATE INDEX IF NOT EXISTS idx_branches_loop ON failed_branches(loop_id);
CREATE INDEX IF NOT EXISTS idx_branches_thread ON failed_branches(thread_id);
CREATE INDEX IF NOT EXISTS idx_branches_iteration
    ON failed_branches(loop_id, iteration);

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
