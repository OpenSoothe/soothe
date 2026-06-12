# CE-as-LoopState Backend: Full Replacement Design

RFC-624 Phase 4: Replace the AgentLoop's Plan-Exec implementation with ContextEngine as the sole data source. Remove all legacy components (PlanManager, PlanDAG, GoalContextManager, adapters). CE becomes the primary data store, backed by PostgreSQL/SQLite instead of files.

## Context

Phases 1–3d of RFC-624 are complete. CE runs as an additive sidecar: when enabled, `StepPlanManagerAdapter` replaces `PlanManager`, `ContextEngineLedgerAdapter` dual-writes to `LedgerManager`, and `ContextEngineLifecycle` manages goal/step lifecycle. But `LoopState` fields (`loop_messages`, `step_results`, `completed_step_ids`) remain the primary data structures consumed by graph nodes. CE is secondary.

This design makes CE the sole data source. Graph nodes still interact with `LoopState`, but its key fields become properties backed by CE queries. Legacy components are removed entirely.

## Requirements

- **Full replacement**: CE is the only path. No `if ce_config.enabled` branching.
- **One shot**: Single IG, not phased.
- **DB persistence**: CE switches from file backend to PostgreSQL/SQLite (same pool as current `AgentLoopStateManager`).
- **Behavioral equivalence**: Same observable outputs (final response, step execution order, error handling). Internal data structures change completely.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                   Graph Nodes                    │
│  (plan_assess, plan_generate, execute, etc.)     │
│         ↓ read/write via LoopState              │
├─────────────────────────────────────────────────┤
│                  LoopState                       │
│  loop_messages    → property → LedgerManager     │
│  step_results     → property → StepDAG.results  │
│  completed_step_ids → property → StepDAG.done   │
│  current_decision   → field   → (unchanged)     │
│  working_memory     → field   → (unchanged)     │
│  evidence_summary   → derived from step_results │
│  evidence_ledger    → property → StepDAG.evidence│
├─────────────────────────────────────────────────┤
│              ContextEngine                       │
│  GoalStepDAG  │  LedgerManager  │  Projection   │
│  (DAG+steps)  │  (ledger store) │  (bundles)    │
├─────────────────────────────────────────────────┤
│          CE Persistence Backend                  │
│  PostgreSQL (prod) │ SQLite (dev)               │
└─────────────────────────────────────────────────┘
```

## LoopState Property Mapping

| Field | Strategy | CE Backend | Mutable? |
|-------|----------|------------|----------|
| `loop_messages` | Property | `LedgerManager.get_messages()` | Writes go to `LedgerManager.record_message()` |
| `step_results` | Property | `StepDAG.completed_steps()` | Writes go to `StepDAG.mark_completed/mark_failed()` |
| `completed_step_ids` | Property | `StepDAG.completed_step_ids` | Writes go to `StepDAG.mark_completed()` |
| `current_decision` | Field (unchanged) | N/A — transient routing state | Direct assignment |
| `working_memory` | Field (unchanged) | N/A — data display only | Direct assignment |
| `evidence_summary` | Computed property | Derived from `step_results` property | Auto-computed |
| `evidence_ledger` | Property | `StepDAG.evidence_entries` | Writes go to `StepDAG.add_evidence()` |

### Why `current_decision` stays a field

`current_decision` is transient routing state set by `resolve_decision` and consumed by `execute`. It's not a CE concept — CE has steps in a DAG, not "decisions." Converting it to a property would add complexity with no benefit, since it's set once per plan and read only within the same iteration.

### Why `working_memory` stays a field

`working_memory` is a data-display mechanism (step outcome recording for prompts). It never influences routing or planning decisions. CE's `LedgerManager` already captures equivalent data. Converting this to a CE property would create a circular dependency between `LedgerManager.record_step_result()` and the working memory API.

## LoopState Property Implementation

LoopState holds a `_ce` reference to ContextEngine. Property getters query CE; mutations go through CE APIs instead of direct list/set operations.

```python
class LoopState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    _ce: ContextEngine | None = PrivateAttr(default=None)

    # ── CE-backed properties ──────────────────────────

    @property
    def loop_messages(self) -> list[LoopHumanMessage | LoopAIMessage]:
        if self._ce is None:
            return self._loop_messages_fallback
        return self._ce.ledger.get_messages()

    @loop_messages.setter
    def loop_messages(self, value: list) -> None:
        if self._ce is None:
            self._loop_messages_fallback = value
            return
        # Reset ledger — used during init from prior goal record
        self._ce.ledger.clear()
        for msg in value:
            self._ce.ledger.record_message(msg, phase=getattr(msg, "phase", None))

    @property
    def step_results(self) -> list[StepResult]:
        if self._ce is None:
            return self._step_results_fallback
        return self._ce.dag.step_results(self._ce_goal_id)

    @property
    def completed_step_ids(self) -> set[str]:
        if self._ce is None:
            return self._completed_step_ids_fallback
        return self._ce.dag.completed_step_ids(self._ce_goal_id)

    @property
    def evidence_summary(self) -> str:
        results = self.step_results
        lines = [r.to_evidence_string() for r in results]
        return "\n".join(lines)

    @property
    def evidence_ledger(self) -> list[EvidenceEntry]:
        if self._ce is None:
            return self._evidence_ledger_fallback
        return self._ce.dag.evidence_entries(self._ce_goal_id)
