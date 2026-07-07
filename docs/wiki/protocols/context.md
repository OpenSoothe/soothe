---
title: "ContextProtocol (Not Implemented)"
parent: Protocols
grand_parent: Wiki
nav_order: 3
description: Within-thread context and working memory — planned protocol design. Context is currently managed by ContextEngine, not a protocol.
---

# ContextProtocol (Not Implemented)

**RFC**: 302 (Protocol Specifications series, draft)
**Status**: **Not implemented** — `ContextProtocol` class does not exist in the codebase
**Supersedes**: [RFC-300](../../specs/archive/RFC-300-context-memory-protocols.md) (archived)

> ⚠️ `ContextProtocol` is defined in RFC-302 (draft) but was **never implemented**. The `ContextProtocol` class does not exist in `packages/soothe/src/soothe/protocols/`. Context management is handled by `ContextEngine` (`soothe.foundation.context`), a concrete engine class — not a protocol abstraction. This article describes the *planned* protocol design and explains how context works today.

## What ContextProtocol Is

ContextProtocol is planned as Soothe's **unbounded knowledge accumulator** for cognitive context engineering. It serves as StrangeLoop's "consciousness" layer — an append-only ledger that captures complete execution knowledge within a thread, then projects bounded, relevance-ranked views back to the orchestrator when it reasons.

The core insight: accumulate everything, never discard, but only ever *show* a bounded slice. This separates durable knowledge from the token-constrained window an LLM actually sees.

## Why It Exists

Current context mechanisms are fragmented across three systems, each with different scopes:

| Mechanism | Scope | Limitation |
|-----------|-------|------------|
| Conversation history (`SummarizationMiddleware`) | Message thread | Summarization discards detail over time |
| `LoopWorkingMemoryProtocol` | Single loop's Plan phase | Bounded scratchpad, not persistent |
| `MemoryProtocol` | Cross-thread knowledge | Explicit population only, not auto-captured |

None of these provides an *unbounded, within-thread* knowledge store that survives summarization. ContextProtocol fills that gap — a per-thread ledger that ingests every tool output, subagent result, and reflection, then serves bounded projections to whoever needs context.

## Planned Design (RFC-302)

The protocol defines two fundamental operations and supporting persistence:

- **`ingest(entry)`** — append a knowledge entry to the thread's ledger. Append-only; entries are never deleted or truncated. The ledger grows unboundedly.
- **`project(query, token_budget)`** — extract a bounded view ranked by relevance to the query, constrained to `token_budget`. This is the read path: the orchestrator asks for "what's relevant to X in N tokens" and gets back a ranked slice.
- **`project_for_subagent(goal, token_budget)`** — a purpose-scoped projection for subagent briefings, so delegated agents receive only the context relevant to their goal.
- **`persist(thread_id)` / `restore(thread_id)`** — save and load the ledger to a durability backend, keyed by thread.

### The Retrieval Module

A notable design decision: `get_retrieval_module()` returns a **self-contained retrieval object** with its own stable API (`retrieve_by_goal_relevance(goal_id, query, token_budget)`). This is deliberately decoupled from the protocol interface so the retrieval *algorithm* can evolve (keyword → embedding → hybrid) without breaking the `ContextProtocol` contract. The module carries an internal version tag (`"v1_keyword"`) to signal which algorithm is active.

## Design Principles

### 1. Accumulate, Never Discard

The ledger is append-only. No entry is ever removed. Boundedness applies only to *projections* — the token-budgeted views served to reasoning. This guarantees no knowledge is lost to summarization, while LLM context windows stay manageable.

### 2. Relevance-Based Projection

Projections rank entries by a composite of importance weighting, tag matching, semantic similarity (when embedding-based), and optional temporal decay. The projection, not the ledger, is what respects token limits.

### 3. Purpose-Scoped Views

Different consumers need different views of the same ledger:

- **Orchestrator reasoning** — full context with goal relevance
- **Subagent briefing** — scoped to the delegated goal only (subagents never see the full ledger)
- **Reflection** — structured evidence summaries
- **User summary** — high-level progress overview

This is why `project()` and `project_for_subagent()` are separate operations rather than one parameterized call: the scoping logic differs meaningfully per consumer.

### 4. Subagent Isolation

Subagents receive projections, not ledger access. They get a bounded, goal-scoped slice and return only results. The orchestrator ingests those results back into the ledger. This enforces a clean information boundary — delegated agents cannot accumulate or leak context beyond their scope.

## Current Context Management

`ContextProtocol` was never implemented. Context management is handled by **`ContextEngine`** (`packages/soothe/src/soothe/foundation/context/`), a concrete engine class that manages within-thread knowledge. It is not a protocol abstraction — it's a direct implementation with its own ledger, projection, and persistence logic.

`ContextEngine` uses these mechanisms:

1. **Context ledger** — an append-only store (`engine.py`, `ledger.py`) that ingests tool outputs, subagent results, and reflections. Unlike the planned `ContextProtocol`, this is a concrete implementation, not a swappable interface.
2. **Projection** — bounded, relevance-ranked views via `projection.py` and `semantic.py`.
3. **Planning integration** — `planning/` submodule integrates context with goal decomposition.
4. **Persistence** — `persistence/` submodule saves/restores the ledger via durability backends.

## Gotchas

- **Not implemented** — `ContextProtocol` does not exist in code. Context is managed by `ContextEngine`, a concrete class, not a protocol. Do not depend on `ContextProtocol` in code.
- **No swappable backends** — unlike `MemoryProtocol` or `DurabilityProtocol`, context has no protocol→backend separation. `ContextEngine` is the sole implementation.
- **Retrieval algorithm is internal** — `semantic.py` implements the current retrieval strategy. There is no version tag or pluggable retrieval module as the draft RFC proposed.
- **Persistence via durability** — the ledger persists through `persistence/` using durability backends, not a dedicated protocol.

## Relationship to Other Protocols

| Protocol | Relationship |
|----------|-------------|
| [MemoryProtocol](memory.md) | Memory is *cross-thread* and explicitly populated; Context is *within-thread* and auto-ingested. Different scopes, different retrieval strategies. |
| [DurabilityProtocol](durability.md) | Provides thread IDs that key context ledgers. Context persistence piggybacks on the thread lifecycle. |
| [LoopWorkingMemoryProtocol](loop-protocols.md) | The bounded scratchpad for Plan-phase prompts. `ContextEngine` provides the richer, persistent ledger that working memory complements. |

## Specification Reference

- **RFC-302**: ContextProtocol: Unbounded Knowledge & Goal-Centric Retrieval (draft)
- **[RFC-300](../../specs/archive/RFC-300-context-memory-protocols.md)**: Context and Memory Architecture Design (archived, superseded by RFC-302)

## Related Documentation

- [RFC-302 Draft](../../specs/RFC-302-context-protocol-architecture.md)
- [Memory Protocol](memory.md) — current cross-thread memory
- [Loop Protocols](loop-protocols.md) — current bounded scratchpad
- [Planner Protocol](planner.md) — consumes bounded context for planning
