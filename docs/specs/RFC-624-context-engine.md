# RFC-624: Context Engine

**RFC**: 624
**Title**: Context Engine — Unified Context Management for Goals, Steps, and Projection
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-06-12
**Updated**: 2026-06-12
**Dependencies**: RFC-000 (System Conceptual Design), RFC-200 (Autonomous Goal Management), RFC-201 (AgentLoop Plan-Execute Loop), RFC-214 (Loop Message Surface), RFC-215 (Persistence Backend)
**Related**: RFC-217 (Goal Context Management), RFC-224 (Automatic Context Window Management), RFC-222 (Autopilot GoalEngine Architecture)

---

## Abstract

This RFC introduces `ContextEngine`, a unified interface for context management across Soothe's GoalEngine (goal-level) and AgentLoop (execution-level). ContextEngine consolidates scattered context handling — goal DAG, step DAG, message ledger, working memory, and project instructions — into a single module with clear ownership boundaries. It provides a unified Goal+Step DAG data structure with lineage tracking, a bounded projection mechanism that outputs structured data for prompt templates, and pluggable persistence.

Phase 1 delivers ContextEngine as a standalone module in `soothe.context` with no changes to existing code. Phase 2 wires it into GoalEngine. Phase 3 wires it into AgentLoop via an adapter pattern that guarantees behavioral equivalence with the existing Plan-Exec loop.

---

## Problem Statement

### Current State

Soothe's context handling is scattered across multiple modules with overlapping responsibilities:

1. **GoalEngine** (`autopilot/engine/engine.py`) owns a flat `dict[str, Goal]` for goal DAG management — scheduling, status transitions, dependencies. Goals carry no lineage and no execution records.

2. **AgentLoop** maintains `PlanDAG` (step-level DAG), `LoopWorkingMemory` (step outcome summaries), and `loop_messages` (full message ledger). These are separate data structures with no unified model.

3. **Autopilot Context** has `GoalDispatchContextStore` + `ContextProjector` for parent goal contributions — a partial context projection mechanism limited to autopilot mode.

4. **No lineage tracking**: Neither goals nor steps record the reasoning that created them. After crash recovery, the "why" behind decisions is lost.

5. **No unified projection**: Context projection is ad-hoc — `plan_ledger_projection.py` handles ledger trimming, `GoalContextManager` handles goal context injection, `ContextProjector` handles parent contributions. Each operates on different data with different bounding strategies.

### Goals

1. **Unified data model**: A single Goal+Step DAG that replaces scattered goal storage, step DAG, and working memory.
2. **Lineage tracking**: Goals and steps record their generating reasoning, enabling context projection to show *why* decisions were made.
3. **Structured projection**: A single `ContextBundle` data model output by ContextEngine, rendered by existing prompt templates.
4. **Standalone development**: Phase 1 builds ContextEngine without modifying existing code.
5. **Behavioral equivalence**: Phase 3 integration preserves identical behavior to the current AgentLoop — same prompts, same step IDs, same ledger format.
6. **Incremental migration**: A config flag enables the ContextEngine path without removing the existing path.

### Non-Goals

- ContextEngine is independent from `ContextProtocol` (RFC-000), which remains the orchestrator's cognitive knowledge ledger.
- Procedure memory (Skills, MCP tools) and episodic memory (distilled working history) are deferred.
- RAG / vector store integration is deferred.
- Postgres-backed persistence is deferred (in-memory and file backends in Phase 1).

---

## Integration Path

| Phase | Scope | Existing code changes | Status |
|-------|-------|-----------------------|--------|
| 1 | Standalone `soothe.context` module | None | Done |
| 2 | GoalEngine reads/writes through ContextEngine | GoalEngine internal storage replaced | Future |
| 3a | CE Engine Completeness (Sub-project 1) | CE internal: public API, state transitions, callbacks, lossless persistence, compaction | Done |
| 3b | Adapter Hardening + Projection Wiring (Sub-project 2) | Adapters use public API; ContextBundle wired into prompts | Done |
| 3c | CE Planning Submodule (Sub-project 3) | `soothe.context.planning` submodule: StepPlanningSubengine, GoalPlanningSubengine, GoalScheduler, PlanningFacade; eliminates adapter heuristic duplication | Done |
| 3d | CE-AgentLoop Full Integration (Sub-project 4) | Wire CE into AgentLoop as fully functional parallel path; close 5 integration gaps | This update |

---

## Solution

### Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│ soothe.context (standalone module)                            │
│                                                                │
│  ContextEngine                                                 │
│   • GoalStepDAG: unified goal + nested step DAGs              │
│   • LedgerManager: loop message ledger                        │
│   • SemanticLoader: CLAUDE.md/AGENTS.md/MEMORY.md            │
│   • ProjectionEngine: builds ContextBundle                    │
│   • PersistenceBackend: durability (pluggable)                │
│                                                                │
│  Data Models:                                                  │
│   • GoalNode, StepNode, StepExecution                         │
│   • GoalStepDAG, StepDAG                                      │
│   • ContextBundle (projection output)                         │
│   • GoalStepDAGSnapshot (persistence format)                  │
└──────────────────────────────────────────────────────────────┘
          ↓ Phase 3: Adapter pattern
┌──────────────────────────────────────────────────────────────┐
│ Context Adapters                                              │
│  • ContextEnginePlanAdapter → PlanManager interface           │
│  • ContextEngineLedgerAdapter → mirrors to LedgerManager     │
│  • ContextEngineGoalContextAdapter → GoalContextManager iface │
└──────────────────────────────────────────────────────────────┘
          ↓ Identical interfaces
┌──────────────────────────────────────────────────────────────┐
│ Existing AgentLoop (unchanged)                                │
│  • PromptBuilder — same XML fragments                         │
│  • Executor — same step execution                             │
│  • LangGraph — same node topology                             │
│  • Step ID allocator — same KFA-01 composite IDs              │
│  • Ledger writers — same LoopHumanMessage/LoopAIMessage       │
│  • AgentLoopStateManager — same DB persistence                │
└──────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Standalone Module (Done)

### §1 Status Types

`GoalStatus` includes 9 states: `pending`, `active`, `completed`, `failed`, `suspended`, `blocked`, `validated`, `awaiting_clarification`, `cancelled`. `TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})` — goals in these states satisfy dependency checks.

`StepStatus` includes 4 states: `pending`, `completed`, `failed`, `skipped`.

### §2 Data Model: Unified Goal+Step DAG

The core data model is a two-level DAG: `GoalStepDAG` contains `GoalNode` entries, each embedding a `StepDAG` of `StepNode` entries.

**GoalNode** represents a goal with: status, priority, nesting (`parent_id`), hard dependencies (`depends_on`), soft dependencies (`informs`), conflicts (`conflicts_with`), an embedded `StepDAG`, lineage fields (`generating_reasoning`, `source`), and observability fields (`total_tokens_used`, `thread_id`, `assigned_loop_id`).

