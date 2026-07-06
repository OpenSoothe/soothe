---
title: Backends
parent: Wiki
has_children: true
nav_order: 5
description: >-
  Memory, durability, vector store, persistence, and policy backend implementations.
permalink: /wiki/backends/
---

# Backends Layer

Concrete implementations for Soothe's protocol interfaces. Each backend category maps one protocol to one or more storage engines, with distinct performance, scalability, and operational trade-offs.

---

## Architecture at a Glance

The backends layer (`soothe.backends`) sits below the protocol layer (`soothe.protocols`) and above external dependencies. Protocols define *what* operations exist; backends define *how* those operations are executed against real storage engines.

Backends never contain business logic — they translate protocol calls into engine-specific operations (SQL, gRPC, file I/O). This separation lets you swap storage engines without touching Soothe's core orchestration.

Source: `packages/soothe/src/soothe/backends/`

---

## Backend Categories

### Memory Backends
Implement `MemoryProtocol` for cross-thread persistent memory that survives thread boundaries.

| Backend | Engine | Search Type | LLM-Powered |
|---------|--------|-------------|-------------|
| **MemUMemory** | File-based | Semantic + tag | ✅ |

**When to use**: You need long-term knowledge accumulation across conversations with semantic recall. The only memory backend; wraps an LLM-powered semantic memory store with clustering and theory-of-mind analysis.

**See**: [Memory Backends](memory-backends.md)

---

### Durability Backends
Implement `DurabilityProtocol` for thread lifecycle and state management (create, suspend, resume, archive).

| Backend | Storage | Concurrent Writes | Best For |
|---------|---------|-------------------|----------|
| **SQLiteDurability** | SQLite | ❌ (single writer) | Local, dev, single-process |
| **PostgreSQLDurability** | PostgreSQL | ✅ | Production, multi-process |

**When to choose**: SQLite for local development and single-process deployments; PostgreSQL for production with concurrent access, connection pooling, and horizontal scalability.

**See**: [Durability Backends](durability-backends.md)

---

### Persistence Backends
Implement `AsyncPersistStore` for generic key-value storage. Foundation layer used by durability, context, and other protocols.

| Backend | Storage | JSON Type | Concurrent Writes |
|---------|---------|-----------|-------------------|
| **SQLitePersistStore** | SQLite | Serialized JSON | ❌ (single writer, WAL) |
| **PostgreSQLPersistStore** | PostgreSQL | Native JSONB | ✅ (pool of 10) |

**When to choose**: SQLite for zero-config local storage; PostgreSQL for production with native JSONB indexing and concurrent access. These are the lowest-level backends — most other backends compose on top of them.

**See**: [Persistence Backends](persistence-backends.md)

---

### Vector Store Backends
Implement `VectorStoreProtocol` for semantic search via vector embeddings.

| Backend | Engine | Index Type | Best For |
|---------|--------|------------|----------|
| **PGVectorStore** | PostgreSQL pgvector | HNSW / IVFFlat | Production, scalable |
| **SQLiteVecStore** | sqlite-vec | HNSW | Local, no dependencies |
| **WeaviateVectorStore** | Weaviate | HNSW (built-in) | Cloud-native, multi-modal |

**When to choose**: SQLiteVec for local/embedded use; PGVector for production with existing PostgreSQL; Weaviate for cloud-native deployments with rich GraphQL querying. All use self-provided vectors — embeddings are generated externally by Soothe's embedding model.

**See**: [Vector Store Backends](vector-store-backends.md)

---

### Policy Backends
Implement `PolicyProtocol` for permission-based access control and least-privilege delegation.

| Backend | Type | Profiles | Child Delegation |
|---------|------|----------|------------------|
| **ConfigDrivenPolicy** | Config-driven (YAML) | readonly, standard, privileged | ✅ (narrow_for_child) |

**When to use**: The only policy backend. Enforces structured `category:action:scope` permissions with deny-rule overrides, interactive approval, and per-subagent permission narrowing. Integrates with `WorkspaceToolOperationSecurity` for filesystem and shell command validation.

**See**: [Policy Backends](policy-backends.md)

---

## Selection Guide

### By Deployment Environment

| Environment | Persistence | Durability | Vector Store | Memory |
|-------------|-------------|------------|--------------|--------|
| **Local / Dev** | SQLite | SQLite | SQLiteVec | MemU (file) |
| **Single-process Prod** | SQLite (WAL) | SQLite | PGVector | MemU (file) |
| **Multi-process Prod** | PostgreSQL | PostgreSQL | PGVector | MemU (file) |
| **Cloud-native** | PostgreSQL | PostgreSQL | Weaviate | MemU (file) |

### Key Decisions

- **SQLite vs PostgreSQL**: SQLite has zero dependencies and uses WAL mode with a reader pool for concurrent reads (single writer). PostgreSQL enables true concurrent writes, native JSONB, and connection pooling (10 connections default). Choose PostgreSQL when multiple processes must write simultaneously.

- **SQLiteVec vs PGVector vs Weaviate**: SQLiteVec is embedded and dependency-free (falls back to Python-side similarity if the extension is unavailable). PGVector integrates with existing PostgreSQL infrastructure and offers HNSW/IVFFlat index choice. Weaviate provides a managed cloud service with GraphQL and multi-modal support but adds network latency.

- **All async**: Every backend uses async I/O (IG-258 Phase 2). SQLite backends use `asyncio.to_thread` to avoid blocking the event loop; PostgreSQL backends use `psycopg`'s async connection pool.

---

## Related Documentation

- **[Protocol Layer](../protocols/index.md)** — Abstract interface definitions
- **[Protocol Resolver](../core/resolver.md)** — How backends are selected at runtime
- **[RFC-001](../../specs/RFC-001-core-modules-architecture.md)** — Core modules architecture
