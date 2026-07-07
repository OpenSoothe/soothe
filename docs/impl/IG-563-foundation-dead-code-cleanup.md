# IG-563: Foundation Legacy and Dead Code Cleanup

## Status

Completed — Phase 1 and Phase 2 implemented.

## Goal

Remove unreferenced modules and dead code paths from `soothe.foundation`, rename stale GoalEngine references to ContextEngine (RFC-625), and consolidate runtime backward-compatibility into normalize-on-read upgrades.

## Phase 1 (completed)

### Removed modules

| Module | Reason |
|--------|--------|
| `foundation/core/entities.py` | `Job`/`JobState` exported but never consumed; daemon Job IPC uses `GoalNode` via ContextEngine |
| `foundation/core/filesystem/audit_logger.py` | No production or test imports |
| `foundation/context/persistence/file_backend.py` | Not wired in CE factory; test-only |

### Removed dead code paths

- `metadata_generator.py`: unreachable `tool_result_registry` v2 branch (missing module, no config field)
- `executor.py`: `tool_result_registry` hasattr block

### Naming cleanup

GoalEngine → ContextEngine in comments, docstrings, and local variable names across foundation and soothe-daemon hot paths.

### Resolved blocked removal

[`IG-blocked-removals-foundation-core.md`](IG-blocked-removals-foundation-core.md): `Job` dataclass confirmed unused (distinct from cron `JobStatus`); removed.

## Phase 2 (completed)

### Minimum supported versions

| Surface | Minimum | Policy |
|---------|---------|--------|
| StrangeLoop checkpoint JSON | `5.0` (`MIN_SUPPORTED_CHECKPOINT_SCHEMA_VERSION`) | Older `schema_version` values upgraded on read |
| SQLite `agentloop_loops.schema_version` default | `5.0` for new databases | Existing rows retain stored value until rewritten |
| ContextEngine ledger rows | `_msg_type` wire shape | Pre-RFC-624 `type`/`content`/`phase` rows normalized on read |
| SQLite `goal_records` | RFC-626 slim index | One-time table rebuild on first open when legacy columns exist |

### Consolidated compatibility (removed dual-path loaders)

| Location | Change |
|----------|--------|
| `context/engine.py` | `_normalize_ledger_entry()` upgrades pre-RFC-624 ledger rows; single reconstruction path in `load()` |
| `sloop/state/checkpoint.py` | `_strip_enriched_goal_index_fields()`; bumps sub-5.0 schema to 5.0 on read |
| `sloop/engine/synthesis_projection.py` | Removed stale XML `<USER_QUERY>` docstring (never implemented in code) |
| `sloop/prompts/user_message.py` | Clarified continuation-mode docstrings (not dead code) |

### Retained operational cleanup (not removed)

| Location | Reason |
|----------|--------|
| `sloop/state/persistence/sqlite_backend.py` `_migrate_goal_records_slim` | Required one-time upgrade for existing SQLite files |
| `sloop/prompts/user_message.py` `_GOAL_ITERATION_SUFFIX_RE` | Strips stale suffixes from persisted goal text |
| `workspace/resolution.py` `anon_*` cleanup | Removes pre-migration anonymous workspace dirs on shutdown |

### Tests added/updated

- `test_engine_completeness.py`: renamed legacy ledger compat test
- `test_checkpoint_normalize.py`: enriched `goal_history` stripping + schema bump
- `test_sqlite_goal_records_migration.py`: RFC-626 goal_records upgrade

## Verification

`./scripts/verify_finally.sh`