**StepNode** represents a step within a goal with: status, intra-goal dependencies, lineage (`plan_iteration`, `reasoning_trace`), and an optional `StepExecution` record.

**StepExecution** captures a CoreAgent run: serialized input/output messages, token usage, duration, error, and thread ID.

**StepDAG** provides: `add_step`, `ready_steps` (with dependency token expansion mirroring `expand_dependency_satisfaction_ids`), status transitions (`mark_completed`, `mark_failed`, `mark_skipped`), stats properties (`total_steps`, `success_rate`), and `chain_depth` (BFS-based longest dependency chain, matching `PlanDAG.max_chain_depth`).

**GoalStepDAG** provides: goal lifecycle (`add_goal`, `complete_goal`, `fail_goal`, `suspend_goal`), scheduling (`ready_goals` mirroring `GoalEngine._filter_ready_candidates`, `active_goals`), lineage (`goal_lineage`), persistence (`snapshot`, `restore_from_snapshot`), and recovery (`recover_active_goals`).

Design decisions:

- **StepDAG embedded in GoalNode**: Steps are goal-scoped — no cross-goal step dependencies. Embedding makes GoalNode the atomic unit of persistence.
- **Lineage via `generating_reasoning`**: Stores the reasoning that produced a goal. Enables context projection to show *why* a goal exists.
- **`source` field**: Tracks origin (`user`, `directive`, `file_discovery`, `decomposition`) for observability and projection filtering.
- **`StepExecution` stored as serialized dicts**: For persistence portability. At runtime, `LedgerManager` holds `BaseMessage` objects; on step completion, ContextEngine serializes into `StepExecution` for durability.
- **Scheduling semantics**: `ready_goals()` filters by `status == "pending"`, checks hard dependencies (`depends_on` all in `TERMINAL_STATES`), checks conflicts (`conflicts_with` no active goal), sorts by `(-priority, created_at)`.

### §3 Context Projection

**ContextBundle** is a structured data model (not a rendered string) containing: goal context (`active_goal`, `goal_progress`), step context (`pending_steps`, `completed_steps`, `failed_steps`), ledger context (`ledger_summary`, `ledger_messages`), semantic context (`project_instructions`, `agent_instructions`, `memory_instructions`), lineage context (`goal_lineage`, `step_lineage`), and observability metadata (`total_tokens_used`, `goal_dag_summary`).

**ProjectionConfig** bounds the output: `max_goals=5`, `max_steps_per_goal=10`, `max_ledger_chars=4000`, `max_ledger_messages=20`, `max_lineage_chars=2000`, `max_project_instructions_chars=8000`.

**ProjectionEngine** builds a `ContextBundle` from `GoalStepDAG` + `LedgerManager` + `SemanticLoader`, bounding each section per `ProjectionConfig`.

Bounding strategy per section:

| Section | Source | Bounding strategy |
|---------|--------|-------------------|
| `active_goal` | GoalStepDAG | Single goal |
| `goal_progress` | StepDAG stats | Rendered summary, max 500 chars |
| `pending_steps` | StepDAG | Top-N by dependency order |
| `completed_steps` | StepDAG | Recent N, truncated descriptions |
| `ledger_summary` | LedgerManager | Condensed text, max `max_ledger_chars` |
| `project_instructions` | SemanticLoader | Raw content, max `max_project_instructions_chars` |
| `goal_lineage` | GoalStepDAG.goal_lineage() | Chain of descriptions, max `max_lineage_chars` |
| `step_lineage` | StepNode.reasoning_trace | Recent reasoning, max `max_lineage_chars` |

### §4 LedgerManager

Replaces `LoopWorkingMemory` and the `loop_messages` list in AgentLoop state. Provides:

- `record_message(message, phase)` — append with phase metadata
- `get_messages(phases)` — filter by phase list
- `project_for_plan(config)` — all phases, bounded by config limits
- `project_for_core_agent()` — execute_step phase only, plus phase=None HumanMessage/AIMessage for compatibility
- `compact()` — summarize old messages (placeholder)
- `record_step_result(step_id, description, output, error, success)` — replaces `LoopWorkingMemory.record_step_result`
- `render_for_reason(max_chars)` — condensed text output

**Ledger-DAG relationship**: LedgerManager is the runtime fast path for message recording and phase-filtered retrieval. The DAG-based recovery is the durability path — after crash recovery, `StepExecution` data is deserialized back into `BaseMessage` objects and the LedgerManager is rehydrated. At runtime, both are kept in sync by `ContextEngine`.

### §5 SemanticLoader

Loads static project instruction files from `workspace` then `SOOTHE_HOME`: `load_project_instructions()` (CLAUDE.md), `load_agent_instructions()` (AGENTS.md), `load_memory()` (MEMORY.md). All methods return empty string on missing files (graceful degradation).

### §6 Persistence

**ContextPersistenceProtocol** defines 5 async methods: `save_dag`, `load_dag`, `save_ledger`, `load_ledger`, `clear`.

| Backend | Use case | Phase |
|---------|----------|-------|
| `InMemoryContextPersistence` | Testing, ephemeral runs | 1 |
| `FileContextPersistence` | Single-process durability | 1 |
| `PostgresContextPersistence` | Multi-process, crash recovery | Future |

`FileContextPersistence` stores JSON under `SOOTHE_HOME/data/context_engine/{loop_id}/` with atomic writes (`.tmp` + `rename`).

### §7 ContextEngine Interface

ContextEngine composes GoalStepDAG, LedgerManager, SemanticLoader, ProjectionEngine, and a PersistenceBackend.

**Goal management**: `create_goal`, `get_goal`, `list_goals`, `complete_goal`, `fail_goal`, `suspend_goal`, `activate_goal` (transitions pending→active, sets `assigned_loop_id`).

**Step management**: `add_step`, `add_steps`, `complete_step`, `fail_step`.

**Ledger management**: `record_message`, `get_ledger`.

**Projection**: `project` → delegates to ProjectionEngine.

**Persistence**: `save`, `load`.

**Recovery**: `recover` — resets goals stuck in `active` to `pending`.

### §8 Module Structure

```
packages/soothe/src/soothe/context/
├── __init__.py              # Public API
├── models.py                # GoalNode, StepNode, StepExecution, StepDAG, GoalStepDAG, GoalStepDAGSnapshot
├── engine.py                # ContextEngine
├── projection.py            # ProjectionEngine, ContextBundle, ProjectionConfig
├── ledger.py                # LedgerManager
├── semantic.py              # SemanticLoader
├── persistence/
│   ├── __init__.py          # ContextPersistenceProtocol + conditional FileContextPersistence
│   ├── base.py              # Protocol definition
│   ├── in_memory.py         # InMemoryContextPersistence
│   └── file_backend.py      # FileContextPersistence
```

