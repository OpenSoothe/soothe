# CE-StrangeLoop Full Integration Design

RFC-624 Phase 3d: Wire ContextEngine into StrangeLoop as a fully functional parallel path, closing all remaining gaps.

## Context

RFC-624 introduced ContextEngine as a unified context management module. Phases 1-3c are done: CE core engine, adapter hardening, projection wiring, and the planning submodule (`soothe.context.planning`). The CE currently runs as a partial sidecar — when enabled, `StepPlanManagerAdapter` replaces `PlanManager` and `ContextEngineLedgerAdapter` provides dual-write, but 5 integration gaps remain.

This design closes all gaps and makes CE the default path for new installs.

## Gap Analysis

| # | Gap | Current State | Fix |
|---|-----|---------------|-----|
| G1 | Goal lifecycle incomplete | `create_goal`/`activate_goal` at startup, but `complete_goal`/`fail_goal` never called | Close the lifecycle in goal_completion node |
| G2 | Step completion feedback missing | `StepPlanningSubengine.record_step_outcomes()` mutates DAG synchronously, but CE async APIs + callbacks never fire | Dual-path: call CE async step APIs alongside sync mutations |
| G3 | Projection never invoked | `ContextEngine.project()` builds ContextBundle but no node calls it | Call in plan_generate, inject into PromptBuilder |
| G4 | CE persistence only at goal end | `ce.save()` only in goal_completion — mid-loop crash loses state | Save after each plan ingest and step execution |
| G5 | Semantic loading unused | SemanticLoader initialized but never called | Load at loop start, inject into ContextBundle |

## Architecture: ContextEngineLifecycle

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

### Lifecycle Hooks

| Hook | Called From | CE Actions |
|------|------------|------------|
| `on_goal_start()` | strange_loop startup | `semantic.load(workspace)` |
| `on_plan_ingested(plan_result, plan_id, iteration)` | plan_assess, resolve_decision (after `ingest_plan`) | `save()` |
| `on_steps_executed(step_results)` | record_iteration (after `record_step_outcomes`) | `complete_step()`/`fail_step()` async + `save()` |
| `on_goal_complete(status, plan_result)` | goal_completion | `complete_goal()`/`fail_goal()` + `save()` |
| `get_context_bundle()` | plan_generate | `ce.project()` → ContextBundle |
| `save()` | (internal, after each mutation) | `ce.save()` to persistence backend |

### Error Handling

All lifecycle methods catch and log exceptions. CE failures never propagate to graph nodes — the plan-exec loop continues regardless. Async step APIs fire via `asyncio.create_task()` so callback errors don't block.

## Integration Points per Graph Node

### strange_loop.py (startup)

Current CE path already creates CE instance, goal, and adapters. Additions:
- Create `ContextEngineLifecycle(ce_instance, ce_goal.id)` and store on `LoopRuntimeContext`
- Call `await ce_lifecycle.on_goal_start()` after goal creation

### plan_assess.py

After `plan_manager.ingest_plan()`:
```python
if ctx.ce_lifecycle and ctx.ce_lifecycle.enabled:
    await ctx.ce_lifecycle.on_plan_ingested(plan_result, state.plan_id, state.iteration)
```

### plan_generate.py

Inject ContextBundle into prompt rendering:
```python
context_bundle = ctx.ce_lifecycle.get_context_bundle() if ctx.ce_lifecycle else None
messages = plan_phase.generate_from_assessment(..., context_bundle=context_bundle)
```

The `PromptBuilder.build_plan_messages()` already accepts `context_bundle` (wired in Phase 3b). No PromptBuilder changes needed.

### execute_steps.py

No change — step outcomes are recorded in record_iteration, not here.

### record_iteration.py

After `plan_manager.record_step_outcomes(step_results)`:
```python
if ctx.ce_lifecycle and ctx.ce_lifecycle.enabled:
    await ctx.ce_lifecycle.on_steps_executed(step_results)
```

### goal_completion.py

Replace the existing `ctx.context_engine.save()` block with:
```python
if ctx.ce_lifecycle and ctx.ce_lifecycle.enabled:
    await ctx.ce_lifecycle.on_goal_complete(status, plan_result)
```

This handles goal lifecycle (G1), persistence (G4), and is cleaner than the scattered save call.

## Step Feedback: Dual-Path Design (G2)

`on_steps_executed()` implements dual-path recording:

