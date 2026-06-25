# RFC-624: Context Engine

**RFC**: 624
**Title**: Context Engine — Unified Context Management for Goals, Steps, and Projection
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-06-12
**Updated**: 2026-06-15 (Phase 4 Stage 2 cleanup)
**Dependencies**: RFC-000 (System Conceptual Design), RFC-200 (Autonomous Goal Management), RFC-201 (StrangeLoop Plan-Execute Loop), RFC-214 (Loop Message Surface), RFC-803 (Persistence Backend)
**Related**: RFC-217 (Goal Context Management), RFC-224 (Automatic Context Window Management), RFC-222 (Autopilot GoalEngine Architecture), RFC-625 (AutopilotMonitor and ContextEngine Unification), RFC-626 (Entity Model and State Management Consolidation)

---

## Abstract

This RFC introduces `ContextEngine`, a unified interface for context management across Soothe's GoalEngine (goal-level) and StrangeLoop (execution-level). ContextEngine consolidates scattered context handling — goal DAG, step DAG, message ledger, working memory, and project instructions — into a single module with clear ownership boundaries. It provides a unified Goal+Step DAG data structure with lineage tracking, a bounded projection mechanism that outputs structured data for prompt templates, and pluggable persistence.

Phase 1 delivers ContextEngine as a standalone module in `soothe.context` with no changes to existing code. Phase 2 wires it into GoalEngine. Phase 3 wires it into StrangeLoop via an adapter pattern that guarantees behavioral equivalence with the existing Plan-Exec loop. Phase 4 makes CE the sole data source for goal/step/ledger state, deleting all adapters and trimming LoopState to a thin `ExecutionState` facade holding only execution-only fields.

---

## Problem Statement

### Current State

Soothe's context handling is scattered across multiple modules with overlapping responsibilities:

1. **GoalEngine** (`autopilot/engine/engine.py`) owns a flat `dict[str, Goal]` for goal DAG management — scheduling, status transitions, dependencies. Goals carry no lineage and no execution records.

2. **StrangeLoop** maintains `PlanDAG` (step-level DAG), `LoopWorkingMemory` (step outcome summaries), and `loop_messages` (full message ledger). These are separate data structures with no unified model.

3. **Autopilot Context** has `GoalDispatchContextStore` + `ContextProjector` for parent goal contributions — a partial context projection mechanism limited to autopilot mode.

4. **No lineage tracking**: Neither goals nor steps record the reasoning that created them. After crash recovery, the "why" behind decisions is lost.

5. **No unified projection**: Context projection is ad-hoc — `plan_ledger_projection.py` handles ledger trimming, `GoalContextManager` handles goal context injection, `ContextProjector` handles parent contributions. Each operates on different data with different bounding strategies.

### Goals

1. **Unified data model**: A single Goal+Step DAG that replaces scattered goal storage, step DAG, and working memory.
2. **Lineage tracking**: Goals and steps record their generating reasoning, enabling context projection to show *why* decisions were made.
3. **Structured projection**: A single `ContextBundle` data model output by ContextEngine, rendered by existing prompt templates.
4. **Standalone development**: Phase 1 builds ContextEngine without modifying existing code.
5. **Behavioral equivalence**: Phase 3 integration preserves identical behavior to the current StrangeLoop — same prompts, same step IDs, same ledger format.
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
| 3d | CE-StrangeLoop Full Integration (Sub-project 4) | Wire CE into StrangeLoop as fully functional parallel path; close 5 integration gaps | Done |
| 4 Stage 1 | CE-backed properties + loop-scoped CE lifecycle | Property migration, persistence polish, loop-scoped CE, projection config | Done |
| 4 Stage 2 | Remaining cleanup + deeper integration | Slim GER, CE-only ledger writes, delete deprecated functions, replace goal_history reads with CE queries | This update |

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
          ↓ Phase 3: Adapter pattern (deprecated in Phase 4)
┌──────────────────────────────────────────────────────────────┐
│ Phase 3: Context Adapters (deleted in Phase 4)               │
│  • ContextEnginePlanAdapter → PlanManager interface           │
│  • ContextEngineLedgerAdapter → mirrors to LedgerManager     │
│  • ContextEngineGoalContextAdapter → GoalContextManager iface │
└──────────────────────────────────────────────────────────────┘
          ↓ Phase 4: Direct CE access (no adapters)
┌──────────────────────────────────────────────────────────────┐
│ StrangeLoop Graph Nodes (Phase 4: call ctx.ce directly)       │
│  • PromptBuilder — same XML fragments                         │
│  • Executor — same step execution                             │
│  • LangGraph — same node topology                             │
│  • Step ID allocator — same KFA-01 composite IDs              │
│  • Ledger writers → ce.ledger.record_message() (sole source)  │
│  • ExecutionState — thin facade, CE-backed properties         │
│  • StrangeLoopStateManager — trimmed checkpoint (schema 4.0)  │
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

Replaces `LoopWorkingMemory` and the `loop_messages` list in StrangeLoop state. Provides:

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

## Phase 3: StrangeLoop Integration

### Design Principle: State Backend Swap with Adapter Pattern