---

## Phase 3: AgentLoop Integration

### Design Principle: State Backend Swap with Adapter Pattern

ContextEngine replaces the internal state management of AgentLoop (`PlanManager`, `LoopWorkingMemory`, `GoalContextManager`) while the existing prompt builders, executor, step ID allocators, and ledger writers remain completely unchanged. A config flag selects the path.

**Constraint: 100% behavioral equivalence.** When the ContextEngine path is enabled, the system must produce identical outputs to the current Plan-Exec loop — same SystemMessage fragments, same composite step IDs, same DAG context XML, same LoopHumanMessage/LoopAIMessage ledger entries, same evidence summaries.

### §9 Adapter Layer

Three adapter classes wrap `ContextEngine` to present identical interfaces to the existing code:

#### ContextEnginePlanAdapter

Wraps ContextEngine to satisfy the `PlanManager` interface. The existing orchestrator nodes (`plan_assess`, `plan_generate`, `resolve_decision`, `record_iteration`) call the adapter as if it were `PlanManager`.

| Method | Mapping |
|--------|---------|
| `ingest_plan(plan_result, plan_id, iteration)` | Maps `PlanResult.steps` → `ContextEngine.add_steps()`, preserving composite step IDs (`KFA-01`) as `StepNode.id` values |
| `record_step_outcomes(step_results)` | Maps each `StepResult` → `ContextEngine.complete_step()` or `fail_step()` |
| `get_planning_context() → DagPlanningContext` | Reads `GoalStepDAG` stats and constructs `DagPlanningContext` with identical fields: `pending_step_ids`, `failed_step_ids`, `ready_step_ids`, `chain_depth`, `success_rate`, `replan_count`, `total_steps`, `completed_steps` |
| `format_completion_dag_report() → str` | Renders from `GoalStepDAG` instead of `PlanDAG`, same output format |
| `determine_goal_completion_needs(...)` | Delegates to existing heuristics (unchanged logic) |
| `determine_completion_strategy(...)` | Delegates to existing heuristics (unchanged logic) |

The adapter also maintains `plan_history: list[PlanResult]` and computes `replan_count` from plan history length — matching `PlanManager.plan_history`.

**Key insight**: `_format_dag_context()` (in `builder.py`) uses duck typing on its parameter, accessing exactly 9 attributes: `has_prior_state`, `total_steps`, `completed_steps`, `failed_step_ids`, `ready_step_ids`, `pending_step_ids`, `chain_depth`, `success_rate`, `replan_count`. The adapter's `get_planning_context()` returns a `DagPlanningContext` dataclass providing all of these, so `_format_dag_context` works without modification.

#### ContextEngineLedgerAdapter

Mirrors ledger writes to both `LoopState.loop_messages` (existing prompt pipeline) and `LedgerManager` (persistence and recovery).

- Every append to `loop_messages` is also recorded in `LedgerManager` with the correct phase tag.
- `project_loop_messages_for_plan()` continues to work on the native `loop_messages` list — the adapter doesn't change how the ledger is consumed by `PromptBuilder`.
- `LedgerManager` serves as the persistence/recovery path; `loop_messages` remains the real-time prompt path.

This dual-write approach is the simplest way to maintain behavioral equivalence: `PromptBuilder` and `Executor` never see a different data structure.

#### ContextEngineGoalContextAdapter

Wraps ContextEngine to provide the same `get_plan_context()` and `get_execute_briefing()` interfaces as `GoalContextManager`, reading from `GoalStepDAG` goal history instead of `AgentLoopStateManager.goal_history`.

### §10 Config Flag

```yaml
agent:
  loop:
    context_engine:
      enabled: false           # default off — existing path untouched
      persistence_backend: "file"  # "file" | "in_memory"
```

When `enabled: false`, zero behavioral changes. The adapters are never instantiated. When `enabled: true`, the adapters wrap a `ContextEngine` instance and mirror state.

### §11 Persistence Strategy

The existing PostgreSQL/SQLite checkpoint system (`AgentLoopStateManager`) remains the primary persistence path. ContextEngine's file persistence supplements it:

- **During `record_iteration`**: Existing `state_manager.record_iteration()` persists the full checkpoint to DB. Additionally, `context_engine.save()` persists the DAG and ledger to files.
- **During recovery**: Existing DB-based recovery runs first. `ContextEngine.load()` supplements by restoring DAG state for the ContextEngine's in-memory model.
- **Rationale**: CE file persistence captures the GoalStepDAG and LedgerManager state for quick recovery without DB deserialization. The DB remains the authoritative checkpoint store. This avoids replacing the proven DB persistence layer while gaining CE's structured recovery benefits.

### §12 Required Additions to ContextEngine

The following gaps were identified between the Phase 1 ContextEngine and what the AgentLoop integration requires:

| Gap | Addition | Status |
|-----|----------|--------|
| No `activate_goal()` method | Add `activate_goal(goal_id, loop_id)` — transitions `pending→active`, sets `assigned_loop_id` | Done (Phase 3) |
| No `chain_depth` on `StepDAG` | Add `chain_depth` property (BFS, same algorithm as `PlanDAG.max_chain_depth`) | Done (Phase 3) |
| No composite step ID support | Adapters store composite IDs (`KFA-01`) as `StepNode.id` directly — no CE model change needed | N/A |
| No `plan_history` tracking | `ContextEnginePlanAdapter` maintains its own `plan_history` list — no CE model change needed | N/A |
| No evidence tracking | Not in CE — the adapter reads evidence from `LoopState` directly — no CE model change needed | N/A |
| Ledger serialization is lossy | Lossless `BaseMessage.model_dump()` round-trip (§18) | Phase 3a |
| No `execution_mode` on steps | Not needed — `AgentDecision.execution_mode` stays in `LoopState`, not in `GoalStepDAG` | N/A |
| No public read API | Adapters access `_dag`/`_ledger` directly; add public accessors (§15) | Phase 3a |
| No cancel/skip/block transitions | Missing state machine methods (§16) | Phase 3a |
| No event/callback mechanism | Simple callbacks on state transitions (§17) | Phase 3a |
| Ledger `compact()` is a no-op | Configurable compaction with `compact_fn` (§19) | Phase 3a |
| `ContextBundle.ledger_messages` always empty | Populate in projection (§20) | Phase 3a |

### §13 Files to Create or Modify

**New files:**

| File | Purpose |
|------|---------|
| `packages/soothe/src/soothe/foundation/loop/engine/context_adapters.py` | All three adapter classes |
| `packages/soothe/tests/unit/core/loop/engine/test_context_adapters.py` | Adapter unit tests |

