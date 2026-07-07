# Unified Persistence Storage Implementation

> Implementation guide for unified PostgreSQL-based persistence across all Soothe components.
>
> **Module**: `soothe.backends.persistence`, `soothe.backends.durability`, `soothe.config`, `soothe.core.resolver`
> **Related**: RFC-001 (Core Protocols), RFC-500 (CLI/TUI Architecture), RFC-300 (Context/Memory Architecture), RFC-201 (Performance Optimization)
> **Created**: 2026-03-16
> **Updated**: 2026-03-16

---

## 1. Overview

### Problem Statement

Soothe previously had multiple persistence backends with inconsistent storage mechanisms:

1. **RESOLVED**: Checkpointer uses PostgreSQL (persistent, no async/sync conflicts)
2. **RESOLVED**: Unified PostgreSQL DSN for checkpointer and persistence backends
3. **RESOLVED**: Context/Memory/Durability now support PostgreSQL backend
4. **RESOLVED**: Renamed `StoreBackedMemory` → `KeywordMemory` for consistency
5. **RESOLVED**: Removed outdated `InMemoryDurability` and `LangGraphDurability` classes
6. **RESOLVED**: Renamed durability backend `langgraph` → `json` for clarity

### Solution

Unify all persistence with PostgreSQL as the default:
- **Checkpoints**: PostgreSQL (persistent, leverages pgvector infrastructure)
- **Durability/Context/Memory**: PostgreSQL (default), JSON or RocksDB (fallback)
- **Thread Logs**: JSONL files (human-readable conversation history)

### Target Architecture

```
~/.soothe/                          # SOOTHE_HOME
├── config/config.yml
├── context/
│   └── data/                       # JSON/RocksDB fallback
├── memory/
│   └── data/                       # JSON/RocksDB fallback
├── durability/
│   └── threads.json                # JSON fallback
├── threads/                        # ThreadLogger JSONL files
│   └── {thread_id}.jsonl
├── [PostgreSQL Database]           # Primary storage (persistent)
│   ├── checkpoints                 # LangGraph checkpoint state
│   ├── checkpoint_blobs            # Large binary data
│   ├── checkpoint_writes           # Pending writes
│   ├── checkpoint_config           # Thread configs
│   └── soothe_persistence          # Unified persistence table (context/memory/durability)
├── generated_agents/
├── logs/soothe.log
└── history.json
```

**Key Improvements**:
- **Single DSN**: One PostgreSQL connection for all persistence needs
- **Namespace isolation**: Each subsystem (context, memory, durability) uses separate namespace
- **Graceful fallback**: If PostgreSQL fails, falls back to JSON file storage
- **Production-ready**: PostgreSQL provides ACID guarantees and rich tooling

---

## 3. Architecture

### Dependencies

- **Existing**: `PersistStore` protocol, `RocksDBPersistStore`, `create_persist_store()` factory
- **Existing**: `DurabilityProtocol` and `ThreadInfo`/`ThreadMetadata` models
- **Existing**: `LangGraphDurability` pattern (reference implementation)
- **New**: `RocksDBDurability` implementation
- **New**: Cleanup/retention policies for ThreadLogger and Weaver

### Integration Points

1. **Configuration** (`src/soothe/config.py`):
   - Update default backends
   - Remove SQLite options
   - Add ThreadLogger/Weaver cleanup config

2. **Resolver** (`src/soothe/core/resolver.py`):
   - Add rocksdb durability case
   - Update checkpointer resolution (PostgreSQL only)
   - Remove SQLite cases

3. **ThreadLogger** (`src/soothe/cli/thread_logger.py`):
   - Add retention/cleanup logic
   - Keep logs in `SOOTHE_HOME/threads/` (per RFC-500)

4. **Daemon** (`src/soothe/cli/daemon.py`):
   - Add periodic cleanup task

5. **Weaver** (`src/soothe/subagents/weaver/registry.py`):
   - Add agent cleanup logic

---

## 4. Module Structure

### New Files

```
src/soothe/
├── backends/
│   └── durability/
│       └── rocksdb.py              # NEW: RocksDB durability backend
└── cli/
    └── migrate.py                  # NEW: Migration utility
```

### Modified Files

```
src/soothe/
├── config.py                       # Update defaults, add config
├── core/
│   └── resolver.py                 # Update resolution logic
├── cli/
│   ├── thread_logger.py            # Add cleanup logic
│   └── daemon.py                   # Add periodic cleanup
└── subagents/
    └── weaver/
        └── registry.py             # Add cleanup logic
```

---

## 5. Implementation Details

### 5.1 Configuration Updates

**File**: `src/soothe/config.py`