1. **Sync path (already done)**: `plan_manager.record_step_outcomes()` mutates the GoalStepDAG via StepPlanningSubengine — this is the source of truth for planning context and reports.
2. **Async path (new)**: For each step result, call `ce.complete_step(goal_id, step_id, execution)` or `ce.fail_step(goal_id, step_id, execution)`. These fire callbacks (on_step_completed, on_step_failed) and events. Fire via `asyncio.create_task()` to avoid blocking.

The sync path always runs first, ensuring planning context is current before any async callbacks fire.

## Projection: ContextBundle Injection (G3)

`get_context_bundle()` calls `ce.project()` with a `ProjectionConfig`:
- **Plan phase**: includes goal lineage, goal progress, step lineage, project/agent/memory instructions
- **Execute phase**: includes goal progress and step lineage only (lighter)

The `ContextBundle` is already wired into `PromptBuilder.build_plan_messages()` from Phase 3b. The injection is additive — existing context sections (PLAN_DAG_CONTEXT, USER_QUERY, PRIOR_PROGRESS) are unchanged.

## Persistence Strategy (G4)

Save CE state at three points:
1. After `on_plan_ingested()` — captures new step nodes
2. After `on_steps_executed()` — captures step outcomes
3. At `on_goal_complete()` — captures final goal status

This ensures CE state survives a crash at any point with at most one iteration of data loss.

## Semantic Loading (G5)

`on_goal_start()` calls `ce.semantic.load(workspace)` which indexes:
- `CLAUDE.md`, `AGENTS.md`, `MEMORY.md` from workspace root
- Same files from `SOOTHE_HOME` as fallback

Loaded instructions flow into `ContextBundle` via `ce.project()`. When semantic loading fails (file not found, permission error), the ContextBundle fields are empty — no injection occurs.

## Config Change

Flip default for new installs:

```yaml
agent:
  loop:
    context_engine:
      enabled: true            # was false
      persistence_backend: "file"
```

Existing config files with `enabled: false` continue to work unchanged. No migration required.

## Backward Compatibility

- **CE disabled**: `ContextEngineLifecycle(None, None)`. All methods are no-ops. `enabled` returns False. Graph node guards (`if ctx.ce_lifecycle and ctx.ce_lifecycle.enabled`) skip all CE calls. Zero behavioral change from current StrangeLoop.
- **CE enabled**: All existing prompt fragments remain identical. ContextBundle is additive only. The StepPlanningSubengine produces the same `DagPlanningContext` with the same 9 attributes. The `format_completion_dag_report()` output uses the hierarchical CE DAG format but contains equivalent information.
- **Existing tests**: All 2600+ tests continue to pass. New tests verify the CE-specific behavior.

## Files to Create/Modify

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/foundation/loop/engine/context_lifecycle.py` | **New**: ContextEngineLifecycle class |
| `packages/soothe/src/soothe/foundation/loop/orchestrator/runtime_context.py` | Add `ce_lifecycle` field |
| `packages/soothe/src/soothe/foundation/loop/engine/strange_loop.py` | Create lifecycle, call `on_goal_start()` |
| `packages/soothe/src/soothe/foundation/loop/orchestrator/nodes/plan_assess.py` | Call `on_plan_ingested()` |
| `packages/soothe/src/soothe/foundation/loop/orchestrator/nodes/plan_generate.py` | Pass `context_bundle` from lifecycle |
| `packages/soothe/src/soothe/foundation/loop/orchestrator/nodes/record_iteration.py` | Call `on_steps_executed()` |
| `packages/soothe/src/soothe/foundation/loop/orchestrator/nodes/goal_completion.py` | Replace `ce.save()` with `on_goal_complete()` |
| `packages/soothe/src/soothe/config/models.py` | Flip `enabled` default to True |
| `packages/soothe/tests/unit/core/loop/engine/test_context_lifecycle.py` | **New**: lifecycle unit tests |
| `packages/soothe/tests/integration/context/test_ce_strange_loop_equivalence.py` | Add lifecycle + goal completion tests |

## Acceptance Criteria

- All 5 gaps closed: goal lifecycle, step feedback, projection, persistence, semantics
- CE on-by-default for new installs
- CE disabled path produces zero behavioral change
- CE enabled path produces identical plan-exec outputs + additive ContextBundle
- All existing tests pass
- New tests cover ContextEngineLifecycle, goal completion, projection injection
