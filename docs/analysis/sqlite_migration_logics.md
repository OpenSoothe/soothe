# SQLite Migration Logics Analysis

**Analysis Date**: 2026-04-28

**Purpose**: Document SQLite backend migration patterns, architecture decisions, and lessons learned.

---

## Executive Summary

The Soothe project has migrated from PostgreSQL to SQLite for persistence backends, implementing three distinct SQLite storage systems with different use cases. The migration focused on async operations, connection pooling, schema versioning, and proper JSON field handling.

**Key Benefits**:
- Simplified deployment (no external database dependency)
- Better test isolation (file-based databases)
- WAL mode for concurrent reads
- Connection pooling for performance
- Zero-config development experience

---

## SQLite Backend Architecture

### 1. SQLitePersistStore (General Key-Value Store)

**Location**: `packages/soothe/src/soothe/backends/persistence/sqlite_store.py`

**Use Case**: General-purpose key-value persistence for durability protocol.

**Features**:
- Namespace isolation (multiple namespaces in single database)
- Async operations via `asyncio.to_thread()` (IG-258 Phase 2)
- Connection pool: 5 reader connections, 1 writer connection
- WAL mode for concurrent reads with single writer
- `asyncio.Lock` (not `threading.Lock`) to avoid event loop blocking

**Schema**:
```sql
CREATE TABLE soothe_kv (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (namespace, key)
)
```

**Migration Pattern** (IG-258 Phase 2):
```python
# Before: Sync blocking (BAD)
def save(self, key: str, data: Any) -> None:
    conn.execute("INSERT ...")
    conn.commit()

# After: Async non-blocking (GOOD)
async def save(self, key: str, data: Any) -> None:
    conn = await self._ensure_writer_connection()
    await asyncio.to_thread(self._save_sync, conn, namespace, key, serialized)
```

### 2. SQLiteVecStore (Vector Store)

**Location**: `packages/soothe/src/soothe/backends/vector_store/sqlite_vec.py`

**Use Case**: Vector similarity search for context/memory retrieval.

**Features**:
- sqlite-vec extension for vector operations
- Fallback to Python-side similarity if extension unavailable
- BLOB vector storage (not vec0 virtual tables)
- Distance metrics: cosine, L2, inner product
- Brute-force search fallback for compatibility

**Schema**:
```sql
CREATE TABLE vec_{collection} (
    id TEXT PRIMARY KEY,
    embedding BLOB NOT NULL,
    vector_size INTEGER NOT NULL,
    payload TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

**Migration Pattern**:
```python
# Pack vectors into F32 binary format
packed = struct.pack(f"{len(vector)}f", *vector)

# Try SQL distance function (sqlite-vec v0.1.x)
rows = conn.execute(
    "SELECT id, payload, vec_distance_cosine(embedding, ?) as dist FROM {table} ORDER BY dist ASC",
    (packed, limit)
).fetchall()
```

### 3. SQLitePersistenceBackend (AgentLoop Checkpoints)

**Location**: `packages/soothe/src/soothe/cognition/agent_loop/persistence/sqlite_backend.py`

**Use Case**: AgentLoop checkpoint persistence for autonomous execution history.

**Features**:
- Schema versioning (SCHEMA_VERSION = "3.1")
- Migration logic for existing databases
- JSON field serialization/deserialization
- Timestamp deserialization from ISO strings
- Backend-agnostic interface (IG-055)

**Schema Tables**:
- `agentloop_loops`: Loop metadata (thread_ids, current_thread_id, status)
- `checkpoint_anchors`: Iteration checkpoints (checkpoint_id, anchor_type, tools_executed)
- `failed_branches`: Failure history (failure_reason, execution_path, failure_insights)
- `goal_records`: Goal execution history (goal_text, status, goal_completion)

**Schema Migration Pattern**:
```python
@staticmethod
def migrate_schema_version(db_path: Path, target_version: str = "3.1") -> None:
    """Migrate existing loop records to target schema version."""
    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        # Check if there are any loops
        count_result = db.execute("SELECT COUNT(*) FROM agentloop_loops").fetchone()
        loop_count = count_result[0] if count_result else 0
        if loop_count == 0:
            return
        # Update schema version for all loops
        db.execute("UPDATE agentloop_loops SET schema_version = ?", (target_version,))
        db.commit()