**Lines 411-421**: Remove SQLite, set PostgreSQL as default
```python
# BEFORE
checkpointer_backend: Literal["sqlite", "postgres"] = "sqlite"
checkpointer_sqlite_path: str | None = None
checkpointer_postgres_dsn: str | None = None

# AFTER
checkpointer_backend: Literal["postgres"] = "postgres"
checkpointer_postgres_dsn: str = "postgresql://postgres:postgres@localhost:5432/soothe"
```

**Lines 386, 398**: Change defaults to RocksDB
```python
# BEFORE
context_persist_backend: Literal["json", "rocksdb"] = "json"
memory_persist_backend: Literal["json", "rocksdb"] = "json"

# AFTER
context_persist_backend: Literal["json", "rocksdb"] = "rocksdb"
memory_persist_backend: Literal["json", "rocksdb"] = "rocksdb"
```

**Lines 411**: Change durability default
```python
# BEFORE
durability_backend: Literal["in_memory", "langgraph", "rocksdb"] = "in_memory"

# AFTER
durability_backend: Literal["langgraph", "rocksdb"] = "rocksdb"
```

**Add after line 424**: ThreadLogger configuration
```python
# Thread logging configuration
thread_log_dir: str | None = None  # Default: SOOTHE_HOME/threads
thread_log_retention_days: int = 30  # Auto-delete threads older than N days
thread_log_max_size_mb: int = 100  # Max total size for thread logs (not enforced yet)
```

**Lines 189-191**: Add Weaver cleanup configuration
```python
class WeaverConfig(BaseModel):
    # ... existing fields ...
    cleanup_old_agents_days: int = 100  # Delete agents not accessed for N days
    max_generated_agents: int = 100  # Max number of generated agents to keep
```

### 5.2 Resolver Updates

**File**: `src/soothe/core/resolver.py`

**Lines 567-584**: Update checkpointer resolution (PostgreSQL only)
```python
def resolve_checkpointer(config: SootheConfig) -> Checkpointer:
    """Resolve a LangGraph checkpointer from config.

    Falls back to ``MemorySaver`` when PostgreSQL is unavailable.
    """
    from langgraph.checkpoint.memory import MemorySaver

    backend = config.checkpointer_backend
    if backend == "postgres":
        return _resolve_postgres_checkpointer(config) or MemorySaver()

    logger.warning("Unknown checkpointer backend '%s'; using memory saver", backend)
    return MemorySaver()
```

**Lines 586-651**: Remove `_resolve_sqlite_checkpointer()` function completely

**Enhance PostgreSQL checkpointer resolution**:
```python
def _resolve_postgres_checkpointer(config: SootheConfig) -> Checkpointer | None:
    """Initialize PostgreSQL checkpointer."""
    dsn = config.checkpointer_postgres_dsn
    if not dsn:
        logger.warning("PostgreSQL checkpointer requires DSN configuration")
        return None

    # Try AsyncPostgresSaver first (better for async agent execution)
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        checkpointer = AsyncPostgresSaver.from_conn_string(dsn)
        logger.info("Using AsyncPostgresSaver with DSN: %s", _mask_dsn(dsn))
        return checkpointer
    except ImportError:
        logger.debug("AsyncPostgresSaver not available, trying sync version")
    except Exception as exc:
        logger.warning("Failed to initialize AsyncPostgresSaver: %s", exc)

    # Fallback to sync PostgresSaver
    try:
        from langgraph.checkpoint.postgres import PostgresSaver

        checkpointer = PostgresSaver.from_conn_string(dsn)
        logger.info("Using PostgresSaver with DSN: %s", _mask_dsn(dsn))
        return checkpointer
    except ImportError:
        logger.warning(
            "PostgreSQL checkpointer requires 'langgraph[postgres]'. "
            "Install with: pip install 'langgraph[postgres]'"
        )
    except Exception as exc:
        logger.warning("Failed to initialize PostgresSaver: %s", exc)

    return None

def _mask_dsn(dsn: str) -> str:
    """Mask password in DSN for logging."""
    import re
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:****@", dsn)
```

### 5.3 ThreadLogger Cleanup

**File**: `src/soothe/cli/thread_logger.py`

**Add new method**:
```python
def cleanup_old_threads(self) -> int:
    """Delete thread files older than retention_days.

    Returns:
        Number of threads deleted.
    """
    from datetime import timedelta

    cutoff = datetime.now(UTC) - timedelta(days=self._retention_days)
    deleted = 0

    try:
        self._ensure_dir()
        for thread_file in self._thread_dir.glob("*.jsonl"):
            try:
                # Check file modification time
                mtime = datetime.fromtimestamp(thread_file.stat().st_mtime, tz=UTC)
                if mtime < cutoff:
                    thread_file.unlink()
                    deleted += 1
                    logger.debug("Deleted old thread log: %s", thread_file.name)
            except Exception:
                logger.debug("Failed to process thread file %s", thread_file, exc_info=True)
                continue
    except Exception:
        logger.warning("Thread cleanup failed", exc_info=True)

    return deleted
```

