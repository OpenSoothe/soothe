# Persistence Architecture Refactor Design

**Date**: 2026-04-22  
**Status**: Design Draft  
**Scope**: Backend storage unification, mode-based validation, in-memory removal

---

## Overview

Refactor Soothe's persistence architecture to enforce production-grade storage, simplify backend options, and establish unified validation across all storage scenarios.

**Key changes**:
- Remove all in-memory storage implementations
- Enforce mode-based validation (production requires PostgreSQL)
- Unify backend options to binary choice: SQLite (dev) or PostgreSQL (prod)
- Consolidate configuration schema into unified persistence section
- Auto-provision databases and initialize schemas on startup

---

## Current State Analysis

### Existing Persistence Scenarios

Soothe currently has **5 major persistence use cases**:

1. **LangGraph Checkpoints** - CoreAgent execution state (Layer 1)
2. **AgentLoop Checkpoints** - Loop orchestration metadata (Layer 2)
3. **Thread Metadata** - DurabilityProtocol thread lifecycle
4. **Vector Stores** - Context/memory embeddings
5. **Memory Backends** - MemU long-term user memory

### Current Storage Backends

| Scenario | Backends | Default |
|----------|----------|---------|
| LangGraph Checkpoints | postgresql, sqlite, memory | sqlite |
| AgentLoop Checkpoints | sqlite (global) | sqlite |
| DurabilityProtocol | postgresql, sqlite, rocksdb, json | sqlite |
| Vector Stores | pgvector, sqlite_vec, in_memory | in_memory |
| Memory | MemU (file-based) | file-based |

### Problems with Current Architecture

1. **In-memory storage allowed in production** - MemorySaver fallback creates ephemeral state
2. **Too many backend options** - 5 storage backends per protocol creates complexity
3. **Inconsistent defaults** - Vector stores default to in_memory, others default to sqlite
4. **Configuration fragmentation** - Persistence settings scattered across multiple sections
5. **No production enforcement** - Users can accidentally run production with sqlite/in-memory
6. **Database organization inconsistent** - SQLite uses separate files, PostgreSQL uses one DSN

---

## Architecture Design

### 1. Mode-Based Validation System

**Mode flag**: Top-level configuration switch

```yaml
mode: development | production
```

**Validation rules by mode**:

| Storage Backend | Development Mode | Production Mode |
|-----------------|------------------|-----------------|
| SQLite | ✅ Allowed | ❌ Rejected (hard error) |
| PostgreSQL | ✅ Allowed | ✅ Required |
| In-Memory | ❌ Removed | ❌ Removed |

**Startup validation sequence**:
1. Load configuration file
2. Read `mode` flag (defaults to `development` if unset)
3. Validate all storage backend declarations against mode rules
4. If production mode: Reject any sqlite/in-memory backend, error with migration guide
5. If development mode: Allow sqlite, reject in-memory, accept postgresql
6. Proceed only if all backends pass validation

**Error messages** (production mode violations):
```
Configuration Error: Production mode requires PostgreSQL backends.
Found: durability.backend=sqlite, checkpointer=sqlite, vector_stores.provider_type=sqlite_vec
Required: All backends must be postgresql.

Migration guide:
1. Set persistence.postgres_base_dsn with PostgreSQL connection
2. Configure persistence.postgres_databases for each purpose
3. Remove backend=sqlite declarations (postgresql auto-applied in production mode)
4. Switch vector_stores.provider_type to pgvector

See: docs/persistence-migration.md
```

---

### 2. Backend Selection Strategy

**Binary backend options**: Only two storage technologies supported

- **SQLite**: Development/testing mode, local single-user scenarios
- **PostgreSQL**: Production mode, multi-user deployments, scalability

**Removed backends**:
- InMemory/MemorySaver (all scenarios)
- RocksDB (DurabilityProtocol)
- JSON files (DurabilityProtocol)

**Backend selection logic**:

```yaml
persistence:
  default_backend: sqlite  # Honored in development mode
```

- **Development mode**: `default_backend` value respected (sqlite or postgresql)
- **Production mode**: `default_backend` field **ignored** (validation requires explicit postgresql backends)
  - Users must configure postgres_base_dsn and postgres_databases in production
  - No silent overrides - production mode enforces explicit PostgreSQL configuration
- **Per-protocol override**: Individual protocols can explicitly set backend (validated against mode)

**Configuration examples**:

