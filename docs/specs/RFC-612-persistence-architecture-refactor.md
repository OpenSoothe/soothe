# RFC-612: Persistence Architecture Refactor

**Status**: Draft  
**Created**: 2026-04-22  
**Last Updated**: 2026-04-22  
**Authors**: Platonic Coding Workflow  
**Scope**: Backend storage unification, mode-based validation, in-memory removal

---

## Abstract

Refactor Soothe's persistence architecture to enforce production-grade storage, simplify backend options, and establish unified validation across all storage scenarios. Introduce mode-based validation (production requires PostgreSQL), remove all in-memory storage implementations, consolidate configuration into unified persistence section, and implement auto-provisioning for database initialization.

---

## Problem Statement

Soothe currently has **5 major persistence scenarios** with fragmented backend options and inconsistent validation:

1. **LangGraph Checkpoints** - CoreAgent execution state
2. **AgentLoop Checkpoints** - Loop orchestration metadata  
3. **Thread Metadata** - DurabilityProtocol thread lifecycle
4. **Vector Stores** - Context/memory embeddings
5. **Memory Backends** - MemU long-term user memory

**Current problems**:
- **In-memory storage allowed in production** - MemorySaver fallback creates ephemeral state
- **Too many backend options** - 5 storage backends (memory, sqlite, postgresql, rocksdb, json) per protocol
- **Inconsistent defaults** - Vector stores default to in_memory, others default to sqlite
- **Configuration fragmentation** - Persistence settings scattered across multiple config sections
- **No production enforcement** - Users can accidentally run production with sqlite/in-memory
- **Database organization inconsistency** - SQLite uses separate files, PostgreSQL uses single DSN

---

## Proposed Solution

### 1. Mode-Based Validation System

**Top-level mode switch**:
```yaml
mode: development | production
```

**Validation matrix**:

| Storage Backend | Development Mode | Production Mode |
|-----------------|------------------|-----------------|
| SQLite | ✅ Allowed | ❌ Rejected (hard error) |
| PostgreSQL | ✅ Allowed | ✅ Required |
| In-Memory | ❌ Removed | ❌ Removed |
| RocksDB/JSON | ❌ Removed | ❌ Removed |

**Startup validation sequence**:
1. Load configuration, read `mode` flag (defaults to development)
2. Validate all storage backends against mode rules
3. Production mode: Reject any sqlite/backend, emit migration guide
4. Development mode: Allow sqlite, reject in-memory, accept postgresql
5. Proceed only if validation passes

**Error messaging** (production violations):
```
Configuration Error: Production mode requires PostgreSQL backends.
Found: durability.backend=sqlite, checkpointer=sqlite, vector_stores.provider_type=sqlite_vec
Required: All backends must be postgresql.

Migration guide:
1. Set persistence.postgres_base_dsn with PostgreSQL connection
2. Configure persistence.postgres_databases for each purpose  
3. Remove backend=sqlite declarations
4. Switch vector_stores.provider_type to pgvector

See: docs/persistence-migration.md
```

---

### 2. Backend Selection Strategy

**Binary backend options**: Only SQLite and PostgreSQL supported.

**Removed backends**:
- InMemory/MemorySaver (all scenarios)
- RocksDB (DurabilityProtocol)
- JSON files (DurabilityProtocol)

**Backend selection logic**:
- **Development mode**: `default_backend` config honored (sqlite or postgresql)
- **Production mode**: Validation requires explicit PostgreSQL configuration (postgres_base_dsn + postgres_databases)
- **Per-protocol override**: Individual protocols can explicitly set backend (validated against mode)

**Configuration examples**:
```yaml
# Development mode
mode: development
persistence:
  default_backend: sqlite

# Production mode (postgresql required)
mode: production
persistence:
  postgres_base_dsn: "postgresql://user:pass@host:5432"  # REQUIRED
  postgres_databases:  # REQUIRED
    checkpoints: soothe_checkpoints
    metadata: soothe_metadata
    vectors: soothe_vectors
    memory: soothe_memory
```

---

### 3. Database Organization: Separate by Purpose

**Architectural principle**: Separate databases by logical purpose, consistent across both modes.

