# IG-480: Context Engine Phase 4 — CE-as-LoopState-Backend

**Status**: In Progress
**Created**: 2026-06-15
**RFC**: RFC-624 Phase 4 (§48–§59)
**Design Draft**: `docs/archive/drafts/2026-06-13-ce-phase4-loopstate-backend-design.md`

## Goal

Make ContextEngine the sole data source for goal/step/ledger state. LoopState's CE-overlapping fields become computed properties backed by CE DAG/Ledger queries. All adapter indirection is removed — graph nodes call CE methods directly. The trimmed LoopState holds only execution-only fields.

**Net result**: ~1,100 lines deleted, no adapters, single source of truth.

## Scope

### In Scope

- SqliteContextPersistence backend + ce.load() on startup
- StepExecution enrichment (6 new fields)
- LoopState property migration (13 fields → CE-backed properties)
- Adapter deletion (ContextEngineGoalContextAdapter, StepPlanManagerAdapter, ContextEngineLifecycle)
- Dual-write removal (_record_ledger_message, seed_loop_ledger_from_prior_goal)
- GoalExecutionRecord trimmed to 7 fields, StrangeLoopCheckpoint schema 4.0
- ContextBundle extended with prior_goals and cross_goal_ledger
- 4-tier error handling

### Out of Scope

- LoopState → ExecutionState rename (Step 8, cosmetic, can be deferred)
- GoalEngine integration (Phase 2)
- PostgreSQL persistence backend (use SQLite for now)
- RAG / vector store integration

## Implementation Phases

### Step 1: CE Persistence + ce.load() on Startup

**Files to create:**
- `packages/soothe/src/soothe/context/sqlite_backend.py` — `SqliteContextPersistence`

**Files to modify:**
- `packages/soothe/src/soothe/context/__init__.py` — export SqliteContextPersistence
- `packages/soothe/src/soothe/loop/engine/strange_loop.py` — call `await ce.load()` after creating CE, before `create_goal()`
- `packages/soothe/src/soothe/config/models.py` — add `"sqlite"` option, change default
- `config/config.template.yml` — `persistence_backend: "sqlite"`
- `config/develop/config.yml` — matching change

**Verification:**
- ce.load() returns prior DAG when loop_id has prior goals
- ce.load() returns False gracefully on first run (no prior state)
- Successive goals in same loop_id accumulate in DAG

### Step 2: Enrich StepExecution

**Files to modify:**
- `packages/soothe/src/soothe/context/models.py` — add 6 fields to StepExecution
- `packages/soothe/src/soothe/loop/orchestrator/nodes/record_iteration.py` — pass enriched StepExecution to ce.complete_step()

**Verification:**
- StepExecution round-trips through save/load with all new fields
- Existing tests pass (new fields have defaults)

### Step 3: Migrate loop_messages → CE Sole Source

**Files to modify:**
- `packages/soothe/src/soothe/loop/state/schemas.py` — `loop_messages` becomes property
- `packages/soothe/src/soothe/loop/utils/messages.py` — delete `_record_ledger_message()` dual-write; delete `seed_loop_ledger_from_prior_goal()`
- All graph nodes that call `_record_ledger_message()` — change to `ce.ledger.record_message()`

**Verification:**
- Prompt content identical before/after
- `state.loop_messages` property matches `ce.ledger.get_messages()`

### Step 4: Migrate step_results / completed_step_ids → CE Properties

**Files to modify:**
- `packages/soothe/src/soothe/loop/state/schemas.py` — `step_results` and `completed_step_ids` become properties; delete `add_step_result()`
- `packages/soothe/src/soothe/loop/orchestrator/nodes/record_iteration.py` — remove `state.add_step_result()` calls

**Verification:**
- `dependency_completion_ids()` returns same results
- Step tracking lives in CE DAG

### Step 5: Migrate current_decision / plan_id → CE Active Plan

**Files to modify:**
- `packages/soothe/src/soothe/context/models.py` — add `GoalNode.active_plan` field
- `packages/soothe/src/soothe/context/engine.py` — add `ingest_plan()`, `active_plan()` methods
- `packages/soothe/src/soothe/loop/state/schemas.py` — `current_decision` and `plan_id` become properties
- `packages/soothe/src/soothe/loop/orchestrator/nodes/resolve_decision.py` — call `ce.ingest_plan()` instead of setting `state.current_decision`

**Verification:**
- Plan ingestion and step ID scoping work identically

### Step 6: Migrate Remaining CE-Overlapping Fields

**Files to modify:**
- `packages/soothe/src/soothe/context/models.py` — add `GoalNode.max_iterations`, `GoalNode.total_duration_ms`, `GoalNode.previous_plan`, `GoalNode.evidence_ledger`, `GoalNode.action_history`
- `packages/soothe/src/soothe/context/engine.py` — add `record_evidence()`, `record_action()`, `finalize_goal()`
- `packages/soothe/src/soothe/loop/state/schemas.py` — properties for all remaining CE fields; delete `working_memory`, `prior_progress`, `evidence_summary`

**Verification:**
- All properties read correct values from CE

### Step 7: Delete Adapters + Simplify Checkpoint

**Files to delete:**
- `packages/soothe/src/soothe/loop/engine/context_adapters.py` (ContextEngineGoalContextAdapter)
- `packages/soothe/src/soothe/loop/engine/context_lifecycle.py` (ContextEngineLifecycle)
- `packages/soothe/src/soothe/context/step_planner.py` → remove `StepPlanManagerAdapter` class

**Files to modify:**
- `packages/soothe/src/soothe/loop/state/checkpoint.py` — trim GoalExecutionRecord to 7 fields; trim StrangeLoopCheckpoint; schema 4.0
- `packages/soothe/src/soothe/loop/orchestrator/runtime_context.py` — remove `goal_context_manager`, `plan_manager`, `ce_lifecycle`
- `packages/soothe/src/soothe/loop/engine/strange_loop.py` — wire nodes to call ctx.ce directly
- All graph node files — replace adapter calls with direct CE calls
- `packages/soothe/src/soothe/context/projection.py` — add PriorGoalSummary, cross_goal_ledger

**Verification:**
- Full integration test: successive goals, crash recovery, context window
- Schema 4.0 lazy migration works

### Step 8: Rename LoopState → ExecutionState (deferred)

**Files to modify:**
- Rename class, update all references

**This step is cosmetic and can be deferred.**

## Risks

| Risk | Mitigation |
|------|-----------|
| CE load latency on large DAGs | Ship eager first; add lazy loading if data warrants |
| Property reads slower than attribute access | Cache within graph iteration; invalidate on CE mutation |
| Dual-write removal causes prompt regressions | A/B equivalence tests before removing |
| StepExecution enrichment breaks persistence | New fields have defaults; old format loads correctly |