**Modified files:**

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/context/engine.py` | Add `activate_goal()` method |
| `packages/soothe/src/soothe/context/models.py` | Add `chain_depth` property to `StepDAG` |
| `packages/soothe/src/soothe/config/models.py` | Add `ContextEngineConfig` to `AgentLoopConfig` |
| `config/config.template.yml` | Add `context_engine` section |
| `config/config.dev.yml` | Add matching section |

**Not modified (by design):**

| Component | Reason |
|-----------|--------|
| `PromptBuilder` | Adapter produces identical `DagPlanningContext` |
| `Executor` | Step execution is independent of state backend |
| `LangGraph topology` | Node graph and routing unchanged |
| `LoopState` schemas | In-memory state model unchanged |
| `PlanDAG` | Still used by existing path when CE disabled |
| `dependency_tokens.py` | Both paths use the same `expand_dependency_satisfaction_ids` |

---

## Phase 3a: CE Engine Completeness (Sub-project 1)

### §14 Purpose

Harden ContextEngine into a self-sufficient engine with a complete public API, full state machine, event callbacks, lossless persistence, bounded ledger growth, and complete projection output. This sub-project makes no changes to existing AgentLoop code — it only fills gaps within the `soothe.context` module.

### §15 Public Read API

Adapters currently access `_ce._dag` and `_ce._ledger._entries` directly, creating tight coupling. New synchronous read accessors:

| Method | Returns | Purpose |
|--------|---------|---------|
| `get_dag_snapshot()` | `GoalStepDAGSnapshot` | Serializable snapshot of full GoalStepDAG |
| `get_step_dag(goal_id)` | `StepDAG \| None` | StepDAG for a specific goal |
| `get_ledger_entries(phases)` | `list[tuple[BaseMessage, str \| None]]` | (message, phase) tuples, filtered by phase |
| `get_all_goals()` | `list[GoalNode]` | All goals in the DAG |
| `get_goal_lineage(goal_id)` | `list[str]` | Chain of goal descriptions from root |

These are synchronous (not async) since they read from in-memory state. The existing async methods remain for API consistency.

### §16 Missing State Transitions

**GoalStepDAG** additions:

| Method | Transition | Notes |
|--------|-----------|-------|
| `cancel_goal(goal_id)` | → `cancelled` (terminal) | Mirrors `complete_goal`/`fail_goal` |
| `block_goal(goal_id)` | → `blocked` | Goal waiting on unmet condition |
| `unblock_goal(goal_id)` | `blocked` → `pending` | Condition resolved |

**ContextEngine** async additions:

| Method | Delegates to | Callback event |
|--------|-------------|----------------|
| `cancel_goal(goal_id)` | `GoalStepDAG.cancel_goal()` | `goal_cancelled` |
| `skip_step(goal_id, step_id)` | `StepDAG.mark_skipped()` | `step_skipped` |
| `block_goal(goal_id)` | `GoalStepDAG.block_goal()` | `goal_blocked` |
| `unblock_goal(goal_id)` | `GoalStepDAG.unblock_goal()` | `goal_unblocked` |

### §17 Callback Event Mechanism

Simple synchronous callbacks registered by event name. Fire after state changes complete. Errors in callbacks are caught and logged — they never block the state transition.

**Event types**: `goal_created`, `goal_activated`, `goal_completed`, `goal_failed`, `goal_suspended`, `goal_cancelled`, `goal_blocked`, `goal_unblocked`, `step_completed`, `step_failed`, `step_skipped`.

**API**:
- `on(event, callback)` — register a callback for an event
- `off(event, callback)` — unregister a callback
- `_fire(event, *args)` — internal dispatch, catches errors per callback

Callback signatures by event:

| Event | Signature |
|-------|-----------|
| `goal_created` | `(goal_id: str)` |
| `goal_activated` | `(goal_id: str)` |
| `goal_completed` | `(goal_id: str)` |
| `goal_failed` | `(goal_id: str, error: str)` |
| `goal_suspended` | `(goal_id: str, reason: str)` |
| `goal_cancelled` | `(goal_id: str)` |
| `goal_blocked` | `(goal_id: str)` |
| `goal_unblocked` | `(goal_id: str)` |
| `step_completed` | `(goal_id: str, step_id: str)` |
| `step_failed` | `(goal_id: str, step_id: str)` |
| `step_skipped` | `(goal_id: str, step_id: str)` |

Existing methods (`activate_goal`, `complete_goal`, `fail_goal`, `suspend_goal`, `create_goal`, `complete_step`, `fail_step`) also fire callbacks — not just the new ones.

### §18 Lossless Ledger Persistence

**Problem**: `engine.save()` only serializes `type + content + phase`, losing `ToolMessage`, `tool_calls`, `response_metadata`, `usage_metadata`.

**Solution**: Use `BaseMessage.model_dump()` for serialization and `message_type.model_validate()` for deserialization. Each persisted entry includes `_phase` and `_msg_type` metadata keys alongside the full message dump.

**Backward compatibility**: Old persisted files (with `type + content + phase` only) continue to load — `load()` detects the absence of `_msg_type` and falls back to the old format.

Message type mapping for reconstruction:

| Type name | Class | Notes |
|-----------|-------|-------|
| `AIMessage` | `AIMessage` | Direct |
| `HumanMessage` | `HumanMessage` | Direct |
| `SystemMessage` | `SystemMessage` | Direct |
| `ToolMessage` | `ToolMessage` | Direct |
| `AIMessageChunk` | `AIMessageChunk` | Direct |
| `LoopAIMessage` | `AIMessage` | Fallback — content preserved |
| `LoopHumanMessage` | `HumanMessage` | Fallback — content preserved |

If reconstruction fails, fall back to content-only message of the mapped type.

### §19 Ledger Compaction

**Design**: Configurable compaction function passed to `LedgerManager.__init__`. When entries exceed `max_entries` (default 200), the oldest entries are compacted.

- **With `compact_fn`**: The function receives the oldest entries and returns a summary string (or None to skip). The summary replaces those entries as a single `SystemMessage` with `phase="compacted"`.
- **Without `compact_fn`** (default): Entries beyond `max_entries` are dropped. This matches current behavior where `loop_messages` grows unbounded but is bounded by the projection layer.

Compaction is auto-triggered after each `record_message()` when the count exceeds `max_entries`.

### §20 Complete ContextBundle Projection

**Problem**: `ContextBundle.ledger_messages` is always empty.

**Solution**: Populate in `ProjectionEngine.project()` — structured list of `{type, phase, content}` dicts, bounded by `max_ledger_messages` and per-message content cap of 500 chars. Provides structured ledger access without full BaseMessage objects.

### §21 LedgerManager Public Access

Add `entries(phases)` method returning `(message, phase)` tuples. This replaces direct `_entries` access by both the engine (for persistence) and future adapter code.

### §22 Files to Modify

All changes are within `soothe.context`. No existing AgentLoop code is modified.

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/context/engine.py` | Public read API, missing transitions, callback mechanism, lossless save/load |
| `packages/soothe/src/soothe/context/models.py` | `cancel_goal`, `block_goal`, `unblock_goal` on `GoalStepDAG` |
| `packages/soothe/src/soothe/context/ledger.py` | `compact()` implementation, `entries()` public method, `max_entries` + `compact_fn` params |
| `packages/soothe/src/soothe/context/projection.py` | Populate `ledger_messages` in ContextBundle |