```yaml
# Development mode - sqlite allowed
mode: development
persistence:
  default_backend: sqlite  # Used as default

protocols:
  durability:
    backend: postgresql  # Explicit override (allowed in dev mode)

# Production mode - postgresql required
mode: production
persistence:
  default_backend: sqlite  # IGNORED - validation error if postgres not configured
  postgres_base_dsn: "postgresql://user:pass@host:5432"  # REQUIRED
  postgres_databases:  # REQUIRED
    checkpoints: soothe_checkpoints
    metadata: soothe_metadata
    vectors: soothe_vectors
    memory: soothe_memory
```

---

### 3. Database Organization: Separate by Purpose

**Architectural principle**: Separate databases by logical purpose, not storage technology.

**Purpose-based databases** (both modes):

| Purpose | PostgreSQL Database | SQLite File | Contents |
|---------|---------------------|-------------|----------|
| LangGraph Checkpoints | soothe_checkpoints | langgraph_checkpoints.db | CoreAgent state |
| AgentLoop Checkpoints | soothe_checkpoints | loop_checkpoints.db | Loop metadata (same PG db) |
| Thread Metadata | soothe_metadata | metadata.db | DurabilityProtocol ThreadInfo |
| Vector Embeddings | soothe_vectors | vectors.db | pgvector/sqlite_vec embeddings |
| User Memory | soothe_memory | memory.db | MemU long-term memory |

**Rationale for separation**:

1. **Lifecycle differences**: Checkpoints can be purged, metadata persists longer
2. **Backup granularity**: Backup critical metadata without huge checkpoint data
3. **Connection pooling**: Different pools for high-frequency checkpoints vs low-frequency metadata
4. **pgvector requirement**: pgvector extension requires dedicated database
5. **Consistent architecture**: Same logical separation across SQLite and PostgreSQL

**Database schema design**:

```sql
-- soothe_checkpoints (PostgreSQL) / langgraph_checkpoints.db + loop_checkpoints.db (SQLite)
CREATE TABLE langgraph_checkpoints (
    thread_id TEXT PRIMARY KEY,
    checkpoint_ns TEXT,
    checkpoint_id TEXT,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint TEXT,  -- JSON blob
    metadata TEXT,    -- JSON blob
    created_at TIMESTAMP
);

CREATE TABLE loop_checkpoints (
    -- See RFC-409 schema (already implemented)
);

-- soothe_metadata (PostgreSQL) / metadata.db (SQLite)
CREATE TABLE soothe_kv (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    data TEXT NOT NULL,  -- JSON blob
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    PRIMARY KEY (namespace, key)
);

-- soothe_vectors (PostgreSQL with pgvector extension)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE embeddings (
    id TEXT PRIMARY KEY,
    embedding vector(1536),  -- Dimension from config
    metadata JSONB,
    created_at TIMESTAMP
);
CREATE INDEX ON embeddings USING hnsw (embedding);

-- soothe_memory (PostgreSQL) / memory.db (SQLite)
-- MemU schema (existing implementation)
```

---

### 4. PostgreSQL Configuration: Base DSN + Database Names

**Configuration schema**:

```yaml
persistence:
  postgres_base_dsn: "postgresql://user:pass@host:port"
  
  postgres_databases:
    checkpoints: soothe_checkpoints  # Required if any backend is postgresql
    metadata: soothe_metadata
    vectors: soothe_vectors
    memory: soothe_memory
```

**Connection pattern**:
- **Base DSN**: Provides connection details without database name
  - Host, port, credentials, SSL options, connection parameters
  - Format: `postgresql://{user}:{password}@{host}:{port}?{options}`
  
- **Database selection**: Backend connects to `{base_dsn}/{database_name}`
  - LangGraph checkpointer → `postgres_base_dsn/checkpoints_db`
  - DurabilityProtocol → `postgres_base_dsn/metadata_db`
  - VectorStoreProtocol → `postgres_base_dsn/vectors_db`
  - MemU memory → `postgres_base_dsn/memory_db`

**Connection pooling**:
- Each backend maintains independent connection pool
- Pool size configurable per-backend (vector_stores.pool_size, etc.)
- Separate pools isolate connection limits per-purpose

**SQLite path configuration**:

```yaml
persistence:
  sqlite_paths:
    checkpoints: ""     # Empty → $SOOTHE_DATA_DIR/langgraph_checkpoints.db
    loop_checkpoints: ""  # Empty → $SOOTHE_DATA_DIR/loop_checkpoints.db
    metadata: ""        # Empty → $SOOTHE_DATA_DIR/metadata.db
    vectors: ""         # Empty → $SOOTHE_DATA_DIR/vectors.db
    memory: ""          # Empty → $SOOTHE_DATA_DIR/memory.db
```

---

### 5. Auto-Provisioning & Schema Initialization

**Database provisioning strategy**: Auto-create missing databases on startup

**Provisioning sequence**:

