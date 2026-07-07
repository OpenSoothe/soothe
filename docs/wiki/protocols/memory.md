---
title: "MemoryProtocol"
parent: Protocols
grand_parent: Wiki
nav_order: 2
description: Cross-thread long-term knowledge protocol with semantic recall, implemented by the MemU backend.
---

# MemoryProtocol

**RFC**: 303 (Protocol Specifications series)
**Location**: `packages/soothe/src/soothe/protocols/memory.py`
**Status**: Implemented

## What MemoryProtocol Is

MemoryProtocol defines the interface for **cross-thread long-term memory** — knowledge that survives beyond a single thread's execution and can be semantically recalled by future threads. It is Soothe's mechanism for an agent to *learn* across sessions: thread A discovers something, stores it; thread B recalls it when working on a related task.

This is explicitly distinct from two other "memory" concepts in Soothe:

| Concept | Scope | Population | Retrieval |
|---------|-------|------------|-----------|
| **MemoryProtocol** | Cross-thread | Explicit (manual `remember()`) | Semantic + tag-based |
| **ContextProtocol** (not implemented) | Within-thread | Auto-ingested | Relevance projection |
| **MemoryMiddleware** | Static files | Authored AGENTS.md | File reads |

MemoryProtocol is *explicitly populated* — not every tool result gets memorized. Callers decide what's worth remembering, which keeps the store curated and noise-free.

## Why It Exists

Without persistent cross-thread memory, every thread starts from scratch. An agent that learned "this project uses PostgreSQL" in thread A would re-discover it in thread B. MemoryProtocol breaks that amnesia by providing:

- **Cross-thread persistence** — knowledge outlives any single thread
- **Semantic retrieval** — query by meaning, not exact keywords ("database optimization" finds "PostgreSQL tuning")
- **Traceability** — every item records its `source_thread` for provenance
- **Curated quality** — explicit population means only important knowledge enters the store

## Key Operations

- **`remember(item) → id`** — store a memory item, returns its UUID. Items carry `content`, `source_thread`, `tags`, `importance` (0.0–1.0), and arbitrary `metadata`.
- **`recall(query, limit=5)`** — semantic retrieval by relevance. Uses embeddings to find conceptually related items, not just keyword matches. Results ordered by relevance.
- **`recall_by_tags(tags, limit=10)`** — tag-based retrieval with AND logic (items must match all specified tags). Results ordered by importance.
- **`forget(item_id) → bool`** — remove a memory item. Returns `True` if found and removed.
- **`update(item_id, content)`** — replace an item's content. Raises `KeyError` if the item doesn't exist.

### The Importance Weight

`MemoryItem.importance` (0.0–1.0, default 0.5) affects retrieval ranking. Higher importance surfaces items earlier in recall results. This lets callers signal critical knowledge ("the production database is read-only" → importance 0.9) versus incidental findings ("the test file is large" → 0.3).

## Design Rationale

### Why Separate Memory from Context?

RFC-000 Principle 4 separates *unbounded context* (within-thread) from *persistent memory* (cross-thread). Different persistence scopes demand different strategies:

- Context is conversation-scoped: bounded projections, summarization-safe
- Memory is knowledge-scoped: persists indefinitely, semantic recall

Conflating them would force either thread-scoped memory (no cross-thread learning) or unbounded context (token blowup).

### Why Explicit Population?

Auto-memorizing every tool result would flood the store with noise — temporary file paths, intermediate debug output, transient search results. Explicit population ensures only reusable, curated knowledge enters. The agent (or caller) decides "this finding is worth remembering."

### Why Semantic Retrieval?

Keyword matching misses conceptual relationships. "Database optimization" and "PostgreSQL tuning" share no keywords but are semantically identical. Embeddings capture these relationships, making recall far more effective than lexical search for knowledge management.

## Integration Points

### Memory ↔ Context (Cross-Thread Learning)

The canonical cross-thread learning flow:

```
Thread A (past):
  → works on a task
  → memory.remember(findings)     ← stored with source_thread="A"

Thread B (new, related task):
  → memory.recall("related topic") ← retrieves A's findings
  → uses recalled knowledge
  → memory.remember(new_findings)  ← stored with source_thread="B"
```

Recalled memories are injected directly into planning prompts. If `ContextProtocol` were ever implemented, recalled memories would be ingested into the context ledger — but this is not the case today.

### Memory ↔ Durability

Memory and Durability are separate concerns:

- **Durability** manages thread *lifecycle state* (metadata, status, create/suspend/archive)
- **Memory** manages thread *knowledge content* (findings, learnings)

Archiving a thread triggers memory consolidation — the thread's accumulated knowledge is flushed to MemoryProtocol so it survives the thread's archival.

### Memory ↔ VectorStore

The current backend (MemU) uses embedding-based semantic search internally. Future backends could use `VectorStoreProtocol` directly for vector storage. The protocol abstracts this — callers call `recall(query)` without knowing the retrieval mechanism.

## Backends

### MemUMemory (Current)

The sole production backend, adapting the internal MemU memory store. Key characteristics:

- LLM-assisted memory categorization (intelligently tags and organizes stored items)
- Embedding-based semantic search
- Importance-weighted retrieval ranking
- Owns its own storage system (not via `AsyncPersistStore` — MemU manages persistence internally)
- Configurable model roles (`llm_chat_role` for categorization, `embedding_role` for embeddings)

### Historical Backends

Earlier implementations included `KeywordMemory` and `VectorMemory`. Both were superseded by MemU, which unifies intelligent categorization and semantic search into a single backend.

## Configuration

```yaml
agent:
  protocols:
    memory:
      enabled: true
      persist_dir: ~/.soothe/memory
      llm_chat_role: planner    # model role for memory operations
      embedding_role: embedding # model role for embeddings
```

Resolved via `resolve_memory(config)` → returns a `MemoryProtocol` instance (currently `MemUMemory`).

## Gotchas

- **Memory is a singleton** — shared across all threads. There's no per-thread memory isolation; all threads see all memories (filtered by tags/importance, not by thread).
- **`recall` is semantic, not exact** — results are ranked by embedding similarity, which means recall can return tangentially related items. Use `recall_by_tags` for precise categorical filtering.
- **`update` replaces content only** — it swaps the `content` field; tags, importance, and metadata are preserved. To change those, you must `forget` and `remember` a new item.
- **MemU owns its storage** — unlike Durability/VectorStore, MemU does not use `AsyncPersistStore`. Its storage location (`persist_dir`) is independent of the multi-database architecture.

## Specification Reference

- **RFC-303**: Memory Protocol Architecture
- **RFC-000**: System Conceptual Design (Principle 4: unbounded context, bounded projection)
- **[RFC-300](../../specs/archive/RFC-300-context-memory-protocols.md)**: Context and Memory Architecture Design (archived, superseded by RFC-302)

## Related Documentation

- **[Memory Backends](../backends/memory-backends.md)** — Backend implementations
- [ContextProtocol](context.md) — not implemented; context managed by ContextEngine
- [Durability Protocol](durability.md) — thread lifecycle (archive triggers memory consolidation)
- [Vector Store & Persistence](vector-store-persistence.md) — underlying vector search
- [Planner Protocol](planner.md) — consumes recalled memories in planning
