# IG-245: Persistence Architecture Refactor

**RFC**: RFC-612  
**Created**: 2026-04-22  
**Status**: Draft  
**Estimated Duration**: 2-3 weeks (6 phases)

---

## Overview

Implement RFC-612 persistence architecture refactor: mode-based validation, remove in-memory storage, unify configuration, auto-provision PostgreSQL databases.

**Key deliverables**:
- Remove all in-memory backend implementations
- Add mode validation system (production requires PostgreSQL)
- Consolidate persistence configuration schema
- Implement auto-provisioning for PostgreSQL databases
- Update vector store validation
- Complete testing and documentation

---

## Phase 1: Remove In-Memory Storage (2-3 days)

### Objective
Delete all in-memory storage implementations and fallback logic.

### Tasks

#### 1.1 Delete InMemoryVectorStore
**File**: `packages/soothe/src/soothe/backends/vector_store/in_memory.py`

```bash
# Delete file
rm packages/soothe/src/soothe/backends/vector_store/in_memory.py
```

**Update imports**:
- `backends/vector_store/__init__.py`: Remove InMemoryVectorStore import
- `__all__`: Remove "InMemoryVectorStore" from exports

#### 1.2 Remove MemorySaver Fallback
**File**: `packages/soothe/src/soothe/core/resolver/_resolver_infra.py`

**Changes**:
```python
# BEFORE:
def resolve_checkpointer(config: SootheConfig) -> Checkpointer:
    from langgraph.checkpoint.memory import MemorySaver
    
    backend = config.protocols.durability.checkpointer
    if backend == "postgresql":
        result = _resolve_postgres_checkpointer(dsn)
        if result:
            return result
        logger.info("PostgreSQL unavailable, falling back")
        return _resolve_sqlite_checkpointer(config) or MemorySaver()
    if backend == "sqlite":
        result = _resolve_sqlite_checkpointer(config)
        if result:
            return result
        logger.info("SQLite unavailable, using MemorySaver")
        return MemorySaver()
    if backend == "memory":
        return MemorySaver()
    
    return MemorySaver()

# AFTER:
def resolve_checkpointer(config: SootheConfig) -> Checkpointer:
    backend = config.protocols.durability.checkpointer
    
    if backend == "postgresql":
        result = _resolve_postgres_checkpointer(dsn)
        if result:
            return result
        raise ConfigurationError(
            "PostgreSQL checkpointer requested but unavailable. "
            "Check DSN configuration and PostgreSQL connectivity. "
            "No fallback - production requires persistent storage."
        )
    
    if backend == "sqlite":
        result = _resolve_sqlite_checkpointer(config)
        if result:
            return result
        raise ConfigurationError(
            "SQLite checkpointer requested but failed. "
            "Check sqlite3 installation and path configuration."
        )
    
    raise ConfigurationError(
        f"Unknown checkpointer backend: {backend}. "
        f"Supported: postgresql, sqlite"
    )
```

**Remove lines**:
- `from langgraph.checkpoint.memory import MemorySaver` (line 129)
- `self._checkpointer = MemorySaver()` (line 145 in runner)
- MemorySaver fallback logic (lines 138, 144, 150)

#### 1.3 Remove RocksDB and JSON Backends
**Files to delete**:
```bash
rm packages/soothe/src/soothe/backends/durability/rocksdb.py
rm packages/soothe/src/soothe/backends/durability/json.py
rm packages/soothe/src/soothe/backends/persistence/rocksdb_store.py
rm packages/soothe/src/soothe/backends/persistence/json_store.py
```

**Update imports**:
- `backends/durability/__init__.py`: Remove RocksDB, JSON exports
- `backends/persistence/__init__.py`: Remove RocksDBStore, JsonPersistStore exports

#### 1.4 Update Resolver Logic
**File**: `packages/soothe/src/soothe/core/resolver/_resolver_infra.py`

**Remove backend options**:
```python
# Remove these branches from resolve_durability():
if config.protocols.durability.backend == "rocksdb":
    # DELETE entire branch
    
if config.protocols.durability.backend == "json":
    # DELETE entire branch
```

**Keep only**:
```python
if config.protocols.durability.backend == "postgresql":
    # PostgreSQL implementation
    
if config.protocols.durability.backend == "sqlite":
    # SQLite implementation
    
raise ConfigurationError(
    f"Unsupported durability backend: {backend}. "
    f"Supported: postgresql, sqlite"
)
```

#### 1.5 Update Configuration Examples
**Files**:
- `config/config.yml`: Remove backend="memory", "rocksdb", "json" examples
- `config/config.dev.yml`: Remove in-memory references
- `packages/soothe/src/soothe/config/config.yml` template: Update comments

**Changes**:
```yaml
# BEFORE:
protocols:
  durability:
    backend: sqlite  # json | rocksdb | postgresql | sqlite | memory
    checkpointer: sqlite  # postgresql | sqlite | memory

# AFTER:
protocols:
  durability:
    backend: sqlite  # postgresql | sqlite (binary choice)
    checkpointer: sqlite  # postgresql | sqlite
```

