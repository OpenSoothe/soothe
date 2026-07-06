---
title: Protocols
nav_order: 7
description: >-
  Protocol layer abstractions — persistence, cognition, and execution protocols.
permalink: /wiki/protocols/
---

# Protocol Layer: Core Abstractions

**Status**: Implemented (except ContextProtocol — draft)
**Philosophy**: Protocol-first, runtime-second (RFC-000 Principle 1)

## What the Protocol Layer Is

Soothe's Protocol Layer defines every core module as a **runtime-agnostic interface** (Python `Protocol`). Protocols declare *what* operations exist; backends define *how* they run. This separation lets Soothe swap SQLite for PostgreSQL, swap an in-memory store for a vector database, or add a plugin backend — all without touching consuming code.

### Why Protocols Exist

Three forces shaped this design:

1. **Testability** — consuming modules (runners, agents, planners) depend on interfaces, not concrete backends. Tests inject fakes.
2. **Pluggability** — the same `MemoryProtocol` shape covers MemU today and custom stores tomorrow. New backends are additive, not invasive.
3. **Runtime decoupling** — protocol signatures never leak runtime types (LangGraph nodes, langchain `BaseTool`). Runtime concerns live in backends, keeping the interface surface stable.

## Protocol Taxonomy

Soothe's protocols organize into four categories:

### Persistence Protocols

| Protocol | Role | Backends | Docs |
|----------|------|----------|------|
| **DurabilityProtocol** | Thread lifecycle (create, resume, suspend, archive) | PostgreSQL, SQLite | [durability.md](durability.md) |
| **MemoryProtocol** | Cross-thread long-term knowledge | MemU | [memory.md](memory.md) |
| **VectorStoreProtocol** | Semantic vector search | PGVector, SQLiteVec, Weaviate | [vector-store-persistence.md](vector-store-persistence.md) |
| **AsyncPersistStore** | Namespaced key-value storage | PostgreSQL, SQLite | [vector-store-persistence.md](vector-store-persistence.md) |

### Cognition Protocols

| Protocol | Role | Backends | Docs |
|----------|------|----------|------|
| **PlannerProtocol** | Goal → plans/steps decomposition with DAG dependencies | LLMPlanner | [planner.md](planner.md) |
| **LoopPlannerProtocol** | StrangeLoop Plan phase (assess + generate) | LLMPlanner (two-phase) | [planner.md](planner.md) |
| **PolicyProtocol** | Permission-based access control, least-privilege delegation | ConfigDrivenPolicy | [policy.md](policy.md) |

### Execution Protocols

| Protocol | Role | Backends | Docs |
|----------|------|----------|------|
| **LoopRunnerProtocol** | StrangeLoop orchestration, streaming, subprocess execution | LocalLoopRunner, RayLoopRunner | [execution-protocols.md](execution-protocols.md) |

### Loop-Level Protocols

| Protocol | Role | Docs |
|----------|------|------|
| **LoopWorkingMemoryProtocol** | Bounded scratchpad for Plan prompts | [loop-protocols.md](loop-protocols.md) |
| **OperationSecurityProtocol** | Operation-level security checks | [loop-protocols.md](loop-protocols.md) |

### Future

| Protocol | Status |
|----------|--------|
| **ContextProtocol** | Draft (RFC-302) — unbounded within-thread knowledge accumulator |

## Protocol Relationships

The protocols form a layered delegation chain. High-level cognition delegates downward; persistence sits at the bottom:

```
ContextEngine (autonomous goal management)
    │  delegates single-goal execution to ↓
StrangeLoop (agentic Plan → Execute loop)
    ├─ LoopPlannerProtocol   (Plan phase)
    ├─ LoopWorkingMemoryProtocol (bounded scratchpad)
    └─ LoopRunnerProtocol    (orchestration)
    │  executes steps via ↓
CoreAgent (runtime)
    └─ PolicyProtocol        (permission checks)
    │  persists via ↓
Persistence Layer
    ├─ DurabilityProtocol    (thread lifecycle)
    ├─ MemoryProtocol        (cross-thread knowledge)
    ├─ VectorStoreProtocol   (semantic search)
    └─ AsyncPersistStore     (key-value storage)
```

## Protocol Interface Conventions

All Soothe protocols share a few invariants worth knowing:

- **`@runtime_checkable`** — enables `isinstance()` structural checks, so code can verify a backend satisfies a protocol at runtime without inheritance.
- **Async-first** — persistence and cognition methods are `async` to support concurrency and connection pooling.
- **Pydantic data models** — structured inputs/outputs (`MemoryItem`, `ThreadInfo`, `Plan`) live alongside their protocol.
- **No runtime types in signatures** — protocol definitions avoid langchain/LangGraph types; backends adapt at the edges.

### Resolution Pattern

Protocols are never instantiated directly. A resolver reads config and returns a backend instance typed as the protocol:

```
Config → resolve_protocol(name, config) → Backend instance (typed as Protocol)
```

Backends are selected purely by configuration keys — `durability_backend: sqlite` vs `postgresql` — so deployment swaps are config-only changes.

## Cross-Protocol Integration Points

A few non-obvious collaborations to keep in mind:

- **Durability ↔ Memory**: archiving a thread triggers memory consolidation. Thread metadata carries a `policy_profile` that flows into policy decisions.
- **Policy ↔ Execution**: `PolicyEnforcementMiddleware` intercepts tool calls and subagent spawns, calling `PolicyProtocol.check()` before any action proceeds.
- **Planner ↔ Runner**: the runner drives the StrangeLoop; each iteration calls `LoopPlanner.plan()`, executes the returned decision, collects `StepResult`s, and loops.
- **VectorStore ↔ Memory**: memory backends use vector search for semantic recall; `AsyncPersistStore` underpins durability and (future) context persistence.

## Multi-Database Architecture (RFC-802)

PostgreSQL deployments split data across dedicated databases for isolation and independent scaling:

- `soothe_metadata` — DurabilityProtocol thread records
- `soothe_vectors` — VectorStoreProtocol embeddings
- `soothe_checkpoints` — LangGraph Checkpointer state
- `soothe_context` — ContextProtocol (future)

Each database has its own connection pool, backup strategy, and ownership boundary, preventing data contamination between concerns.

## Source Reference

Protocol interfaces live in `packages/soothe/src/soothe/protocols/`. Several are re-exported from the SDK package (`packages/soothe-sdk/src/soothe_sdk/protocols/`) for reuse across packages. See individual protocol docs for specific file locations.

## Related Documentation

- [RFC-000](../../specs/) — System Conceptual Design (protocol philosophy)
- [RFC-802](../../specs/) — Persistence Architecture Refactor
- [Backend Implementation Guide](../backends/index.md)
