# IG-666: PostgreSQL Display Card Ledger

**Status**: Implemented  
**Date**: 2026-07-19  
**Related**: RFC-413, RFC-612, RFC-631

## Goal

When `persistence.default_backend: postgresql`, persist the RFC-413 display card ledger in PostgreSQL (`soothe_metadata`) instead of always using SQLite `display.db`.

## Changes

1. `PostgresDisplayCardStore` — sync psycopg pool store mirroring `DisplayCardStore` API
2. `configure_display_card_store(config)` — selects backend from `persistence.default_backend`
3. Daemon `start()` configures the store after Postgres DB provisioning
4. Schema added to `sql/soothe_metadata/init.sql`
5. RFC-413 / rfc-history / CHANGELOG updated

## Non-Goals

- Migrating existing SQLite `display.db` rows into Postgres
- New RFC-612 database key (reuses `metadata` / `soothe_metadata`)

## Verify

```bash
cd packages/soothe && python -m pytest tests/unit/backends/persistence/test_display_store_backend.py tests/unit/backends/persistence/test_goal_snapshot_auto_index.py -q
```