### §23 Testing

New unit tests in `packages/soothe/tests/unit/context/`:

- Public read API: `get_dag_snapshot`, `get_step_dag`, `get_ledger_entries`, `get_all_goals`, `get_goal_lineage`
- State transitions: `cancel_goal`, `skip_step`, `block_goal`/`unblock_goal`
- Callbacks: registration, firing, error handling, unregistration
- Lossless persistence: round-trip with Human, AI, Tool, System messages; backward compat with old format
- Ledger compaction: with and without `compact_fn`
- Projection: `ledger_messages` populated with bounded content

All existing tests (22 adapter + 9 integration) must continue to pass without modification.

---

## Phase 3b: Adapter Hardening + Projection Wiring (Sub-project 2)

### §24 Purpose

Fix the adapter gap (GoalContextAdapter reads from old state_manager instead of CE DAG), refactor adapters to use the public API from Sub-project 1, and wire ContextBundle into the prompt pipeline as supplementary context when CE is enabled.

### §25 Adapter Hardening

**GoalContextAdapter gap**: Both `get_plan_context()` and `get_execute_briefing()` read from `self._state_manager` (the old `AgentLoopStateManager`) instead of `self._ce` (the ContextEngine). Fix:

- `get_plan_context()`: Read completed goals from `self._ce.get_all_goals()`, filter by `status == "completed"`, format as `<previous_goal>` XML blocks using goal description and step outcomes.
- `get_execute_briefing()`: Read from CE DAG goals for thread-switch briefing, using `self._ce.get_goal_lineage()` and step summaries.

**Private field access refactor**: All three adapters currently access `self._ce._dag` and `self._ce._ledger._entries` directly. Replace with public API:

- `self._ce._dag.get_goal(goal_id)` → `self._ce.get_step_dag(goal_id)` (for step operations) or keep `await self._ce.get_goal(goal_id)` (for goal-level operations)
- `self._ce._dag.goals.values()` → `self._ce.get_all_goals()`
- `self._ce._ledger.get_messages(...)` → `self._ce.get_ledger_entries(...)`
- `self._ce._ledger.record_message(...)` → `await self._ce.record_message(...)`

### §26 Projection Wiring (Supplementary Injection)

When CE is enabled, `ContextBundle` from `ContextEngine.project()` is injected into the prompt pipeline as supplementary context. No existing context is removed or replaced.

**Integration point**: Add `context_bundle: ContextBundle | None = None` parameter to `PromptBuilder.build_plan_messages()`. Thread it to `_build_system_message()` and `_build_plan_context_human_text()`.

**Supplementary injections when bundle is available**:

| Location | Current | Bundle supplement |
|----------|---------|-------------------|
| `_build_system_message` | `load_workspace_project_instructions(workspace)` | Use `bundle.project_instructions` instead of disk read |
| `_build_system_message` | N/A | Append `bundle.agent_instructions` and `bundle.memory_instructions` if non-empty |
| `_build_plan_context_human_text` | `<PLAN_DAG_CONTEXT>` from `_format_dag_context()` | Keep current; add `<GOAL_LINEAGE>` block from `bundle.goal_lineage` if non-empty |
| `_build_plan_context_human_text` | N/A | Add `<GOAL_PROGRESS>` block from `bundle.goal_progress` if non-empty |
| `_build_plan_context_human_text` | N/A | Add `<STEP_LINEAGE>` block from `bundle.step_lineage` if non-empty |

**When CE is disabled**: `context_bundle` is `None`, all supplementary injections are skipped, behavior is identical to current.

### §27 Files to Modify

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/foundation/loop/engine/context_adapters.py` | Fix GoalContextAdapter to read from CE; refactor all adapters to use public API |
| `packages/soothe/src/soothe/foundation/loop/prompts/builder.py` | Add `context_bundle` param; supplementary injections |
| `packages/soothe/src/soothe/foundation/loop/planning/planner.py` | Pass `context_bundle` to `build_plan_messages()` when CE enabled |
| `packages/soothe/src/soothe/foundation/loop/orchestrator/runtime_context.py` | Add `context_bundle` field (computed per planning call) |

### §28 Behavioral Equivalence

When CE is enabled, the supplementary injections add context but do not change existing context. The existing `<PLAN_DAG_CONTEXT>`, `<USER_QUERY>`, `<PRIOR_PROGRESS>`, ledger projection, and system message fragments all remain identical. The only differences are additive: goal lineage, goal progress, step lineage, and pre-loaded project/agent/memory instructions.

When CE is disabled, zero changes — `context_bundle` is `None` and all code paths are guarded.

---

## Phase 3c: CE Planning Submodule (Sub-project 3)

### §29 Purpose

Create a `soothe.context.planning` submodule that absorbs step-level planning into CE (eliminating the adapter heuristic duplication), adds goal-level planning stubs, and provides scheduling logic. This sub-project makes `StepPlanManagerAdapter` a ~30-line thin wrapper, replacing the 420+ line `ContextEnginePlanAdapter` that duplicated ~150 lines of heuristic logic from `PlanManager`.

### §30 Extracted Completion Heuristics

`soothe.context.planning.completion.py` is the single source of truth for all planning heuristics. Functions take primitive keyword arguments (preserving CE independence from `LoopState`):

| Function | Purpose |
|----------|---------|
| `heuristic_requires_goal_completion(...)` | Check execution complexity indicators requiring synthesis |
| `is_simple_execution(...)` | Check if the DAG represents a single-plan execution |
| `dag_requires_synthesis(...)` | Check whether DAG complexity warrants synthesis |
| `determine_goal_completion_needs(...)` | Decide whether goal-completion synthesis is required |
| `determine_completion_strategy(...)` | Determine final response strategy from DAG + history |

Threshold constants defined once: `LOW_SUCCESS_RATE_THRESHOLD = 0.6`, `DAG_DEPENDENCY_THRESHOLD = 3`, `SIMPLE_DAG_LEDGER_DIRECT_MAX_STEPS = 2`.

`PlanManager` in `soothe.foundation.loop.planning.manager.py` delegates to these functions instead of containing its own implementations. No behavioral change — purely internal refactoring.

### §31 StepPlanningSubengine

Reads/writes directly through `GoalStepDAG`. No ownership of state — CE is the single source of truth. All methods take `goal_id` as first parameter for multi-goal awareness.

| Method | Description |
|--------|-------------|
| `ingest_plan(goal_id, plan_result, plan_id, iteration)` | Map `PlanResult.steps` → `StepNode` entries in goal's `StepDAG` |
| `record_step_outcomes(goal_id, step_results)` | Map `StepResult` → StepDAG status transitions |
| `get_planning_context(goal_id) → DagPlanningContext` | 9-attribute context identical to `PlanManager.get_planning_context()` |
| `determine_goal_completion_needs(goal_id, ...)` | Delegate to `completion.py` with extracted DAG stats |
| `determine_completion_strategy(goal_id, ...)` | Delegate to `completion.py` with extracted DAG stats |
| `format_completion_dag_report(goal_id=None)` | Render full hierarchical or single-goal DAG report |

Internal `_DagStats` dataclass extracts primitive values from `GoalNode`/`StepDAG` for heuristic functions, maintaining CE independence from `LoopState`.

### §32 StepPlanManagerAdapter

Thin adapter that binds `goal_id` to `StepPlanningSubengine` to satisfy the `PlanManager` duck-typed interface. ~30 lines vs the previous `ContextEnginePlanAdapter` at 420+ lines with 150 lines of duplicated heuristics.

```python
class StepPlanManagerAdapter:
    def __init__(self, subengine: StepPlanningSubengine, goal_id: str) -> None:
        self._subengine = subengine
        self._goal_id = goal_id
        self.plan_history: list[PlanResult] = []

    def ingest_plan(self, plan_result, plan_id, iteration): ...
    def record_step_outcomes(self, step_results): ...
    def get_planning_context(self) -> DagPlanningContext: ...
    def determine_goal_completion_needs(self, llm_decision, state, mode="llm_only"): ...
    def determine_completion_strategy(self, state, plan_result, mode="adaptive"): ...
    def format_completion_dag_report(self) -> str: ...
