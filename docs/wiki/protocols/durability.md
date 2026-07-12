---
title: "DurabilityProtocol"
parent: Protocols
grand_parent: Wiki
nav_order: 1
description: >-
  Thread lifecycle protocol — create, resume, suspend, and archive threads — with PostgreSQL and SQLite backends.
---

# DurabilityProtocol

**RFC**: 306 (Protocol Specifications series)
**Location**: `packages/soothe/src/soothe/protocols/durability.py`
**Status**: Implemented

## What DurabilityProtocol Is

DurabilityProtocol defines the interface for **thread lifecycle management**. A "thread" is Soothe's unit of conversational continuity — an agent run with its own ID, metadata, and status. DurabilityProtocol handles creating, resuming, suspending, archiving, and querying threads, plus their metadata.

A critical distinction: DurabilityProtocol manages *thread metadata and lifecycle status*, not execution state. Checkpoint state (LangGraph graph snapshots) and run artifacts are handled separately by the Checkpointer system and `RunArtifactStore` (RFC-802). DurabilityProtocol is the *identity and metadata* layer; the Checkpointer is the *execution state* layer.

## Why It Exists

Without a dedicated thread lifecycle abstraction, thread management scatters across the runtime — ad-hoc UUIDs, inconsistent status transitions, no queryable metadata. The protocol centralizes:

- **Identity** — stable thread IDs that survive restarts and crashes
- **Lifecycle** — a defined state machine (active → suspended → archived)
- **Metadata** — tags, labels, policy profiles, priority attached to each thread
- **Querying** — filter threads by status, tags, priority, time ranges

This separation lets the daemon manage many concurrent threads (interactive, autopilot, background) with a uniform interface, regardless of backend.

## Thread Lifecycle State Machine

Threads move through three core states:

```
create → active ⇄ suspended → archived
```

- **`create_thread(metadata, thread_id?)`** — creates a new thread. If `thread_id` is omitted, a UUID is generated; providing it lets you persist a draft thread with its existing ID.
- **`suspend_thread(id)`** — pauses an active thread, persisting its state. The thread can be resumed later.
- **`resume_thread(id)`** — wakes a suspended thread back to active. Supports **prefix matching**: if the ID is a prefix matching multiple threads, the first match resumes.
- **`archive_thread(id)`** — archives a thread. Archiving triggers **memory consolidation**, flushing thread knowledge into long-term storage.
- **`get_thread(id)`** — loads thread info *without* changing lifecycle status (read-only, exact match only).

### Two-Level Filtering

A non-obvious design: `ThreadFilter` splits filter fields into two tiers:

- **Protocol-level** (used by the durability backend): `status`, `tags`, `created_after`/`created_before`
- **Manager-level** (used by `ThreadContextManager` in-memory): `labels`, `priority`, `category`, `updated_after`/`updated_before`

This split exists because the backend database may not index all fields efficiently. Heavy user-defined metadata filtering happens in-memory after the backend narrows by its indexed fields.

## Data Models (Conceptual)

The protocol defines three associated models — see `durability.py` for full definitions:

- **`ThreadMetadata`** — tags (system categorical), `policy_profile` (security profile applied to thread operations), `plan_summary`, user-defined `labels`/`priority`/`category` (RFC-452).
- **`ThreadInfo`** — the full thread record: `thread_id`, `status`, `created_at`, `updated_at`, `metadata`.
- **`ThreadFilter`** — the two-tier filter criteria described above.

A key gotcha: `update_thread_metadata` does a **partial merge** — only fields present in the new metadata are updated; absent fields keep their existing values. It accepts either a `dict` or a `ThreadMetadata` instance.

## Integration Points

### Durability ↔ Memory

Archiving a thread (`archive_thread`) triggers memory consolidation. Thread knowledge is flushed to `MemoryProtocol` so it survives beyond the thread's lifecycle. Memory items carry `source_thread` for traceability back to the archived thread.

### Durability ↔ Policy

Each thread's `ThreadMetadata.policy_profile` determines which `PolicyProfile` governs all operations within that thread. A thread created with `policy_profile="readonly"` will enforce read-only permissions for its entire lifetime. See [policy.md](policy.md).

### Durability ↔ Persistence

PostgreSQL deployments store thread records in a dedicated `soothe_metadata` database (RFC-802 multi-database architecture). SQLite deployments use a single-file `metadata.db`. Both implement `DurabilityProtocol` identically from the consumer's perspective.

## Backends

| Backend | Status | Use Case |
|---------|--------|----------|
| PostgreSQL (`PostgreSQLDurability`) | Production | Multi-process, concurrent thread management |
| SQLite (`SQLiteDurability`) | Development | Single-process, zero-config, rapid iteration |

Backends are selected via `persistence.durability_backend` in config. The `resolve_persist_store` helper creates the underlying `AsyncPersistStore` that backends use for key-value storage.

## Gotchas

- **Prefix matching on resume** — `resume_thread` accepts a prefix and resumes the *first* match. If multiple threads share a prefix, you may not get the one you expect. Use full IDs when precision matters.
- **`get_thread` is exact-match only** — unlike `resume_thread`, `get_thread` does not do prefix matching. It returns `None` (not an error) if the thread doesn't exist.
- **`resume_thread` raises `KeyError`** — unlike `get_thread` (which returns `None`), `resume_thread` raises `KeyError` if the thread doesn't exist. Callers must handle this differently.
- **Archive is terminal** — archiving triggers memory consolidation and moves the thread out of active/suspended states. There's no "unarchive" in the core protocol.
- **Metadata merge semantics** — `update_thread_metadata` merges, it doesn't replace. To clear a field, you must explicitly set it (where the model allows `None`).
- **`list_threads` ordering** — results are ordered by `updated_at` descending (most recently touched first), not by creation time.

## Specification Reference

- **RFC-306**: Durability Protocol Architecture
- **RFC-452**: Enhanced thread metadata (labels, priority, category)
- **RFC-802**: Multi-database persistence architecture
- **RFC-802**: RunArtifactStore (separate from durability)

## Related Documentation

- **[Durability Backends](../backends/durability-backends.md)** — Backend implementations
- [Memory Protocol](memory.md) — triggered on archive
- [Policy Protocol](policy.md) — `policy_profile` in thread metadata
- [Vector Store & Persistence](vector-store-persistence.md) — `AsyncPersistStore` backends