### 5.4 Daemon Periodic Cleanup

**File**: `src/soothe/cli/daemon.py`

**Add new method**:
```python
async def _periodic_cleanup(self) -> None:
    """Run cleanup every 24 hours."""
    while self._running:
        await asyncio.sleep(24 * 3600)  # 24 hours
        if self._thread_logger:
            try:
                deleted = self._thread_logger.cleanup_old_threads()
                if deleted > 0:
                    logger.info("Cleaned up %d old thread logs", deleted)
            except Exception:
                logger.warning("Periodic cleanup failed", exc_info=True)
```

### 5.5 Weaver Agent Cleanup

**File**: `src/soothe/subagents/weaver/registry.py`

**Add new method**:
```python
def cleanup_old_agents(self, max_age_days: int = 30, max_agents: int = 100) -> int:
    """Remove old/unused generated agents.

    Args:
        max_age_days: Delete agents not accessed for N days.
        max_agents: Keep at most N agents (delete oldest first).

    Returns:
        Number of agents deleted.
    """
    from datetime import datetime, timedelta, UTC
    import shutil

    deleted = 0

    if not self._base_dir.is_dir():
        return deleted

    # Get all agents with their access times
    agents: list[tuple[Path, datetime]] = []
    try:
        for manifest_file in self._base_dir.glob("*/manifest.yml"):
            try:
                stat = manifest_file.stat()
                atime = datetime.fromtimestamp(stat.st_atime, tz=UTC)
                agents.append((manifest_file.parent, atime))
            except Exception:
                logger.debug("Failed to stat %s", manifest_file, exc_info=True)
                continue

        # Sort by access time (oldest first)
        agents.sort(key=lambda x: x[1])

        # Delete by age
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        for agent_dir, atime in agents:
            if atime < cutoff:
                try:
                    shutil.rmtree(agent_dir)
                    deleted += 1
                    logger.info("Deleted old generated agent: %s", agent_dir.name)
                except Exception:
                    logger.warning("Failed to delete agent %s", agent_dir, exc_info=True)

        # Delete by count (if still over limit)
        remaining = [(d, t) for d, t in agents if t >= cutoff]
        if len(remaining) > max_agents:
            for agent_dir, _ in remaining[:-max_agents]:
                try:
                    shutil.rmtree(agent_dir)
                    deleted += 1
                    logger.info("Deleted excess generated agent: %s", agent_dir.name)
                except Exception:
                    logger.warning("Failed to delete agent %s", agent_dir, exc_info=True)
    except Exception:
        logger.warning("Agent cleanup failed", exc_info=True)

    return deleted
```

---

## 6. Error Handling

### 6.1 PostgreSQL Checkpointer Failure

If PostgreSQL fails to initialize, the system falls back gracefully to `MemorySaver`:

```python
def _resolve_postgres_checkpointer(config: SootheConfig) -> Checkpointer | None:
    try:
        # Try to initialize PostgreSQL checkpointer
        ...
    except ImportError:
        logger.warning(
            "PostgreSQL checkpointer requires 'langgraph[postgres]'. "
            "Install with: pip install 'langgraph[postgres]'"
        )
    except Exception as exc:
        logger.warning("Failed to initialize PostgresSaver: %s", exc)

    return None  # Falls back to MemorySaver
```

### 6.2 RocksDB Initialization Failure

If RocksDB fails to initialize (e.g., missing `rocksdict` package), the system falls back to `LangGraphDurability`:

```python
def resolve_durability(config: SootheConfig) -> DurabilityProtocol:
    if config.durability_backend == "rocksdb":
        try:
            from soothe.backends.durability.rocksdb import RocksDBDurability
            return RocksDBDurability(persist_dir=persist_dir)
        except (ImportError, RuntimeError) as e:
            logger.warning(
                "RocksDB durability requested but dependencies unavailable: %s. "
                "Falling back to langgraph durability (JSON-based). "
                "Install with: pip install soothe[rocksdb]",
                e,
            )
            # Fall through to langgraph backend
    ...
```

### 6.3 Cleanup Failures

Cleanup operations should never crash the system:
- Wrap all cleanup in try/except
- Log failures but continue
- Return count of successful deletions

---

## 7. Configuration

### 7.1 New Configuration Options

```yaml
# config.yml example

# Thread logging
thread_log_dir: null  # Default: ~/.soothe/threads/
thread_log_retention_days: 30
thread_log_max_size_mb: 100

# Weaver cleanup
weaver:
  cleanup_old_agents_days: 30
  max_generated_agents: 100

# Persistence backends (new defaults)
checkpointer_backend: postgres  # Only option
checkpointer_postgres_dsn: "postgresql://postgres:postgres@localhost:5432/soothe"
context_persist_backend: rocksdb  # Was: json
memory_persist_backend: rocksdb   # Was: json
durability_backend: rocksdb       # Was: in_memory
```

