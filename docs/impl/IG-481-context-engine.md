# IG-481: Context Engine Implementation

**IG**: 481
**RFC**: 624
**Title**: Context Engine — Unified Context Management
**Status**: Draft
**Created**: 2026-06-12

## Overview

Implement `soothe.context` as a standalone module per RFC-624. No changes to existing GoalEngine, AgentLoop, or CoreAgent code.

## Build Sequence

### Step 1: Data models (`models.py`)

Create `packages/soothe/src/soothe/context/models.py` with all Pydantic models:

- `GoalStatus`, `StepStatus`, `TERMINAL_STATES` type definitions
- `StepExecution(BaseModel)` — serialized CoreAgent execution record
- `StepNode(BaseModel)` — step in a goal's step DAG
- `StepDAG(BaseModel)` — goal-scoped step DAG with `ready_steps()`, `mark_completed()`, `mark_failed()`, `mark_skipped()`, stats properties
- `GoalNode(BaseModel)` — goal node with embedded `StepDAG`, lineage fields, observability fields
- `GoalStepDAGSnapshot(BaseModel)` — persistence format

Key algorithms:
- `StepDAG.ready_steps()`: pending steps whose deps are all in completed/failed/skipped, using `expand_dependency_satisfaction_ids` pattern from `loop/planning/dependency_tokens.py`
- `GoalStepDAG.ready_goals()`: mirror `GoalEngine._filter_ready_candidates()` — filter pending, check deps in TERMINAL_STATES, check conflicts_with no active goal, sort `(-priority, created_at)`
- `GoalStepDAG.goal_lineage()`: walk parent_id chain from leaf to root
- `GoalStepDAG.recover_active_goals()`: reset active → pending, clear assigned_loop_id

### Step 2: Ledger manager (`ledger.py`)

Create `packages/soothe/src/soothe/context/ledger.py`:

- `LedgerManager` — message ledger with phase tagging, spill-to-disk, compaction
- `record_message(msg, phase)` — append with phase metadata
- `get_messages(phases)` — filter by phase list
- `project_for_plan()` — all phases, trimmed by config limits (mirrors `project_loop_messages_for_plan`)
- `project_for_core_agent()` — execute_step phase + plain messages with phase=None (mirrors `project_loop_messages_for_core_agent`)
- `record_step_result()` — outcome summary (mirrors `LoopWorkingMemory.record_step_result`)
- `compact()` — summarize old messages
- `render_for_reason()` — condensed text output (mirrors `LoopWorkingMemory.render_for_reason`)

### Step 3: Semantic loader (`semantic.py`)

Create `packages/soothe/src/soothe/context/semantic.py`:

- `SemanticLoader` — loads CLAUDE.md, AGENTS.md, MEMORY.md from workspace
- `load_project_instructions()` — read CLAUDE.md
- `load_agent_instructions()` — read AGENTS.md
- `load_memory()` — read MEMORY.md
- All methods return empty string if file missing (graceful degradation)

### Step 4: Projection (`projection.py`)

Create `packages/soothe/src/soothe/context/projection.py`:

- `ProjectionConfig(BaseModel)` — bounding limits
- `ContextBundle(BaseModel)` — structured projection output
- `ProjectionEngine` — builds ContextBundle from GoalStepDAG + LedgerManager + SemanticLoader

Key logic:
- Select active goal (or specified goal_id)
- Build step lists: pending (top-N by dep order), completed (recent N), failed (recent N)
- Render goal_progress from StepDAG stats (max 500 chars)
- Build goal_lineage from GoalStepDAG.goal_lineage() (max `max_lineage_chars`)
- Build step_lineage from recent StepNode.reasoning_trace (max `max_lineage_chars`)
- Build ledger_summary from LedgerManager.render_for_reason() (max `max_ledger_chars`)
- Load semantic context via SemanticLoader (max `max_project_instructions_chars`)
- Build goal_dag_summary — compact overview of all goals

### Step 5: Persistence (`persistence/`)

Create `packages/soothe/src/soothe/context/persistence/`:

