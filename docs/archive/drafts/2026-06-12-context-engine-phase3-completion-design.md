# Context Engine Phase 3 Completion Design

## 1. Purpose

Complete the StrangeLoop integration of ContextEngine (RFC-624 Phase 3) by wiring the ledger adapter into all message-writing call sites, fixing behavioral gaps in existing adapters, and adding integration tests that prove 100% behavioral equivalence with the non-CE path.

The adapters and StrangeLoop wiring were implemented in a prior session. The remaining work is making the dual-write strategy functional and verifying equivalence.

## 2. Scope

### In scope

- Wire `ContextEngineLedgerAdapter.record_message()` into the 5 call sites that append to `loop_messages`
- Fix adapter behavioral gaps: named constants, logging parity, `__new__()` hack
- Add integration test for behavioral equivalence

### Out of scope

- Protocol extraction (PlanManagerProtocol, GoalContextManagerProtocol) — deferred
- `get_plan_context()` wiring — method is unused in current orchestrator
- Changes to LangGraph topology, LoopState schemas, or PromptBuilder
- Postgres-backed CE persistence

## 3. Ledger Adapter Wiring

### 3.1 Helper Function

Add `_record_ledger_message()` to `soothe/sloop/utils/messages.py`:

```python
def _record_ledger_message(
    ctx: LoopRuntimeContext,
    msg: Any,
    phase: str,
    loop_messages: list[Any],
) -> None:
    """Append a message to loop_messages, mirroring to CE LedgerManager when enabled."""
    if ctx.ce_ledger_adapter is not None:
        ctx.ce_ledger_adapter.record_message(msg, phase, loop_messages)
    else:
        loop_messages.append(msg)
```

When `ce_ledger_adapter` is None (CE disabled), behavior is identical to the current `loop_messages.append(msg)`. When enabled, the adapter handles the dual-write: append to `loop_messages` AND record in `LedgerManager` with the phase tag.

### 3.2 Call Sites

Five locations need wiring. Each replaces `state.loop_messages.append(msg)` with `_record_ledger_message(ctx, msg, phase, state.loop_messages)`.

| File | Lines | Phase Tag | Description |
|------|-------|-----------|-------------|
| `executor.py` | ~1775-1836 | `"execute_step"` | Step execution Human+AI message pairs (success and failure) |
| `planner.py` | ~1159-1160 | `"plan_assess"` | Plan assess Human+AI pair |
| `planner.py` | ~1328-1329 | `"plan_generate"` | Plan generate Human+AI pair |
| `execute_steps.py` | ~142-143 | `"execute_step"` | Ask-user clarification Q&A |
| `goal_completion.py` | ~57, 67 | `"goal_completion"` | Goal completion Human+AI pair |

Each call site needs access to `ctx: LoopRuntimeContext`. The executor already receives `ctx`; the planner is called from graph nodes that have `ctx`. The `execute_steps.py` and `goal_completion.py` nodes already have `ctx` in scope.

### 3.3 Context Passing for Planner

The planner (`planner.py`) methods `assess_status()` and `generate_from_assessment()` do NOT receive `ctx: LoopRuntimeContext` — they receive `state: LoopState`. They append directly to `state.loop_messages`. To wire the ledger adapter through these methods, the adapter reference needs to reach them.

**Approach**: Pass `ce_ledger_adapter` as an optional keyword argument to `assess_status()` and `generate_from_assessment()`, following the same pattern as the existing `plan_manager` kwarg. The orchestrator nodes (`plan_assess.py`, `plan_generate.py`) already have `ctx` and will pass `ctx.ce_ledger_adapter`.

```python
# In planner.py:
async def assess_status(self, goal, state, context, *, ce_ledger_adapter=None):
    ...
    if ce_ledger_adapter is not None:
        ce_ledger_adapter.record_message(recorded_human, "plan_assess", state.loop_messages)
        ce_ledger_adapter.record_message(ai_msg, "plan_assess", state.loop_messages)
    else:
        state.loop_messages.append(recorded_human)
        state.loop_messages.append(ai_msg)
```

The helper `_record_ledger_message` is still used in the other 3 call sites (executor, execute_steps, goal_completion) where `ctx` is directly available. For the planner, the adapter is passed explicitly since the planner shouldn't depend on `LoopRuntimeContext`.

## 4. Adapter Behavioral Fixes

### 4.1 Named Constants

Import the existing constants from `manager.py` in `context_adapters.py`:

```python
from soothe.sloop.planning.manager import (
    _LOW_SUCCESS_RATE_THRESHOLD,
    _DAG_DEPENDENCY_THRESHOLD,
    _SIMPLE_DAG_LEDGER_DIRECT_MAX_STEPS,
)
```

Replace all hardcoded values:
- `0.6` → `_LOW_SUCCESS_RATE_THRESHOLD` (in `_heuristic_requires_goal_completion` and `_dag_requires_synthesis`)
- `3` → `_DAG_DEPENDENCY_THRESHOLD` (in both heuristics)
- `2` → `_SIMPLE_DAG_LEDGER_DIRECT_MAX_STEPS` (in `_is_simple_execution`)

