# RFC-0006: Context and Memory Architecture Design

**RFC**: 0006
**Title**: Context and Memory Architecture Design
**Status**: Implemented
**Created**: 2026-03-14
**Updated**: 2026-03-27
**Related**: RFC-0001, RFC-0002, RFC-0003

## Abstract

This RFC provides a detailed architecture design for Soothe's context and memory subsystems. It clarifies the distinction between within-thread context (ContextProtocol) and cross-thread memory (MemoryProtocol), defines the persistence lifecycle, explains the implementation backend naming conventions, and proposes future directions for scalability and intelligence.

## Motivation

RFC-0002 defined the protocol interfaces for Context and Memory but left several design decisions implicit. As the implementation matured, the following gaps emerged:

1. **Naming consistency** — `KeywordContext` and `KeywordMemory` names now clearly communicate their approach (keyword matching) to users configuring the system.
2. **Persistence lifecycle gaps** — Context persistence (`persist()`/`restore()`) was implemented but never wired into the execution flow.
3. **Memory backend default** — `memory_backend` defaulted to `"none"`, meaning memory was silently disabled for most users.
4. **SOOTHE_HOME integration** — Persistence paths had no sensible defaults, requiring explicit configuration.
5. **No design rationale** — The architectural choices behind the two-tier (keyword/vector) approach and the PersistStore abstraction were undocumented.

## Core Concepts

### Context vs Memory vs Conversation History

| Concept | Scope | Lifetime | Managed By |
|---------|-------|----------|-----------|
| **Conversation History** | Current LLM context window | Auto-summarized by deepagents | `SummarizationMiddleware` |
| **Context (ContextProtocol)** | Current thread | Thread-scoped, persisted per thread | `SootheRunner` pre/post-stream |
| **Memory (MemoryProtocol)** | Cross-thread | Indefinite, grows over time | `SootheRunner` post-stream |

**Context** is the orchestrator's structured knowledge ledger for the current thread. It accumulates tool results, subagent findings, and agent responses as `ContextEntry` records. Before each LLM call, it projects a bounded subset into the prompt.

**Memory** is long-term knowledge that persists across threads. When a thread ends, significant findings are stored as `MemoryItem` records. When a new thread starts, relevant memories are recalled and injected into the context.

### The Unbounded Ledger / Bounded Projection Pattern

From RFC-0001 principle 4: *"Unbounded context, bounded projection."*

```
[Unbounded Ledger]                    [Bounded Projection]
+-------------------+                +------------------+
| Entry 1: tool:X   |  project()    | Entry 47: ...    |
| Entry 2: agent     |  -------->   | Entry 52: ...    |
| ...                |  (query,     | Entry 53: ...    |
| Entry N: subagent:Y|   budget)    | (within budget)  |
+-------------------+                +------------------+
```

The ledger is append-only and unbounded. The `project()` method selects the most relevant entries that fit within a token budget, using scoring that combines keyword overlap, recency, and importance weight.

## Implementation Architecture

### ContextProtocol Implementations

#### KeywordContext (default)

**Config**: `context_backend: keyword`

Lightweight implementation with no external dependencies. Uses keyword/tag matching for relevance scoring.

```
Scoring = keyword_overlap * 0.6 + recency * 0.2 + importance * 0.2
```

- **Persistence**: Via `PersistStore` (JSON, RocksDB, or PostgreSQL), one key per thread
- **Data location**: `$SOOTHE_HOME/context/context_{thread_id}.json`
- **Strengths**: Zero setup, fast, deterministic
- **Limitations**: No semantic understanding, keyword-only matching

#### VectorContext

**Config**: `context_backend: vector` (requires `vector_store_provider`)

Semantic implementation using embeddings for projection. Entries are embedded on ingest and retrieved via vector similarity search.

- **Persistence**: Delegated to the configured VectorStore
- **Strengths**: Semantic relevance, handles conceptual similarity
- **Limitations**: Requires embedding model and vector store

### MemoryProtocol Implementations

#### KeywordMemory (default)

**Config**: `memory_backend: keyword`

Keyword-based memory with `PersistStore` backend. Loads all items at initialization, making recall fast for moderate item counts.

- **Persistence**: Via `PersistStore` (JSON, RocksDB, or PostgreSQL), items stored individually with a manifest
- **Data location**: `$SOOTHE_HOME/memory/memory_{item_id}.json` + `memory__manifest.json`
- **Recall**: Keyword overlap + importance weighting
- **Strengths**: Simple, no external dependencies, auto-loads at startup

#### VectorMemory

**Config**: `memory_backend: vector` (requires `vector_store_provider`)

Semantic memory using embeddings. All data lives in the vector store.

- **Persistence**: Delegated to VectorStore
- **Recall**: Embedding similarity search
- **Strengths**: Semantic recall, scales to large memory sets

## Persistence Lifecycle

### Context Lifecycle

```
┌─────────────────────────────────────────────┐
│ Thread Start (SootheRunner._pre_stream)     │
│                                             │
│ 1. DurabilityProtocol.create/resume_thread()│
│ 2. ContextProtocol.restore(thread_id)       │  ← Load from disk
│ 3. MemoryProtocol.recall(query)             │
│ 4. ContextProtocol.project(query, budget)   │  ← Score & select
│ 5. Build enriched input                     │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ Thread End (SootheRunner._post_stream)      │
│                                             │
│ 1. ContextProtocol.ingest(response)         │  ← Append to ledger
│ 2. ContextProtocol.persist(thread_id)       │  ← Save to disk
│ 3. MemoryProtocol.remember(response)        │  ← Cross-thread store
│ 4. DurabilityProtocol.save_state()          │
└─────────────────────────────────────────────┘
```

