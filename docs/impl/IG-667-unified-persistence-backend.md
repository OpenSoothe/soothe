# IG-667: Unified Persistence Backend (No Mixed Mode)

**Status**: Implemented  
**Date**: 2026-07-19  
**Related**: AGENTS.md §10, RFC-612, RFC-413, RFC-229, RFC-307

## Goal

`persistence.default_backend` is one mode for the whole process (`postgresql` XOR `sqlite`). Fill remaining SQLite hard-codes when Postgres is configured.

## Changes

1. AGENTS.md §10 — MUST rule
2. Display cards → Postgres (`soothe_metadata`) when postgresql (IG-666)
3. Cron → `PostgresCronJobStore` / `create_cron_job_store(config)`; SQLite default path `$SOOTHE_DATA_DIR/cron.db`
4. Identity → `postgres_dsn` path via `IdentityDbConnection` adapter; CLI uses same backend/path as daemon (`identity.db` or metadata DSN)
5. `configure_unified_persistence()` — display + override validation + vector warning
6. Skip SQLite WAL checkpoint on shutdown in Postgres mode
7. Schema: cron + identity tables in `sql/soothe_metadata/init.sql`

## Verify

```bash
cd packages/soothe && python -m pytest \
  tests/unit/foundation/persistence/test_unified_persistence.py \
  tests/unit/backends/persistence/test_display_store_backend.py \
  tests/unit/cron/test_store.py \
  tests/unit/core/security/test_identity_service.py -q
```