```

---

## Critical Migration Issues & Fixes

### Issue 1: JSON Field Deserialization (Commits 9d1ffc8, 1cc3068)

**Problem**: SQLite stores JSON fields as TEXT strings, but the application expects Python objects (lists, dicts).

**Symptoms**:
```python
# Database returns string
row["tools_executed"] = '[{"name": "search", "args": {...}}]'

# Code expects list
tools: list[dict] = row["tools_executed"]  # WRONG! Type mismatch
```

**Solution**: Deserialize JSON fields when reading from database.

**Implementation** (`sqlite_backend.py`):
```python
def _deserialize_anchor_json_fields(self, row_dict: dict[str, Any]) -> dict[str, Any]:
    """Deserialize JSON fields and timestamp fields in anchor row."""
    # Deserialize tools_executed if present and not None
    if "tools_executed" in row_dict and row_dict["tools_executed"] is not None:
        row_dict["tools_executed"] = json.loads(row_dict["tools_executed"])

    # Deserialize timestamp field from ISO string to datetime
    if "timestamp" in row_dict and row_dict["timestamp"] is not None:
        row_dict["timestamp"] = datetime.fromisoformat(row_dict["timestamp"])

    return row_dict

def _get_anchors_range_sync(self, conn, loop_id, start, end) -> list[dict]:
    rows = conn.execute("SELECT ... FROM checkpoint_anchors WHERE ...").fetchall()
    # Apply deserialization to each row
    return [self._deserialize_anchor_json_fields(dict(row)) for row in rows]
```

**Affected Fields**:
- `checkpoint_anchors`: `tools_executed`
- `failed_branches`: `execution_path`, `failure_insights`, `avoid_patterns`, `suggested_adjustments`
- `agentloop_loops`: `thread_ids` (stored as JSON array)
- Timestamps: All ISO string fields converted to `datetime` objects

### Issue 2: Database Pollution in Integration Tests (Commit 1cc3068)

**Problem**: Integration tests polluted developer's local database (~/.soothe/data/metadata.db).

**Root Cause**: Tests used real SOOTHE_HOME/SOOTHE_DATA_DIR environment variables.

**Solution**: Mock both environment variables in integration tests.

**Implementation** (`test_detachment_reattachment.py`):
```python
from unittest.mock import patch
from pathlib import Path
import tempfile