#### 1.6 Update Tests
**Remove fixtures**:
- `tests/unit/backends/vector_store/test_in_memory.py` - DELETE
- `tests/unit/backends/durability/test_rocksdb.py` - DELETE
- `tests/unit/backends/durability/test_json.py` - DELETE

**Update test configurations**:
- Remove `backend="memory"` test cases
- Ensure all tests use sqlite or postgresql fixtures

---

### Verification
```bash
# Run tests after Phase 1
./scripts/verify_finally.sh

# Verify no memory imports
grep -r "MemorySaver\|InMemoryVectorStore" packages/soothe/src --include="*.py"
# Expected: 0 matches

# Verify no rocksdb/json imports  
grep -r "rocksdb\|json.*backend" packages/soothe/src --include="*.py"
# Expected: Only comments/docs, no implementation imports
```

---

## Phase 2: Add Mode-Based Validation (3-4 days)

### Objective
Implement top-level mode switch and validation logic.

### Tasks

#### 2.1 Add Mode Field to SootheConfig
**File**: `packages/soothe/src/soothe/config/models.py`

**Add new field**:
```python
class SootheConfig(BaseSettings):
    """Main configuration model."""
    
    # Add mode field at top
    mode: Literal["development", "production"] = "development"
    """Deployment mode switch."""
    
    # Existing fields...
    providers: list[ModelProviderConfig] = Field(default_factory=list)
    router: ModelRouter = ModelRouter()
    # ...
```

**Add validation**:
```python
from pydantic import field_validator

class SootheConfig(BaseSettings):
    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        """Validate mode configuration."""
        if v not in ("development", "production"):
            raise ValueError(f"Invalid mode: {v}. Must be 'development' or 'production'")
        return v
```

#### 2.2 Implement Backend Validation
**File**: `packages/soothe/src/soothe/config/models.py`

**Add method**:
```python
class SootheConfig(BaseSettings):
    def validate_backends_for_mode(self) -> list[str]:
        """Validate all backends against mode rules.
        
        Returns list of validation errors (empty if valid).
        """
        errors = []
        
        if self.mode == "production":
            # Check durability backend
            if self.protocols.durability.backend == "sqlite":
                errors.append("protocols.durability.backend=sqlite")
            
            # Check default_backend
            if self.persistence.default_backend == "sqlite":
                errors.append("persistence.default_backend=sqlite")
            
            # Check checkpointer
            if self.protocols.durability.checkpointer == "sqlite":
                errors.append("protocols.durability.checkpointer=sqlite")
            
            # Check vector stores
            for store in self.vector_stores:
                if store.provider_type == "sqlite_vec":
                    errors.append(f"vector_stores.{store.name}.provider_type=sqlite_vec")
        
        return errors
    
    def raise_if_invalid_for_mode(self) -> None:
        """Raise ConfigurationError if backends violate mode rules."""
        errors = self.validate_backends_for_mode()
        
        if errors:
            raise ConfigurationError(
                f"Production mode requires PostgreSQL backends.\n"
                f"Found: {', '.join(errors)}\n"
                f"Required: All backends must be postgresql.\n\n"
                f"Migration guide:\n"
                f"1. Set persistence.postgres_base_dsn with PostgreSQL connection\n"
                f"2. Configure persistence.postgres_databases for each purpose\n"
                f"3. Remove backend=sqlite declarations\n"
                f"4. Switch vector_stores.provider_type to pgvector\n\n"
                f"See: docs/persistence-migration.md"
            )
```

#### 2.3 Update Resolver Validation
**File**: `packages/soothe/src/soothe/core/resolver/_resolver_infra.py`

**Add validation call**:
```python
def resolve_durability(config: SootheConfig) -> DurabilityProtocol:
    """Instantiate DurabilityProtocol implementation."""
    
    # Validate mode compatibility
    config.raise_if_invalid_for_mode()
    
    # Proceed with resolution
    if config.protocols.durability.backend == "postgresql":
        # PostgreSQL implementation
    elif config.protocols.durability.backend == "sqlite":
        # SQLite implementation (development mode only)
    else:
        raise ConfigurationError(...)
```

**Similar validation** for:
- `resolve_checkpointer()`
- `resolve_vector_stores()`

#### 2.4 Update Runner Initialization
**File**: `packages/soothe/src/soothe/core/runner/__init__.py`

**Add validation**:
```python
class SootheRunner:
    def __init__(self, config: SootheConfig | None = None) -> None:
        self._config = config or SootheConfig()
        
        # Validate mode compatibility before initialization
        self._config.raise_if_invalid_for_mode()
        
        # Proceed with initialization...
```

#### 2.5 Update Config Templates
**File**: `packages/soothe/src/soothe/config/config.yml`

**Add mode section**:
```yaml
# =============================================================================
# Deployment Mode
# =============================================================================
# Deployment mode controls storage backend validation and defaults.

mode: development  # development | production
  # development: Allows SQLite backends, simpler local setup
  # production: Requires PostgreSQL backends, enforced validation
```

**File**: `config/config.dev.yml`

```yaml
# Development mode (default)
mode: development  # Optional - defaults to development

# Use SQLite defaults (no explicit persistence config needed)
```

