# IG-023: PostgreSQL DB Separation and Persistence Deadlock Fix

## Objective

Resolve PostgreSQL runtime failures and hangs by:
1. Fixing persistence deadlock in daemon/headless mode.
2. Separating configurable DSNs for Soothe metadata DB and vector DB.
3. Aligning Docker and config defaults so local startup works out of the box.

## Problem Statement

Two issues were observed together:

- PostgreSQL connection failures:
  - `FATAL: database "soothe" does not exist`
  - connection attempts alternating between `::1` and `127.0.0.1`
- Headless query hangs in daemon mode after query classification.

In local Docker setup, `docker-compose.yml` created `vectordb`, while
`config/config.yml` pointed persistence to `soothe`. In parallel, persistence
store internals could deadlock when called from the active event loop.

## Root Cause Analysis

### 1) Database mismatch

- `docker-compose.yml` initialized `POSTGRES_DB=vectordb`.
- `config/config.yml` used `persistence.postgres_dsn=.../soothe`.
- Result: persistence/checkpointer/durability tried to use a DB that did not
  exist in default local container startup.

### 2) Event-loop deadlock in persistence store

- `PostgreSQLPersistStore` exposed synchronous protocol methods (`save/load/delete`)
  but internally used `AsyncConnectionPool` + `run_coroutine_threadsafe(...).result()`.
- When those methods were invoked from the same running event loop (daemon path),
  `.result()` blocked the loop waiting for work that required the same loop.
- Result: stream stalled after "Query classified as ...", appearing as a hang.

## Design

### 1) Make `PostgreSQLPersistStore` truly synchronous

- Use psycopg `ConnectionPool` (sync) instead of `AsyncConnectionPool`.
- Keep `PersistStore` API synchronous and thread-safe with lazy init lock.
- Remove event-loop bridging in `save/load/delete`.

### 2) Add explicit configurable DSNs

- Add `persistence.soothe_postgres_dsn` for:
  - context/memory persistence
  - durability metadata
  - checkpointer
- Add `persistence.vector_postgres_dsn` for pgvector vector storage.

### 3) Runtime DSN resolution rules

- `resolve_persistence_postgres_dsn()`:
  - uses `soothe_postgres_dsn`
- `resolve_vector_store_config()`:
  - resolves env placeholders in `vector_store_config`
  - for `pgvector`, injects `dsn` from `vector_postgres_dsn` when not explicitly
    provided.

### 4) Docker initialization alignment

- Add init SQL script to create `soothe` database in addition to `vectordb`.
- Mount script into `docker-entrypoint-initdb.d` in compose service.

## Files

- `src/soothe/backends/persistence/postgres_store.py`
  - convert to sync pool and remove async-to-sync deadlock pattern
- `src/soothe/config.py`
  - add DSN fields and resolution helpers
- `src/soothe/core/resolver.py`
  - use resolved persistence DSN and resolved vector config
- `src/soothe/subagents/skillify/__init__.py`
- `src/soothe/subagents/weaver/__init__.py`
  - use resolved vector config for consistent pgvector DSN behavior
- `config/config.yml`
  - document/configure separate soothe/vector DSNs
- `docker-compose.yml`
- `config/init-db.sql`
  - create missing `soothe` DB in local setup

## Validation

- `soothe run --no-tui "who are you"` finishes successfully with daemon running.
- `soothe server stop` exits cleanly and removes pid/socket.
- starting daemon twice reports "already running" on second attempt.
- in dockerized postgres, both `vectordb` and `soothe` exist.
- config can be user-overridden via:
  - `persistence.soothe_postgres_dsn`
  - `persistence.vector_postgres_dsn`
  - optional `vector_store_config.dsn` explicit override