```
Startup:
1. Validate mode + backend configuration
2. Resolve backend type (sqlite | postgresql)
3. If postgresql:
   a. Connect to postgres_base_dsn (no database)
   b. For each required database in postgres_databases:
      - Check existence (SELECT datname FROM pg_database)
      - If missing: CREATE DATABASE {name}
      - Validate required privileges (CREATEDB permission)
   c. Connect to each provisioned database
4. Initialize schemas in each database
5. Verify connectivity
6. Start agent/daemon operations
```

**Required PostgreSQL privileges**:
- Base DSN user must have `CREATEDB` privilege
- Must have CREATE TABLE, INSERT, UPDATE, DELETE on target databases
- pgvector: Must have permission to CREATE EXTENSION

**Schema initialization**: Embedded schema, auto-sync on startup

**Implementation pattern**:

```python
class PostgreSQLPersistStore:
    def initialize_schema(self):
        """Auto-sync schema on startup."""
        # CREATE TABLE IF NOT EXISTS pattern
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS soothe_kv (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                ...
            )
        """)
        # No migration version tracking (current scope)
```

**Migration extensibility**:
- Current scope: Schema auto-sync, no version tracking
- Future: Add migration infrastructure (Alembic-style versioned migrations)
- Structure ready: Can add `soothe/backends/persistence/migrations/` directory later

---

### 6. Vector Stores Unified Validation

**Vector stores follow same mode rules**: Unified storage policy across all backends

| Mode | Allowed Vector Providers |
|------|--------------------------|
| Development | sqlite_vec, pgvector |
| Production | pgvector only |

**Removed**: InMemoryVectorStore deleted entirely

**Configuration example**:

```yaml
mode: production

vector_stores:
  - name: pgvector_primary
    provider_type: pgvector  # Required in production
    dsn: "${PERSISTENCE_POSTGRES_BASE_DSN}/${PERSISTENCE_POSTGRES_VECTORS_DB}"
    pool_size: 5
    index_type: hnsw
```

**DSN derivation**: Vector stores use persistence.postgres_databases.vectors name

**Validation logic**:
- Production mode startup: Reject `provider_type: sqlite_vec`
- Development mode: Accept both sqlite_vec and pgvector
- DSN validation: Ensure vector store DSN matches persistence configuration

---

### 7. Configuration Schema: Unified Persistence Section

**Complete YAML structure**:

```yaml
# Top-level mode switch
mode: production  # development | production

persistence:
  # Backend selection
  default_backend: sqlite  # Development mode default, ignored in production
  
  # PostgreSQL configuration (required if any backend is postgresql)
  postgres_base_dsn: "postgresql://postgres:postgres@localhost:5432"
  postgres_databases:
    checkpoints: soothe_checkpoints  # Required in production
    metadata: soothe_metadata        # Required in production
    vectors: soothe_vectors          # Required in production
    memory: soothe_memory            # Required in production
  
  # SQLite paths (development mode defaults)
  sqlite_paths:
    checkpoints: ""      # Empty → $SOOTHE_DATA_DIR/langgraph_checkpoints.db
    loop_checkpoints: "" # Empty → $SOOTHE_DATA_DIR/loop_checkpoints.db
    metadata: ""         # Empty → $SOOTHE_DATA_DIR/metadata.db
    vectors: ""          # Empty → $SOOTHE_DATA_DIR/vectors.db
    memory: ""           # Empty → $SOOTHE_DATA_DIR/memory.db

# Protocol backend overrides (optional)
protocols:
  durability:
    backend: default  # Inherits default_backend, or explicit: postgresql
  # checkpointer inherited from persistence.default_backend
  
# Vector stores (validated against mode)
vector_stores:
  - name: primary
    provider_type: pgvector  # Required in production
    dsn: "${PERSISTENCE_POSTGRES_BASE_DSN}/${PERSISTENCE_POSTGRES_VECTORS_DB}"
    pool_size: 5
    index_type: hnsw

# Memory protocol (inherits backend from persistence.default_backend)
protocols:
  memory:
    enabled: true
    # Backend auto-selected based on mode (sqlite in dev, postgresql in prod)
```

**Configuration validation**:
- Mode + backend consistency check
- PostgreSQL DSN required when any postgresql backend configured
- Database names required for all 4 purposes in production mode
- SQLite paths optional (default convention if empty)
- No in-memory references anywhere

---

### 8. Removed Components

**Deleted from codebase**:

