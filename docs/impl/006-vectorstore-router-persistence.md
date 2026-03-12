# VectorStore, Model Router, and Persistence Upgrades

**Guide**: IG-006
**Title**: Multi-Provider Model Router, VectorStoreProtocol, RocksDB Persistence, Vector-based Context/Memory
**Created**: 2026-03-12
**Related RFCs**: RFC-0001, RFC-0002

## Overview

This guide covers four interconnected feature areas:

1. **Multi-provider model router** -- replace the flat `llm_*` config with a providers list + role-based router
2. **VectorStoreProtocol** -- async protocol for vector storage with pgvector and weaviate backends
3. **RocksDB persistence** -- upgrade KeywordContext and StoreBackedMemory from JSON files to RocksDB
4. **Vector-based context/memory** -- new ContextProtocol and MemoryProtocol implementations backed by vector stores

## Part 1: Multi-Provider Model Router

### Problem

Current `SootheConfig` has flat, single-provider fields (`llm_provider`, `llm_api_key`, `llm_base_url`, `llm_chat_model`). This forces one provider, one model, one API key for the entire system. In practice, different tasks need different models from different providers.

### Design

**New config models** in `src/soothe/config.py`:

- `ModelProviderConfig` -- name, api_base_url, api_key (supports `${ENV_VAR}`), provider_type, models list
- `ModelRouter` -- maps role names to `provider_name:model_name` strings
  - Roles: `default`, `think`, `fast`, `image`, `embedding`, `web_search`
  - Unset roles fall back to `default`

**New methods** on `SootheConfig`:

- `resolve_model(role) -> str` -- role -> `provider_name:model_name`
- `create_chat_model(role) -> BaseChatModel` -- resolves role, finds provider credentials, calls `init_chat_model()`
- `create_embedding_model() -> Embeddings` -- resolves `"embedding"` role, calls `init_embeddings()`
- `_find_provider(name) -> ModelProviderConfig | None`

**No backward compatibility** -- the old flat `llm_*` fields are removed entirely.

### Files

- `src/soothe/config.py` -- rewritten

## Part 2: VectorStoreProtocol

### Design

Async `Protocol` inspired by noesium's `BaseVectorStore` but following Soothe's protocol-first pattern.

- `VectorRecord(BaseModel)` -- id, score, payload
- `VectorStoreProtocol(Protocol)` -- async methods: create_collection, insert, search, delete, update, get, list_records, delete_collection, reset

### Implementations

- `PGVectorStore` -- async via `psycopg` (v3), supports HNSW/DiskANN indexes
- `WeaviateVectorStore` -- async via `weaviate-client` v4, self-provided vectors

### Files

- `src/soothe/protocols/vector_store.py`
- `src/soothe/vector_store/__init__.py`
- `src/soothe/vector_store/pgvector.py`
- `src/soothe/vector_store/weaviate.py`

## Part 3: RocksDB Persistence

### Design

Replace JSON file persistence in `KeywordContext` and `StoreBackedMemory` with a pluggable persistence backend supporting both JSON and RocksDB.

- Shared `PersistStore` interface: `save(key, data)`, `load(key)`, `delete(key)`, `close()`
- `JsonPersistStore` -- writes JSON files (existing behavior)
- `RocksDBPersistStore` -- uses `rocksdict` for fast key-value storage
- `KeywordContext` keeps in-memory list for projection (hot path), uses store for persist/restore
- `StoreBackedMemory` uses per-item keys for O(1) operations

### Files

- `src/soothe/persistence/__init__.py`
- `src/soothe/persistence/json_store.py`
- `src/soothe/persistence/rocksdb_store.py`
- `src/soothe/context/keyword.py` (modified)
- `src/soothe/memory_store/store_backed.py` (modified)

## Part 4: Vector-Based Context and Memory

### Design

New implementations using `VectorStoreProtocol` + langchain `Embeddings` for semantic operations.

- `VectorContext` -- embeds entries on ingest, semantic search for projection
- `VectorMemory` -- embeds items on remember, semantic search for recall

### Files

- `src/soothe/context/vector_context.py`
- `src/soothe/memory_store/vector_memory.py`

## New Dependencies

```toml
[project.optional-dependencies]
rocksdb = ["rocksdict>=0.3"]
pgvector = ["psycopg[pool]>=3.1", "pgvector>=0.3"]
weaviate = ["weaviate-client>=4.0"]
```

## Verification

- [ ] `SootheConfig` with providers + router resolves models correctly
- [ ] `create_chat_model(role)` creates models with correct provider credentials
- [ ] `create_embedding_model()` creates embeddings with correct provider credentials
- [ ] `VectorStoreProtocol` defined with all async methods
- [ ] PGVectorStore and WeaviateVectorStore satisfy protocol
- [ ] KeywordContext persist/restore works with both JSON and RocksDB backends
- [ ] StoreBackedMemory works with both JSON and RocksDB backends
- [ ] VectorContext ingests, projects, persists correctly
- [ ] VectorMemory remembers, recalls, forgets correctly
- [ ] All existing tests still pass
- [ ] ruff lint clean