```

`ContextEnginePlanAdapter` is removed. `agent_loop.py` wires `StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=ce_goal.id)` instead.

### §33 Planning Models

`soothe.context.planning.models.py` contains:

- `PlanWave`: Record of a single plan ingestion wave
- `SubGoalSpec`: Specification for a subgoal to be created during decomposition
- `DecompositionRequest` / `DecompositionResult`: LLM-driven goal decomposition (Phase 2 future)
- `OrchestrationStrategy`: Multi-goal orchestration strategy
- `CompletionStrategy` (StrEnum): `ledger_direct`, `synthesize`, `summary` — moved from `manager.py` to break circular imports
- `DagPlanningContext` (dataclass): 9-attribute structured DAG summary — moved from `manager.py` to break circular imports

Moving `CompletionStrategy` and `DagPlanningContext` to CE planning models eliminates the circular import chain: `manager.py` → `completion.py` → `__init__.py` → `step_planner.py` → `manager.py`.

### §34 PlanningFacade and Subengines

```python
@dataclass
class PlanningFacade:
    step: StepPlanningSubengine
    goal: GoalPlanningSubengine
    scheduler: GoalScheduler
```

`ContextEngine.planning` property returns `PlanningFacade`.

**GoalPlanningSubengine**: Stub for Phase 2 — `decompose_goal()` returns empty decomposition, `compute_orchestration_strategy()` computes from goal DAG.

**GoalScheduler**: Extracts scheduling logic from `GoalEngine._filter_ready_candidates` — `ready_goals()`, `claim_goal()`, `is_complete()`.

### §35 Phase 3c Files

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/context/planning/__init__.py` | New: `PlanningFacade` |
| `packages/soothe/src/soothe/context/planning/completion.py` | New: extracted heuristic functions (single source of truth) |
| `packages/soothe/src/soothe/context/planning/models.py` | New: planning models, `DagPlanningContext`, `CompletionStrategy` |
| `packages/soothe/src/soothe/context/planning/step_planner.py` | New: `StepPlanningSubengine` + `StepPlanManagerAdapter` |
| `packages/soothe/src/soothe/context/planning/goal_planner.py` | New: `GoalPlanningSubengine` (stub) |
| `packages/soothe/src/soothe/context/planning/scheduling.py` | New: `GoalScheduler` |
| `packages/soothe/src/soothe/context/engine.py` | Add planning subengines and `planning` property |
| `packages/soothe/src/soothe/foundation/loop/planning/manager.py` | Delegate heuristics to `completion.py`; import `DagPlanningContext` and `CompletionStrategy` from `soothe.context.planning.models` |
| `packages/soothe/src/soothe/foundation/loop/engine/agent_loop.py` | Wire `StepPlanManagerAdapter` instead of `ContextEnginePlanAdapter` |
| `packages/soothe/src/soothe/foundation/loop/engine/context_adapters.py` | Remove `ContextEnginePlanAdapter` |
| `packages/soothe/src/soothe/foundation/loop/orchestrator/runtime_context.py` | Update `plan_manager` type to accept `PlanManager | StepPlanManagerAdapter` |

---

## Phase 3d: CE-AgentLoop Full Integration (Sub-project 4)

### §36 Purpose

Wire ContextEngine into AgentLoop as a fully functional parallel path, closing 5 integration gaps that remain from Phases 3a–3c. When CE is enabled, every graph node correctly interacts with CE — goal lifecycle, step feedback, projection, persistence, and semantic loading all function. When CE is disabled, zero behavioral change.

### §37 Gap Analysis

Five gaps remain between the current partial sidecar integration and a fully functional CE path:

| # | Gap | Current State | Fix |
|---|-----|---------------|-----|
| G1 | Goal lifecycle incomplete | `create_goal`/`activate_goal` called at startup, but `complete_goal`/`fail_goal` never called | Close the lifecycle in `goal_completion` node |
| G2 | Step completion feedback missing | `StepPlanningSubengine.record_step_outcomes()` mutates DAG synchronously, but CE async APIs + callbacks never fire | Dual-path: call CE async step APIs alongside sync mutations |
| G3 | Projection never invoked | `ContextEngine.project()` builds `ContextBundle` but no node calls it | Call in `plan_generate`, inject into `PromptBuilder` |
| G4 | CE persistence only at goal end | `ce.save()` only in `goal_completion` — mid-loop crash loses state | Save after each plan ingest and step execution |
| G5 | Semantic loading unused | `SemanticLoader` initialized but never called | Load at loop start, inject into `ContextBundle` |

### §38 ContextEngineLifecycle

New class `ContextEngineLifecycle` encapsulates all CE interactions for one goal run. Stored on `LoopRuntimeContext.ce_lifecycle`.

```python
class ContextEngineLifecycle:
    """All ContextEngine interactions for one AgentLoop goal run.

    CE disabled → all methods are no-ops.
    CE enabled → each method handles goal lifecycle, step feedback,
    projection, persistence atomically.
    """

    def __init__(self, context_engine: ContextEngine | None, goal_id: str | None) -> None:
        self._ce = context_engine
        self._goal_id = goal_id

    @property
    def enabled(self) -> bool:
        return self._ce is not None and self._goal_id is not None
```

