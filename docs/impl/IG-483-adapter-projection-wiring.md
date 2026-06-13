# IG-483: Adapter Hardening + Projection Wiring

**RFC**: 624 (Phase 3b)
**Status**: Done
**Created**: 2026-06-13
**Depends on**: IG-484 (CE Engine Completeness)

---

## Objective

Fix the GoalContextAdapter gap (reads from old state_manager instead of CE DAG), refactor all adapters to use the public API from IG-484, and wire ContextBundle into the prompt pipeline as supplementary context when CE is enabled.

## Implementation Steps

### Step 1: Refactor ContextEnginePlanAdapter to use public API

**File**: `packages/soothe/src/soothe/foundation/loop/engine/context_adapters.py`

Replace private field access in `ContextEnginePlanAdapter`:

| Current | Replacement |
|---------|-------------|
| `self._ce._dag.get_goal(self._goal_id)` | `await self._ce.get_goal(self._goal_id)` |
| `self._ce._dag.goals.values()` | `self._ce.get_all_goals()` |
| `self._ce._dag.goal_lineage(goal.id)` | `self._ce.get_goal_lineage(goal.id)` |

Note: `ingest_plan()` and `record_step_outcomes()` still need goal-level access for step mutations. Use `await self._ce.get_goal()` to get the GoalNode, then mutate its `steps` directly (same as now, but via public getter).

`format_completion_dag_report()`: Replace `self._ce._dag` with `self._ce.get_all_goals()` and `self._ce.get_goal_lineage()`. Iterate goals from `get_all_goals()` instead of `self._ce._dag.goals.values()`.

`_heuristic_requires_goal_completion()`, `_is_simple_execution()`, `_dag_requires_synthesis()`: Replace `self._ce._dag.get_goal()` with `await self._ce.get_goal()`. Since these are called from synchronous contexts, we need a sync accessor — use the new `self._ce.get_step_dag()` where only step stats are needed, or cache the goal reference.

**Important**: Several PlanAdapter methods are synchronous (not async) but the public API `get_goal()` is async. Options:
- Add a private `_get_goal_sync()` helper that calls `self._ce._dag.get_goal()` — but this defeats the purpose
- Better: since all the internal state is in-memory (no actual I/O), make `ContextEngine.get_goal()` and `get_step_dag()` also available as sync methods (they already are — `get_step_dag` is sync, and we can add a sync `get_goal_sync()`)

**Decision**: Add `get_goal_sync()` as a synchronous alias that reads from `_dag.get_goal()` directly. This is justified because all CE reads are in-memory. The async `get_goal()` remains for the public async API.

### Step 2: Refactor ContextEngineLedgerAdapter to use public API

Replace:
- `self._ce._ledger.record_message(message, phase)` → `await self._ce.record_message(message, phase)`

