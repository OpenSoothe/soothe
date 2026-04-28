# IG-054: RFC-612 PostgreSQL Multi-Database Architecture Implementation

**Status**: Completed  
**Created**: 2026-04-27  
**RFC Reference**: RFC-612 (Multi-database PostgreSQL architecture)

## Objective

Implement RFC-612 multi-database PostgreSQL architecture to replace the legacy single-DSN configuration with a structured multi-database approach for better lifecycle isolation, backup granularity, and pgvector extension requirements.

## Current State

The `PersistenceConfig` model uses a legacy single DSN field:
```python
soothe_postgres_dsn: str = "postgresql://postgres:postgres@localhost:5432/soothe"
```

All PostgreSQL components (checkpointer, durability, vector stores) share a single database.

## Target State

Implement multi-database architecture with:
- **postgres_base_dsn**: Base connection string without database name
- **postgres_databases**: Named database mapping for each component
- **Separate databases**: checkpoints, metadata, vectors, memory

## Implementation Plan

### Phase 1: Model Updates (models.py)

1. Update `PersistenceConfig` class:
   - Add `postgres_base_dsn: str | None = None` field
   - Add `postgres_databases: dict[str, str]` field with defaults
   - Deprecate `soothe_postgres_dsn` (keep for backward compatibility)
   - Add validator to construct full DSNs from base + database name

2. Database mapping defaults:
   ```python
   postgres_databases: dict[str, str] = {
       "checkpoints": "soothe_checkpoints",
       "metadata": "soothe_metadata",
       "vectors": "soothe_vectors",
       "memory": "soothe_memory"
   }
   ```

### Phase 2: DSN Resolution (settings.py)

1. Add helper methods in `SootheConfig`:
   - `resolve_postgres_dsn_for_database(db_key: str) -> str`
   - Construct full DSN: `{base_dsn}/{database_name}`
   - Support environment variable resolution

2. Update `resolve_persistence_postgres_dsn()`:
   - Check for new fields first (postgres_base_dsn)
   - Fall back to legacy soothe_postgres_dsn for backward compatibility
   - Return appropriate DSN based on context

### Phase 3: Resolver Infrastructure (_resolver_infra.py)

1. Update checkpointer resolver:
   - Use `resolve_postgres_dsn_for_database("checkpoints")`
   - Pass correct database name to pool creation

2. Update durability resolver:
   - Use `resolve_postgres_dsn_for_database("metadata")`

3. Update vector store resolver:
   - Support environment variable `${PERSISTENCE_POSTGRES_BASE_DSN}/${PERSISTENCE_POSTGRES_VECTORS_DB}`
   - Or use `resolve_postgres_dsn_for_database("vectors")`

### Phase 4: Configuration Templates

1. Update `config/config.yml` template:
   - Uncomment RFC-612 fields
   - Add clear documentation
   - Remove legacy field from examples

2. Update `config/config.dev.yml`:
   - Use new multi-database fields
   - Configure Docker port 6432 correctly
   - Remove workaround comments

### Phase 5: Health Checks

1. Update `persistence_check.py`:
   - Use new DSN resolution methods
   - Check connectivity for each database
   - Provide database-specific health status

### Phase 6: Backward Compatibility

1. Deprecation strategy:
   - If `soothe_postgres_dsn` is set, warn and convert to single-database mode
   - If `postgres_base_dsn` is set, use multi-database mode
   - Environment variables override both

2. Migration path:
   - Provide clear documentation for users
   - Add deprecation warnings in logs

## Testing Strategy

1. Unit tests for:
   - DSN resolution logic
   - Multi-database configuration
   - Backward compatibility fallback

2. Integration tests:
   - PostgreSQL connection to each database
   - Checkpointer with separate database
   - Vector stores with separate database

3. Manual verification:
   - Docker PostgreSQL with 4 databases
   - Daemon restart with new config
   - Doctor health check verification

## Files Modified

- `packages/soothe/src/soothe/config/models.py` - PersistenceConfig model
- `packages/soothe/src/soothe/config/settings.py` - DSN resolution methods
- `packages/soothe/src/soothe/core/resolver/_resolver_infra.py` - Resolver updates
- `packages/soothe/src/soothe/config/config.yml` - Template configuration
- `config/config.dev.yml` - Development configuration
- `packages/soothe/src/soothe/daemon/health/checks/persistence_check.py` - Health check updates

## Success Criteria

- ✅ Multi-database PostgreSQL architecture implemented
- ✅ Backward compatibility with legacy configuration
- ✅ All databases connect successfully
- ✅ Health checks verify each database
- ✅ Documentation updated
- ✅ All tests passing