@pytest.fixture
def mock_soothe_home():
    """Context manager to mock SOOTHE_HOME and SOOTHE_DATA_DIR for test isolation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        with patch("soothe_sdk.client.config.SOOTHE_HOME", tmp_path), \
             patch("soothe_sdk.client.config.SOOTHE_DATA_DIR", tmp_path / "data"):
            yield tmp_path

# Usage in test
def test_checkpoint_persistence(mock_soothe_home):
    manager = AgentLoopCheckpointPersistenceManager(db_path=None)  # None triggers default path resolution
    # Now uses isolated tmpdir, not ~/.soothe
```

**Why This Matters**:
- Tests should never modify developer's production data
- SQLite's file-based storage makes isolation critical
- PostgreSQL tests don't have this issue (server-based, database-per-test)

### Issue 3: Connection Pool Initialization

**Problem**: Connection pool needs lazy initialization to avoid blocking startup.

**Solution**: Use `asyncio.Lock` and lazy initialization pattern.

**Before** (BAD - blocking):
```python
def __init__(self):
    # BLOCKS EVENT LOOP!
    self._writer_conn = sqlite3.connect(db_path)
    self._init_reader_pool()  # BLOCKS!
```

**After** (GOOD - async lazy):
```python
def __init__(self):
    self._writer_conn = None  # Not initialized yet
    self._lock = asyncio.Lock()  # Async lock (not threading.Lock)

async def _ensure_writer_connection(self) -> sqlite3.Connection:
    if self._writer_conn is not None:
        return self._writer_conn

    async with self._lock:  # Prevent race conditions
        if self._writer_conn is not None:
            return self._writer_conn  # Double-checked locking

        # Execute sync operation in thread pool (non-blocking)
        await asyncio.to_thread(self._init_writer_connection)
        return self._writer_conn
```

---

## Migration Timeline

| Commit | Date | Description | Impact |
|--------|------|-------------|--------|
| b30f3c1 | 2026-04 | RFC-409: Isolated directory structure | Foundation for SQLite migration |
| d596061 | 2026-04 | Migrate AgentLoop to SQLite backend | Core persistence migration |
| ae72e3b | 2026-04 | Add sqlite-vec extension support | Vector store migration |
| 3fadc7f | 2026-04 | Change dev config to SQLite | Default backend change |
| 655dfd4 | 2026-04 | RFC-612: PostgreSQL multi-database architecture | Alternative backend design |
| 9d1ffc8 | 2026-04-27 | Fix JSON field deserialization | Critical data type fix |
| 1cc3068 | 2026-04-28 | Fix database pollution in tests | Test isolation fix |

---

## Architecture Patterns

### Pattern 1: Async-to-Sync Bridge

**Pattern**: Use `asyncio.to_thread()` to execute sync SQLite operations without blocking the event loop.

**Rationale**: SQLite's Python API is synchronous. Direct calls block the event loop, preventing concurrent operations.

**Code Pattern**:
```python
async def save(self, key: str, data: Any) -> None:
    conn = await self._ensure_writer_connection()
    serialized = json.dumps(data)

    # Execute sync operation in thread pool (non-blocking)
    await asyncio.to_thread(
        self._save_sync,
        conn,
        self._namespace,
        key,
        serialized,
    )

def _save_sync(self, conn: sqlite3.Connection, namespace: str, key: str, serialized: str) -> None:
    """Sync operation executed in thread pool."""
    conn.execute("INSERT INTO ... VALUES (?, ?, ?)", (namespace, key, serialized))
    conn.commit()
```

**Benefits**:
- Event loop remains responsive
- Multiple reads can run concurrently (semaphore-limited)
- Writer operations are serialized (single writer connection)

### Pattern 2: Reader Pool with Semaphore

**Pattern**: Pool of reader connections limited by semaphore for concurrent reads.

**Rationale**: SQLite WAL mode allows concurrent reads but limited connections prevent resource exhaustion.

**Code Pattern**:
```python
def __init__(self):
    self._reader_pool: list[sqlite3.Connection] = []
    self._pool_semaphore = asyncio.Semaphore(reader_pool_size)

async def load(self, key: str) -> Any | None:
    # Acquire semaphore (limits concurrent reads)
    async with self._pool_semaphore:
        conn = await self._get_reader_connection()

        # Execute sync read in thread pool
        row_data = await asyncio.to_thread(
            self._load_sync,
            conn,
            self._namespace,
            key,
        )

        # Return connection to pool
        async with self._lock:
            self._reader_pool.append(conn)

        return json.loads(row_data) if row_data else None
```

**Configuration**:
- Reader pool size: 5 connections (default)
- Semaphore: Limits concurrent reads to pool size
- Lock: Prevents race conditions in pool management

### Pattern 3: WAL Mode for Concurrency

**Pattern**: Enable WAL (Write-Ahead Logging) mode for concurrent reads.

**Rationale**: Default rollback journal blocks reads during writes. WAL allows concurrent reads with single writer.

**Code Pattern**:
```python
def _init_writer_connection(self) -> None:
    self._writer_conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
    self._writer_conn.execute("PRAGMA journal_mode=WAL")
    self._writer_conn.execute("PRAGMA foreign_keys=ON")
    self._writer_conn.row_factory = sqlite3.Row
```

**Benefits**:
- Reads don't block writes
- Writes don't block reads
- Multiple readers can read simultaneously
- Writer has exclusive access (serializable writes)

**Limitations**:
- Single writer only (no concurrent writes)
- WAL file grows without checkpointing (need periodic VACUUM)
- Not suitable for high write concurrency (>100 writes/sec)

### Pattern 4: Namespace Isolation

**Pattern**: Namespace column for multi-tenant storage in single database.

**Rationale**: Avoid creating multiple database files for different modules.

**Code Pattern**:
```python
CREATE TABLE soothe_kv (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (namespace, key)  # Composite primary key
)

CREATE INDEX idx_soothe_kv_namespace ON soothe_kv(namespace)

# Query by namespace
SELECT data FROM soothe_kv WHERE namespace = ? AND key = ?
```

**Benefits**:
- Single database file for multiple modules
- Clear data separation via namespace
- Index on namespace for fast queries
- No cross-namespace interference

**Example Namespaces**:
- `"durability"`: ThreadInfo storage
- `"context"`: Context ledger persistence
- `"memory"`: Agent memory state
- `"policy"`: Policy configuration cache

---

## Testing Patterns

### Pattern 1: Mock Environment Variables

**Pattern**: Mock `SOOTHE_HOME` and `SOOTHE_DATA_DIR` to isolate test databases.

**Code**:
```python
@pytest.fixture
def mock_soothe_home():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        with patch("soothe_sdk.client.config.SOOTHE_HOME", tmp_path), \
             patch("soothe_sdk.client.config.SOOTHE_DATA_DIR", tmp_path / "data"):
            yield tmp_path
```

**Why**: SQLite databases are files in `~/.soothe/data/`. Tests must not pollute production data.

### Pattern 2: Async Test Pattern

**Pattern**: Use `pytest-asyncio` for async backend tests.

**Code**:
```python
@pytest.mark.asyncio
async def test_sqlite_persist_store_save_load():
    store = SQLitePersistStore(db_path=":memory:", namespace="test")

    await store.save("key1", {"data": "value1"})
    result = await store.load("key1")

    assert result == {"data": "value1"}

    await store.close()
```

**Note**: Use `:memory:` for ephemeral test databases (no file cleanup needed).

### Pattern 3: Integration Test Pattern

**Pattern**: Test actual SQLite behavior, not mocks.

**Rationale**: SQLite's behavior is predictable. Mocking adds complexity without value.

**Code**:
```python
@pytest.mark.asyncio
async def test_checkpoint_persistence_workflow(mock_soothe_home):
    manager = AgentLoopCheckpointPersistenceManager(db_path=None)

    # Save checkpoint
    await manager.backend.save_checkpoint_anchor(
        loop_id="test-loop",
        iteration=1,
        thread_id="thread-1",
        checkpoint_id="cp-001",
        anchor_type="iteration_start",
        execution_summary={"tools_executed": [{"name": "search"}]}
    )

    # Retrieve checkpoint
    anchors = await manager.backend.get_checkpoint_anchors_for_range("test-loop", 1, 1)

    assert len(anchors) == 1
    assert anchors[0]["tools_executed"] == [{"name": "search"}]  # Deserialized!
```

---

## Lessons Learned

### Lesson 1: JSON Fields Need Explicit Deserialization

**Issue**: SQLite stores JSON as TEXT. Python code expects objects.

**Solution**: Deserialize on read, serialize on write. Add helper methods.

**Code Impact**: All retrieval methods must deserialize JSON fields.

**Why Not Automate**: SQLite doesn't support JSON column types like PostgreSQL. Manual handling is required.

### Lesson 2: Async Locks Prevent Event Loop Blocking

**Issue**: `threading.Lock` blocks the event loop during lock acquisition.

**Solution**: Use `asyncio.Lock` for async code, `threading.Lock` only for sync thread operations.

**Pattern**:
```python
# Event loop context: asyncio.Lock
self._lock = asyncio.Lock()
async with self._lock: ...

# Thread pool context: threading.Lock
self._thread_lock = threading.Lock()
with self._thread_lock: ...
```

### Lesson 3: Schema Versioning Enables Safe Migration

**Issue**: Database schema changes must handle existing data.

**Solution**: Store schema version in metadata table, run migrations on startup.

**Pattern**:
```python
SCHEMA_VERSION = "3.1"

CREATE TABLE agentloop_loops (
    schema_version TEXT DEFAULT '3.1'
)

# Migration on startup
migrate_schema_version(db_path, target_version="3.1")
```

### Lesson 4: WAL Mode is Essential for Concurrency

**Issue**: Default rollback journal blocks reads during writes.

**Solution**: Enable WAL mode immediately after connection.

**Code**: `conn.execute("PRAGMA journal_mode=WAL")`

**Benefit**: 5-10x performance improvement for concurrent operations.

### Lesson 5: Connection Pool Size is Tunable

**Issue**: Too many connections waste memory. Too few limit concurrency.

**Solution**: Default pool size = 5 readers. Tunable via config.

**Benchmark**:
- 5 readers: Handles 5 concurrent async reads
- 10 readers: More concurrency, but 2x memory
- Recommended: Start with 5, increase if bottleneck detected

### Lesson 6: Test Isolation is Critical for File-Based Storage

**Issue**: SQLite tests can pollute `~/.soothe/data/`.

**Solution**: Mock both `SOOTHE_HOME` and `SOOTHE_DATA_DIR` in all integration tests.

**Pattern**: Use `tempfile.TemporaryDirectory()` for automatic cleanup.

---

## Future Improvements

### Improvement 1: Connection Pool Health Checks

**Current**: Connections created once, never validated.

**Proposed**: Periodic connection health checks (execute `SELECT 1`).

**Benefit**: Detect broken connections, reconnect automatically.

### Improvement 2: WAL Checkpoint Automation

**Current**: WAL file grows indefinitely.

**Proposed**: Periodic WAL checkpoint (`PRAGMA wal_checkpoint(PASSIVE)`).

**Benefit**: Prevent unbounded WAL file growth.

### Improvement 3: Connection Pool Reuse Across Backends

**Current**: Each backend has its own connection pool.

**Proposed**: Shared connection pool service for all SQLite backends.

**Benefit**: Reduce memory usage, centralize connection management.

### Improvement 4: Async SQLite Library Evaluation

**Current**: `sqlite3` (sync) + `asyncio.to_thread()`.

**Alternative**: `aiosqlite` (native async SQLite wrapper).

**Evaluation**:
- `aiosqlite`: Native async, simpler code
- `sqlite3 + to_thread`: More control, better thread pool tuning
- Recommendation: Keep current pattern (more flexible)

### Improvement 5: Migration Framework

**Current**: Manual schema versioning, simple migration.

**Proposed**: Alembic-like migration framework for complex schema changes.

**Benefit**: Handle multi-step migrations, rollback support.

---

## Configuration Reference

### SQLitePersistStore Config

```yaml
persistence:
  backend: sqlite  # 'sqlite' or 'postgresql'
  db_path: ~/.soothe/data/soothe.db
  reader_pool_size: 5  # Number of concurrent readers
```

### SQLiteVecStore Config

```yaml
vector_store:
  provider: sqlite_vec  # 'sqlite_vec', 'pgvector', 'weaviate'
  db_path: ~/.soothe/data/vector.db
  collection: soothe_vectors
  vector_size: 1536  # Embedding dimension
  distance: cosine  # 'cosine', 'l2', 'ip'
```

### SQLitePersistenceBackend Config

```yaml
agent_loop:
  persistence:
    backend: sqlite  # SQLite backend for checkpoints
    db_path: ~/.soothe/data/langgraph_checkpoints.db
    pool_size: 5
```

---

## Related RFCs

| RFC | Title | Description |
|-----|-------|-------------|
| RFC-409 | AgentLoop Persistence Backend | SQLite backend architecture for checkpoints |
| RFC-612 | Multi-Database PostgreSQL Architecture | Alternative PostgreSQL backend design |
| IG-258 | Async SQLite Operations | Phase 2 async migration pattern |
| IG-055 | Backend-Agnostic Persistence | Abstract interface for swappable backends |

---

## Conclusion

The SQLite migration successfully simplified deployment and improved test isolation while maintaining performance through:

1. **Async patterns** (`asyncio.to_thread`) for non-blocking operations
2. **Connection pooling** (reader pool + semaphore) for concurrency
3. **WAL mode** for concurrent reads with single writer
4. **Schema versioning** for safe migrations
5. **JSON deserialization** for proper data type handling
6. **Test isolation** for development safety

**Primary Use Cases**:
- Development environments (zero-config, file-based)
- Testing environments (isolated, ephemeral databases)
- Small-scale production (<100 writes/sec)
- Edge deployments (no external database dependency)

**PostgreSQL Recommended When**:
- High write concurrency (>100 writes/sec)
- Multi-server deployment (shared database)
- Complex queries (full SQL feature set)
- Enterprise compliance (audit, replication)

---

**Document Status**: Complete

**Next Review**: After RFC-612 PostgreSQL architecture deployment