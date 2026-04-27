# IG-055: AgentLoop Persistence Unification

**Status**: Completed  
**Completed**: 2026-04-27  
**Created**: 2026-04-27  
**RFC Reference**: RFC-612 (Multi-database PostgreSQL architecture)

## Objective

Merge AgentLoop's separate SQLite persistence system into the unified PostgreSQL persistence architecture to:
1. Eliminate dual persistence system complexity
2. Leverage RFC-612 `soothe_checkpoints` database for AgentLoop state
3. Improve production reliability with PostgreSQL-based persistence
4. Simplify backup and lifecycle management

## Current State

AgentLoop uses its own SQLite backend:
- Database: `/Users/xiamingchen/.soothe/data/loop_checkpoints.db`
- Managed by: `AgentLoopStateManager` → `SQLitePersistenceBackend`
- Separate from main Soothe PostgreSQL persistence (RFC-409, RFC-608)

Main persistence uses PostgreSQL:
- soothe_checkpoints (LangGraph conversation state)
- soothe_metadata (DurabilityProtocol ThreadInfo)
- soothe_vectors (pgvector embeddings)
- soothe_memory (MemU long-term memory)

## Target State

Unified PostgreSQL persistence with shared database:
- AgentLoop state stored in **`soothe_checkpoints` database** (shared with LangGraph)
- Same database, separate tables for schema isolation
- RFC-612 multi-database architecture:
  - `soothe_checkpoints` - LangGraph + AgentLoop checkpoints (shared)
  - `soothe_metadata` - DurabilityProtocol ThreadInfo
  - `soothe_vectors` - pgvector embeddings
  - `soothe_memory` - MemU long-term memory

Schema in shared database:
  - `langgraph_checkpoints` - LangGraph conversation checkpoints (existing)
  - `agentloop_checkpoints` - AgentLoop execution state (NEW)
  - JSON-based storage for flexible checkpoint data

## Implementation Plan

### Phase 1: Create PostgreSQL Backend

**File**: `src/soothe/cognition/agent_loop/persistence/postgres_backend.py`

1. Create `PostgreSQLPersistenceBackend` class:
   - Similar API to `SQLitePersistenceBackend`
   - Use psycopg connection pool
   - Support async operations
   - Schema creation for AgentLoop tables

2. Table schema:
   ```sql
   CREATE TABLE agentloop_checkpoints (
     loop_id TEXT PRIMARY KEY,
     thread_id TEXT NOT NULL,
     status TEXT NOT NULL,
     created_at TIMESTAMP,
     updated_at TIMESTAMP,
     checkpoint_data JSONB
   );
   
   CREATE TABLE agentloop_goals (
     goal_id TEXT PRIMARY KEY,
     loop_id TEXT NOT NULL,
     goal_index INTEGER,
     status TEXT,
     checkpoint_data JSONB
   );
   
   CREATE TABLE agentloop_steps (
     step_id TEXT PRIMARY KEY,
     goal_id TEXT NOT NULL,
     step_index INTEGER,
     status TEXT,
     checkpoint_data JSONB
   );
   ```

### Phase 2: Update State Manager

**File**: `src/soothe/cognition/agent_loop/state_manager.py`

1. Add configuration-driven backend selection:
   - Check `persistence.default_backend`
   - Use PostgreSQL when `postgresql` configured
   - Fall back to SQLite for backward compatibility

2. Modify `AgentLoopStateManager.__init__`:
   ```python
   def __init__(
       self, 
       loop_id: str | None = None,
       config: SootheConfig | None = None
   ):
       if config and config.persistence.default_backend == "postgresql":
           dsn = config.resolve_postgres_dsn_for_database("checkpoints")
           self.backend = PostgreSQLPersistenceBackend(dsn)
       else:
           self.backend = SQLitePersistenceBackend()
   ```

### Phase 3: Update Persistence Manager

**File**: `src/soothe/cognition/agent_loop/persistence/manager.py`

1. Update to support PostgreSQL backend
2. Add connection pool management
3. Implement async save/load operations

### Phase 4: Configuration Integration

**Files**: `config/config.yml`, `config/config.dev.yml`

1. Document AgentLoop uses `checkpoints` database
2. No separate configuration needed (inherits from persistence config)

### Phase 5: Migration Path

1. Automatic migration on first PostgreSQL startup:
   - Read existing SQLite `loop_checkpoints.db`
   - Write to PostgreSQL `soothe_checkpoints` database
   - Keep SQLite as backup (read-only)

2. Backward compatibility:
   - SQLite still works if PostgreSQL not configured
   - Development mode can use SQLite
   - Production mode uses PostgreSQL

## Files Modified

- `src/soothe/cognition/agent_loop/persistence/postgres_backend.py` - NEW PostgreSQL backend
- `src/soothe/cognition/agent_loop/state_manager.py` - Backend selection logic
- `src/soothe/cognition/agent_loop/persistence/manager.py` - PostgreSQL support
- `src/soothe/cognition/agent_loop/persistence/directory_manager.py` - Update path logic
- `src/soothe/config/models.py` - Document AgentLoop uses checkpoints database

## Testing Strategy

1. Unit tests for PostgreSQL backend
2. Integration tests for state manager with PostgreSQL
3. Migration tests (SQLite → PostgreSQL)
4. Backward compatibility tests

## Success Criteria

- ✅ AgentLoop uses PostgreSQL when configured
- ✅ SQLite fallback works for development
- ✅ Migration path documented
- ✅ No data loss during migration
- ✅ All tests passing