"""001_checkpoint_hot_cold.sql

Hot index column for iteration-boundary writes and cold blob table for goal history.
"""

ALTER TABLE agentloop_checkpoints
    ADD COLUMN IF NOT EXISTS checkpoint_index JSONB;

CREATE TABLE IF NOT EXISTS agentloop_checkpoint_blobs (
    loop_id TEXT PRIMARY KEY REFERENCES agentloop_checkpoints(loop_id) ON DELETE CASCADE,
    cold_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agentloop_checkpoint_blobs_updated_at
    ON agentloop_checkpoint_blobs(updated_at DESC);

-- Backfill hot index from existing rows
UPDATE agentloop_checkpoints
SET checkpoint_index = jsonb_build_object(
    'status', checkpoint_data->>'status',
    'current_goal_index', (checkpoint_data->>'current_goal_index')::int,
    'total_goals_completed', (checkpoint_data->>'total_goals_completed')::int,
    'current_thread_id', checkpoint_data->>'current_thread_id',
    'total_duration_ms', (checkpoint_data->>'total_duration_ms')::bigint,
    'total_tokens_used', (checkpoint_data->>'total_tokens_used')::bigint,
    'total_thread_switches', (checkpoint_data->>'total_thread_switches')::int,
    'execution_checkpoint', checkpoint_data->'execution_checkpoint',
    'updated_at', checkpoint_data->>'updated_at'
)
WHERE checkpoint_index IS NULL;

INSERT INTO agentloop_checkpoint_blobs (loop_id, cold_json, updated_at)
SELECT
    loop_id,
    jsonb_build_object(
        'loop_id', checkpoint_data->'loop_id',
        'thread_ids', checkpoint_data->'thread_ids',
        'goal_history', checkpoint_data->'goal_history',
        'working_memory_state', checkpoint_data->'working_memory_state',
        'thread_health_metrics', checkpoint_data->'thread_health_metrics',
        'created_at', checkpoint_data->>'created_at',
        'schema_version', checkpoint_data->>'schema_version',
        'client_workspace', checkpoint_data->'client_workspace',
        'detached_at', checkpoint_data->'detached_at',
        'user_id', checkpoint_data->'user_id'
    ),
    updated_at
FROM agentloop_checkpoints
ON CONFLICT (loop_id) DO NOTHING;