**Database mapping**:

| Purpose | PostgreSQL DB | SQLite File | Contents |
|---------|---------------|-------------|----------|
| LangGraph Checkpoints | soothe_checkpoints | langgraph_checkpoints.db | CoreAgent state |
| AgentLoop Checkpoints | soothe_checkpoints | loop_checkpoints.db | Loop metadata (same PG db) |
| Thread Metadata | soothe_metadata | metadata.db | DurabilityProtocol ThreadInfo |
| Vector Embeddings | soothe_vectors | vectors.db | pgvector/sqlite_vec |
| User Memory | soothe_memory | memory.db | MemU long-term memory |

**Separation rationale**:
1. **Lifecycle differences**: Checkpoints can be purged, metadata persists longer
2. **Backup granularity**: Backup critical metadata without checkpoint data
3. **Connection pooling**: Different pools per-purpose for isolation
4. **pgvector requirement**: Extension requires dedicated PostgreSQL database
5. **Consistent architecture**: Same logical separation across SQLite/PostgreSQL

**Schema design** (see detailed schemas in implementation section):

```sql
-- soothe_checkpoints (PostgreSQL)
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
    -- RFC-409 schema (already implemented)
    loop_id TEXT PRIMARY KEY,
    -- ... see RFC-409 for full schema
);

-- soothe_metadata
CREATE TABLE soothe_kv (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    PRIMARY KEY (namespace, key)
);

-- soothe_vectors (pgvector extension)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE embeddings (
    id TEXT PRIMARY KEY,
    embedding vector(1536),
    metadata JSONB,
    created_at TIMESTAMP
);
CREATE INDEX ON embeddings USING hnsw (embedding);
```

---

### 4. PostgreSQL Configuration Schema

**Unified configuration structure**:

```yaml
persistence:
  postgres_base_dsn: "postgresql://user:pass@host:port"
  
  postgres_databases:
    checkpoints: soothe_checkpoints  # Required if postgresql used
    metadata: soothe_metadata
    vectors: soothe_vectors
    memory: soothe_memory
  
  sqlite_paths:
    checkpoints: ""      # Empty → $SOOTHE_DATA_DIR/langgraph_checkpoints.db
    loop_checkpoints: "" # Empty → $SOOTHE_DATA_DIR/loop_checkpoints.db
    metadata: ""         # Empty → $SOOTHE_DATA_DIR/metadata.db
    vectors: ""          # Empty → $SOOTHE_DATA_DIR/vectors.db
    memory: ""           # Empty → $SOOTHE_DATA_DIR/memory.db
```

**Connection pattern**:
- Base DSN provides: host, port, credentials, SSL options (no database name)
- Each backend connects to: `{base_dsn}/{database_name}`
- Connection pools per-database for isolation