**Lifecycle Hooks:**

| Hook | Called From | CE Actions |
|------|------------|------------|
| `on_goal_start()` | `agent_loop` startup | `semantic.load(workspace)` |
| `on_plan_ingested(plan_result, plan_id, iteration)` | `plan_assess`, `resolve_decision` (after `ingest_plan`) | `save()` |
| `on_steps_executed(step_results)` | `record_iteration` (after `record_step_outcomes`) | `complete_step()`/`fail_step()` async + `save()` |
| `on_goal_complete(status, plan_result)` | `goal_completion` | `complete_goal()`/`fail_goal()` + `save()` |
| `get_context_bundle()` | `plan_generate` | `ce.project()` → `ContextBundle` |
| `save()` | (internal, after each mutation) | `ce.save()` to persistence backend |

**Error handling**: All lifecycle methods catch and log exceptions. CE failures never propagate to graph nodes — the plan-exec loop continues regardless. Async step APIs fire via `asyncio.create_task()` so callback errors don't block.

### §39 Integration Points per Graph Node

#### agent_loop.py (startup)

Current CE path already creates CE instance, goal, and adapters. Additions:

- Create `ContextEngineLifecycle(ce_instance, ce_goal.id)` and store on `LoopRuntimeContext`
- Call `await ce_lifecycle.on_goal_start()` after goal creation

#### plan_assess.py

After `plan_manager.ingest_plan()`:
```python
if ctx.ce_lifecycle and ctx.ce_lifecycle.enabled:
    await ctx.ce_lifecycle.on_plan_ingested(plan_result, state.plan_id, state.iteration)
```

#### plan_generate.py

Inject `ContextBundle` into prompt rendering:
```python
context_bundle = ctx.ce_lifecycle.get_context_bundle() if ctx.ce_lifecycle else None
messages = plan_phase.generate_from_assessment(..., context_bundle=context_bundle)
```

The `PromptBuilder.build_plan_messages()` already accepts `context_bundle` (wired in Phase 3b). No `PromptBuilder` changes needed.

#### execute_steps.py

No change — step outcomes are recorded in `record_iteration`, not here.

#### record_iteration.py

After `plan_manager.record_step_outcomes(step_results)`:
```python
if ctx.ce_lifecycle and ctx.ce_lifecycle.enabled:
    await ctx.ce_lifecycle.on_steps_executed(step_results)
```

#### goal_completion.py

Replace the existing `ctx.context_engine.save()` block with:
```python
if ctx.ce_lifecycle and ctx.ce_lifecycle.enabled:
    await ctx.ce_lifecycle.on_goal_complete(status, plan_result)
```

This handles goal lifecycle (G1), persistence (G4), and is cleaner than the scattered save call.

### §40 Step Feedback: Dual-Path Design (G2)

`on_steps_executed()` implements dual-path recording:

1. **Sync path (already done)**: `plan_manager.record_step_outcomes()` mutates the `GoalStepDAG` via `StepPlanningSubengine` — this is the source of truth for planning context and reports.
2. **Async path (new)**: For each step result, call `ce.complete_step(goal_id, step_id, execution)` or `ce.fail_step(goal_id, step_id, execution)`. These fire callbacks (`on_step_completed`, `on_step_failed`) and events. Fire via `asyncio.create_task()` to avoid blocking.

The sync path always runs first, ensuring planning context is current before any async callbacks fire.

### §41 Projection: ContextBundle Injection (G3)

`get_context_bundle()` calls `ce.project()` with a `ProjectionConfig`:

- **Plan phase**: includes goal lineage, goal progress, step lineage, project/agent/memory instructions
- **Execute phase**: includes goal progress and step lineage only (lighter)

The `ContextBundle` is already wired into `PromptBuilder.build_plan_messages()` from Phase 3b. The injection is additive — existing context sections (`PLAN_DAG_CONTEXT`, `USER_QUERY`, `PRIOR_PROGRESS`) are unchanged.

### §42 Persistence Strategy (G4)

Save CE state at three points:

1. After `on_plan_ingested()` — captures new step nodes
2. After `on_steps_executed()` — captures step outcomes
3. At `on_goal_complete()` — captures final goal status

This ensures CE state survives a crash at any point with at most one iteration of data loss.

### §43 Semantic Loading (G5)

`on_goal_start()` calls `ce.semantic.load(workspace)` which indexes:

- `CLAUDE.md`, `AGENTS.md`, `MEMORY.md` from workspace root
- Same files from `SOOTHE_HOME` as fallback

Loaded instructions flow into `ContextBundle` via `ce.project()`. When semantic loading fails (file not found, permission error), the `ContextBundle` fields are empty — no injection occurs.

### §44 Config Change

Flip default for new installs:

```yaml
agent:
  loop:
    context_engine:
      enabled: true            # was false
      persistence_backend: "file"
```

Existing config files with `enabled: false` continue to work unchanged. No migration required.

### §45 Backward Compatibility

- **CE disabled**: `ContextEngineLifecycle(None, None)`. All methods are no-ops. `enabled` returns `False`. Graph node guards (`if ctx.ce_lifecycle and ctx.ce_lifecycle.enabled`) skip all CE calls. Zero behavioral change from current AgentLoop.
- **CE enabled**: All existing prompt fragments remain identical. `ContextBundle` is additive only. The `StepPlanningSubengine` produces the same `DagPlanningContext` with the same 9 attributes. The `format_completion_dag_report()` output uses the hierarchical CE DAG format but contains equivalent information.
- **Existing tests**: All existing tests continue to pass. New tests verify the CE-specific behavior.

### §46 Phase 3d Files

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/foundation/loop/engine/context_lifecycle.py` | **New**: `ContextEngineLifecycle` class |
| `packages/soothe/src/soothe/foundation/loop/orchestrator/runtime_context.py` | Add `ce_lifecycle` field |
| `packages/soothe/src/soothe/foundation/loop/engine/agent_loop.py` | Create lifecycle, call `on_goal_start()` |
| `packages/soothe/src/soothe/foundation/loop/orchestrator/nodes/plan_assess.py` | Call `on_plan_ingested()` |
| `packages/soothe/src/soothe/foundation/loop/orchestrator/nodes/plan_generate.py` | Pass `context_bundle` from lifecycle |
| `packages/soothe/src/soothe/foundation/loop/orchestrator/nodes/record_iteration.py` | Call `on_steps_executed()` |
| `packages/soothe/src/soothe/foundation/loop/orchestrator/nodes/goal_completion.py` | Replace `ce.save()` with `on_goal_complete()` |
| `packages/soothe/src/soothe/config/models.py` | Flip `enabled` default to `True` |
| `packages/soothe/tests/unit/core/loop/engine/test_context_lifecycle.py` | **New**: lifecycle unit tests |
| `packages/soothe/tests/integration/context/test_ce_agent_loop_equivalence.py` | Add lifecycle + goal completion tests |

### §47 Acceptance Criteria

- All 5 gaps closed: goal lifecycle, step feedback, projection, persistence, semantics
- CE on-by-default for new installs
- CE disabled path produces zero behavioral change
- CE enabled path produces identical plan-exec outputs + additive `ContextBundle`
- All existing tests pass
- New tests cover `ContextEngineLifecycle`, goal completion, projection injection

---

## Data Flow

### Phase 1: Standalone ContextEngine

```
User Goal
  │
  ▼