```

### Fallback fields

Pydantic requires backing fields for properties. Private attributes (`_loop_messages_fallback`, etc.) are used when `_ce` is None. This only occurs during tests that construct `LoopState` without CE. In production, `_ce` is always set.

### `add_step_result()` becomes a method that writes to CE

```python
def add_step_result(self, result: StepResult) -> None:
    if self._ce is not None:
        if result.success:
            self._ce.dag.mark_completed(self._ce_goal_id, result.step_id, ...)
        else:
            self._ce.dag.mark_failed(self._ce_goal_id, result.step_id, ...)
    else:
        self._step_results_fallback.append(result)
        if result.success:
            self._completed_step_ids_fallback.add(result.step_id)
```

### `dependency_completion_ids()` reads from CE

```python
def dependency_completion_ids(self) -> set[str]:
    return self.completed_step_ids  # already includes historical successes via StepDAG
```

The `StepDAG.completed_step_ids` method returns all step IDs in `completed` status, which naturally includes historical successes from prior plan waves (unlike the old `completed_step_ids` set which was cleared on replan and relied on `step_results` for historical tracking).

## CE Persistence Backend: Database

Add `DatabasePersistenceBackend` implementing `ContextPersistenceProtocol`.

```python
# soothe/context/persistence/db_backend.py
class DatabasePersistenceBackend:
    """PostgreSQL/SQLite persistence for ContextEngine state."""

    def __init__(self, dsn: str, pool_size: int = 4) -> None: ...
    async def save_dag(self, dag: GoalStepDAG) -> None: ...
    async def load_dag(self) -> GoalStepDAG | None: ...
    async def save_ledger(self, messages: list[dict]) -> None: ...
    async def load_ledger(self) -> list[dict]: ...
    async def clear(self) -> None: ...
