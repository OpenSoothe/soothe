# IG-022: RFC-0009 Polish -- Tests, TUI DAG Visualization, and Spec Fixes

**Implements**: RFC-0009 (gap closure and polish), cross-RFC consistency
**Status**: Completed
**Created**: 2026-03-18
**Completed**: 2026-03-18

## Overview

Closes minor implementation gaps between RFC-0009 spec and code, fixes cross-RFC
consistency issues, adds comprehensive unit tests for all new DAG modules,
and enhances the TUI plan panel with DAG dependency visualization.

**Note**: Core RFC-0009 functionality (DAG execution, concurrency control, GoalReport assembly) is fully implemented. This guide addresses polish items only.

## Phase 1: RFC Consistency Fixes

### 1.1 RFC-0001

Add RFC-0009 to Related Documents.

### 1.2 RFC-0003

- Update protocol events table: replace `index`-based `step_started`/`step_completed`
  with `step_id`-based schemas; add `batch_started`, `step_failed`,
  `goal.batch_started`, `goal.report`.
- Add RFC-0009 to Related Documents.
- Note step loop in three-phase execution model.

### 1.3 RFC-0007

- Update execution flow: `next_goal()` → `ready_goals()` with parallel dispatch.
- Add `parallel_goals` to `soothe.iteration.started` event description.

### 1.4 RFC-0008

- Add RFC-0009 to Related Documents.
- Update Phase 2 to mention step loop for multi-step plans.
- Clarify reflection covers all steps.

## Phase 2: Implementation Gap Closure

### 2.1 HIGH -- GoalReport assembly (`runner.py`)

After goal completion in `_execute_autonomous_goal`, assemble `GoalReport`
from step reports, ingest into context, emit `soothe.goal.report` event,
and store on `Goal.report`.

```python
from soothe.protocols.planner import GoalReport, StepReport

step_reports = [
    StepReport(
        step_id=s.id,
        description=s.description,
        status=s.status,
        result=s.result or "",
        duration_ms=0,
    )
    for s in iter_state.plan.steps
    if s.status in ("completed", "failed")
]

completed = sum(1 for r in step_reports if r.status == "completed")
failed = sum(1 for r in step_reports if r.status == "failed")

goal_report = GoalReport(
    goal_id=goal.id,
    description=goal.description,
    step_reports=step_reports,
    summary=response_text[:500],
    status="completed" if failed == 0 else "failed",
    duration_ms=duration_ms,
)

goal.report = goal_report.model_dump_json()

if self._context:
    await self._context.ingest(
        ContextEntry(
            source="goal_report",
            content=f"[Goal {goal.id}] {goal_report.summary[:1000]}",
            tags=["goal_report", f"goal:{goal.id}"],
            importance=0.9,
        )
    )

yield _custom({
    "type": "soothe.goal.report",
    "goal_id": goal.id,
    "step_count": len(step_reports),
    "completed": completed,
    "failed": failed,
    "summary": goal_report.summary[:200],
})
```

### 2.2 MEDIUM -- `acquire_llm_call` wrap for single-step fallback

In `_run_single_pass`, wrap the direct `_stream_phase` call:

```python
async with self._concurrency.acquire_llm_call():
    async for chunk in self._stream_phase(user_input, state):
        yield chunk
```

Same in `_execute_autonomous_goal` single-step path.

### 2.3 MEDIUM -- Missing event fields

- `soothe.plan.step_started`: add `batch_index` parameter
- `soothe.plan.step_failed`: add `blocked_steps` (steps with failed dep)
- `soothe.iteration.started`: add `parallel_goals` count

### 2.4 LOW -- `depends_on` in `soothe.plan.created`

Add `depends_on` to step dict in plan created events:

```python
{"id": s.id, "description": s.description, "status": s.status, "depends_on": s.depends_on}
```

### 2.5 LOW -- `ConcurrencyController.available_*`

Remove from RFC-0009 spec (semaphores don't cleanly expose available count
in async context). Keep the properties that exist (`max_parallel_*`).

## Phase 3: TUI DAG Visualization

### 3.1 `render_plan_tree()` dependency annotations

Extend `tui_shared.py:render_plan_tree()`:

```python
def render_plan_tree(plan: Plan, title: str | None = None) -> Tree:
    label = title or f"Plan: {plan.goal}"
    tree = Tree(Text(label, style="bold cyan"))
    for step in plan.steps:
        marker, style = _STATUS_MARKERS.get(step.status, ("[ ]", "dim"))
        step_style = {"in_progress": "yellow", "completed": "green"}.get(step.status, "dim")
        parts: list[Text | str] = [Text(marker, style=style), " ", Text(step.description, style=step_style)]
        if step.depends_on:
            dep_str = ", ".join(step.depends_on)
            parts.append(Text(f"  (< {dep_str})", style="dim italic"))
        tree.add(Text.assemble(*parts))
    return tree
```

### 3.2 Pass `depends_on` in PlanStep reconstruction

In `_handle_protocol_event` for `soothe.plan.created`:

```python
PlanStep(
    id=s.get("id", str(i)),
    description=s.get("description", ""),
    status=s.get("status", "pending"),
    depends_on=s.get("depends_on", []),
)
```

### 3.3 DAG snapshot event for logs

Emit `soothe.plan.dag_snapshot` after StepScheduler init in `_run_step_loop`:

```python
batches = []
temp_scheduler = StepScheduler(plan)
while not temp_scheduler.is_complete():
    ready = temp_scheduler.ready_steps(limit=0, parallelism="dependency")
    if not ready:
        break
    batches.append([s.id for s in ready])
    for s in ready:
        temp_scheduler.mark_completed(s.id, "")

yield _custom({
    "type": "soothe.plan.dag_snapshot",
    "steps": [{"id": s.id, "depends_on": s.depends_on} for s in plan.steps],
    "batches": batches,
})
```

## Phase 4: Tests

### 4.1 `test_step_scheduler.py` (15 tests)

Covers: init, cycle detection, ready_steps with modes, mark_completed/failed,
failure propagation, is_complete, get_dependency_results, summary, parallel batch.

### 4.2 `test_concurrency.py` (10 tests)

Covers: init, acquire/release, semaphore blocking at limit, concurrent slots,
properties, global LLM budget.

### 4.3 `test_goal_engine.py` extensions (12 tests)

Covers: ready_goals (empty, no deps, waits, limit, priority, activation),
is_complete (empty, terminal, pending), next_goal delegation, depends_on default,
report field.

### 4.4 `test_plan_models.py` (8 tests)

Covers: StepReport creation/status, GoalReport creation/nesting,
PlanStep.depends_on, serialization round-trip.

### 4.5 `test_progress_rendering.py` extensions (8 tests)

Covers: batch_started, step_started by id, step_completed by id,
step_failed, goal_batch_started, _set_plan_step_status_by_id,
render_plan_tree with depends_on.

## Phase 5: Lint and Verify

Run `make lint`, fix any issues. Run `pytest` on new tests.