**Production example**: Create `config/config.prod.yml.example`

```yaml
mode: production

persistence:
  postgres_base_dsn: "postgresql://user:${DB_PASSWORD}@host:5432"
  postgres_databases:
    checkpoints: soothe_checkpoints
    metadata: soothe_metadata
    vectors: soothe_vectors
    memory: soothe_memory

vector_stores:
  - name: primary
    provider_type: pgvector
    dsn: "${PERSISTENCE_POSTGRES_BASE_DSN}/${PERSISTENCE_POSTGRES_VECTORS_DB}"
```

---

### Verification
```bash
# Test mode validation
python -c "
from soothe.config import SootheConfig

# Test production mode rejects sqlite
config = SootheConfig(mode='production')
config.persistence.default_backend = 'sqlite'
errors = config.validate_backends_for_mode()
print(f'Production + SQLite errors: {errors}')
# Expected: ['persistence.default_backend=sqlite']

# Test development mode allows sqlite
config = SootheConfig(mode='development')
errors = config.validate_backends_for_mode()
print(f'Development + SQLite errors: {errors}')
# Expected: [] (empty)
"

# Run unit tests
pytest tests/unit/config/test_mode_validation.py -v
```

---

## Phase 3: Unified Persistence Configuration (2-3 days)

### Objective
Consolidate configuration fields into unified persistence section.

### Tasks

#### 3.1 Add New Configuration Fields
**File**: `packages/soothe/src/soothe/config/models.py`

**Add PersistenceConfig model**:
```python
class PersistenceConfig(BaseModel):
    """Unified persistence configuration.
    
    Args:
        default_backend: Default backend for protocols (sqlite | postgresql).
        postgres_base_dsn: PostgreSQL connection string without database name.
        postgres_databases: Database names for each purpose (checkpoints, metadata, vectors, memory).
        sqlite_paths: SQLite file paths for each purpose (empty = default convention).
    """
    
    default_backend: Literal["sqlite", "postgresql"] = "sqlite"
    
    postgres_base_dsn: str | None = None
    postgres_databases: dict[str, str] | None = None
    
    sqlite_paths: dict[str, str] = Field(default_factory=lambda: {
        "checkpoints": "",
        "loop_checkpoints": "",
        "metadata": "",
        "vectors": "",
        "memory": "",
    })
    
    @field_validator("postgres_databases")
    @classmethod
    def validate_postgres_databases(cls, v: dict | None) -> dict | None:
        """Validate required database names."""
        if v is not None:
            required_keys = ["checkpoints", "metadata", "vectors", "memory"]
            missing = [k for k in required_keys if k not in v]
            if missing:
                raise ValueError(f"Missing required databases: {missing}")
        return v
```

**Update SootheConfig**:
```python
class SootheConfig(BaseSettings):
    # Replace old fields with unified section
    persistence: PersistenceConfig = PersistenceConfig()
    
    # REMOVE these old fields:
    # soothe_postgres_dsn: str  # Replaced by postgres_base_dsn + databases
    # metadata_sqlite_path: str  # Replaced by sqlite_paths["metadata"]
    # checkpoint_sqlite_path: str  # Replaced by sqlite_paths["checkpoints"]
```

#### 3.2 Update Backend Resolution
**File**: `packages/soothe/src/soothe/core/resolver/_resolver_infra.py`

**Update SQLite checkpointer**:
```python
def _resolve_sqlite_checkpointer(config: SootheConfig) -> Checkpointer | None:
    """Initialize SQLite checkpointer."""
    
    # Use new configuration
    db_path = config.persistence.sqlite_paths.get("checkpoints", "")
    if not db_path:
        # Default convention
        db_path = str(Path(SOOTHE_DATA_DIR) / "langgraph_checkpoints.db")
    
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    
    logger.info("SQLite checkpointer at %s", db_path)
    return (None, conn)
```

**Update PostgreSQL checkpointer**:
```python
def _resolve_postgres_checkpointer(config: SootheConfig) -> Checkpointer | None:
    """Initialize PostgreSQL checkpointer."""
    
    base_dsn = config.persistence.postgres_base_dsn
    db_name = config.persistence.postgres_databases["checkpoints"]
    
    if not base_dsn or not db_name:
        logger.warning("PostgreSQL configuration incomplete")
        return None
    
    # Connect to specific database
    full_dsn = f"{base_dsn}/{db_name}"
    pool = AsyncConnectionPool(full_dsn)
    
    logger.info("PostgreSQL checkpointer at %s", full_dsn)
    return (None, pool)
```

#### 3.3 Update Backend Implementations
**File**: `packages/soothe/src/soothe/backends/durability/sqlite.py`

**Update initialization**:
```python
class SQLiteDurability(BasePersistStoreDurability):
    def __init__(self, persist_store=None, db_path=None) -> None:
        if persist_store is None:
            # Use new configuration
            from soothe_sdk.client.config import SOOTHE_DATA_DIR
            
            actual_path = db_path or str(Path(SOOTHE_DATA_DIR) / "metadata.db")
            persist_store = SQLitePersistStore(actual_path, namespace="durability")
        
        super().__init__(persist_store)
```