| Component | File/Location | Replacement |
|-----------|---------------|-------------|
| MemorySaver | core/resolver/_resolver_infra.py | Remove fallback, use sqlite/postgresql only |
| InMemoryVectorStore | backends/vector_store/in_memory.py | Delete file entirely |
| backend="memory" | config/config.yml | Remove option from docs/examples |
| RocksDB backend | backends/durability/rocksdb.py | Remove, keep sqlite/postgresql only |
| JSON backend | backends/durability/json.py | Remove, keep sqlite/postgresql only |
| backend="rocksdb" | protocols.durability.backend | Remove config option |
| backend="json" | protocols.durability.backend | Remove config option |

**Code changes**:
- Resolver: Remove `MemorySaver` fallback logic, error if backend unavailable
- Runner: Remove temporary MemorySaver initialization
- Vector store factory: Remove InMemoryVectorStore branch
- Config validation: Reject memory/rocksdb/json backend declarations
- Documentation: Remove all in-memory storage references

---

## Implementation Plan

### Phase 1: Remove In-Memory Storage

1. Delete `InMemoryVectorStore` implementation
2. Remove `MemorySaver` fallback from resolver/runner
3. Remove rocksdb/json durability backends
4. Update configuration examples (remove memory options)
5. Update tests (remove in-memory test fixtures)

### Phase 2: Add Mode-Based Validation

1. Add `mode` field to `SootheConfig` model
2. Implement mode validation logic (production rejects sqlite)
3. Update resolver to validate backends against mode
4. Add startup validation errors with migration guidance
5. Update config.dev.yml and config.yml templates

### Phase 3: Unified Persistence Configuration

1. Add `postgres_base_dsn` and `postgres_databases` fields
2. Add `sqlite_paths` configuration section
3. Update backend resolution to use new configuration structure
4. Remove old `soothe_postgres_dsn`, `metadata_sqlite_path` fields (consolidate)
5. Update config models, validation, and defaults

### Phase 4: Auto-Provisioning & Schema Init

1. Add database auto-provisioning logic (CREATE DATABASE)
2. Implement schema initialization for all backends
3. Add PostgreSQL privilege validation
4. Test provisioning with various PostgreSQL configurations
5. Handle provisioning errors gracefully

### Phase 5: Vector Store Validation

1. Update vector store factory to validate against mode
2. Remove InMemoryVectorStore references
3. Update vector store DSN resolution to use postgres_databases
4. Validate pgvector extension installation
5. Update vector store tests

### Phase 6: Testing & Documentation

1. Add tests for mode validation logic
2. Add tests for auto-provisioning
3. Add tests for production mode restrictions
4. Write migration guide (sqlite → postgresql)
5. Update RFC-409 and related docs
6. Update user guide with new persistence configuration

---

## Success Criteria

1. **No in-memory storage**: All tests pass with memory backends removed
2. **Mode validation**: Production mode rejects sqlite with clear errors
3. **Auto-provisioning**: PostgreSQL databases auto-created on startup
4. **Schema initialization**: All tables auto-created, no manual setup needed
5. **Unified config**: Single persistence section, clear structure
6. **Migration smoothness**: Dev config works unchanged, production guide available
7. **Backward compatibility**: Development mode uses existing SQLite paths by default

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Users have existing sqlite data | Migration guide + doctor command to assist transition |
| PostgreSQL auto-provision fails | Graceful error with privilege validation, manual fallback docs |
| Schema initialization race conditions | Connection pooling per-database, WAL mode for SQLite |
| pgvector extension missing | Pre-flight validation, installation guide in error message |
| Large checkpoint data in PostgreSQL | Partitioning strategy, retention policies, backup guidance |
| Connection pool exhaustion | Pool size configuration, monitoring docs |

---

## Future Extensions

1. **Migration infrastructure**: Add versioned migrations (Alembic-style) for schema evolution
2. **Backup/restore commands**: `soothe backup`, `soothe restore` CLI tools
3. **Database metrics**: Connection pool monitoring, query performance tracking
4. **Multi-region support**: PostgreSQL replication, read replicas for scalability
5. **Encryption at rest**: PostgreSQL TLS + client encryption for sensitive data

---

## Related RFCs

- RFC-409: AgentLoop Persistence Backend Architecture (loop_checkpoints.db)
- RFC-0002: Core Modules Architecture (DurabilityProtocol, VectorStoreProtocol)
- RFC-0013: Daemon Multi-Transport Configuration (production deployment)

---

## References

- Current SQLite backend: `backends/persistence/sqlite_store.py`
- Current PostgreSQL backend: `backends/persistence/postgres_store.py`
- Current vector stores: `backends/vector_store/` (pgvector, sqlite_vec, in_memory)
- LangGraph checkpointer: `core/resolver/_resolver_infra.py`
- Configuration models: `config/models.py`