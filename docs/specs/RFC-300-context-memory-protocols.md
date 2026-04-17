# RFC-300: Context and Memory Architecture Design

**RFC**: 300
**Title**: Context and Memory Architecture Design
**Status**: Implemented
**Created**: 2026-03-14
**Updated**: 2026-03-27
**Related**: RFC-000, RFC-001, RFC-500

## Abstract

This RFC provides a detailed architecture design for Soothe's context and memory subsystems. It clarifies the distinction between within-thread context (ContextProtocol) and cross-thread memory (MemoryProtocol), defines the persistence lifecycle, explains the implementation backend naming conventions, and proposes future directions for scalability and intelligence.

## Motivation

RFC-001 defined the protocol interfaces for Context and Memory but left several design decisions implicit. As the implementation matured, the following gaps emerged:

1. **Context backend naming** — `KeywordContext` and `VectorContext` now clearly communicate their retrieval approach to users configuring the system.
2. **Persistence lifecycle wiring** — context persistence and memory recall/remember are now wired into the execution flow, but the RFC still describes older sequencing and backend assumptions.
3. **Memory architecture evolution** — the codebase converged on a MemU-backed `MemoryProtocol` implementation rather than the older keyword/vector memory split described here.
4. **Configuration surface drift** — context, memory, persistence, and vector-store settings moved from flat top-level fields to nested protocol and router configuration.
5. **No updated rationale** — the current relationship between ContextProtocol, MemU memory, PersistStore, and vector-store routing was underdocumented in the spec.

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

From RFC-000 principle 4: *"Unbounded context, bounded projection."*

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

#### MemUMemory (current implementation)

**Config**: `protocols.memory.enabled: true`

The current memory backend is `MemUMemory`, an adapter over the internal MemU memory store. It uses configured chat and embedding model roles for memory operations and persists data inside the MemU storage layout rather than through `PersistStore`.

- **Persistence**: Managed by `MemuMemoryStore` under the configured memory directory
- **Data location**: `protocols.memory.persist_dir` if set; otherwise the current implementation falls back to `~/.soothe/memory`
- **Recall**: `MemoryProtocol.recall()` delegates to MemU search; embeddings can be enabled, but the store currently reconstructs and searches its file-backed mappings internally rather than using the RFC's older VectorMemory design
- **Strengths**: Richer long-term memory model, configurable categorization/summaries, integrated LLM-assisted memory operations

Historical note: earlier RFC drafts described `KeywordMemory` and `VectorMemory` families. The current codebase no longer resolves memory through that keyword/vector split.

## Persistence Lifecycle

### Context Lifecycle

```text
Resumed thread start:
  1. DurabilityProtocol resumes/creates thread lifecycle state elsewhere in the runner stack
  2. ContextProtocol.restore(thread_id) runs for resumed threads
  3. MemoryProtocol.recall(query) may run before the stream
  4. Recalled memories are ingested into context when available
  5. ContextProtocol.project(query, budget) produces a bounded projection
  6. Build enriched input

Thread end:
  1. ContextProtocol.ingest(response) appends the final agent response
  2. ContextProtocol.persist(thread_id) saves thread-scoped context
  3. MemoryProtocol.remember(response) stores cross-thread memory when the response is large enough
```

Current implementation nuance: when `performance.parallel_pre_stream` is enabled, memory recall and context projection can run concurrently. In that path, recalled memories are ingested into context after the projection result has already been produced, so the same pre-stream projection may not yet reflect those newly recalled items.

### Memory Lifecycle

```text
Thread A (past):
  ... work ...
  → memory.remember(findings)    ← Stored with source_thread="A"

Thread B (new or resumed):
  → memory.recall("related topic")  ← Retrieves findings from A
  → context.ingest(recalled_items)   ← Merged into current context when available
  ... work using recalled knowledge ...
  → memory.remember(new_findings)    ← Stored with source_thread="B"
```

## PersistStore Abstraction

The `PersistStore` protocol provides a simple key-value interface that decouples context and durability logic from storage backends. It remains the persistence abstraction for `KeywordContext` and several durability backends, but the current MemU memory implementation does not persist through `PersistStore`.

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
| `JsonPersistStore` | `backends/persistence/json_store.py` | Development, small datasets, portability |
| `RocksDBPersistStore` | `backends/persistence/rocksdb_store.py` | Production, large datasets, high throughput |
| `PostgreSQLPersistStore` | `backends/persistence/postgres_store.py` | Production, distributed deployments, ACID guarantees |

## Configuration Reference

```yaml
protocols:
  context:
    enabled: true
    backend: vector-postgresql   # keyword-json | keyword-rocksdb | keyword-postgresql | vector-postgresql | none
    persist_dir: ""

  memory:
    enabled: true
    persist_dir: ""
    llm_chat_role: fast
    llm_embed_role: embedding
    enable_embeddings: true
    enable_auto_categorization: true
    enable_category_summaries: true

  durability:
    backend: postgresql
    persist_dir: ""
    checkpointer: postgresql

persistence:
  default_backend: postgresql
  soothe_postgres_dsn: "postgresql://postgres:postgres@localhost:5432/soothe"

vector_stores:
  - name: pgvector_default
    provider_type: pgvector
    dsn: "postgresql://postgres:postgres@localhost:5432/vectordb"
    pool_size: 5
    index_type: hnsw

vector_store_router:
  default: pgvector_default:soothe_default
  context: pgvector_default:soothe_context
  skillify: pgvector_default:soothe_skillify
  weaver_reuse: pgvector_default:soothe_weaver_reuse
```

### Defaults and SOOTHE_HOME

Current defaults are split between model defaults, shipped config, and runtime fallback code:

| Surface | Current behavior |
|--------|------------------|
| `protocols.context.backend` | Model default is `keyword-postgresql`; shipped config sets `vector-postgresql` |
| `protocols.context.persist_dir` | Empty config is documented as `SOOTHE_HOME/context/`; current resolver fallback uses `SOOTHE_HOME/context/data` for keyword context |
| `protocols.memory.persist_dir` | Empty config currently falls back to `~/.soothe/memory` in `MemUMemory` |
| Thread logs | `$SOOTHE_HOME/threads/` |
| Application log | `$SOOTHE_HOME/logs/soothe.log` |
| Input history | `$SOOTHE_HOME/history.json` |

## Naming Conventions

### Implementation Names

The current names reflect the retrieval/storage method used:

| Current Name | Backend Type | Config Surface |
|-------------|-------------|----------------|
| `KeywordContext` | Keyword/tag matching + PersistStore | `protocols.context.backend: keyword-*` |
| `VectorContext` | Embedding + VectorStore | `protocols.context.backend: vector-postgresql` |
| `MemUMemory` | MemU-backed long-term memory | `protocols.memory.*` |

For context, the backend string is user-facing and follows a `{behavior}-{storage}` pattern. Memory no longer follows the older `memory_backend: keyword|vector` split described in earlier drafts.

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

- RFC-000 (System Conceptual Design) — Principle 4: Unbounded context, bounded projection
- RFC-001 (Core Modules Architecture) — Protocol definitions
- RFC-500 (CLI TUI Architecture) — Session logging integration

## Related Documents

- [RFC-000](./RFC-000-system-conceptual-design.md) - System Conceptual Design
- [RFC-001](./RFC-001-core-modules-architecture.md) - Core Modules Architecture Design
- [RFC-500](./RFC-500-cli-tui-architecture.md) - CLI TUI Architecture Design
- [RFC Index](./rfc-index.md) - All RFCs