But `record_message()` is async while the adapter's `record_message()` is sync. Solution: keep the sync path — the adapter can call `self._ce._ledger.record_message()` directly for the sync write (since it's in-memory), OR we make `ContextEngine.record_message()` synchronous (it doesn't await anything internally).

**Decision**: The `ContextEngine.record_message()` is async but has no `await` in its body. Add a sync `record_message_sync()` to ContextEngine, or simply keep the adapter calling `self._ce._ledger.record_message()` for now since `LedgerManager.record_message()` is already public. The adapter already holds a reference to the CE, and `LedgerManager` is a public class with public methods. This is acceptable — the adapter is tightly coupled to CE by design.

### Step 3: Fix GoalContextAdapter to read from CE DAG

**File**: `packages/soothe/src/soothe/foundation/loop/engine/context_adapters.py`

**`get_plan_context()`**: Replace `self._state_manager.load()` with reading from CE DAG:

```python
async def get_plan_context(self, limit: int | None = None) -> list[str]:
    if self._config is not None and not getattr(self._config, "enabled", True):
        return []

    try:
        actual_limit = limit or getattr(self._config, "plan_limit", 10) if self._config else 10

        # Read completed goals from CE DAG
        all_goals = self._ce.get_all_goals()
        completed = [g for g in all_goals if g.status == "completed"][-actual_limit:]

        if not completed:
            # Fallback to state_manager if CE has no completed goals
            if self._state_manager is not None:
                checkpoint = await self._state_manager.load()
                if checkpoint and checkpoint.goal_history:
                    # ... existing fallback logic
            return []

        context_blocks = []
        for goal in completed:
            # Build completion summary from step outcomes
            step_summary = self._render_step_summary(goal)
            context_block = (
                f"<previous_goal>\n"
                f"Goal: {goal.description}\n"
                f"Status: {goal.status}\n"
                f"Output:\n{step_summary}\n"
                f"</previous_goal>"
            )
            context_blocks.append(context_block)

        return context_blocks
    except Exception as e:
        logger.warning("CE GoalContextAdapter: failed to load plan context: %s", e)
        return []
```

Add a `_render_step_summary()` helper that produces a text summary from a GoalNode's completed steps.

**`get_execute_briefing()`**: Replace `self._state_manager.load()` with CE DAG reads:

```python
async def get_execute_briefing(self, limit: int | None = None) -> str | None:
    if self._config is not None and not getattr(self._config, "enabled", True):
        return None

    try:
        # Thread switch detection still needs state_manager
        if self._state_manager is not None:
            checkpoint = await self._state_manager.load()
            if not checkpoint or not checkpoint.thread_switch_pending:
                return None
            checkpoint.thread_switch_pending = False
            await self._state_manager.save(checkpoint)

        actual_limit = limit or getattr(self._config, "execute_limit", 10) if self._config else 10
        all_goals = self._ce.get_all_goals()
        completed = [g for g in all_goals if g.status == "completed"][-actual_limit:]

        if not completed:
            return None

        return format_execute_briefing_from_ce_goals(completed, checkpoint.current_thread_id if checkpoint else "")
    except Exception as e:
        logger.error("CE GoalContextAdapter: failed to generate execute briefing: %s", e)
        return None
```

Add `format_execute_briefing_from_ce_goals()` that formats GoalNode objects into the same markdown briefing format.

### Step 4: Add sync accessor to ContextEngine

**File**: `packages/soothe/src/soothe/context/engine.py`

Add `get_goal_sync()` method for use by synchronous adapter methods:

```python
def get_goal_sync(self, goal_id: str) -> GoalNode | None:
    """Synchronous goal lookup (in-memory, no I/O)."""
    return self._dag.get_goal(goal_id)
```

### Step 5: Wire ContextBundle into PromptBuilder

**File**: `packages/soothe/src/soothe/foundation/loop/prompts/builder.py`

1. Add `context_bundle: ContextBundle | None = None` parameter to `build_plan_messages()`.

2. Thread to `_build_system_message(context, state, plan_phase, context_bundle)`:
   - If `context_bundle` and `context_bundle.project_instructions`: skip `load_workspace_project_instructions()` and use `bundle.project_instructions`
   - If `context_bundle` and `context_bundle.agent_instructions`: append as additional system section
   - If `context_bundle` and `context_bundle.memory_instructions`: append as additional system section

3. Thread to `_build_plan_context_human_text(goal, state, context, plan_phase, dag_context, context_bundle)`:
   - If `context_bundle` and `context_bundle.goal_lineage`: add `<GOAL_LINEAGE>` block
   - If `context_bundle` and `context_bundle.goal_progress`: add `<GOAL_PROGRESS>` block
   - If `context_bundle` and `context_bundle.step_lineage`: add `<STEP_LINEAGE>` block

All supplements are additive and guarded by `context_bundle is not None`.

### Step 6: Pass ContextBundle from planner

**File**: `packages/soothe/src/soothe/foundation/loop/planning/planner.py`

In `LLMPlanner.generate_from_assessment()` and `LLMPlanner.plan()`:
- When `context_engine` is available on the plan_manager (or passed separately), call `await context_engine.project()` to get a `ContextBundle`
- Pass it to `build_plan_messages(..., context_bundle=bundle)`

### Step 7: Tests

- Unit tests for refactored adapters using public API
- Unit tests for GoalContextAdapter reading from CE DAG
- Unit tests for PromptBuilder with `context_bundle` (supplements injected)
- Unit tests for PromptBuilder without `context_bundle` (no changes)
- Existing adapter (22) + integration (9) tests must still pass

## Build Sequence

1. Step 4 (sync accessor) — no dependencies
2. Step 1 (PlanAdapter refactor) — depends on Step 4
3. Step 2 (LedgerAdapter refactor) — depends on Step 4
4. Step 3 (GoalContextAdapter fix) — depends on Step 4
5. Step 5 (PromptBuilder wiring) — independent
6. Step 6 (Planner wiring) — depends on Steps 3, 5
7. Step 7 (Tests) — depends on all

## Acceptance Criteria

- All adapters use public API (no `_dag` or `_ledger._entries` direct access)
- GoalContextAdapter reads from CE DAG for plan context and execute briefing
- PromptBuilder receives optional ContextBundle and injects supplementary context
- When CE disabled, all behavior is identical to current
- All existing tests pass
