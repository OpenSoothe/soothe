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

-- RFC-413 display card ledger (used when persistence.default_backend=postgresql)
CREATE TABLE IF NOT EXISTS display_card_mutations (
    loop_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts TEXT NOT NULL,
    op TEXT NOT NULL,
    card_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    data_json JSONB NOT NULL,
    PRIMARY KEY (loop_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_display_cards_loop
    ON display_card_mutations(loop_id, seq);

CREATE TABLE IF NOT EXISTS goal_display_snapshots (
    loop_id TEXT NOT NULL,
    goal_index INTEGER NOT NULL,
    goal_id TEXT NOT NULL,
    frozen_at TEXT NOT NULL,
    snapshot_json JSONB NOT NULL,
    card_count INTEGER NOT NULL,
    PRIMARY KEY (loop_id, goal_index)
);

CREATE INDEX IF NOT EXISTS idx_goal_snapshots_loop
    ON goal_display_snapshots(loop_id, goal_index);

-- RFC-229 cron jobs (when persistence.default_backend=postgresql)
CREATE TABLE IF NOT EXISTS cron_jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    description TEXT NOT NULL,
    schedule_kind TEXT NOT NULL,
    schedule_value TEXT NOT NULL,
    end_condition TEXT,
    priority INTEGER DEFAULT 50,
    status TEXT DEFAULT 'pending',
    next_run TEXT NOT NULL,
    last_run TEXT,
    run_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cron_jobs_user_status ON cron_jobs(user_id, status);
CREATE INDEX IF NOT EXISTS idx_cron_jobs_next_run ON cron_jobs(next_run) WHERE status = 'pending';

-- RFC-307 identity (when persistence.default_backend=postgresql)
CREATE TABLE IF NOT EXISTS identity_users (
    user_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS identity_aksk_pairs (
    aksk_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES identity_users(user_id),
    access_key TEXT NOT NULL UNIQUE,
    secret_key_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    revoked INTEGER NOT NULL DEFAULT 0,
    revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS identity_tokens (
    jti TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    aksk_id TEXT NOT NULL REFERENCES identity_aksk_pairs(aksk_id),
    token_type TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0,
    revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS identity_external_mappings (
    mapping_id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    sender_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES identity_users(user_id),
    created_at TEXT NOT NULL,
    UNIQUE(channel, sender_id)
);

CREATE TABLE IF NOT EXISTS identity_revoked_jtis (
    jti TEXT PRIMARY KEY,
    revoked_at TEXT NOT NULL,
    reason TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_identity_aksk_user ON identity_aksk_pairs(user_id);
CREATE INDEX IF NOT EXISTS idx_identity_tokens_user ON identity_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_identity_tokens_aksk ON identity_tokens(aksk_id);
CREATE INDEX IF NOT EXISTS idx_identity_mappings_channel_sender
    ON identity_external_mappings(channel, sender_id);
CREATE INDEX IF NOT EXISTS idx_identity_mappings_user ON identity_external_mappings(user_id);
