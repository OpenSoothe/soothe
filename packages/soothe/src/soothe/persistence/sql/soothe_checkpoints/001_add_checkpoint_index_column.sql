-- Add checkpoint_index column to agentloop_checkpoints.
--
-- This column was added to init.sql's CREATE TABLE (aa19fcb9, 2026-07-06) after
-- the table already existed in deployed databases. CREATE TABLE IF NOT EXISTS is
-- a no-op against an existing table, so databases bootstrapped before that
-- commit never received the column and persisted goal boundaries fail with
-- psycopg.errors.UndefinedColumn on INSERT/UPDATE of checkpoint_index.
--
-- Idempotent: IF NOT EXISTS makes this safe to apply on databases that already
-- have the column (re-run is a no-op) and adds it to those that do not.

ALTER TABLE agentloop_checkpoints
    ADD COLUMN IF NOT EXISTS checkpoint_index JSONB;