ContextEngine.create_goal(description, generating_reasoning=...)
  │  → GoalNode added to GoalStepDAG
  │
  ▼
ContextEngine.project() → ContextBundle
  │  → Prompt templates render bundle into system/user messages
  │  → CoreAgent receives rendered messages
  │
  ▼
CoreAgent executes → output messages
  │
  ▼
ContextEngine.add_steps(goal_id, [StepNode(...)], plan_iteration=N)
  │  → Steps added to goal's StepDAG
  │
  ▼
ContextEngine.complete_step(goal_id, step_id, StepExecution(...))
  │  → StepNode.status = "completed", execution recorded
  │  → LedgerManager records step result
  │
  ▼
ContextEngine.project() → updated ContextBundle
  │  → Next iteration sees completed steps, pending steps, lineage
  │
  ▼
... all steps complete ...
  │
  ▼
ContextEngine.complete_goal(goal_id)
  → GoalNode.status = "completed"
```

### Phase 3: AgentLoop Integration (when CE enabled)

```
AgentLoop.run_with_progress(goal, ...)
  │
  ├─ Create ContextEngine (with FileContextPersistence)
  ├─ Create adapters wrapping ContextEngine
  ├─ Pass adapter as plan_manager to orchestrator nodes
  │
  ▼
LangGraph iteration cycle (unchanged topology):
  │
  plan_assess / plan_generate
  │  → PromptBuilder builds messages (unchanged)
  │  → ce_lifecycle.get_context_bundle() → ContextBundle injected into prompts (Phase 3d)
  │  → LLM returns PlanResult
  │
  ▼
resolve_decision
  │  → allocate_plan_id, assign_plan_step_ids (unchanged)
  │  → Adapter.ingest_plan() records steps in ContextEngine
  │  → ce_lifecycle.on_plan_ingested() → save (Phase 3d)
  │
  ▼
execute
  │  → Executor runs steps (unchanged)
  │  → LedgerAdapter mirrors writes to both loop_messages and LedgerManager
  │
  ▼
record_iteration
  │  → state_manager.record_iteration() → DB (unchanged)
  │  → ce_lifecycle.on_steps_executed() → async step feedback + save (Phase 3d)
  │
  ▼
  ... loop until goal complete ...
  │
  ▼
goal_completion
  │  → Adapter.get_planning_context() → DagPlanningContext (unchanged format)
  │  → Existing completion strategy logic (unchanged)
  │  → ce_lifecycle.on_goal_complete() → complete_goal/fail_goal + save (Phase 3d)
```

### Ledger Recovery from GoalStepDAG

The loop message ledger is always derivable from the GoalStepDAG. Given a `GoalStepDAG`, the ledger is reconstructed by:

1. Collecting all `StepExecution.input_messages` and `StepExecution.output_messages` across all steps, ordered by step execution sequence
2. Including `GoalNode.generating_reasoning` as plan-phase messages

This makes the ledger a view of the DAG rather than a separate source of truth.

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Step execution failure | `StepNode.status = "failed"`, `execution.error` set. Goal remains active. AgentLoop decides replan vs fail-goal. |
| Goal failure | `GoalNode.status = "failed"`. Dependent goals remain blocked (dependencies not met). |
| Persistence failure | In-memory fallback with warning log. Query and projection continue; durability degraded. |
| Crash recovery | On `load()`, `recover()` resets active goals to pending. Steps with no execution reset to pending. |
| Invalid DAG operation | Cycle detection on `add_dependency`. Depth limit on goal nesting (max 5). |

---

## Invariants

1. `GoalStepDAG` is the single source of truth for goal and step data within `soothe.context`.
2. Step dependencies are strictly within the same goal — cross-goal coordination uses goal-level `depends_on`.
3. `ContextBundle` is a read-only projection; mutation happens through `ContextEngine` methods only.
4. The message ledger is derivable from the GoalStepDAG (via `StepExecution` records).
5. `ContextPersistenceProtocol` implementations must support atomic save/load (no partial writes).
6. `ContextEngine` does not depend on `GoalEngine`, `AgentLoop`, or `CoreAgent` — it is standalone.
7. When the ContextEngine path is enabled in AgentLoop, all adapter outputs must be indistinguishable from the current Plan-Exec loop outputs (behavioral equivalence).
8. The existing AgentLoop path (CE disabled) must remain completely untouched — zero behavioral changes.
9. `ContextEngineLifecycle` is the sole entry point for CE interactions from graph nodes — nodes never call CE methods directly.
10. CE failures must never propagate to graph nodes — the plan-exec loop continues regardless of CE errors.

---

## Migration Path (Future Phases)

### Phase 2: GoalEngine Integration

- GoalEngine reads/writes goals through ContextEngine instead of internal `_goals` dict
- `GoalEngine.create_goal()` becomes a thin wrapper delegating to `ContextEngine.create_goal()`
- ContextProjector reads from ContextEngine instead of GoalDispatchContextStore
- Backward-compatible: GoalEngine's public API unchanged, internal storage replaced

### Phase 3: AgentLoop Integration

- AgentLoop's `PlanManager` replaced by `StepPlanManagerAdapter` wrapping `StepPlanningSubengine` (Phase 3c)
- `ContextEnginePlanAdapter` removed — heuristic duplication eliminated via `completion.py` (Phase 3c)
- `LoopWorkingMemory` + `loop_messages` mirrored to `LedgerManager` via `ContextEngineLedgerAdapter` (Phase 3)
- `GoalContextManager` replaced by `ContextEngineGoalContextAdapter` (Phase 3)
- Config flag `agent.loop.context_engine.enabled` selects the path (Phase 3)
- `ContextEngineLifecycle` encapsulates all CE interactions per goal run (Phase 3d)
- Goal lifecycle, step feedback, projection, persistence, semantic loading fully wired (Phase 3d)
- CE on-by-default for new installs (Phase 3d)
- Existing prompt pipeline, executor, and LangGraph topology remain unchanged
- DB persistence remains primary; CE file persistence supplements for DAG state