### 7.2 Backward Compatibility

The following backends remain available for backward compatibility:
- `durability_backend: langgraph` (JSON file-based)
- `context_persist_backend: json`
- `memory_persist_backend: json`

**Note**: SQLite checkpointer backend is **removed** completely.

---

## 8. Testing Strategy

### 8.1 Unit Tests

**Test PostgreSQL Checkpointer**:
```python
# tests/unit_tests/test_checkpointer.py

@pytest.mark.asyncio
async def test_postgres_checkpointer_persistence():
    """Test that checkpoints persist in PostgreSQL."""
    dsn = "postgresql://postgres:postgres@localhost:5432/soothe_test"

    # Create and save checkpoint
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    checkpointer = AsyncPostgresSaver.from_conn_string(dsn)

    config = {"configurable": {"thread_id": "test-thread"}}
    checkpoint = {"id": "cp1", "messages": [...]}

    await checkpointer.aput(config, checkpoint, {}, {})

    # Verify persistence (simulate restart by creating new instance)
    checkpointer2 = AsyncPostgresSaver.from_conn_string(dsn)
    loaded = await checkpointer2.aget(config)

    assert loaded is not None
    assert loaded["id"] == "cp1"
```

### 8.2 Integration Tests

**Test Full Persistence Workflow**:
```bash
#!/bin/bash
# tests/integration/test_persistence.sh

# Start PostgreSQL
docker-compose up -d

# Run conversation
soothe run "Hello, I'm Alice"

# Stop daemon
soothe daemon stop

# Restart daemon
soothe daemon start

# Resume conversation
soothe attach
# Ask: "What's my name?"
# Should answer: "Your name is Alice"

# Verify PostgreSQL storage
psql -h localhost -U postgres -d soothe -c "SELECT * FROM checkpoints;"
```

---

## 9. Migration Guide

### For Existing Users

**No action required if using MemorySaver (was default):**
- MemorySaver was ephemeral anyway
- New PostgreSQL checkpointer provides persistence automatically

**If using SQLite config:**
```yaml
# OLD config.yml
checkpointer_backend: sqlite
checkpointer_sqlite_path: ~/.soothe/checkpoints.sqlite

# NEW config.yml (automatic)
checkpointer_backend: postgres
checkpointer_postgres_dsn: "postgresql://postgres:postgres@localhost:5432/soothe"
```

### For New Users

**Prerequisites:**
```bash
# Start pgvector
docker-compose up -d

# Install PostgreSQL support
pip install 'langgraph[postgres]'
```

**Configuration:**
```yaml
# config/config.yml (defaults)
checkpointer_backend: postgres
checkpointer_postgres_dsn: "postgresql://postgres:postgres@localhost:5432/soothe"
```

---

## 10. Verification

After implementation, verify:

1. **Daemon starts without errors**:
   ```bash
   soothe daemon start
   # Check logs for: "Using AsyncPostgresSaver with DSN: postgresql://postgres:****@localhost:5432/soothe"
   ```

2. **Checkpoints persist across restarts**:
   ```bash
   # Run conversation
   soothe run "Remember: my favorite color is blue"

   # Restart daemon
   soothe daemon stop && sleep 2 && soothe daemon start

   # Resume and ask
   soothe run "What's my favorite color?"
   # Should answer: "blue"
   ```

3. **PostgreSQL tables created**:
   ```bash
   psql -h localhost -U postgres -d soothe -c "\dt checkpoint*"
   # Should show: checkpoints, checkpoint_blobs, checkpoint_writes, checkpoint_config
   ```

4. **No RocksDB lock conflicts**:
   ```bash
   # Run multiple queries
   soothe run "query 1" --no-tui
   soothe run "query 2" --no-tui
   # Should not see: "IO error: While lock file"
   ```

---

## 11. Future Enhancements

Not in initial scope:
- Checkpoint cleanup/retention policies
- Checkpoint export/import
- Connection pooling configuration
- Multiple PostgreSQL instances (sharding)

---

## 12. References

- `src/soothe/protocols/durability.py` - DurabilityProtocol definition
- `src/soothe/backends/persistence/__init__.py` - PersistStore protocol
- `src/soothe/backends/persistence/rocksdb_store.py` - RocksDBPersistStore implementation
- `src/soothe/backends/durability/langgraph.py` - Reference implementation (JSON-based)
- `src/soothe/config.py` - Configuration model
- `src/soothe/core/resolver.py` - Backend resolution logic
- `docs/specs/RFC-500-cli-tui-architecture.md` - CLI/TUI Architecture (defines thread terminology)
- `docs/specs/RFC-201-agentic-goal-execution.md` - Performance Optimization