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
| 3 | AgentLoop uses ContextEngine via adapters | Adapters bridge CE to existing interfaces; PromptBuilder, Executor, LangGraph unchanged | This update |

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

| Gap | Addition |
|-----|----------|
| No `activate_goal()` method | Add `activate_goal(goal_id, loop_id)` — transitions `pending→active`, sets `assigned_loop_id` |
| No `chain_depth` on `StepDAG` | Add `chain_depth` property (BFS, same algorithm as `PlanDAG.max_chain_depth`) |
| No composite step ID support | Adapters store composite IDs (`KFA-01`) as `StepNode.id` directly — no CE model change needed |
| No `plan_history` tracking | `ContextEnginePlanAdapter` maintains its own `plan_history` list — no CE model change needed |
| No evidence tracking | Not in CE — the adapter reads evidence from `LoopState` directly — no CE model change needed |
| Ledger serialization is lossy | Acceptable because CE persistence is supplementary — the DB handles full ledger serialization |
| No `execution_mode` on steps | Not needed — `AgentDecision.execution_mode` stays in `LoopState`, not in `GoalStepDAG` |

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
  │  → LLM returns PlanResult
  │
  ▼
resolve_decision
  │  → allocate_plan_id, assign_plan_step_ids (unchanged)
  │  → Adapter.ingest_plan() records steps in ContextEngine
  │
  ▼
execute
  │  → Executor runs steps (unchanged)
  │  → LedgerAdapter mirrors writes to both loop_messages and LedgerManager
  │
  ▼
record_iteration
  │  → state_manager.record_iteration() → DB (unchanged)
  │  → context_engine.save() → file backup (new)
  │
  ▼
  ... loop until goal complete ...
  │
  ▼
goal_completion
  │  → Adapter.get_planning_context() → DagPlanningContext (unchanged format)
  │  → Existing completion strategy logic (unchanged)
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

---

## Migration Path (Future Phases)

### Phase 2: GoalEngine Integration

- GoalEngine reads/writes goals through ContextEngine instead of internal `_goals` dict
- `GoalEngine.create_goal()` becomes a thin wrapper delegating to `ContextEngine.create_goal()`
- ContextProjector reads from ContextEngine instead of GoalDispatchContextStore
- Backward-compatible: GoalEngine's public API unchanged, internal storage replaced

### Phase 3: AgentLoop Integration (this update)

- AgentLoop's `PlanManager` replaced by `ContextEnginePlanAdapter`
- `LoopWorkingMemory` + `loop_messages` mirrored to `LedgerManager` via `ContextEngineLedgerAdapter`
- `GoalContextManager` replaced by `ContextEngineGoalContextAdapter`
- Config flag `agent.loop.context_engine.enabled` selects the path
- Existing prompt pipeline, executor, and LangGraph topology remain unchanged
- DB persistence remains primary; CE file persistence supplements for DAG state