```

Schema — two tables in the existing `soothe_metadata` database:

```sql
CREATE TABLE IF NOT EXISTS ce_goal_dag (
    loop_id TEXT PRIMARY KEY,
    dag_json JSONB NOT NULL,
    saved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ce_ledger (
    loop_id TEXT PRIMARY KEY,
    messages_json JSONB NOT NULL,
    saved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Uses the same connection pool as `AgentLoopStateManager` (via `persistence.soothe_postgres_dsn`). Falls back to SQLite when PostgreSQL is unavailable (mirrors existing daemon behavior).

## Removed Components

| Component | Lines | Location | Replacement |
|-----------|-------|----------|-------------|
| `PlanManager` | ~260 | `foundation/loop/planning/manager.py` | `StepPlanningSubengine` (already exists) |
| `PlanDAG` | ~350 | `foundation/loop/planning/dag.py` | `GoalStepDAG` (already exists) |
| `GoalContextManager` | ~200 | `foundation/loop/planning/goal_context.py` | `ContextEngineGoalContextAdapter` logic moves into CE |
| `ContextEngineLedgerAdapter` | ~35 | `foundation/loop/engine/context_adapters.py` | Direct `LedgerManager` calls |
| `ContextEngineGoalContextAdapter` | ~190 | `foundation/loop/engine/context_adapters.py` | CE queries (already in `ContextEngineGoalContextAdapter.get_plan_context()`) |
| `StepPlanManagerAdapter` | ~60 | `context/planning/step_planner.py` | Direct `StepPlanningSubengine` calls |
| `ContextEngineLifecycle` | ~144 | `foundation/loop/engine/context_lifecycle.py` | CE operations inline in nodes (simpler with single path) |
| `if ce_config.enabled` branches | ~50 | `agent_loop.py` | Removed — CE is always active |
| `PlanManager` heuristic methods | ~80 | `foundation/loop/planning/manager.py` | Already in `completion.py` |
| `ContextEngineConfig.enabled` | ~5 | `config/models.py` | Removed — always enabled |

**Total removed: ~1,374 lines**
**Total added: ~250 lines** (DB backend + property getters + node updates)
**Net reduction: ~1,100 lines**

## Graph Node Changes

All nodes change from calling `plan_manager.X()` to calling `ce.planning.step.X()`. The `plan_manager` field on `LoopRuntimeContext` is replaced by a `ce` field (ContextEngine reference).

### plan_assess.py

```python
# Before:
plan_manager.ingest_plan(plan_result, plan_id, iteration)
plan_manager.determine_goal_completion_needs(llm_decision, state, mode)

# After:
ce.planning.step.ingest_plan(goal_id, plan_result, plan_id, iteration)
ce.planning.step.determine_goal_completion_needs(goal_id, llm_decision, state, mode)
await ce.save()
```

### plan_generate.py

```python
# Before:
plan_phase.generate_from_assessment(plan_manager=plan_manager, ce_ledger_adapter=..., context_engine=...)

# After:
plan_phase.generate_from_assessment(plan_manager=ce.planning.step, context_engine=ce)
```

`ce_ledger_adapter` parameter removed — ledger reads come from `state.loop_messages` property (backed by LedgerManager).

### resolve_decision.py

```python
# Before:
plan_manager.ingest_plan(plan_result, plan_id, iteration)

# After:
ce.planning.step.ingest_plan(goal_id, plan_result, plan_id, iteration)
await ce.save()
```

### record_iteration.py

```python
# Before:
plan_manager.record_step_outcomes(step_results)
if ctx.ce_lifecycle:
    await ctx.ce_lifecycle.on_steps_executed(step_results)

# After:
ce.planning.step.record_step_outcomes(goal_id, step_results)
await ce.save()
```

### goal_completion.py

```python
# Before:
plan_manager.determine_completion_strategy(state, plan_result, mode)
plan_manager.format_completion_dag_report()
if ctx.ce_lifecycle:
    await ctx.ce_lifecycle.on_goal_complete(status, plan_result)

# After:
ce.planning.step.determine_completion_strategy(goal_id, state, plan_result, mode)
ce.planning.step.format_completion_dag_report(goal_id)
await ce.complete_goal(goal_id)  # or ce.fail_goal()
await ce.save()
```

### execute_steps.py

```python
# Before (in _append_ask_user_loop_messages, etc.):
_record_ledger_message(..., state.loop_messages)

# After:
state._ce.ledger.record_message(message, phase=phase)
# Or: state.loop_messages is now a property — callers that append must use
# a new state.append_loop_message(msg, phase) method instead.
```

### agent_loop.py

```python
# Before:
if ce_config.enabled:
    ce_instance = ContextEngine(...)
    ce_goal = await ce_instance.create_goal(...)
    plan_manager = StepPlanManagerAdapter(...)
    ce_ledger_adapter = ContextEngineLedgerAdapter(...)
    goal_context_adapter = ContextEngineGoalContextAdapter(...)
    ce_lifecycle = ContextEngineLifecycle(...)
else:
    plan_manager = PlanManager(goal=...)

# After (always):
ce_instance = ContextEngine(...)
ce_goal = await ce_instance.create_goal(...)
state._ce = ce_instance
state._ce_goal_id = ce_goal.id
# plan_manager is ce.planning.step (no adapter needed)
```

## LoopRuntimeContext Changes

```python
# Before:
@dataclass
class LoopRuntimeContext:
    plan_manager: PlanManager | Any
    ce_lifecycle: Any | None = None
    ce_ledger_adapter: Any | None = None
    ce_goal_context_adapter: Any | None = None
    context_engine: Any | None = None

# After:
@dataclass
class LoopRuntimeContext:
    ce: ContextEngine  # Always present
    ce_goal_id: str     # Always present
```

All adapter and lifecycle references collapse into `ce` + `ce_goal_id`.

## Message Write Path

The biggest change is how messages are appended. Currently, `_record_ledger_message()` appends to `state.loop_messages` (a list). With the property, direct `.append()` won't work.

**Solution**: Add `state.append_loop_message(msg, phase)` method:

```python
def append_loop_message(self, message: LoopHumanMessage | LoopAIMessage, phase: str) -> None:
    """Append a message to the loop ledger."""
    if self._ce is not None:
        self._ce.ledger.record_message(message, phase=phase)
    else:
        self._loop_messages_fallback.append(message)
```

Replace all `_record_ledger_message(..., state.loop_messages)` calls with `state.append_loop_message(msg, phase)`. This is ~8 call sites across planner.py, goal_completion.py, execute_steps.py.

## LedgerManager ↔ LoopMessage Type Bridge

`LedgerManager` stores `BaseMessage` objects with phase tags. `state.loop_messages` currently stores `LoopHumanMessage | LoopAIMessage` (which are subclasses of `HumanMessage` / `AIMessage` with extra `phase` fields).

**Approach**: `LoopHumanMessage` and `LoopAIMessage` already carry a `phase` attribute (via `LoopMessageMixin`). When `LedgerManager.record_message()` receives one, it extracts the phase from the message's `phase` attribute if not explicitly provided:

```python
def record_message(self, message: BaseMessage, phase: str | None = None) -> None:
    effective_phase = phase or getattr(message, "phase", None)
    self._entries.append(_LedgerEntry(message=message, phase=effective_phase))
```

When `LedgerManager.get_messages()` returns messages, it returns the original message objects (which are already `LoopHumanMessage`/`LoopAIMessage` instances). This means `state.loop_messages` returns the same types as before, and `project_loop_messages_for_plan()` works unchanged.

## Persistence: Replacing AgentLoopStateManager

The `AgentLoopStateManager` currently persists:
- `loop_messages` (full ledger)
- `step_results`, `completed_step_ids`, `evidence_ledger`, `evidence_summary`
- `current_plan` (from `current_decision` + `evidence_summary`)
- `working_memory_state` (spill file paths)

With CE as the backend, all of this is already captured in `GoalStepDAG` + `LedgerManager`:
- `loop_messages` → `LedgerManager` entries
- `step_results`, `completed_step_ids` → `StepDAG` step nodes with status
- `evidence_ledger` → `StepDAG` evidence entries
- `current_plan` → derived from DAG state
- `working_memory` → stays as LoopState field, persisted via LangGraph checkpoint

**LangGraph checkpointing**: LangGraph's `AsyncPostgresSaver` serializes `LoopState` via `model_dump()`. Pydantic properties are NOT included in `model_dump()` — only the backing fields are. This is the correct behavior: the fallback fields (`_loop_messages_fallback`, `_step_results_fallback`, etc.) act as serialization targets. Before serialization, we sync the fallback fields from CE state so `model_dump()` captures current data. This happens in `state_manager.record_iteration()` and `state_manager.finalize_goal()` where we call `state._sync_fallbacks()` before the checkpoint write.

```python
def _sync_fallbacks(self) -> None:
    """Sync CE-backed data to fallback fields for Pydantic serialization."""
    if self._ce is not None:
        self._loop_messages_fallback = list(self.loop_messages)
        self._step_results_fallback = list(self.step_results)
        self._completed_step_ids_fallback = set(self.completed_step_ids)
        self._evidence_summary_fallback = self.evidence_summary
        self._evidence_ledger_fallback = list(self.evidence_ledger)
```

The `_ce` reference is excluded from serialization (it's a `PrivateAttr`).

**Migration**: Existing checkpoint data in PostgreSQL is read-compatible. When a loop resumes, `AgentLoopStateManager.load()` deserializes the old `loop_messages` list → the `loop_messages` setter copies them into `LedgerManager`. Old `step_results` and `completed_step_ids` → `add_step_result()` copies them into `StepDAG`. This provides seamless migration from old checkpoints.

## Error Handling

Same pattern as `ContextEngineLifecycle` — CE errors are caught and logged, never propagated to graph nodes:

- **Property getters**: Return empty defaults on CE errors. `state.step_results` → `[]`, `state.completed_step_ids` → `set()`, `state.loop_messages` → `[]`.
- **CE mutation calls** (`ce.save()`, `ce.complete_goal()`, etc.): Wrapped in try/except with warning logs. Graph flow continues.
- **StepDAG queries**: Return empty results on errors. This means dependency resolution falls back to "all steps ready" (conservative — all steps become eligible).

This ensures a CE backend failure degrades gracefully: the loop continues with potentially less optimal dependency scheduling but never crashes.

## Removed Config

```yaml
agent:
  loop:
    context_engine:
      enabled: true      # REMOVED — always enabled
      persistence_backend: "file"  # Changed to "db" (PostgreSQL/SQLite)
```

New config:
```yaml
agent:
  loop:
    context_engine:
      persistence_backend: "db"  # "db" (default) | "file" | "in_memory"
```

The `enabled` field is removed. CE is always active. The `persistence_backend` defaults to `"db"` for production, falls back to `"file"` or `"in_memory"` for testing.

## Testing Strategy

1. **Property equivalence tests**: For each property, verify that `state.step_results` returns the same data as the old list-based approach. Test with both CE-backed and fallback paths.

2. **Mutation equivalence tests**: `add_step_result()`, `append_loop_message()`, `trim_loop_messages()`, `clear_goal_state()` must produce the same observable state changes.

3. **Integration equivalence test**: Run the same query through old and new code paths, compare step-by-step execution trace.

4. **Persistence round-trip test**: Save CE state to DB, reload, verify all properties return same data.

5. **Regression**: All 667 existing loop tests must pass unchanged. Test helpers that construct `LoopState` without CE use the fallback fields.

6. **Migration test**: Load an old-format checkpoint (with `loop_messages` as a list), verify it populates `LedgerManager` correctly.

## Build Sequence

1. Add `DatabasePersistenceBackend` (no dependencies)
2. Add `LoopState` properties and `append_loop_message()` method (depends on CE API)
3. Wire `LoopState._ce` in `agent_loop.py` (depends on #2)
4. Update graph nodes to call `ce.planning.step` directly (depends on #3)
5. Update `LoopRuntimeContext` — remove adapters, add `ce` field (depends on #4)
6. Remove `_record_ledger_message()` — replace with `state.append_loop_message()` (depends on #2)
7. Remove `PlanManager`, `PlanDAG`, `GoalContextManager` (depends on #4, #5)
8. Remove adapters and lifecycle (depends on #5, #6)
9. Remove `ContextEngineConfig.enabled` (depends on #3)
10. Update `config/config.template.yml` and `config/config.dev.yml`
11. Add migration logic in `AgentLoopStateManager.load()` (depends on #2)
12. Tests (depends on all)

## Acceptance Criteria

- `PlanManager`, `PlanDAG`, `GoalContextManager` removed
- All adapters (`ContextEngineLedgerAdapter`, `ContextEngineGoalContextAdapter`, `StepPlanManagerAdapter`) removed
- `ContextEngineLifecycle` removed (CE ops inline in nodes)
- `if ce_config.enabled` branching removed from `agent_loop.py`
- `LoopState.loop_messages`, `step_results`, `completed_step_ids`, `evidence_summary`, `evidence_ledger` are properties backed by CE
- `current_decision`, `working_memory` remain as fields
- CE persistence backend is PostgreSQL/SQLite (not file)
- Same observable behavior: identical final responses, step execution order, error handling
- All existing tests pass (with fallback fields for test-constructed LoopState)
- Net code reduction ~1,100 lines

## Out of Scope

- **GoalEngine replacement**: AutopilotService still uses GoalEngine for goal scheduling. This is a separate concern (RFC-624 Phase 2 future work).
- **Graph topology changes**: No node additions, removals, or edge changes. Same 12-node graph.
- **Prompt changes**: Existing prompt templates unchanged. ContextBundle injection unchanged (additive only).
- **LangGraph checkpoint replacement**: `AsyncPostgresSaver` still handles graph state serialization. CE only replaces the business data storage.