**Similar updates** for:
- `backends/persistence/sqlite_store.py`
- `backends/persistence/postgres_store.py`
- `backends/vector_store/pgvector.py`
- `backends/vector_store/sqlite_vec.py`

#### 3.4 Update Config Template
**File**: `packages/soothe/src/soothe/config/config.yml`

**Replace old persistence section**:
```yaml
# BEFORE:
persistence:
  soothe_postgres_dsn: "postgresql://..."
  default_backend: sqlite
  metadata_sqlite_path: ""
  checkpoint_sqlite_path: ""

# AFTER:
persistence:
  default_backend: sqlite
  
  postgres_base_dsn: "postgresql://postgres:postgres@localhost:5432"
  postgres_databases:
    checkpoints: soothe_checkpoints
    metadata: soothe_metadata
    vectors: soothe_vectors
    memory: soothe_memory
  
  sqlite_paths:
    checkpoints: ""      # Empty = $SOOTHE_DATA_DIR/langgraph_checkpoints.db
    loop_checkpoints: "" # Empty = $SOOTHE_DATA_DIR/loop_checkpoints.db
    metadata: ""         # Empty = $SOOTHE_DATA_DIR/metadata.db
    vectors: ""          # Empty = $SOOTHE_DATA_DIR/vectors.db
    memory: ""           # Empty = $SOOTHE_DATA_DIR/memory.db
```

---

### Verification
```bash
# Test configuration parsing
python -c "
from soothe.config import SootheConfig

# Test SQLite defaults
config = SootheConfig()
print(config.persistence.sqlite_paths)
# Expected: {'checkpoints': '', ...}

# Test PostgreSQL config
config = SootheConfig(
    persistence={
        'postgres_base_dsn': 'postgresql://localhost:5432',
        'postgres_databases': {
            'checkpoints': 'soothe_cp',
            'metadata': 'soothe_meta',
            'vectors': 'soothe_vec',
            'memory': 'soothe_mem'
        }
    }
)
print(config.persistence.postgres_databases)
# Expected: dict with 4 keys
"

# Test backend resolution
pytest tests/unit/core/resolver/test_persistence_resolution.py -v
```

---

## Phase 4: Auto-Provisioning & Schema Init (3-4 days)

### Objective
Implement automatic database creation and schema initialization.

### Tasks

#### 4.1 Add PostgreSQL Provisioning
**File**: `packages/soothe/src/soothe/backends/persistence/postgres_store.py`

**Add provisioning method**:
```python
class PostgreSQLPersistStore:
    def provision_database(self, base_dsn: str, db_name: str) -> None:
        """Auto-provision PostgreSQL database if missing.
        
        Args:
            base_dsn: Connection string without database name.
            db_name: Database name to create.
        """
        import psycopg
        
        # Connect to PostgreSQL server (no specific database)
        conn = psycopg.connect(base_dsn)
        
        try:
            # Check if database exists
            result = conn.execute(
                "SELECT datname FROM pg_database WHERE datname = %s",
                (db_name,)
            ).fetchone()
            
            if not result:
                logger.info(f"Creating PostgreSQL database: {db_name}")
                conn.execute(f"CREATE DATABASE {db_name}")
                conn.commit()
                logger.info(f"Database {db_name} created successfully")
            
        except Exception as e:
            logger.error(f"Failed to provision database {db_name}: {e}")
            raise ConfigurationError(
                f"PostgreSQL database provisioning failed: {db_name}\n"
                f"Error: {e}\n"
                f"Ensure PostgreSQL user has CREATEDB privilege"
            )
        finally:
            conn.close()
```

#### 4.2 Add Schema Initialization
**File**: `packages/soothe/src/soothe/backends/persistence/postgres_store.py`

**Add schema init**:
```python
class PostgreSQLPersistStore:
    def initialize_schema(self) -> None:
        """Initialize database schema (tables, indexes)."""
        
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS soothe_kv (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (namespace, key)
            )
        """)
        
        self._conn.commit()
        logger.info("Schema initialized in database")
```

#### 4.3 Update Resolver Startup
**File**: `packages/soothe/src/soothe/core/resolver/_resolver_infra.py`

**Add provisioning step**:
```python
def resolve_durability(config: SootheConfig) -> DurabilityProtocol:
    """Instantiate DurabilityProtocol with auto-provisioning."""
    
    config.raise_if_invalid_for_mode()
    
    if config.protocols.durability.backend == "postgresql":
        from soothe.backends.persistence import PostgreSQLPersistStore
        
        base_dsn = config.persistence.postgres_base_dsn
        db_name = config.persistence.postgres_databases["metadata"]
        
        # Auto-provision database
        store = PostgreSQLPersistStore()
        store.provision_database(base_dsn, db_name)
        
        # Connect to provisioned database
        full_dsn = f"{base_dsn}/{db_name}"
        store.connect(full_dsn)
        
        # Initialize schema
        store.initialize_schema()
        
        # Create durability backend
        from soothe.backends.durability.postgresql import PostgreSQLDurability
        return PostgreSQLDurability(persist_store=store)
```