These are module-level constants with no runtime state dependency.

### 4.2 Logging Parity

Add `logger.debug`/`logger.info` calls to `ContextEnginePlanAdapter` methods matching PlanManager's logging. Use `"CEPlanAdapter:"` prefix to distinguish CE-path logs. Key methods needing logging:

- `ingest_plan()`: debug log for step count and goal ID (already partially present)
- `determine_goal_completion_needs()`: debug log for mode and decision
- `_heuristic_requires_goal_completion()`: info log for each heuristic branch triggered
- `_dag_requires_synthesis()`: info log for each synthesis trigger
- `_is_simple_execution()`: debug log for the result

### 4.3 Fix `__new__()` Hack

Extract the briefing formatting logic from `GoalContextManager._format_execute_briefing()` into a standalone function in `goal_context_manager.py`:

```python
def format_execute_briefing_from_goals(
    previous_goals: list,
    current_thread_id: str,
) -> str | None:
    """Format execute briefing from completed goal records."""
    # ... extracted logic from _format_execute_briefing
```

Then:
- `GoalContextManager.get_execute_briefing()` calls `format_execute_briefing_from_goals()` instead of `self._format_execute_briefing()`
- `ContextEngineGoalContextAdapter.get_execute_briefing()` calls `format_execute_briefing_from_goals()` directly, eliminating the `__new__()` hack

The `_format_execute_briefing` method on `GoalContextManager` becomes a thin wrapper calling the standalone function.

## 5. Integration Test

### 5.1 Test Strategy

A parameterized test that runs the same StrangeLoop scenario with CE enabled and disabled, then compares observable outputs.

### 5.2 Test Location

`packages/soothe/tests/integration/loop/test_ce_strange_loop_equivalence.py`

### 5.3 Test Design

```python
@pytest.mark.parametrize("ce_enabled", [True, False])
async def test_plan_execute_complete_equivalence(ce_enabled):
    """Run a single plan→execute→complete cycle with and without CE.
    Assert identical observable outputs."""
    config = make_config(context_engine_enabled=ce_enabled)
    strange_loop = StrangeLoop(core_agent=mock_core, loop_planner=mock_planner, config=config)

    result = await strange_loop.run(goal="Test goal", thread_id="test-thread")

    # Collect results for comparison
    # ... verify plan_result, loop_messages content, DAG report
```

The test mocks:
- **LLM planner**: Returns a deterministic 2-step plan, then a completion decision
- **CoreAgent**: Returns known step results (success for step 1, success for step 2)
- **StateManager**: Uses in-memory checkpoint

The test asserts:
- `PlanResult.status` matches
- `LoopState.loop_messages` have the same message types and content
- `format_completion_dag_report()` produces equivalent output
- `determine_completion_strategy()` returns the same strategy

### 5.4 Equivalence Verification

A companion test runs both paths and does a structural diff:

```python
async def test_ce_non_ce_output_equivalence():
    """Run both paths and diff observable outputs."""
    result_ce = await run_with_ce(enabled=True)
    result_no_ce = await run_with_ce(enabled=False)

    assert result_ce.status == result_no_ce.status
    assert len(result_ce.loop_messages) == len(result_no_ce.loop_messages)
    assert result_ce.completion_strategy == result_no_ce.completion_strategy
```

## 6. Files Changed

| File | Change Type | Description |
|------|-------------|-------------|
| `foundation/sloop/utils/messages.py` | Add | `_record_ledger_message()` helper |
| `foundation/sloop/engine/executor.py` | Modify | Replace `loop_messages.append` with `_record_ledger_message` (2 pairs) |
| `foundation/sloop/planning/planner.py` | Modify | Replace `loop_messages.append` with `_record_ledger_message` (2 pairs) |
| `foundation/sloop/nodes/execute_steps.py` | Modify | Replace append with `_record_ledger_message` (1 pair) |
| `foundation/sloop/nodes/goal_completion.py` | Modify | Replace append with `_record_ledger_message` (1 pair) |
| `foundation/sloop/engine/context_adapters.py` | Modify | Add named constants, logging, remove `__new__()` hack |
| `foundation/sloop/engine/goal_context_manager.py` | Modify | Extract `format_execute_briefing_from_goals()` |
| `tests/integration/loop/test_ce_strange_loop_equivalence.py` | Add | Integration test for behavioral equivalence |

## 7. Risk and Mitigations

| Risk | Mitigation |
|------|------------|
| Adding `ce_ledger_adapter` kwarg to planner methods changes signature | Follows existing `plan_manager` kwarg pattern. Planner is internal API. Update callers in orchestrator nodes. |
| `_record_ledger_message` adds a branch to hot path (every message) | Branch is a simple `is not None` check; negligible overhead |
| Extracting `_format_execute_briefing` could break existing GoalContextManager behavior | Standalone function has identical logic; existing tests cover it |
| Integration test may be flaky due to async timing | Use deterministic mocks, no real LLM calls |
