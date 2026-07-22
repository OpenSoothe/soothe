# CE-StrangeLoop Integration: Gap Fixes + DB Persistence

Date: 2026-06-13
Status: Draft
RFC: RFC-624 (Context Engine)

## Summary

Close 5 integration gaps between ContextEngine and StrangeLoop, then add SQLite and PostgreSQL persistence backends for CE state. The CE path is always active (100% behavioral compatibility with the old PlanManager/GoalContextManager path is guaranteed by the CE implementation itself). SQLite is the new default persistence backend.

## Gap Fixes

### G1: Goal lifecycle -- add `fail_goal` calls

`goal_completion.py` calls `complete_goal` on success but never calls `fail_goal` on failure. Failed goals leave CE goal status stuck at "active".

**Fix**: In `goal_completion.py`, after the goal outcome is determined, if the outcome is not "completed", call `await ctx.ce.fail_goal(ctx.ce_goal_id, reason)`. The `reason` comes from the goal completion evidence or error summary.

### G2: Step methods become sync

`complete_step()`, `fail_step()`, `skip_step()`, `add_step()`, and `add_steps()` on `ContextEngine` are `async` but only perform in-memory DAG mutations and fire synchronous callbacks. No I/O occurs. Callers in graph nodes (e.g., `record_iteration.py`) invoke them without `await`, creating unawaited coroutines.