#### 4.4 Update SQLite Backend
**File**: `packages/soothe/src/soothe/backends/persistence/sqlite_store.py`

**Schema already auto-creates** (existing implementation), verify it handles new paths correctly.

#### 4.5 Update Vector Store Provisioning
**File**: `packages/soothe/src/soothe/backends/vector_store/pgvector.py`

**Add pgvector provisioning**:
```python
class PGVectorStore(VectorStoreProtocol):
    def provision_database(self, base_dsn: str, db_name: str) -> None:
        """Provision pgvector database and extension."""
        import psycopg
        
        conn = psycopg.connect(base_dsn)
        
        # Create database
        result = conn.execute(
            "SELECT datname FROM pg_database WHERE datname = %s",
            (db_name,)
        ).fetchone()
        
        if not result:
            conn.execute(f"CREATE DATABASE {db_name}")
            conn.commit()
        
        conn.close()
        
        # Connect to database and create extension
        full_dsn = f"{base_dsn}/{db_name}"
        conn = psycopg.connect(full_dsn)
        
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                id TEXT PRIMARY KEY,
                embedding vector({self.dimension}),
                metadata JSONB,
                created_at TIMESTAMP
            )
        """)
        conn.execute(f"CREATE INDEX IF NOT EXISTS embeddings_idx ON embeddings USING {self.index_type} (embedding)")
        conn.commit()
        
        logger.info(f"pgvector database {db_name} provisioned with extension")
```

#### 4.6 Update Checkpointer Provisioning
**File**: `packages/soothe/src/soothe/core/resolver/_resolver_infra.py`

**Add LangGraph checkpoint table creation**:
```python
def _resolve_postgres_checkpointer(config: SootheConfig) -> Checkpointer:
    """Initialize PostgreSQL checkpointer with auto-provisioning."""
    
    base_dsn = config.persistence.postgres_base_dsn
    db_name = config.persistence.postgres_databases["checkpoints"]
    
    # Provision database
    provision_database(base_dsn, db_name)
    
    # Create checkpoint tables
    full_dsn = f"{base_dsn}/{db_name}"
    conn = psycopg.connect(full_dsn)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS checkpoints (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL,
            parent_checkpoint_id TEXT,
            type TEXT,
            checkpoint JSONB NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
        )
    """)
    conn.commit()
    
    # Create AsyncPostgresSaver from connection
    pool = AsyncConnectionPool(full_dsn)
    return (None, pool)
```

---

### Verification
```bash
# Test PostgreSQL provisioning (requires PostgreSQL running)
python -c "
from soothe.backends.persistence import PostgreSQLPersistStore

store = PostgreSQLPersistStore()
store.provision_database('postgresql://localhost:5432', 'test_soothe_meta')

# Check database exists
import psycopg
conn = psycopg.connect('postgresql://localhost:5432')
result = conn.execute('SELECT datname FROM pg_database WHERE datname = test_soothe_meta').fetchone()
print(f'Database created: {result}')
"

# Test schema initialization
python -c "
store = PostgreSQLPersistStore()
store.connect('postgresql://localhost:5432/test_soothe_meta')
store.initialize_schema()

# Check table exists
result = store._conn.execute('SELECT table_name FROM information_schema.tables WHERE table_name = soothe_kv').fetchone()
print(f'Table created: {result}')
"

# Run provisioning tests
pytest tests/unit/backends/persistence/test_postgres_provisioning.py -v
```

---

## Phase 5: Vector Store Validation (2-3 days)

### Objective
Update vector store factory for mode validation and pgvector support.

### Tasks

#### 5.1 Update Vector Store Factory
**File**: `packages/soothe/src/soothe/backends/vector_store/__init__.py`

**Remove in_memory branch**:
```python
# BEFORE:
def create_vector_store(provider_type: str, ...) -> VectorStoreProtocol:
    if provider_type == "in_memory":
        from soothe.backends.vector_store.in_memory import InMemoryVectorStore
        return InMemoryVectorStore(collection)
    elif provider_type == "sqlite_vec":
        # ...
    elif provider_type == "pgvector":
        # ...

# AFTER:
def create_vector_store(provider_type: str, ...) -> VectorStoreProtocol:
    if provider_type == "sqlite_vec":
        from soothe.backends.vector_store.sqlite_vec import SQLiteVecStore
        return SQLiteVecStore(collection=collection, db_path=db_path)
    
    elif provider_type == "pgvector":
        from soothe.backends.vector_store.pgvector import PGVectorStore
        return PGVectorStore(dsn=dsn, ...)
    
    else:
        raise ValueError(
            f"Unknown vector store provider: {provider_type}. "
            f"Supported: sqlite_vec, pgvector"
        )
```

#### 5.2 Add Mode Validation
**File**: `packages/soothe/src/soothe/backends/vector_store/__init__.py`