ContextEngine replaces the internal state management of StrangeLoop (`PlanManager`, `LoopWorkingMemory`, `GoalContextManager`) while the existing prompt builders, executor, step ID allocators, and ledger writers remain completely unchanged. A config flag selects the path.

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

Wraps ContextEngine to provide the same `get_plan_context()` and `get_execute_briefing()` interfaces as `GoalContextManager`, reading from `GoalStepDAG` goal history instead of `StrangeLoopStateManager.goal_history`.

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

The existing PostgreSQL/SQLite checkpoint system (`StrangeLoopStateManager`) remains the primary persistence path. ContextEngine's file persistence supplements it:

- **During `record_iteration`**: Existing `state_manager.record_iteration()` persists the full checkpoint to DB. Additionally, `context_engine.save()` persists the DAG and ledger to files.
- **During recovery**: Existing DB-based recovery runs first. `ContextEngine.load()` supplements by restoring DAG state for the ContextEngine's in-memory model.
- **Rationale**: CE file persistence captures the GoalStepDAG and LedgerManager state for quick recovery without DB deserialization. The DB remains the authoritative checkpoint store. This avoids replacing the proven DB persistence layer while gaining CE's structured recovery benefits.

### §12 Required Additions to ContextEngine

The following gaps were identified between the Phase 1 ContextEngine and what the StrangeLoop integration requires:

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
| `packages/soothe/src/soothe/config/models.py` | Add `ContextEngineConfig` to `StrangeLoopConfig` |
| `config/config.template.yml` | Add `context_engine` section |
| `config/develop/config.yml` | Add matching section |

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

Harden ContextEngine into a self-sufficient engine with a complete public API, full state machine, event callbacks, lossless persistence, bounded ledger growth, and complete projection output. This sub-project makes no changes to existing StrangeLoop code — it only fills gaps within the `soothe.context` module.

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

All changes are within `soothe.context`. No existing StrangeLoop code is modified.

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

**GoalContextAdapter gap**: Both `get_plan_context()` and `get_execute_briefing()` read from `self._state_manager` (the old `StrangeLoopStateManager`) instead of `self._ce` (the ContextEngine). Fix:

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

`ContextEnginePlanAdapter` is removed. `strange_loop.py` wires `StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=ce_goal.id)` instead.

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
| `packages/soothe/src/soothe/foundation/loop/engine/strange_loop.py` | Wire `StepPlanManagerAdapter` instead of `ContextEnginePlanAdapter` |
| `packages/soothe/src/soothe/foundation/loop/engine/context_adapters.py` | Remove `ContextEnginePlanAdapter` |
| `packages/soothe/src/soothe/foundation/loop/orchestrator/runtime_context.py` | Update `plan_manager` type to accept `PlanManager | StepPlanManagerAdapter` |

---

## Phase 3d: CE-StrangeLoop Full Integration (Sub-project 4)

### §36 Purpose