### Memory Lifecycle

```
Thread A (past):
  ... work ...
  → memory.remember(findings)    ← Stored with source_thread="A"

Thread B (new):
  → memory.recall("related topic")  ← Retrieves findings from A
  → context.ingest(recalled_items)   ← Merged into B's context
  ... work using recalled knowledge ...
  → memory.remember(new_findings)    ← Stored with source_thread="B"
```

## PersistStore Abstraction

The `PersistStore` protocol provides a simple key-value interface that decouples context/memory logic from storage backends.

```python
class PersistStore(Protocol):
    def save(self, key: str, data: Any) -> None: ...
    def load(self, key: str) -> Any | None: ...
    def delete(self, key: str) -> None: ...
    def close(self) -> None: ...
```

### Why a Separate Abstraction?

1. **Backend swappability** — JSON for development, RocksDB for production
2. **Testability** — Easy to mock in tests
3. **Separation of concerns** — Context/memory logic doesn't know about file I/O
4. **Future extensibility** — Could add SQLite, Redis, S3 backends without changing context/memory code

### Current Backends

| Backend | Module | Use Case |
|---------|--------|----------|
| `JsonPersistStore` | `persistence/json_store.py` | Development, small datasets, portability |
| `RocksDBPersistStore` | `persistence/rocksdb_store.py` | Production, large datasets, high throughput |
| `PostgreSQLPersistStore` | `persistence/postgres_store.py` | Production, distributed deployments, ACID guarantees |

## Configuration Reference

```yaml
# PostgreSQL DSN (unified for all persistence backends and checkpointer)
persistence_postgres_dsn: "postgresql://postgres:postgres@localhost:5432/soothe"

# Context configuration
context_backend: keyword     # "keyword" | "vector" | "none"
context_persist_dir: null    # defaults to $SOOTHE_HOME/context/
context_persist_backend: postgresql  # "json" | "rocksdb" | "postgresql"

# Memory configuration
memory_backend: keyword      # "keyword" | "vector" | "none"
memory_persist_path: null    # defaults to $SOOTHE_HOME/memory/
memory_persist_backend: postgresql # "json" | "rocksdb" | "postgresql"

# Durability configuration
durability_backend: postgresql  # "json" | "rocksdb" | "postgresql"

# Vector store (required for vector backends)
vector_store_provider: none  # "pgvector" | "weaviate" | "none"
vector_store_collection: soothe_default
vector_store_config: {}      # Provider-specific config
```

### Defaults and SOOTHE_HOME

When persistence paths are not explicitly set, they default to subdirectories of `$SOOTHE_HOME`:

| Config Field | Default |
|-------------|---------|
| `context_persist_dir` | `$SOOTHE_HOME/context/` |
| `memory_persist_path` | `$SOOTHE_HOME/memory/` |
| Thread logs | `$SOOTHE_HOME/threads/` |
| Application log | `$SOOTHE_HOME/logs/soothe.log` |
| Input history | `$SOOTHE_HOME/history.json` |

## Naming Conventions

### Implementation Names

The current names reflect the retrieval method used:

| Current Name | Backend Type | Config Value |
|-------------|-------------|-------------|
| `KeywordContext` | Keyword/tag matching | `context_backend: keyword` |
| `VectorContext` | Embedding + VectorStore | `context_backend: vector` |
| `KeywordMemory` | Keyword + PersistStore | `memory_backend: keyword` |
| `VectorMemory` | Embedding + VectorStore | `memory_backend: vector` |

The config values (`keyword`, `vector`) are the user-facing names. Class names follow the pattern `{Method}{Protocol}` to clearly indicate the approach.

### Guideline for New Implementations

Pattern: `{Method}{Protocol}` — e.g., `HybridContext` (keyword + vector), `GraphMemory` (knowledge graph-based).

## Future Directions

### Hybrid Context (keyword + vector scoring)

Combine keyword matching with embedding similarity for projection scoring. Useful when keywords are important but semantic understanding adds value.

### Tiered Memory

Implement importance-based tiers: hot (frequently recalled), warm (recent), cold (archived). Auto-promote/demote based on recall frequency.

### Auto-Memorization Policy

Instead of storing every response >50 chars, use LLM-based importance assessment to decide what warrants long-term storage.

### Knowledge Graph Memory

Store memories as a knowledge graph with entity-relation triples. Enable structured queries like "What tools did we use for task X?"

### Distributed Persistence

Support remote persistence backends (S3, Redis, PostgreSQL) for multi-instance deployments.

## Dependencies

- RFC-0001 (System Conceptual Design) — Principle 4: Unbounded context, bounded projection
- RFC-0002 (Core Modules Architecture) — Protocol definitions
- RFC-0003 (CLI TUI Architecture) — Session logging integration

## Related Documents

- [RFC-0001](./RFC-0001.md) - System Conceptual Design
- [RFC-0002](./RFC-0002.md) - Core Modules Architecture Design
- [RFC-0003](./RFC-0003.md) - CLI TUI Architecture Design
- [RFC Index](./rfc-index.md) - All RFCs
