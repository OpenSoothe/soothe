# SQLite Backend Design

**Date**: 2026-04-04
**Topic**: SQLite persistent backend and vector store with sqlite-vec

## Problem

Soothe currently requires PostgreSQL (or RocksDB) for production-grade persistence. For local development, single-node deployments, and lightweight usage, this creates an unnecessary infrastructure barrier. Users must either:
- Run a PostgreSQL instance (Docker, system package, etc.)
- Fall back to JSON file storage (no concurrent access, no querying)
- Use in-memory vector store (non-persistent, brute-force search)

## Solution

Add SQLite backends across three layers:
1. **SQLitePersistStore** - key-value persistence replacing JSON/RocksDB
2. **SQLiteDurability** - thread lifecycle management
3. **SQLiteVecStore** - vector search via sqlite-vec extension

Make SQLite the default for local/dev configurations.

## Design Decisions

### Why sqlite-vec (not sqlite-vss)?
- More actively maintained, simpler API
- Native binary vector support (F32_BLOB)
- No FAISS dependency, lighter weight
- Better suited for the scale Soothe targets (thousands, not millions of vectors)

### Why SQLite as default?
- Zero external dependencies for single-node deployments
- `$SOOTHE_HOME/soothe.db` + `$SOOTHE_HOME/vector.db` is all that's needed
- Production can still use PostgreSQL via explicit config
- Eliminates Docker requirement for local dev

### File Structure
- Single `.db` file for persistence + durability (shared SQLite instance)
- Separate `.db` file for vectors (sqlite-vec extension requirement)
- Both files under `$SOOTHE_HOME/`

### Concurrency Model
- WAL mode for persistence DB (concurrent reads, single writer)
- sqlite-vec handles vector search in-process
- No need for connection pooling (SQLite handles this via file locking)

### Migration Path
- Existing PostgreSQL configs continue working unchanged
- New users get SQLite by default
- `soothe checkhealth` validates SQLite backends at startup