**Add validation**:
```python
def create_vector_store(provider_type: str, config: SootheConfig, ...) -> VectorStoreProtocol:
    """Create vector store with mode validation."""
    
    # Validate against mode
    if config.mode == "production" and provider_type == "sqlite_vec":
        raise ConfigurationError(
            "Production mode requires pgvector vector store. "
            f"Found: provider_type={provider_type}. "
            "Change vector_stores.provider_type to pgvector."
        )
    
    # Proceed with creation
    if provider_type == "sqlite_vec":
        # Development mode only
        return SQLiteVecStore(...)
    
    elif provider_type == "pgvector":
        # Production + development
        # Use postgres_databases["vectors"] from config
        db_name = config.persistence.postgres_databases["vectors"]
        full_dsn = f"{config.persistence.postgres_base_dsn}/{db_name}"
        
        # Auto-provision
        store = PGVectorStore(full_dsn, ...)
        store.provision_database(config.persistence.postgres_base_dsn, db_name)
        return store
```

#### 5.3 Update Vector Store Configuration
**File**: `packages/soothe/src/soothe/config/models.py`

**Add vector store DSN resolution**:
```python
class VectorStoreProviderConfig(BaseModel):
    name: str
    provider_type: Literal["sqlite_vec", "pgvector"]
    
    # SQLite options
    db_path: str | None = None
    
    # PostgreSQL options (use persistence.postgres_databases)
    pool_size: int = 5
    index_type: Literal["hnsw", "ivfflat"] = "hnsw"
    
    def resolve_dsn(self, config: SootheConfig) -> str:
        """Resolve DSN based on provider type and persistence config."""
        if self.provider_type == "pgvector":
            base_dsn = config.persistence.postgres_base_dsn
            db_name = config.persistence.postgres_databases["vectors"]
            return f"{base_dsn}/{db_name}"
        
        elif self.provider_type == "sqlite_vec":
            db_path = self.db_path or config.persistence.sqlite_paths.get("vectors", "")
            if not db_path:
                db_path = str(Path(SOOTHE_DATA_DIR) / "vectors.db")
            return db_path
```

#### 5.4 Update Vector Store Resolver
**File**: `packages/soothe/src/soothe/core/resolver/_resolver_infra.py` (new file)

**Add vector store resolution**:
```python
def resolve_vector_stores(config: SootheConfig) -> dict[str, VectorStoreProtocol]:
    """Resolve vector stores with auto-provisioning."""
    
    stores = {}
    
    for store_config in config.vector_stores:
        dsn = store_config.resolve_dsn(config)
        
        if store_config.provider_type == "pgvector":
            # Auto-provision
            from soothe.backends.vector_store.pgvector import PGVectorStore
            store = PGVectorStore(dsn=dsn, ...)
            store.provision_database(config.persistence.postgres_base_dsn, ...)
            stores[store_config.name] = store
        
        elif store_config.provider_type == "sqlite_vec":
            # SQLite auto-creates file
            from soothe.backends.vector_store.sqlite_vec import SQLiteVecStore
            store = SQLiteVecStore(db_path=dsn, ...)
            stores[store_config.name] = store
    
    return stores
```

---

### Verification
```bash
# Test vector store factory
python -c "
from soothe.backends.vector_store import create_vector_store
from soothe.config import SootheConfig

# Test production mode rejects sqlite_vec
config = SootheConfig(mode='production')
try:
    create_vector_store('sqlite_vec', config)
    print('ERROR: Should have raised exception')
except ConfigurationError as e:
    print(f'✅ Production validation: {e}')
"

# Test pgvector creation
pytest tests/unit/backends/vector_store/test_pgvector_provisioning.py -v
```

---

## Phase 6: Testing & Documentation (3-4 days)

### Objective
Complete testing, migration guide, and documentation updates.

### Tasks

#### 6.1 Add Mode Validation Tests
**File**: `tests/unit/config/test_mode_validation.py`

**Test cases**:
```python
import pytest
from soothe.config import SootheConfig, ConfigurationError

def test_production_rejects_sqlite():
    """Production mode must reject sqlite backends."""
    config = SootheConfig(
        mode='production',
        persistence={'default_backend': 'sqlite'}
    )
    
    errors = config.validate_backends_for_mode()
    assert 'persistence.default_backend=sqlite' in errors

def test_production_requires_postgresql():
    """Production mode requires postgres configuration."""
    config = SootheConfig(mode='production')
    config.raise_if_invalid_for_mode()  # Should raise without postgres config

def test_development_allows_sqlite():
    """Development mode allows sqlite backends."""
    config = SootheConfig(
        mode='development',
        persistence={'default_backend': 'sqlite'}
    )
    
    errors = config.validate_backends_for_mode()
    assert len(errors) == 0

def test_development_accepts_postgresql():
    """Development mode can use postgresql explicitly."""
    config = SootheConfig(
        mode='development',
        persistence={
            'postgres_base_dsn': 'postgresql://localhost:5432',
            'postgres_databases': {...}
        }
    )
    
    errors = config.validate_backends_for_mode()
    assert len(errors) == 0
```

#### 6.2 Add Provisioning Tests
**File**: `tests/unit/backends/persistence/test_postgres_provisioning.py`

