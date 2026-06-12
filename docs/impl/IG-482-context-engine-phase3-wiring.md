# IG-482: Context Engine Phase 3 — Ledger Wiring & Behavioral Equivalence

> RFC-624 Phase 3 completion: wire the ledger adapter into all message-writing call sites, fix adapter behavioral gaps, and add integration tests proving 100% equivalence with the non-CE path.

## Context

Phase 3 adapters (`ContextEnginePlanAdapter`, `ContextEngineLedgerAdapter`, `ContextEngineGoalContextAdapter`) and the `AgentLoop.run_with_progress()` wiring are already implemented. The `ce_ledger_adapter` is stored on `LoopRuntimeContext` but never invoked — the dual-write strategy is non-functional.

Additionally, the adapters have behavioral gaps vs. PlanManager: hardcoded constants, missing logging, and a fragile `GoalContextManager.__new__()` hack.

## Build Sequence

### Step 1: Add `_record_ledger_message()` helper

Add to `soothe/foundation/loop/utils/messages.py`:

```python
def _record_ledger_message(
    ce_ledger_adapter: Any | None,
    msg: Any,
    phase: str,
    loop_messages: list[Any],
) -> None:
    if ce_ledger_adapter is not None:
        ce_ledger_adapter.record_message(msg, phase, loop_messages)
    else:
        loop_messages.append(msg)
```

### Step 2: Extract `format_execute_briefing_from_goals()`

In `goal_context_manager.py`, extract the body of `_format_execute_briefing` and the three `_extract_*` helper methods into a module-level function `format_execute_briefing_from_goals(goals, current_thread) -> str | None`. The `GoalContextManager._format_execute_briefing` becomes a thin wrapper. The adapter calls the standalone function directly.

### Step 3: Fix adapter behavioral gaps

In `context_adapters.py`:
- Import and use `_LOW_SUCCESS_RATE_THRESHOLD`, `_DAG_DEPENDENCY_THRESHOLD`, `_SIMPLE_DAG_LEDGER_DIRECT_MAX_STEPS` from `manager.py`
- Add logging (debug/info) to match PlanManager's logging, with `"CEPlanAdapter:"` prefix
- Replace `GoalContextManager.__new__()` hack with `format_execute_briefing_from_goals()`

### Step 4: Wire ledger adapter into executor

Pass `ce_ledger_adapter` to `Executor.__init__()` as an optional kwarg. Replace `state.loop_messages.append(human_msg)` and `state.loop_messages.append(ai_msg)` pairs (lines ~1775, ~1826) with `self._ce_ledger_adapter.record_message(msg, "execute_step", state.loop_messages)` when adapter is not None, else direct append.

### Step 5: Wire ledger adapter into planner

Add `ce_ledger_adapter=None` kwarg to `assess_status()` and `generate_from_assessment()`. Replace `state.loop_messages.append()` pairs with conditional calls through the adapter. Update callers in `plan_assess.py` and `plan_generate.py` to pass `ctx.ce_ledger_adapter`.

### Step 6: Wire ledger adapter into execute_steps and goal_completion

In `execute_steps.py`, replace `_append_ask_user_loop_messages()` direct appends with `_record_ledger_message(ctx.ce_ledger_adapter, msg, "execute_step", state.loop_messages)`.

In `goal_completion.py`, replace `_append_goal_completion_ledger_pair()` direct appends with `_record_ledger_message(ctx.ce_ledger_adapter, msg, "goal_completion", state.loop_messages)`.

### Step 7: Integration test

Add `tests/integration/loop/test_ce_agent_loop_equivalence.py` with a parameterized test that runs the same AgentLoop scenario with CE enabled and disabled, asserting identical observable outputs.

### Step 8: Verification

Run `./scripts/verify_finally.sh` — zero lint errors, all tests pass.

## Files Changed

| File | Change |
|------|--------|
| `foundation/loop/utils/messages.py` | Add `_record_ledger_message()` |
| `foundation/loop/engine/goal_context_manager.py` | Extract `format_execute_briefing_from_goals()` |
| `foundation/loop/engine/context_adapters.py` | Named constants, logging, remove `__new__()` hack |
| `foundation/loop/engine/executor.py` | Accept `ce_ledger_adapter`, wire into ledger appends |
| `foundation/loop/planning/planner.py` | Accept `ce_ledger_adapter` kwarg, wire into ledger appends |
| `orchestrator/nodes/execute_steps.py` | Wire adapter into ask_user appends, pass to Executor |
| `orchestrator/nodes/goal_completion.py` | Wire adapter into completion appends |
| `orchestrator/nodes/plan_assess.py` | Pass `ctx.ce_ledger_adapter` to planner |
| `orchestrator/nodes/plan_generate.py` | Pass `ctx.ce_ledger_adapter` to planner |
| `tests/integration/loop/test_ce_agent_loop_equivalence.py` | New integration test |

## Constraints

- Zero behavioral change when `context_engine.enabled: false`
- Adapter method signatures match PlanManager duck-typed interface
- Executor and planner receive adapter via constructor/kwarg, not global state
- Named constants from `manager.py` — no new magic numbers