Wire ContextEngine into StrangeLoop as a fully functional parallel path, closing 5 integration gaps that remain from Phases 3a–3c. When CE is enabled, every graph node correctly interacts with CE — goal lifecycle, step feedback, projection, persistence, and semantic loading all function. When CE is disabled, zero behavioral change.

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
    """All ContextEngine interactions for one StrangeLoop goal run.

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
| `on_goal_start()` | `strange_loop` startup | `semantic.load(workspace)` |
| `on_plan_ingested(plan_result, plan_id, iteration)` | `plan_assess`, `resolve_decision` (after `ingest_plan`) | `save()` |
| `on_steps_executed(step_results)` | `record_iteration` (after `record_step_outcomes`) | `complete_step()`/`fail_step()` async + `save()` |
| `on_goal_complete(status, plan_result)` | `goal_completion` | `complete_goal()`/`fail_goal()` + `save()` |
| `get_context_bundle()` | `plan_generate` | `ce.project()` → `ContextBundle` |
| `save()` | (internal, after each mutation) | `ce.save()` to persistence backend |

**Error handling**: All lifecycle methods catch and log exceptions. CE failures never propagate to graph nodes — the plan-exec loop continues regardless. Async step APIs fire via `asyncio.create_task()` so callback errors don't block.

### §39 Integration Points per Graph Node

#### strange_loop.py (startup)

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

- **CE disabled**: `ContextEngineLifecycle(None, None)`. All methods are no-ops. `enabled` returns `False`. Graph node guards (`if ctx.ce_lifecycle and ctx.ce_lifecycle.enabled`) skip all CE calls. Zero behavioral change from current StrangeLoop.
- **CE enabled**: All existing prompt fragments remain identical. `ContextBundle` is additive only. The `StepPlanningSubengine` produces the same `DagPlanningContext` with the same 9 attributes. The `format_completion_dag_report()` output uses the hierarchical CE DAG format but contains equivalent information.
- **Existing tests**: All existing tests continue to pass. New tests verify the CE-specific behavior.

### §46 Phase 3d Files

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/foundation/loop/engine/context_lifecycle.py` | **New**: `ContextEngineLifecycle` class |
| `packages/soothe/src/soothe/foundation/loop/orchestrator/runtime_context.py` | Add `ce_lifecycle` field |
| `packages/soothe/src/soothe/foundation/loop/engine/strange_loop.py` | Create lifecycle, call `on_goal_start()` |
| `packages/soothe/src/soothe/foundation/loop/orchestrator/nodes/plan_assess.py` | Call `on_plan_ingested()` |
| `packages/soothe/src/soothe/foundation/loop/orchestrator/nodes/plan_generate.py` | Pass `context_bundle` from lifecycle |
| `packages/soothe/src/soothe/foundation/loop/orchestrator/nodes/record_iteration.py` | Call `on_steps_executed()` |
| `packages/soothe/src/soothe/foundation/loop/orchestrator/nodes/goal_completion.py` | Replace `ce.save()` with `on_goal_complete()` |
| `packages/soothe/src/soothe/config/models.py` | Flip `enabled` default to `True` |
| `packages/soothe/tests/unit/core/loop/engine/test_context_lifecycle.py` | **New**: lifecycle unit tests |
| `packages/soothe/tests/integration/context/test_ce_strange_loop_equivalence.py` | Add lifecycle + goal completion tests |

### §47 Acceptance Criteria

- All 5 gaps closed: goal lifecycle, step feedback, projection, persistence, semantics
- CE on-by-default for new installs
- CE disabled path produces zero behavioral change
- CE enabled path produces identical plan-exec outputs + additive `ContextBundle`
- All existing tests pass
- New tests cover `ContextEngineLifecycle`, goal completion, projection injection

---


## Phase 4: CE-as-LoopState-Backend (Revised)

### §48 Purpose

Make ContextEngine the sole data source for goal/step/ledger state via CE-backed `@property` accessors on LoopState. Three changes ship together in a big-bang migration:

1. **Persistence backend polish** — remove `InMemoryContextPersistence`, add `PgsqlContextPersistence`, improve file/sqlite backends
2. **LoopState property migration** — `loop_messages`, `step_results`, `completed_step_ids` become CE-backed properties; no sync calls needed
3. **Loop-scoped CE lifecycle** — CE instance persists across goals within a loop_id, `ce.load()` on startup, goals accumulate in the DAG

**`state_manager` stays alongside CE** — checkpoint persistence, iteration recording, and thread-switch detection remain its responsibility. CE owns goal/step/ledger data only.

### §49 Persistence Backend Polish

**Remove `InMemoryContextPersistence`:**

- Delete `context/persistence/in_memory.py`
- Remove from `__init__.py` exports and `ContextEngine.__init__()` default
- CE now requires an explicit persistence backend
- All tests that create CE without persistence must provide sqlite `:memory:` or file in tmp
- Update `ContextEngineConfig.persistence_backend` to `Literal["file", "sqlite", "pgsql"]`

**Add `PgsqlContextPersistence`:**

New file: `context/persistence/pgsql_backend.py`. Uses `asyncpg` connection pool. Same `ContextPersistenceProtocol` as other backends.

```python
class PgsqlContextPersistence:
    def __init__(self, loop_id: str, dsn: str, *,
                 pool_min_size: int = 2, pool_max_size: int = 10):
```

Schema uses JSONB for queryability and compression:
```sql
CREATE TABLE IF NOT EXISTS ce_dag (
    loop_id TEXT PRIMARY KEY,
    dag_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS ce_ledger (
    loop_id TEXT PRIMARY KEY,
    ledger_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Natively async (no `asyncio.to_thread`). Upsert same as sqlite (`INSERT ... ON CONFLICT DO UPDATE`). Pool created lazily on first use, closed via `close()` or `clear()`.

Config:
```python
class PgsqlPersistenceConfig(BaseModel):
    dsn: str
    pool_min_size: int = 2
    pool_max_size: int = 10

class ContextEngineConfig(BaseModel):
    persistence_backend: Literal["file", "sqlite", "pgsql"] = "sqlite"
    pgsql_config: PgsqlPersistenceConfig | None = None
```

**FileContextPersistence improvements:** Add `asyncio.to_thread` for file I/O (currently synchronous, blocks event loop).

**SqliteContextPersistence improvements:** Add public `close()` method, fix thread-safety in `_ensure_connection()` with a lock.

### §50 LoopState Property Migration

Three fields become CE-backed `@property` accessors. When CE is bound, the property queries CE in-process (no I/O, <1ms). When CE is not bound (test/legacy mode), a private `_cache` field serves as fallback.

**Become CE-backed properties:**

| Field | CE source | Write path |
|---|---|---|
| `loop_messages` | `ce.ledger.get_messages()` + Loop-type wrapping | `ce.ledger.record_message()` |
| `step_results` | `ce.get_goal_sync(goal_id).steps.nodes` → map to `StepResult` | `ce.complete_step()` / `ce.fail_step()` |
| `completed_step_ids` | `{s.id for s in goal.steps.nodes.values() if s.status == "completed"}` | `ce.complete_step()` / `ce.fail_step()` |

**Fields staying on LoopState** (execution-only):

| Cluster | Fields | Reason |
|---|---|---|
| Execution context | `goal`, `thread_id`, `workspace`, `git_status`, `goal_user_submission`, `skill_context` | Per-invocation routing |
| Wave metrics | `last_wave_*`, `total_tokens_used`, `total_duration_ms`, `context_percentage_consumed` | Ephemeral per-wave |
| Skill/MCP | `sent_skill_names`, `activated_skill_names`, `invoked_skill_names`, etc. | UI/middleware concern |
| Orchestration | `intent`, `routing_classification`, `continue_loop`, `current_decision`, `plan_id`, `previous_plan` | Control flow |
| Execution signals | `last_execute_assistant_text`, `last_wave_answer_from_delegate_final`, etc. | Executor internals |
| Step-thread map | `step_thread_ids` | Executor isolation |
| Tracking | `iteration`, `max_iterations`, `action_history`, `evidence_summary`, `evidence_ledger`, `working_memory`, `prior_progress` | Future migration candidates |

**Property implementation pattern:**

```python
class LoopState:
    _loop_messages_cache: list[LoopHumanMessage | LoopAIMessage]
    _step_results_cache: list[StepResult]
    _completed_step_ids_cache: set[str]

    @property
    def loop_messages(self) -> list[LoopHumanMessage | LoopAIMessage]:
        if self._ce is None:
            return self._loop_messages_cache
        return self._build_loop_messages_from_ce()

    @property
    def step_results(self) -> list[StepResult]:
        if self._ce is None:
            return self._step_results_cache
        return self._build_step_results_from_ce()

    @property
    def completed_step_ids(self) -> set[str]:
        if self._ce is None:
            return self._completed_step_ids_cache
        goal = self._ce.get_goal_sync(self._ce_goal_id)
        if goal is None:
            return set()
        return {sid for sid, n in goal.steps.nodes.items() if n.status == "completed"}
```

**Key invariant**: Properties return fresh collections each call. `state.loop_messages.append()` is a no-op (appends to an orphaned list). This enforces single source of truth — all writes must go through CE methods.

**StepResult mapping from CE:**

All 11 `StepResult` fields map to CE data:

| StepResult field | CE source | Notes |
|---|---|---|
| `step_id` | `StepNode.id` | Direct |
| `success` | `StepNode.status == "completed"` | Derived |
| `outcome` | `StepExecution.outcome or {}` | Direct |
| `error` | `StepExecution.error` | Direct |
| `error_type` | `_clamp_error_type(StepExecution.error_type)` | Unknown values → `"unknown"` |
| `duration_ms` | `StepExecution.duration_ms` | Direct |
| `thread_id` | `StepExecution.thread_id or ""` | Nullable → empty string |
| `tool_call_count` | `StepExecution.tool_call_count` | Direct |
| `subagent_task_completions` | `StepExecution.subagent_task_completions` | Direct |
| `hit_subagent_cap` | `StepExecution.hit_subagent_cap` | Direct |
| `hit_tool_budget` | `StepExecution.hit_tool_budget` | Direct |

**`_record_ledger_message()` simplification**: The `loop_messages` parameter is removed. When CE is bound, always write to CE. When CE is not bound, raise `ValueError` — tests must provide CE.

**`sync_loop_messages_from_ce()` retirement**: Public method deleted. The `loop_messages` property replaces it — every read automatically gets fresh data from CE.

**`bind_ce()` change**: After binding CE, clears the cache fields (CE is now authoritative).

### §51 Adapter Deletion & Direct CE Access

| Deleted component | Current role | Replacement |
|---|---|---|
| `_record_ledger_message()` dual-write | Writes to both `state.loop_messages` and `ce.ledger` | Simplified: CE-only writes |
| `sync_loop_messages_from_ce()` | Repopulates loop_messages from CE ledger | Deleted: property replaces it |
| `state.add_step_result()` | Appends to `state.step_results` list | Deleted: `ce.complete_step()` / `ce.fail_step()` is the sole write |
| `state.completed_step_ids.add()` / `.clear()` | Direct mutation of set | Deleted: property derives from CE StepDAG |
| `state.loop_messages.append()` | Direct mutation of list | Deleted: all writes through `ce.ledger.record_message()` |
| `InMemoryContextPersistence` | Default no-op backend | Deleted: explicit backend required |
| `seed_loop_ledger_from_prior_goal()` | Copies prior goal messages | Deleted: CE ledger spans all goals |

**What stays:**

| Component | Why |
|---|---|
| `ContextEngineGoalContextAdapter` | Thin convenience for plan context; reads completed goals from CE DAG |
| `StepPlanManagerAdapter` | Binds goal_id to planning submodule |
| `state_manager` | Checkpoint persistence, iteration recording, thread-switch detection — distinct from CE |

**Graph node migration pattern:**

Before (dual-write):
```python
_record_ledger_message(ctx.ce, human_msg, "record_iteration", state.loop_messages)
state.step_results.append(result)
state.completed_step_ids.add(step_id)
```

After (CE-only writes):
```python
ctx.ce.ledger.record_message(human_msg, "record_iteration")
await ctx.ce.complete_step(ctx.ce_goal_id, step_id, execution)
# step_results and completed_step_ids are properties — no explicit mutation needed
```

### §52 Loop-Scoped CE Lifecycle

CE instance is created lazily on first `run_with_progress()` call and stored on `StrangeLoop._ce`. Subsequent calls reuse the same instance.

```
run_with_progress():
  if self._ce is None:
      persistence = _select_backend(ce_config, loop_id)
      self._ce = ContextEngine(persistence=persistence, ...)
  await self._ce.load()  # restore prior goals
  ce_goal = await self._ce.create_goal(execution_goal, ...)
  await self._ce.activate_goal(ce_goal.id, loop_id=state_manager.loop_id)
  state.bind_ce(self._ce, ce_goal.id)
  ... run graph ...
```

**Cross-goal continuity:**

```
Goal 1 completes:
  ├─ await ce.finalize_goal(goal_1_id, status="completed")
  ├─ await ce.save()  # persist DAG with goal_1 (completed) + full ledger
  └─ run_with_progress() returns

Goal 2 starts (same loop_id):
  └─ run_with_progress()
       ├─ ce.load() → DAG: goal_1 (completed), ledger: all prior messages
       ├─ goal_2 = ce.create_goal("Goal 2 description")
       ├─ ce.activate_goal(goal_2.id)
       └─ Graph runs with full context (prior goals in DAG)
```

`ContextEngineGoalContextAdapter.get_plan_context()` already reads completed goals from the CE DAG. With loop-scoped CE, completed goals are always present — no changes needed to the adapter's logic.

### §53 AgentLoopCheckpoint Simplification

**GoalExecutionRecord: 18 fields → 7.** A lightweight index: goal_id, text, thread_id, status, completion text, timestamps.

| Field | After | Reason |
|---|---|---|
| `goal_id` | kept | Identity |
| `goal_text` | kept | Human-readable summary |
| `thread_id` | kept | Thread routing |
| `iteration` | deleted | CE StepDAG query |
| `max_iterations` | deleted | `GoalNode.max_iterations` |
| `status` | kept | Checkpoint-level status |
| `current_plan` | deleted | `GoalNode.previous_plan` |
| `completed_step_ids` | deleted | CE StepDAG property |
| `plan_revision_count` | deleted | `GoalNode.plan_revision_count` |
| `step_results` | deleted | CE StepDAG + StepExecution |
| `evidence_ledger` | deleted | CE `GoalNode.evidence_ledger` |
| `loop_messages` | deleted | CE LedgerManager |
| `goal_completion` | kept | Final user-facing text |
| `evidence_summary` | deleted | CE `ledger.render_for_reason()` |
| `duration_ms` | deleted | `GoalNode.total_duration_ms` |
| `tokens_used` | deleted | `GoalNode.total_tokens_used` |
| `started_at` | kept | Timestamp |
| `completed_at` | kept | Timestamp |

**AgentLoopCheckpoint: 16 fields → 12.** `goal_history` is an index, not a data store.

| Field | After | Reason |
|---|---|---|
| `working_memory_state` | deleted | CE LedgerManager replaces |
| `total_goals_completed` | deleted | Derived from `goal_history` |
| `total_tokens_used` | deleted | Derived from CE DAG |
| `schema_version` | bumped | `"4.0"` |

**Schema migration: 3.3 → 4.0.** On `load()`, if `schema_version < "4.0"`:

1. Load old-format checkpoint (with full GoalExecutionRecord data)
2. Reconstruct CE state from goal_history: create GoalNode per record, populate steps from step_results, populate ledger from loop_messages
3. Save new-format checkpoint (trimmed) + CE state
4. Update `schema_version = "4.0"`

One-time migration per loop. Lazy upgrade.

### §54 StepExecution Enrichment

Enrich `StepExecution` to carry all `StepResult` fields. `StepResult` becomes a view over `StepNode` + `StepExecution`.

```python
class StepExecution(BaseModel):
    input_messages: list[dict[str, Any]] = []
    output_messages: list[dict[str, Any]] = []
    tokens_used: int = 0
    duration_ms: int = 0
    error: str | None = None
    error_type: str | None = None          # NEW
    thread_id: str | None = None
    outcome: dict[str, Any] | None = None  # NEW
    tool_call_count: int = 0               # NEW
    subagent_task_completions: int = 0     # NEW
    hit_subagent_cap: bool = False         # NEW
    hit_tool_budget: bool = False          # NEW
```

`StepResult` class is not deleted — it remains the shape that planner prompts and synthesis consume. But it is no longer stored independently; it is derived via `_step_node_to_result()`.

### §55 Migration Sequence (Big-Bang)

All steps ship together in one PR.

| Step | Scope |
|------|-------|
| 1 | Persistence backend polish: delete InMemory, add Pgsql, fix File/Sqlite |
| 2 | Add CE-backed properties to LoopState (with cache fallback) |
| 3 | Migrate all write sites to CE-only (remove dual-write, delete add_step_result, etc.) |
| 4 | Migrate all read sites (remove sync calls, verify property access) |
| 5 | Wire loop-scoped CE (lazy creation on StrangeLoop, ce.load() + create_goal()) |
| 6 | Cleanup: remove cache fallbacks, clean docstrings, run verify_finally.sh |

### §56 Error Handling

**CE-backed property failure**: Properties catch exceptions from CE queries and return empty defaults:

```python
@property
def step_results(self) -> list[StepResult]:
    if self._ce is None:
        return self._step_results_cache
    try:
        return self._build_step_results_from_ce()
    except Exception:
        logger.warning("step_results property: CE query failed", exc_info=True)
        return []
```

**4-tier degradation model:**

| Tier | Scenario | Behavior |
|------|----------|----------|
| 1 | `ce.save()` transient failure | Log warning, continue. In-memory CE still authoritative. |
| 2 | `ce.load()` failure on startup | Start with empty DAG. Degraded mode: no prior goal context. |
| 3 | `ce.complete_step()` mutation failure | Catch at graph node, log, continue. Step stays pending → benign replan. |
| 4 | Complete CE unavailability | Fall back to cache-backed LoopState fields. |

### §57 Projection Updates for Multi-Goal Context

**New model: `PriorGoalSummary`**:

```python
class PriorGoalSummary(BaseModel):
    goal_id: str
    description: str
    status: str
    step_summary: str
    completion_text: str
    total_duration_ms: int
    total_tokens_used: int
```

**ContextBundle additions**:

```python
class ContextBundle(BaseModel):
    # ... existing fields unchanged ...
    prior_goals: list[PriorGoalSummary]  # completed goals in this loop
    cross_goal_ledger: list[dict]         # recent messages from prior goals
```

**Projection behavior**: When `ce.project(goal_id)` is called, `prior_goals` is populated from all goals with terminal status, bounded by `ProjectionConfig.max_goals` (default 5). `cross_goal_ledger` from most recent N messages, bounded by `ProjectionConfig.max_ledger_messages`.

No prompt format changes. `PromptBuilder` renders `prior_goals` into the same `<previous_goal>` format.

### §58 Phase 4 Files

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/context/models.py` | Enrich `StepExecution` (add 6 fields) |
| `packages/soothe/src/soothe/context/engine.py` | `create_goal()` accepts `max_iterations` |
| `packages/soothe/src/soothe/context/projection.py` | Add `PriorGoalSummary`, populate `prior_goals` and `cross_goal_ledger` |
| `packages/soothe/src/soothe/context/persistence/pgsql_backend.py` | **New**: `PgsqlContextPersistence` |
| `packages/soothe/src/soothe/context/persistence/in_memory.py` | **Delete**: `InMemoryContextPersistence` |
| `packages/soothe/src/soothe/context/persistence/file_backend.py` | Add `asyncio.to_thread` for file I/O |
| `packages/soothe/src/soothe/context/persistence/sqlite_backend.py` | Add `close()`, fix thread-safety |
| `packages/soothe/src/soothe/context/persistence/__init__.py` | Remove InMemory export, add Pgsql export |
| `packages/soothe/src/soothe/foundation/loop/state/schemas.py` | Add CE-backed properties for `loop_messages`, `step_results`, `completed_step_ids`; delete `sync_loop_messages_from_ce()`; simplify `bind_ce()` |
| `packages/soothe/src/soothe/foundation/loop/state/checkpoint.py` | Trim `GoalExecutionRecord` to 7 fields; schema 4.0 |
| `packages/soothe/src/soothe/foundation/loop/engine/strange_loop.py` | Lazy CE creation, `ce.load()` on startup, remove InMemory fallback |
| `packages/soothe/src/soothe/foundation/loop/orchestrator/nodes/*.py` | Replace dual-write with CE-only writes; remove sync calls |
| `packages/soothe/src/soothe/foundation/loop/utils/messages.py` | Simplify `_record_ledger_message()`; delete `seed_loop_ledger_from_prior_goal()` |
| `packages/soothe/src/soothe/config/models.py` | Default `"sqlite"`, add `"pgsql"`, remove `"in_memory"`; add `PgsqlPersistenceConfig` |

### §59 Acceptance Criteria

- `InMemoryContextPersistence` deleted; `PgsqlContextPersistence` available with asyncpg
- `state.loop_messages`, `state.step_results`, `state.completed_step_ids` are CE-backed properties (no sync calls)
- `_record_ledger_message()` writes to CE only (no `loop_messages` parameter)
- `sync_loop_messages_from_ce()` deleted
- `seed_loop_ledger_from_prior_goal()` deleted
- CE instance is loop-scoped (persists across goals within a loop_id)
- `ce.load()` called on `run_with_progress()` startup; successive goals accumulate in DAG
- `state_manager` still handles checkpoint persistence, iteration recording, thread-switch detection
- `StepExecution` enriched with all `StepResult` fields
- `GoalExecutionRecord` trimmed to 7 fields; schema 4.0
- ContextBundle includes `prior_goals` and `cross_goal_ledger`
- All existing tests pass; new tests cover properties, pgsql persistence, cross-goal continuity

### §60 Phase 4 Stage 2: Remaining Cleanup

Stage 1 (big-bang property migration) shipped with some items deferred. Stage 2 completes the Phase 4 acceptance criteria.

**Items completed in Stage 1:**

| Criterion | Status |
|---|---|
| `InMemoryContextPersistence` deleted | Done |
| `PgsqlContextPersistence` available | Done |
| CE-backed properties on LoopState | Done |
| CE instance loop-scoped on `StrangeLoop._ce` | Done |
| `ce.load()` on `run_with_progress()` startup | Done |
| `ce.create_goal()` accumulates in existing DAG | Done |
| `state_manager` untouched (checkpoint, thread-switch) | Done |
| `StepExecution` enriched with all fields | Done |
| Projection config in `ContextEngineConfig` | Done |

**Items deferred to Stage 2:**

| Criterion | Current state | Stage 2 fix |
|---|---|---|
| `_record_ledger_message()` CE-only writes | Still has `loop_messages` param (unused when CE bound) | Remove param; raise ValueError without CE |
| `sync_loop_messages_from_ce()` deleted | Exists as no-op, zero callers | Delete entirely |
| `seed_loop_ledger_from_prior_goal()` deleted | Deprecated docstring, 2 test callers | Delete function, update tests |
| `GoalExecutionRecord` trimmed to 7 fields | Still has all 18+ fields; `finalize_goal()` writes empty data | Remove CE-owned fields; schema 3.4 |
| `completed_step_ids.clear()` in resolve_decision | Writes to cache (invisible when CE bound) | Remove call entirely |
| `goal_completion` save/restore for step_results | `pre_clear_step_results` dance; cache-only writes when CE bound | Read from CE DAG directly |
| `_prior_goal_summaries()` from CE | Reads `checkpoint.goal_history[:-1]` | Query `ce.get_all_goals(status='completed')` |

**Stage 2 migration sequence:**

| Step | Scope |
|------|-------|
| 1 | Slim `GoalExecutionRecord`: remove `loop_messages`, `step_results`, `completed_step_ids`, `evidence_ledger`, `current_plan`; remove mirroring in `finalize_goal()`; schema 3.4 |
| 2 | Simplify `_record_ledger_message()`: remove `loop_messages` param; update 6 callers |
| 3 | Eliminate goal_completion save/restore: synthesis reads from CE DAG; delete `pre_clear_step_results` |
| 4 | Remove `state.completed_step_ids.clear()` in `resolve_decision.py:71` |
| 5 | Replace `_prior_goal_summaries()` with CE query; delete `seed_loop_ledger_from_prior_goal()` |
| 6 | Delete `sync_loop_messages_from_ce()` |
| 7 | Update tests; run `verify_finally.sh` |

**Design reference:** `docs/drafts/2026-06-13-ce-phase4-loopstate-backend-design.md` — Stage 2 section.

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

### Phase 3: StrangeLoop Integration (when CE enabled)

```
StrangeLoop.run_with_progress(goal, ...)
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

### Phase 4: CE-as-LoopState-Backend (multi-goal DAG flow)

```
AgentLoop.run_with_progress(goal, ...)
  │
  ├─ ce = ContextEngine(persistence=SqliteContextPersistence(loop_id))
  ├─ ce.load() → DAG: prior goals (completed), ledger: all prior messages
  ├─ goal = ce.create_goal(description, max_iterations=...)
  ├─ ce.activate_goal(goal.id, loop_id)
  │
  ▼
LangGraph iteration cycle (nodes call ctx.ce directly, no adapters):
  │
  plan_assess / plan_generate
  │  → ctx.ce.ledger.record_message(human_msg, "plan")
  │  → ctx.ce.project(ce_goal_id) → ContextBundle (includes prior_goals, cross_goal_ledger)
  │  → LLM returns PlanResult
  │
  ▼
resolve_decision
  │  → ctx.ce.planning.step.ingest_plan(ce_goal_id, plan_result, ...)
  │  → ctx.ce.save()  ← persists new step nodes
  │
  ▼
execute
  │  → Executor runs steps (unchanged)
  │
  ▼
record_iteration
  │  → ctx.ce.complete_step(ce_goal_id, step_id, execution)  ← sole write
  │  → ctx.ce.ledger.record_message(ai_msg, "execute_step")
  │  → ctx.ce.save()  ← persists step outcomes
  │  → state.step_results / state.completed_step_ids → CE-backed properties
  │
  ▼
  ... loop until goal complete ...
  │
  ▼
goal_completion
  │  → ctx.ce.finalize_goal(ce_goal_id)  ← sets completed, clears active_plan
  │  → ctx.ce.save()  ← persists final goal state
  │  → state_manager.finalize_goal()  ← writes trimmed checkpoint (7-field GoalExecutionRecord)
```

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Step execution failure | `StepNode.status = "failed"`, `execution.error` set. Goal remains active. StrangeLoop decides replan vs fail-goal. |
| Goal failure | `GoalNode.status = "failed"`. Dependent goals remain blocked (dependencies not met). |
| Persistence failure | In-memory fallback with warning log. Query and projection continue; durability degraded. |
| Crash recovery | On `load()`, `recover()` resets active goals to pending. Steps with no execution reset to pending. |
| Invalid DAG operation | Cycle detection on `add_dependency`. Depth limit on goal nesting (max 5). |

### Phase 4: 4-Tier Degradation Model (Revised)

| Tier | Scenario | Behavior |
|------|----------|----------|
| 1 | `ce.save()` transient failure | Log warning, continue. In-memory CE still authoritative. Next successful save persists full state. |
| 2 | `ce.load()` failure on startup | Start with empty DAG. Degraded mode: no prior goal context. `ce.recover_from_checkpoint()` can rebuild from checkpoint index. |
| 3 | `ce.complete_step()` / `ce.ingest_plan()` mutation failure | Catch at graph node, log, continue. Step stays pending → benign replan. No data loss. |
| 4 | Complete CE unavailability | CE-backed properties return cache fallback values (empty defaults if no cache). |

---

## Invariants

1. `GoalStepDAG` is the single source of truth for goal and step data within `soothe.context`.
2. Step dependencies are strictly within the same goal — cross-goal coordination uses goal-level `depends_on`.
3. `ContextBundle` is a read-only projection; mutation happens through `ContextEngine` methods only.
4. The message ledger is derivable from the GoalStepDAG (via `StepExecution` records).
5. `ContextPersistenceProtocol` implementations must support atomic save/load (no partial writes).
6. `ContextEngine` does not depend on `GoalEngine`, `StrangeLoop`, or `CoreAgent` — it is standalone.
7. When the ContextEngine path is enabled in StrangeLoop, all outputs must be indistinguishable from the current Plan-Exec loop outputs (behavioral equivalence).
8. The existing StrangeLoop path (CE disabled) must remain completely untouched — zero behavioral changes.
9. CE failures must never propagate to graph nodes — the plan-exec loop continues regardless of CE errors.

### Phase 4 additions (Revised)

10. **CE-backed properties are the sole read path** — `state.loop_messages`, `state.step_results`, `state.completed_step_ids` are `@property` accessors that query CE when bound. No sync calls needed.
11. **All mutations go through CE methods** — `state.loop_messages.append()`, `state.step_results.append()`, `state.completed_step_ids.add()` are deleted. Writes go to `ce.ledger.record_message()`, `ce.complete_step()`, `ce.fail_step()`.
12. **CE persistence is loop-scoped** — CE instance persists across goals within a loop_id. `ce.load()` restores prior DAG on startup. No checkpoint fallback for goal data.
13. **Checkpoint owns lifecycle; CE owns data** — `state_manager` handles checkpoint persistence, iteration recording, thread-switch detection. CE DAG holds goal/step/execution data. Complementary, not redundant.
14. **`StepResult` is a view over `StepNode` + `StepExecution`** — not independently stored. Derived via `_step_node_to_result()`.
15. **`InMemoryContextPersistence` is deleted** — CE requires an explicit persistence backend (file, sqlite, or pgsql). No no-op default.

---

## Migration Path (Future Phases)

### Phase 2: GoalEngine Integration

- GoalEngine reads/writes goals through ContextEngine instead of internal `_goals` dict
- `GoalEngine.create_goal()` becomes a thin wrapper delegating to `ContextEngine.create_goal()`
- ContextProjector reads from ContextEngine instead of GoalDispatchContextStore
- Backward-compatible: GoalEngine's public API unchanged, internal storage replaced

### Phase 3: StrangeLoop Integration (Done)

- StrangeLoop's `PlanManager` replaced by `StepPlanManagerAdapter` wrapping `StepPlanningSubengine` (Phase 3c)
- `ContextEnginePlanAdapter` removed — heuristic duplication eliminated via `completion.py` (Phase 3c)
- `LoopWorkingMemory` + `loop_messages` mirrored to `LedgerManager` via `ContextEngineLedgerAdapter` (Phase 3)
- `GoalContextManager` replaced by `ContextEngineGoalContextAdapter` (Phase 3)
- Config flag `agent.loop.context_engine.enabled` selects the path (Phase 3)
- `ContextEngineLifecycle` encapsulates all CE interactions per goal run (Phase 3d)
- Goal lifecycle, step feedback, projection, persistence, semantic loading fully wired (Phase 3d)
- CE on-by-default for new installs (Phase 3d)
- Existing prompt pipeline, executor, and LangGraph topology remain unchanged
- DB persistence remains primary; CE file persistence supplements for DAG state

### Phase 4: CE-as-LoopState-Backend (Revised)

- CE-backed `@property` accessors for `loop_messages`, `step_results`, `completed_step_ids` — no sync calls
- `InMemoryContextPersistence` deleted; `PgsqlContextPersistence` added with asyncpg
- Loop-scoped CE lifecycle — instance persists across goals within a loop_id
- `state_manager` kept alongside CE for checkpoint/iteration/thread-switch
- `ContextEngineGoalContextAdapter` and `StepPlanManagerAdapter` kept as thin convenience wrappers
- Dual-write eliminated: `_record_ledger_message()` simplified, `sync_loop_messages_from_ce()` deleted
- `seed_loop_ledger_from_prior_goal()` deleted; CE ledger spans all goals
- `StepExecution` enriched with `outcome`, `error_type`, `tool_call_count`, `subagent_task_completions`, `hit_subagent_cap`, `hit_tool_budget`
- `GoalExecutionRecord` trimmed from 18 → 7 fields; `AgentLoopCheckpoint` schema 4.0
- ContextBundle extended with `prior_goals` and `cross_goal_ledger` for multi-goal projection
- Big-bang migration (6 steps, single PR)
- 4-tier error handling: transient → load failure → mutation failure → cache fallback