**Test cases**:
```python
@pytest.mark.asyncio
async def test_auto_provision_database(postgres_server):
    """Test automatic database provisioning."""
    from soothe.backends.persistence import PostgreSQLPersistStore
    
    store = PostgreSQLPersistStore()
    store.provision_database(
        postgres_server.base_dsn,
        'test_soothe_meta'
    )
    
    # Verify database exists
    conn = psycopg.connect(postgres_server.base_dsn)
    result = conn.execute(
        "SELECT datname FROM pg_database WHERE datname = 'test_soothe_meta'"
    ).fetchone()
    
    assert result is not None

@pytest.mark.asyncio
async def test_schema_initialization(postgres_db):
    """Test automatic schema creation."""
    store = PostgreSQLPersistStore()
    store.connect(postgres_db.dsn)
    store.initialize_schema()
    
    # Verify table exists
    result = store._conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name = 'soothe_kv'"
    ).fetchone()
    
    assert result is not None

@pytest.mark.asyncio
async def test_provisioning_with_missing_database(postgres_server):
    """Test provisioning creates missing database."""
    # Connect to non-existent database should trigger provisioning
    config = SootheConfig(
        persistence={
            'postgres_base_dsn': postgres_server.base_dsn,
            'postgres_databases': {
                'checkpoints': 'soothe_test_checkpoints',
                'metadata': 'soothe_test_metadata',
                'vectors': 'soothe_test_vectors',
                'memory': 'soothe_test_memory'
            }
        }
    )
    
    # All databases should be provisioned
    from soothe.core.resolver import resolve_durability
    durability = resolve_durability(config)
    
    # Verify databases exist
    conn = psycopg.connect(postgres_server.base_dsn)
    for db_name in config.persistence.postgres_databases.values():
        result = conn.execute(
            f"SELECT datname FROM pg_database WHERE datname = '{db_name}'"
        ).fetchone()
        assert result is not None
```

#### 6.3 Add Configuration Parsing Tests
**File**: `tests/unit/config/test_persistence_config.py`

**Test cases**:
```python
def test_persistence_config_defaults():
    """Test default persistence configuration."""
    config = SootheConfig()
    
    assert config.persistence.default_backend == 'sqlite'
    assert config.persistence.sqlite_paths['checkpoints'] == ''

def test_postgres_databases_validation():
    """Test postgres_databases required keys."""
    with pytest.raises(ValueError):
        PersistenceConfig(
            postgres_databases={'checkpoints': 'soothe_cp'}  # Missing metadata, vectors, memory
        )

def test_sqlite_path_convention():
    """Test empty sqlite paths use convention."""
    config = SootheConfig()
    paths = config.persistence.sqlite_paths
    
    assert paths['metadata'] == ''  # Empty means default
    # Resolver will use $SOOTHE_DATA_DIR/metadata.db
```

#### 6.4 Write Migration Guide
**File**: `docs/persistence-migration.md`

**Content**:
```markdown
# Persistence Migration Guide: SQLite → PostgreSQL

## Overview

Migrate from SQLite (development mode) to PostgreSQL (production mode) for production deployments.

## Prerequisites

- PostgreSQL server installed and running
- PostgreSQL user with CREATEDB privilege
- Connection credentials (host, port, user, password)

## Migration Steps

### Step 1: Install PostgreSQL

```bash
# macOS
brew install postgresql@16
brew services start postgresql@16

# Ubuntu/Debian
sudo apt install postgresql-16
sudo systemctl start postgresql

# Create user
createuser -s soothe_user
psql -c "ALTER USER soothe_user WITH PASSWORD 'your_password';"
```

### Step 2: Update Configuration

Create `config/config.prod.yml`:

```yaml
mode: production

persistence:
  postgres_base_dsn: "postgresql://soothe_user:${SOOTHE_DB_PASSWORD}@localhost:5432"
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
    backend: postgresql
```

Set environment variable:
```bash
export SOOTHE_DB_PASSWORD="your_password"
```

### Step 3: Run with Auto-Provisioning

Soothe will automatically create databases on startup:

```bash
soothe --config config/config.prod.yml "your query"
```

Check logs for provisioning confirmation:
```
INFO: Creating PostgreSQL database: soothe_checkpoints
INFO: Database soothe_checkpoints created successfully
INFO: Schema initialized in database
```

### Step 4: Verify Databases

```bash
psql -U soothe_user -d soothe_checkpoints -c "\dt"
# Should show: checkpoints, loop_checkpoints tables

psql -U soothe_user -d soothe_metadata -c "\dt"
# Should show: soothe_kv table

psql -U soothe_user -d soothe_vectors -c "\dx"
# Should show: vector extension installed
```

## Data Migration (Optional)

If you have existing SQLite data to migrate:

### Migrate LangGraph Checkpoints

```python
import sqlite3
import psycopg

# Export from SQLite
sqlite_conn = sqlite3.connect('data/langgraph_checkpoints.db')
rows = sqlite_conn.execute("SELECT * FROM checkpoints").fetchall()

# Import to PostgreSQL
pg_conn = psycopg.connect('postgresql://localhost:5432/soothe_checkpoints')
for row in rows:
    pg_conn.execute(
        "INSERT INTO checkpoints VALUES (...)",
        row
    )