- `base.py` — `ContextPersistenceProtocol(Protocol)`
- `in_memory.py` — `InMemoryContextPersistence` (dict-backed, testing/ephemeral)
- `file_backend.py` — `FileContextPersistence` (JSON files under SOOTHE_HOME)

File layout: `SOOTHE_HOME/data/context_engine/{thread_id}/goal_step_dag.json` + `ledger.json`

### Step 6: ContextEngine (`engine.py`)

Create `packages/soothe/src/soothe/context/engine.py`:

- `ContextEngine` — main orchestrator composing GoalStepDAG, LedgerManager, SemanticLoader, ProjectionEngine, PersistenceBackend
- Goal management: `create_goal`, `get_goal`, `list_goals`, `complete_goal`, `fail_goal`, `suspend_goal`
- Step management: `add_step`, `add_steps`, `complete_step`, `fail_step`
- Ledger management: `record_message`, `get_ledger`
- Projection: `project` → delegates to ProjectionEngine
- Persistence: `save`, `load`
- Recovery: `recover` — delegates to GoalStepDAG.recover_active_goals()

### Step 7: Package init (`__init__.py`)

Create `packages/soothe/src/soothe/context/__init__.py` with public API exports:
- `ContextEngine`, `ContextBundle`, `ProjectionConfig`
- `GoalNode`, `StepNode`, `StepExecution`, `StepDAG`, `GoalStepDAG`
- `ContextPersistenceProtocol`, `InMemoryContextPersistence`, `FileContextPersistence`
- `LedgerManager`, `SemanticLoader`

### Step 8: Tests

Unit tests in `packages/soothe/tests/unit/context/`:
- `test_goal_step_dag.py` — scheduling, deps, cycle detection, depth limits, lineage, recovery
- `test_step_dag.py` — readiness, completion, failure, skip, dep satisfaction
- `test_projection.py` — ContextBundle building, limit enforcement
- `test_ledger_manager.py` — recording, filtering, compaction, step results
- `test_semantic_loader.py` — file loading, missing files
- `test_persistence.py` — save/load/clear for in-memory and file backends

Integration tests in `packages/soothe/tests/integration/context/`:
- `test_context_engine_lifecycle.py` — full lifecycle
- `test_recovery.py` — crash recovery
- `test_ledger_recovery_from_dag.py` — reconstruct ledger from DAG

## File List

```
NEW: packages/soothe/src/soothe/context/__init__.py
NEW: packages/soothe/src/soothe/context/models.py
NEW: packages/soothe/src/soothe/context/engine.py
NEW: packages/soothe/src/soothe/context/projection.py
NEW: packages/soothe/src/soothe/context/ledger.py
NEW: packages/soothe/src/soothe/context/semantic.py
NEW: packages/soothe/src/soothe/context/persistence/__init__.py
NEW: packages/soothe/src/soothe/context/persistence/base.py
NEW: packages/soothe/src/soothe/context/persistence/in_memory.py
NEW: packages/soothe/src/soothe/context/persistence/file_backend.py
NEW: packages/soothe/tests/unit/context/__init__.py
NEW: packages/soothe/tests/unit/context/test_goal_step_dag.py
NEW: packages/soothe/tests/unit/context/test_step_dag.py
NEW: packages/soothe/tests/unit/context/test_projection.py
NEW: packages/soothe/tests/unit/context/test_ledger_manager.py
NEW: packages/soothe/tests/unit/context/test_semantic_loader.py
NEW: packages/soothe/tests/unit/context/test_persistence.py
NEW: packages/soothe/tests/integration/context/__init__.py
NEW: packages/soothe/tests/integration/context/test_context_engine_lifecycle.py
NEW: packages/soothe/tests/integration/context/test_recovery.py
NEW: packages/soothe/tests/integration/context/test_ledger_recovery_from_dag.py
```

## Constraints

- Python ≥3.11, type hints on all public functions
- Pydantic v2 BaseModel for all data models
- No imports from `soothe.foundation.autopilot`, `soothe.foundation.loop`, or `soothe.foundation.core` — standalone module
- Ruff-compliant (lint + format)
- Google-style docstrings