**SQLite defaults**: Convention-based paths if empty (developers don't configure paths manually).

---

### 5. Auto-Provisioning & Schema Initialization

**Database provisioning**: Auto-create missing databases on startup.

**Provisioning sequence**:
1. Validate mode + backend configuration
2. Resolve backend type (sqlite | postgresql)
3. If postgresql:
   - Connect to postgres_base_dsn (no database)
   - Check existence of each required database
   - CREATE DATABASE {name} for missing databases
   - Validate PostgreSQL privileges (CREATEDB permission)
   - Connect to each provisioned database
4. Initialize schemas (CREATE TABLE IF NOT EXISTS)
5. Verify connectivity
6. Start operations

**Required PostgreSQL privileges**:
- Base DSN user must have CREATEDB privilege
- CREATE TABLE, INSERT, UPDATE, DELETE on target databases
- CREATE EXTENSION permission (pgvector)

**Schema initialization**: Embedded schema, auto-sync on startup.

```python
class PostgreSQLPersistStore:
    def initialize_schema(self):
        """Auto-sync schema on startup."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS soothe_kv (...)
        """)
        # No migration version tracking (current scope)
```

**Migration extensibility**: Infrastructure can be added later for versioned migrations.

---

### 6. Vector Stores Unified Validation

**Vector stores follow same mode rules**:

| Mode | Allowed Providers |
|------|-------------------|
| Development | sqlite_vec, pgvector |
| Production | pgvector only |

**Removed**: InMemoryVectorStore deleted entirely.

**Configuration**:
```yaml
vector_stores:
  - name: pgvector_primary
    provider_type: pgvector  # Required in production
    dsn: "${PERSISTENCE_POSTGRES_BASE_DSN}/${PERSISTENCE_POSTGRES_VECTORS_DB}"
    pool_size: 5
    index_type: hnsw
```

**DSN derivation**: Uses `persistence.postgres_databases.vectors` name.

---

### 7. Configuration Schema: Unified Persistence Section

**Complete structure**:

```yaml
mode: production

persistence:
  default_backend: sqlite  # Development default, ignored in production
  
  postgres_base_dsn: "postgresql://postgres:postgres@localhost:5432"
  postgres_databases:
    checkpoints: soothe_checkpoints
    metadata: soothe_metadata
    vectors: soothe_vectors
    memory: soothe_memory
  
  sqlite_paths:
    checkpoints: ""
    loop_checkpoints: ""
    metadata: ""
    vectors: ""
    memory: ""

protocols:
  durability:
    backend: default  # Inherits default_backend or explicit: postgresql

vector_stores:
  - name: primary
    provider_type: pgvector
    dsn: "${PERSISTENCE_POSTGRES_BASE_DSN}/${PERSISTENCE_POSTGRES_VECTORS_DB}"
```

**Validation**:
- Mode + backend consistency check
- PostgreSQL DSN required when postgresql backend configured
- Database names required for all 4 purposes in production mode
- SQLite paths optional (default conventions)
- No in-memory/rocksdb/json references

---

### 8. Removed Components

**Deleted from codebase**:

| Component | Location | Action |
|-----------|----------|--------|
| MemorySaver | core/resolver/_resolver_infra.py | Remove fallback logic |
| InMemoryVectorStore | backends/vector_store/in_memory.py | Delete file |
| backend="memory" | config files | Remove from examples |
| RocksDB backend | backends/durability/rocksdb.py | Remove implementation |
| JSON backend | backends/durability/json.py | Remove implementation |
| backend="rocksdb" | config options | Remove from protocols.durability |
| backend="json" | config options | Remove from protocols.durability |

**Code changes**:
- Resolver: Remove MemorySaver fallback, error if backend unavailable
- Runner: Remove temporary MemorySaver initialization
- Vector store factory: Remove InMemoryVectorStore branch
- Config validation: Reject memory/rocksdb/json backend declarations
- Tests: Remove in-memory test fixtures

---

## Implementation Specification

### Phase 1: Remove In-Memory Storage

**Changes**:
1. Delete `InMemoryVectorStore` implementation
2. Remove `MemorySaver` fallback from resolver/runner
3. Remove rocksdb/json durability backends
4. Update configuration examples
5. Update tests (remove in-memory fixtures)

**Files affected**:
- `backends/vector_store/in_memory.py` - DELETE
- `backends/durability/rocksdb.py` - DELETE
- `backends/durability/json.py` - DELETE
- `core/resolver/_resolver_infra.py` - Remove fallback logic
- `core/runner/_runner_phases.py` - Remove MemorySaver initialization
- `tests/` - Update fixtures

---

### Phase 2: Add Mode-Based Validation

**Changes**:
1. Add `mode` field to `SootheConfig` model
2. Implement mode validation logic
3. Update resolver to validate backends against mode
4. Add startup validation errors with migration guidance
5. Update config templates

**Files affected**:
- `config/models.py` - Add mode field, validation logic
- `core/resolver/_resolver_infra.py` - Backend validation
- `config/config.yml` - Add mode section
- `config/config.dev.yml` - Development mode template

**Validation logic**:
```python
def validate_backends_for_mode(config: SootheConfig) -> None:
    """Validate all backends against mode."""
    if config.mode == "production":
        errors = []
        if config.protocols.durability.backend == "sqlite":
            errors.append("durability.backend=sqlite")
        if config.persistence.default_backend == "sqlite":
            errors.append("persistence.default_backend=sqlite")
        # Check vector stores
        for store in config.vector_stores:
            if store.provider_type == "sqlite_vec":
                errors.append(f"vector_stores[{store.name}].provider_type=sqlite_vec")
        
        if errors:
            raise ConfigurationError(
                f"Production mode requires PostgreSQL backends.\n"
                f"Found: {', '.join(errors)}\n"
                f"Required: All backends must be postgresql.\n\n"
                f"Migration guide:\n"
                f"1. Set persistence.postgres_base_dsn\n"
                f"2. Configure persistence.postgres_databases\n"
                f"3. Remove sqlite backend declarations\n"
                f"See: docs/persistence-migration.md"
            )
```

---

### Phase 3: Unified Persistence Configuration

**Changes**:
1. Add `postgres_base_dsn` and `postgres_databases` fields
2. Add `sqlite_paths` configuration section
3. Update backend resolution to use new structure
4. Remove old fields (consolidate)
5. Update config models

**Files affected**:
- `config/models.py` - Add new fields, remove old ones
- `core/resolver/_resolver_infra.py` - Update resolution logic
- `backends/persistence/*.py` - Update path/connection handling

**Model changes**:
```python
class PersistenceConfig(BaseModel):
    default_backend: Literal["sqlite", "postgresql"] = "sqlite"
    
    postgres_base_dsn: str | None = None
    postgres_databases: dict[str, str] | None = None
    
    sqlite_paths: dict[str, str] = Field(default_factory=dict)
    
    # Removed:
    # soothe_postgres_dsn: str  # Replaced by postgres_base_dsn + databases
    # metadata_sqlite_path: str  # Consolidated into sqlite_paths
    # checkpoint_sqlite_path: str  # Consolidated into sqlite_paths
```

---

### Phase 4: Auto-Provisioning & Schema Init

**Changes**:
1. Add database auto-provisioning logic
2. Implement schema initialization for all backends
3. Add PostgreSQL privilege validation
4. Test provisioning scenarios

**Files affected**:
- `backends/persistence/postgres_store.py` - Add provisioning
- `backends/persistence/sqlite_store.py` - Update schema init
- `backends/durability/*.py` - Add schema initialization
- `backends/vector_store/pgvector.py` - Add provisioning

**Provisioning implementation**:
```python
class PostgreSQLPersistStore:
    def provision_database(self, db_name: str) -> None:
        """Auto-provision database if missing."""
        # Connect to base DSN (no database)
        conn = psycopg.connect(self.base_dsn)
        
        # Check existence
        result = conn.execute(
            "SELECT datname FROM pg_database WHERE datname = %s",
            (db_name,)
        ).fetchone()
        
        if not result:
            logger.info(f"Creating database: {db_name}")
            conn.execute(f"CREATE DATABASE {db_name}")
            conn.commit()
        
        conn.close()
    
    def initialize_schema(self) -> None:
        """Auto-sync schema on startup."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS soothe_kv (...)
        """)
        self._conn.commit()
```

---

### Phase 5: Vector Store Validation

**Changes**:
1. Update vector store factory validation
2. Remove InMemoryVectorStore references
3. Update DSN resolution
4. Validate pgvector extension

**Files affected**:
- `backends/vector_store/__init__.py` - Update factory
- `backends/vector_store/pgvector.py` - Add provisioning
- `config/models.py` - Add vector store validation

---

### Phase 6: Testing & Documentation

**Changes**:
1. Add mode validation tests
2. Add provisioning tests
3. Add production restriction tests
4. Write migration guide
5. Update RFC-409 and related docs
6. Update user guide

**Test coverage**:
- Mode validation logic
- Backend consistency checks
- Database provisioning scenarios
- Schema initialization
- Production mode error messages
- Configuration parsing

**Documentation**:
- `docs/persistence-migration.md` - SQLite → PostgreSQL guide
- RFC-409 updates - Reference RFC-612 architecture
- User guide - New persistence configuration section

---

## Success Criteria

1. ✅ **No in-memory storage** - All tests pass with memory backends removed
2. ✅ **Mode validation** - Production mode rejects sqlite with clear errors
3. ✅ **Auto-provisioning** - PostgreSQL databases auto-created on startup
4. ✅ **Schema initialization** - All tables auto-created, no manual setup
5. ✅ **Unified config** - Single persistence section, clear structure
6. ✅ **Migration smoothness** - Dev config works unchanged, production guide available
7. ✅ **Backward compatibility** - Development mode uses existing SQLite paths by default

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Existing sqlite user data | Migration guide + doctor command |
| PostgreSQL auto-provision fails | Graceful error + privilege validation |
| Schema initialization race conditions | Connection pooling, WAL mode |
| pgvector extension missing | Pre-flight validation + install guide |
| Large checkpoint data in PostgreSQL | Partitioning strategy, retention docs |
| Connection pool exhaustion | Pool size config, monitoring docs |

---

## Future Extensions

1. **Migration infrastructure** - Alembic-style versioned migrations
2. **Backup/restore commands** - `soothe backup`, `soothe restore`
3. **Database metrics** - Pool monitoring, query performance
4. **Multi-region support** - PostgreSQL replication, read replicas
5. **Encryption at rest** - TLS + client encryption

---

## Related RFCs

- **RFC-409**: AgentLoop Persistence Backend Architecture (loop_checkpoints.db)
- **RFC-0002**: Core Modules Architecture (DurabilityProtocol, VectorStoreProtocol)
- **RFC-0013**: Daemon Multi-Transport Configuration (production deployment)

---

## Implementation Timeline

**Estimated effort**: 6 phases, 2-3 weeks total

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Remove in-memory storage | 2-3 days | None |
| Mode-based validation | 3-4 days | Phase 1 |
| Unified configuration | 2-3 days | Phase 2 |
| Auto-provisioning | 3-4 days | Phase 3 |
| Vector store validation | 2-3 days | Phase 4 |
| Testing & documentation | 3-4 days | All phases |

---

## Appendix A: Configuration Migration Examples

### Development Mode (Minimal Config)

```yaml
mode: development  # Optional, defaults to development

# No persistence section needed - uses SQLite defaults:
# - langgraph_checkpoints.db, loop_checkpoints.db, metadata.db
# - vectors.db (sqlite_vec), memory.db (MemU)

# Optional: Use PostgreSQL in dev
persistence:
  postgres_base_dsn: "postgresql://localhost:5432"
  postgres_databases:
    checkpoints: soothe_dev_checkpoints
    metadata: soothe_dev_metadata
    vectors: soothe_dev_vectors
    memory: soothe_dev_memory
```

### Production Mode (Full Config)

```yaml
mode: production

persistence:
  postgres_base_dsn: "postgresql://soothe_user:${SOOTHE_DB_PASSWORD}@db.internal:5432"
  postgres_databases:
    checkpoints: soothe_checkpoints
    metadata: soothe_metadata
    vectors: soothe_vectors
    memory: soothe_memory

vector_stores:
  - name: primary
    provider_type: pgvector
    dsn: "${PERSISTENCE_POSTGRES_BASE_DSN}/${PERSISTENCE_POSTGRES_VECTORS_DB}"
    pool_size: 10
    index_type: hnsw

protocols:
  durability:
    backend: postgresql  # Explicit (or use default)
```

---

## Appendix B: PostgreSQL Database Schema Details

**Detailed schemas for each purpose database** (see implementation for full SQL):

```sql
-- soothe_checkpoints database
CREATE TABLE langgraph_checkpoints (...);
CREATE TABLE loop_checkpoints (...);  -- RFC-409 schema
CREATE TABLE checkpoint_anchors (...);
CREATE TABLE failed_branches (...);
CREATE TABLE goal_records (...);

-- soothe_metadata database
CREATE TABLE soothe_kv (namespace, key, data, timestamps);
CREATE TABLE thread_history (...);

-- soothe_vectors database
CREATE EXTENSION vector;
CREATE TABLE embeddings (id, embedding vector(N), metadata, timestamps);
CREATE INDEX embeddings_hnsw_idx ON embeddings USING hnsw (embedding);

-- soothe_memory database
-- MemU schema (existing implementation)
```

---

**End of RFC-612**