pg_conn.commit()
```

### Migrate Metadata

```python
# Similar migration script for metadata.db → soothe_metadata
```

## Troubleshooting

### Database Provisioning Fails

**Error**: `PostgreSQL database provisioning failed`

**Solution**: Ensure user has CREATEDB privilege:
```bash
psql -c "ALTER USER soothe_user CREATEDB;"
```

### pgvector Extension Missing

**Error**: `CREATE EXTENSION vector failed`

**Solution**: Install pgvector extension:
```bash
# macOS
brew install pgvector

# Ubuntu
sudo apt install postgresql-16-pgvector

# Enable in PostgreSQL
psql -c "CREATE EXTENSION vector;"
```

### Connection Refused

**Error**: `Connection refused to PostgreSQL`

**Solution**: Check PostgreSQL running and credentials:
```bash
psql -U soothe_user -h localhost -p 5432
```

## Rollback to Development Mode

To switch back to SQLite (development):

```yaml
mode: development

# Remove postgres config (optional)
# persistence: {}  # Uses SQLite defaults
```

Soothe will use SQLite files: `langgraph_checkpoints.db`, `loop_checkpoints.db`, `metadata.db`, `vectors.db`.

## Production Best Practices

1. **Backup strategy**: Regular PostgreSQL backups
2. **Connection pooling**: Tune pool_size per workload
3. **Indexing**: Use HNSW for embeddings, B-tree for metadata
4. **Monitoring**: Track connection pool usage, query latency
5. **Security**: Use TLS for connections, encrypt credentials in env vars
```

#### 6.5 Update RFC-409 Reference
**File**: `docs/specs/RFC-409-agentloop-persistence-backend.md`

**Add reference**:
```markdown
## Related RFCs

- **RFC-612**: Persistence Architecture Refactor - Unified configuration, mode validation, auto-provisioning
```

#### 6.6 Update User Guide
**File**: `docs/user_guide.md`

**Add persistence section**:
```markdown
## Persistence Configuration

### Development Mode (SQLite)

Default configuration uses SQLite for local development:

```yaml
mode: development  # Optional, defaults to development

# SQLite databases created automatically:
# - data/langgraph_checkpoints.db
# - data/loop_checkpoints.db
# - data/metadata.db
# - data/vectors.db
```

No additional configuration needed - databases created on startup.

### Production Mode (PostgreSQL)

Production deployments require PostgreSQL:

```yaml
mode: production

persistence:
  postgres_base_dsn: "postgresql://user:${DB_PASSWORD}@host:5432"
  postgres_databases:
    checkpoints: soothe_checkpoints
    metadata: soothe_metadata
    vectors: soothe_vectors
    memory: soothe_memory
```

Databases auto-created on startup with schema initialization.

See [Persistence Migration Guide](./persistence-migration.md) for detailed setup.
```

---

### Verification
```bash
# Run all tests
./scripts/verify_finally.sh

# Check test coverage
pytest --cov=soothe.config --cov=soothe.backends.persistence tests/unit/

# Validate documentation
grep -r "mode.*production" docs/ --include="*.md"
# Expected: Migration guide, user guide, RFC-612

grep -r "MemorySaver\|InMemoryVectorStore" docs/
# Expected: Only in migration guide as "removed"
```

---

## Success Criteria Checklist

- [ ] ✅ No in-memory storage implementations in codebase
- [ ] ✅ Mode validation logic implemented and tested
- [ ] ✅ Production mode rejects sqlite with clear errors
- [ ] ✅ Unified persistence configuration schema active
- [ ] ✅ PostgreSQL auto-provisioning functional
- [ ] ✅ Schema initialization for all databases
- [ ] ✅ Vector stores validate against mode
- [ ] ✅ Migration guide published
- [ ] ✅ User guide updated
- [ ] ✅ All tests passing (1312+ tests)
- [ ] ✅ Lint check clean (0 errors)

---

## Rollback Plan

If implementation fails:

1. **Phase 1 rollback**: Restore deleted files from git history
   ```bash
   git checkout HEAD -- packages/soothe/src/soothe/backends/vector_store/in_memory.py
   git checkout HEAD -- packages/soothe/src/soothe/backends/durability/rocksdb.py
   ```

2. **Phase 2 rollback**: Remove mode field from SootheConfig
   ```python
   # Remove mode field, validation logic
   ```

3. **Phase 3 rollback**: Restore old persistence fields
   ```python
   # Restore soothe_postgres_dsn, metadata_sqlite_path, checkpoint_sqlite_path
   ```

4. **Full rollback**: `git revert` implementation commits

---

## Dependencies

- **External**: PostgreSQL server (for production testing)
- **Internal**: RFC-409 (AgentLoop persistence), RFC-611 (Checkpoint tree)
- **Libraries**: psycopg, psycopg-pool, pgvector extension

---

## Risks

| Risk | Mitigation | Status |
|------|------------|--------|
| PostgreSQL unavailable in tests | Mock provisioning, use SQLite for unit tests | Mitigated |
| Breaking existing configs | Migration guide + backward compat check | Mitigated |
| Large data migration slow | Parallel batch inserts, progress tracking | Accepted |
| pgvector extension missing | Pre-flight validation + install guide | Mitigated |

---

**End of IG-245**