**Fix**: Change all five methods from `async def` to `def`. Remove `await` from any internal calls (none exist -- they're all sync). Update all call sites to drop `await`. The `ContextPersistenceProtocol` methods remain async since they do I/O.

### G3: Persistence cadence -- save after step execution

`ce.save()` is called after plan assess, resolve_decision, and goal_completion, but not after step execution. A crash between plan ingestion and goal completion loses step outcomes.

**Fix**: Add `await ctx.ce.save()` in `execute_steps.py` after each step execution completes (after the existing ledger recording and before the next step). This is a single line addition at the existing step-completion point.

### G4: Public semantic loading API

`strange_loop.py` accesses `ce_instance._semantic` directly to call `load_project_instructions()`, `load_agent_instructions()`, `load_memory()`. This is a private API.

**Fix**: Add `ContextEngine.load_semantic_context()` as a public sync method:

```python
def load_semantic_context(self, workspace: Path | None = None) -> None:
    if workspace is not None:
        self._semantic.workspace = workspace
    self._semantic.load_project_instructions()
    self._semantic.load_agent_instructions()
    self._semantic.load_memory()
```

Replace the `_semantic` access in `strange_loop.py` with this call. Error handling (try/except) moves to the caller as it is now.

### G5: Config model update

`ContextEngineConfig.persistence_backend` currently supports only `"file"` and `"in_memory"`. Need to add `"sqlite"` and `"postgresql"` options. Crucially, CE should use the Soothe default DB backend (same DB path/DSN as other persistence subsystems), not its own separate connection config.

**Fix**: Update `ContextEngineConfig`:

```python
class ContextEngineConfig(BaseModel):
    persistence_backend: Literal["sqlite", "postgresql", "file", "in_memory"] = Field(
        default="sqlite",
        description=(
            "Persistence backend for ContextEngine. "
            "'sqlite' and 'postgresql' use the Soothe default persistence backend "
            "(same database as checkpoints and KV store). "
            "'file' uses per-loop JSON files under SOOTHE_HOME. "
            "'in_memory' is for testing only."
        ),
    )
```

No `db_path` or `dsn` fields. When `persistence_backend` is `"sqlite"` or `"postgresql"`, the CE persistence backend derives the database path/DSN from `SootheConfig.persistence` (same as `StrangeLoopStateManager` does).

## Database Persistence

### Schema

Two dedicated tables for CE state, scoped by `loop_id`:

```sql
CREATE TABLE IF NOT EXISTS ce_dag (
    loop_id TEXT PRIMARY KEY,
    dag_json TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ce_ledger (
    loop_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    msg_type TEXT NOT NULL,
    phase TEXT,
    msg_json TEXT NOT NULL,
    PRIMARY KEY (loop_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_ce_ledger_loop_id ON ce_ledger(loop_id);
```

For PostgreSQL, `dag_json` and `msg_json` use JSONB type instead of TEXT.

### SqliteContextPersistence

File: `packages/soothe/src/soothe/context/sqlite_backend.py`

Implements `ContextPersistenceProtocol` (5 async methods):

- `save_dag(dag)`: Serialize `GoalStepDAG` to JSON via `.snapshot().model_dump_json()`, upsert into `ce_dag`
- `load_dag()`: Load from `ce_dag`, deserialize via `GoalStepDAGSnapshot.model_validate_json()` then reconstruct
- `save_ledger(messages)`: Delete existing ledger rows for `loop_id`, insert batch
- `load_ledger()`: SELECT all rows for `loop_id` ordered by `seq`, return list of dicts
- `clear()`: DELETE from both tables for `loop_id`

Pattern: follows `SQLitePersistStore` conventions:
- Single writer connection with `asyncio.Lock`
- `asyncio.to_thread` for all sync SQLite operations
- WAL mode, `PRAGMA foreign_keys=ON`
- Lazy connection initialization
- Shares the Soothe default SQLite database file (same as KV store and checkpoints)
- `close()` method for cleanup

Constructor:

```python
class SqliteContextPersistence:
    def __init__(self, loop_id: str, db_path: str | None = None) -> None:
        self._loop_id = loop_id
        self._db_path = db_path  # Derived from SootheConfig in strange_loop.py
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()
```

The `db_path` is resolved in `strange_loop.py` from the Soothe default persistence config, using the same path as `PersistenceDirectoryManager.get_loop_checkpoint_path()` or `SootheConfig.persistence.metadata_sqlite_path`.

### PostgresContextPersistence

File: `packages/soothe/src/soothe/context/postgres_backend.py`

Implements `ContextPersistenceProtocol` (5 async methods). Same method signatures as SQLite variant.

Pattern: follows `PostgreSQLPersistStore` conventions:
- `psycopg_pool.AsyncConnectionPool` with lazy initialization
- JSONB for `dag_json` and `msg_json` columns
- Auto-provisioning (CREATE TABLE IF NOT EXISTS on first use)
- `close()` method delegates to pool.close()
- Uses the same Soothe PostgreSQL DSN as other subsystems

Constructor:

```python
class PostgresContextPersistence:
    def __init__(self, loop_id: str, dsn: str, pool_size: int = 5) -> None:
        self._loop_id = loop_id
        self._dsn = dsn  # Derived from config.resolve_postgres_dsn_for_database("checkpoints")
        self._pool_size = pool_size
        self._pool: Any = None
        self._init_lock = asyncio.Lock()
```

The `dsn` is resolved in `strange_loop.py` from `config.resolve_postgres_dsn_for_database("checkpoints")`, using the same database as StrangeLoop checkpoints. CE tables live alongside checkpoint tables in the same database, scoped by table name prefix (`ce_dag`, `ce_ledger`).

### Serialization Strategy

**DAG serialization**: `GoalStepDAG.snapshot()` produces `GoalStepDAGSnapshot` (a Pydantic model). Serialize with `model_dump_json()`, deserialize with `model_validate_json()`, then reconstruct the `GoalStepDAG` from the snapshot. This requires adding a `GoalStepDAG.from_snapshot()` class method that rebuilds the DAG's internal `goals` dict and other fields from the snapshot data.

**Ledger serialization**: Same format as `FileContextPersistence` -- each entry is a dict with `_msg_type`, `_phase`, plus the full `BaseMessage.model_dump()` fields. The `seq` column preserves insertion order.

## Persistence Wiring in StrangeLoop

In `strange_loop.py:run_with_progress()`, replace the current persistence selection block with a 4-way switch. DB path/DSN is derived from the Soothe default persistence config (not from CE-specific config):

```python
persistence: ContextPersistenceProtocol
if ce_config.persistence_backend == "sqlite":
    from soothe.context.store_sqlite import SqliteContextPersistence
    # Use the same DB path as the Soothe default persistence subsystem
    db_path = getattr(self.config.persistence, 'metadata_sqlite_path', None)
    persistence = SqliteContextPersistence(
        loop_id=state_manager.loop_id,
        db_path=db_path,
    )
elif ce_config.persistence_backend == "postgresql":
    from soothe.context.postgres_backend import PostgresContextPersistence
    # Use the same DSN resolution as StrangeLoopStateManager
    dsn = self.config.resolve_postgres_dsn_for_database("checkpoints")
    persistence = PostgresContextPersistence(
        loop_id=state_manager.loop_id,
        dsn=dsn,
    )
elif ce_config.persistence_backend == "file":
    from soothe.context.file_backend import FileContextPersistence
    persistence = FileContextPersistence(
        loop_id=state_manager.loop_id,
        soothe_home=soothe_home,
    )
else:
    from soothe.context.in_memory import InMemoryContextPersistence
    persistence = InMemoryContextPersistence()
```

Also add `await persistence.close()` (or equivalent) in the `finally` block alongside `state_manager.close()` and `anchor_manager.close()`.

## Config Sync

Both `config/config.template.yml` and `config/develop/config.yml` update to:

```yaml
context_engine:
  persistence_backend: "sqlite"  # "sqlite" | "postgresql" | "file" | "in_memory"
```

No `db_path` or `dsn` fields. SQLite and PostgreSQL backends derive their connection details from the Soothe default persistence config (`persistence.default_backend`, `persistence.metadata_sqlite_path`, `persistence.resolve_postgres_dsn_for_database()`).

## Testing

- **Unit tests**: `SqliteContextPersistence` and `PostgresContextPersistence` CRUD round-trips (save_dag/load_dag, save_ledger/load_ledger, clear, empty-load returns None/[])
- **Fidelity test**: Create a CE with DAG + ledger state, save, create fresh CE with same persistence, load, verify DAG and ledger match
- **Existing tests**: All 2812 unit + 88 integration tests must continue passing
- **No new equivalence tests**: The existing `test_ce_strange_loop_equivalence.py` covers behavioral parity. The gap fixes are correctness fixes, not behavioral changes.

## File Change Summary

| File | Change |
|------|--------|
| `soothe/context/engine.py` | Make step methods sync (G2); add `load_semantic_context()` (G4) |
| `soothe/context/sqlite_backend.py` | **New**: SqliteContextPersistence |
| `soothe/context/postgres_backend.py` | **New**: PostgresContextPersistence |
| `soothe/context/__init__.py` | Update exports |
| `soothe/config/models.py` | Update ContextEngineConfig (G5) |
| `soothe/sloop/engine/strange_loop.py` | 4-way persistence switch; use `load_semantic_context()` (G4) |
| `soothe/sloop/nodes/goal_completion.py` | Add `fail_goal` call (G1) |
| `soothe/sloop/nodes/execute_steps.py` | Add `ce.save()` after step execution (G3) |
| `soothe/sloop/nodes/record_iteration.py` | Drop `await` from step method calls (G2) |
| `config/config.template.yml` | Update context_engine section |
| `config/develop/config.yml` | Update context_engine section |
| `packages/soothe/tests/unit/context/` | New test files for DB persistence |
