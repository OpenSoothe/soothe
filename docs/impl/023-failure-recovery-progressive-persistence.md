# IG-023: Failure Recovery and Progressive Persistence

**Implements**: RFC-0010
**Status**: Draft
**Created**: 2026-03-18

## Overview

Implements progressive checkpointing after each step/goal, crash recovery
via `load_state` + `restore_from_snapshot`, daemon restart detection of
incomplete threads, cross-validated final report synthesis, and enhanced
reflection with dependency awareness.

## Current State Analysis

### What Exists But Is Unused

```python
# DurabilityProtocol -- load_state exists, never called by runner
async def load_state(self, thread_id: str) -> Any | None: ...

# GoalEngine -- restore exists, never called
def restore_from_snapshot(self, data: list[dict[str, Any]]) -> None: ...
```

### What Is Lost on Crash

- Plan / PlanStep / StepScheduler state (memory only)
- GoalEngine goals, DAG, status (saved at end, never restored)
- Iteration progress (autonomous mode)
- Current step results (in_progress step)

### What Survives

- Thread metadata (DurabilityProtocol)
- Context ledger (context.persist/restore)
- LangGraph checkpoints (PostgreSQL backend)
- Memory items (MemoryProtocol backend)

## Phase 1: CheckpointEnvelope and Progressive Saves

### 1.1 Create `CheckpointEnvelope` in `protocols/planner.py`

```python
class CheckpointEnvelope(BaseModel):
    """Progressive checkpoint for crash recovery (RFC-0010).

    Stored via DurabilityProtocol.save_state after each step and goal
    completion.  Loaded via load_state on thread resume.

    Args:
        version: Schema version for forward compatibility.
        timestamp: ISO-8601 checkpoint time.
        mode: Execution mode when checkpoint was created.
        last_query: The user's original query.
        thread_id: Thread identifier.
        goals: GoalEngine snapshot (autonomous mode).
        active_goal_id: Currently executing goal.
        plan: Serialized Plan for the active goal.
        completed_step_ids: Steps already completed in the active plan.
        total_iterations: Iteration counter (autonomous mode).
        status: Whether execution is still in progress.
    """

    version: int = 1
    timestamp: str = ""
    mode: Literal["single_pass", "autonomous"] = "single_pass"
    last_query: str = ""
    thread_id: str = ""
    goals: list[dict[str, Any]] = Field(default_factory=list)
    active_goal_id: str | None = None
    plan: dict[str, Any] | None = None
    completed_step_ids: list[str] = Field(default_factory=list)
    total_iterations: int = 0
    status: Literal["in_progress", "completed", "failed"] = "in_progress"
```

### 1.2 Add `_save_checkpoint()` helper to `runner.py`

```python
async def _save_checkpoint(
    self,
    state: RunnerState,
    *,
    user_input: str,
    mode: str = "single_pass",
    status: str = "in_progress",
) -> None:
    """Save progressive checkpoint for crash recovery (RFC-0010)."""
    from datetime import UTC, datetime

    plan_data = state.plan.model_dump(mode="json") if state.plan else None
    completed = [
        s.id for s in (state.plan.steps if state.plan else [])
        if s.status == "completed"
    ]
    goals_data = self._goal_engine.snapshot() if self._goal_engine else []

    envelope = {
        "version": 1,
        "timestamp": datetime.now(UTC).isoformat(),
        "mode": mode,
        "last_query": user_input,
        "thread_id": state.thread_id,
        "goals": goals_data,
        "active_goal_id": None,
        "plan": plan_data,
        "completed_step_ids": completed,
        "total_iterations": 0,
        "status": status,
    }

    try:
        await self._durability.save_state(state.thread_id, envelope)
    except Exception:
        logger.debug("Checkpoint save failed", exc_info=True)
```

### 1.3 Insert checkpoints in `_run_step_loop`

After each step completion (both sequential and parallel paths):

```python
# After scheduler.mark_completed or mark_failed:
await self._save_checkpoint(state, user_input=goal_description, mode="single_pass")
```

### 1.4 Insert checkpoints in `_execute_autonomous_goal`

After each goal completes or fails:

```python
# After goal_engine.complete_goal or fail_goal:
await self._save_checkpoint(
    parent_state, user_input=user_input, mode="autonomous"
)
```

### 1.5 Mark completed at end

```python
# At end of _run_single_pass and _run_autonomous:
await self._save_checkpoint(state, user_input=user_input, status="completed")
```

## Phase 2: Recovery on Resume

### 2.1 Add `_try_recover_checkpoint()` to `runner.py`

```python
async def _try_recover_checkpoint(
    self, state: RunnerState
) -> bool:
    """Attempt to restore from a progressive checkpoint (RFC-0010).

    Returns True if recovery occurred and step loop should skip
    completed steps.
    """
    try:
        loaded = await self._durability.load_state(state.thread_id)
    except Exception:
        logger.debug("load_state failed", exc_info=True)
        return False

    if not loaded or not isinstance(loaded, dict):
        return False

    if loaded.get("status") != "in_progress":
        return False

    version = loaded.get("version", 0)
    if version < 1:
        return False

    # Restore GoalEngine
    goals_data = loaded.get("goals", [])
    if goals_data and self._goal_engine:
        self._goal_engine.restore_from_snapshot(goals_data)
        logger.info(
            "Recovered %d goals from checkpoint", len(goals_data)
        )

    # Restore Plan with completed step status
    plan_data = loaded.get("plan")
    completed_ids = set(loaded.get("completed_step_ids", []))
    if plan_data:
        plan = Plan.model_validate(plan_data)
        for step in plan.steps:
            if step.id in completed_ids:
                step.status = "completed"
        state.plan = plan
        self._current_plan = plan
        logger.info(
            "Recovered plan: %d/%d steps completed",
            len(completed_ids), len(plan.steps),
        )

    yield _custom({
        "type": "soothe.recovery.resumed",
        "thread_id": state.thread_id,
        "completed_steps": list(completed_ids),
        "completed_goals": [
            g["id"] for g in goals_data
            if g.get("status") == "completed"
        ],
        "mode": loaded.get("mode", "single_pass"),
    })

    return True
```

### 2.2 Call in `_pre_stream`

After `context.restore()` and before plan creation:

```python
# In _pre_stream, after context restore:
recovered = await self._try_recover_checkpoint(state)
if recovered and state.plan:
    # Skip plan creation -- plan is already restored
    yield _custom({
        "type": "soothe.plan.created",
        "goal": state.plan.goal,
        "steps": [...],  # with recovered statuses
    })
```

### 2.3 StepScheduler handles pre-completed steps

`StepScheduler` already works correctly with pre-completed steps:
`ready_steps()` checks `step.status != "pending"` and skips completed
steps.  `is_complete()` returns True when all are terminal.

No changes needed to `StepScheduler`.

## Phase 3: Daemon Restart Detection

### 3.1 Add `_detect_incomplete_threads()` to daemon

```python
async def _detect_incomplete_threads(self) -> list[dict[str, Any]]:
    """Detect threads left in_progress from a previous daemon run."""
    incomplete = []
    try:
        threads = await self._runner._durability.list_threads(
            ThreadFilter(status="active")
        )
        for t in threads:
            loaded = await self._runner._durability.load_state(t.id)
            if loaded and isinstance(loaded, dict):
                if loaded.get("status") == "in_progress":
                    incomplete.append({
                        "thread_id": t.id,
                        "query": loaded.get("last_query", ""),
                        "mode": loaded.get("mode", ""),
                        "completed_steps": loaded.get("completed_step_ids", []),
                        "goals": len(loaded.get("goals", [])),
                    })
    except Exception:
        logger.debug("Incomplete thread detection failed", exc_info=True)
    return incomplete
```

### 3.2 Log on startup

```python
# In daemon start:
incomplete = await self._detect_incomplete_threads()
if incomplete:
    logger.info(
        "Found %d incomplete threads from previous run", len(incomplete)
    )
    for t in incomplete:
        logger.info(
            "  Thread %s: %s (%d steps done)",
            t["thread_id"], t["query"][:60], len(t["completed_steps"]),
        )
```

## Phase 4: Cross-Validated Final Report

### 4.1 Add `_synthesize_root_goal_report()` to runner

```python
async def _synthesize_root_goal_report(
    self,
    goal: Goal,
    step_reports: list[StepReport],
    child_goal_reports: list[GoalReport],
) -> str:
    """Generate a cross-validated summary for the root goal (RFC-0010).

    Uses an LLM call to synthesize findings from all steps and child
    goals, cross-checking for contradictions and gaps.
    """
    parts = [f"Goal: {goal.description}\n"]

    if step_reports:
        parts.append("Step results:")
        for r in step_reports:
            status_icon = "+" if r.status == "completed" else "x"
            parts.append(
                f"  [{status_icon}] {r.step_id}: {r.description}\n"
                f"      Result: {r.result[:400]}"
            )

    if child_goal_reports:
        parts.append("\nChild goal reports:")
        for cr in child_goal_reports:
            parts.append(
                f"  Goal {cr.goal_id}: {cr.description}\n"
                f"    Status: {cr.status}, Steps: {len(cr.step_reports)}\n"
                f"    Summary: {cr.summary[:300]}"
            )

    synthesis_prompt = "\n".join(parts) + """

Based on the above results, produce a brief synthesis (3-5 sentences):
1. Summarize what was accomplished across all steps/goals.
2. Cross-validate: note any contradictions or conflicting information.
3. Identify gaps: what information is missing or incomplete?
4. State confidence level: high/medium/low based on source agreement.
"""

    try:
        if self._planner and hasattr(self._planner, "_invoke"):
            summary = await self._planner._invoke(synthesis_prompt)
            return summary[:2000]
    except Exception:
        logger.debug("LLM synthesis failed, using heuristic", exc_info=True)

    # Heuristic fallback
    completed = [r for r in step_reports if r.status == "completed"]
    failed = [r for r in step_reports if r.status == "failed"]
    lines = [
        f"Completed {len(completed)}/{len(step_reports)} steps.",
    ]
    if failed:
        lines.append(f"Failed: {', '.join(r.step_id for r in failed)}.")
    if completed:
        lines.append("Results: " + "; ".join(
            f"{r.description[:50]}" for r in completed[:5]
        ))
    return " ".join(lines)
```

### 4.2 Use in GoalReport assembly

Replace `summary=response_text[:500]` with synthesized summary:

```python
# In _execute_autonomous_goal, after step loop:
if iter_state.plan:
    sr_list = [...]  # existing step report assembly

    # Collect child goal reports for cross-validation
    child_reports = []
    if self._goal_engine:
        for dep_id in goal.depends_on:
            dep_goal = self._goal_engine.get_goal(dep_id)
            if dep_goal and dep_goal.report:
                child_reports.append(dep_goal.report)

    # Synthesize with cross-validation
    summary = await self._synthesize_root_goal_report(
        goal, sr_list, child_reports
    )

    goal_report = GoalReport(
        goal_id=goal.id,
        description=goal.description,
        step_reports=sr_list,
        summary=summary,
        status=...,
        duration_ms=...,
        reflection_assessment=reflection.assessment if reflection else "",
        cross_validation_notes="",
    )
```

## Phase 5: Enhanced Reflection

### 5.1 Update `Reflection` model

```python
class Reflection(BaseModel):
    assessment: str
    should_revise: bool
    feedback: str
    blocked_steps: list[str] = Field(default_factory=list)
    failed_details: dict[str, str] = Field(default_factory=dict)
```

### 5.2 Enhance `reflect()` in planners

All planners (Direct, Claude, Subagent) share the same `reflect()` logic.
Enhance it:

```python
async def reflect(self, plan: Plan, step_results: list[StepResult]) -> Reflection:
    completed = sum(1 for r in step_results if r.success)
    failed_list = [r for r in step_results if not r.success]
    total = len(plan.steps)

    # Identify blocked vs directly failed
    failed_ids = {r.step_id for r in failed_list}
    blocked = []
    direct_failed = []
    for r in failed_list:
        step = next((s for s in plan.steps if s.id == r.step_id), None)
        if step and any(dep in failed_ids for dep in step.depends_on):
            blocked.append(r.step_id)
        else:
            direct_failed.append(r.step_id)

    # Build rich feedback
    failed_details = {}
    for r in failed_list:
        failed_details[r.step_id] = r.output[:200] if r.output else "no output"

    if failed_list:
        parts = [f"{completed}/{total} steps completed, {len(failed_list)} failed"]
        if direct_failed:
            parts.append(f"Directly failed: {direct_failed}")
        if blocked:
            parts.append(f"Blocked by dependencies: {blocked}")
        return Reflection(
            assessment=". ".join(parts),
            should_revise=True,
            feedback=f"Failed steps: {direct_failed}. Blocked: {blocked}.",
            blocked_steps=blocked,
            failed_details=failed_details,
        )

    return Reflection(
        assessment=f"{completed}/{total} steps completed successfully",
        should_revise=False,
        feedback="",
    )
```

## Phase 6: Model Updates

### 6.1 `StepReport` -- add `depends_on`

```python
class StepReport(BaseModel):
    step_id: str
    description: str
    status: Literal["completed", "failed", "skipped"]
    result: str = ""
    duration_ms: int = 0
    depends_on: list[str] = Field(default_factory=list)
```

### 6.2 `GoalReport` -- add reflection and cross-validation

```python
class GoalReport(BaseModel):
    goal_id: str
    description: str
    step_reports: list[StepReport] = Field(default_factory=list)
    summary: str = ""
    status: Literal["completed", "failed"] = "completed"
    duration_ms: int = 0
    reflection_assessment: str = ""
    cross_validation_notes: str = ""
```

## Testing Checklist

- [ ] Checkpoint saved after each step completion
- [ ] Checkpoint saved after each goal completion (autonomous)
- [ ] Checkpoint marked `completed` at end of run
- [ ] `load_state` restores plan with completed step statuses
- [ ] `restore_from_snapshot` restores goal DAG
- [ ] StepScheduler skips pre-completed steps
- [ ] Daemon detects incomplete threads on startup
- [ ] Cross-validated summary uses LLM when available
- [ ] Heuristic fallback produces reasonable summary
- [ ] Enhanced reflection distinguishes blocked vs failed steps
- [ ] New model fields serialize/deserialize correctly
- [ ] Backward compat: old checkpoint format (no version) handled gracefully

## Files to Modify

| File | Changes |
|------|---------|
| `protocols/planner.py` | `CheckpointEnvelope`, `StepReport.depends_on`, `GoalReport.reflection_assessment`+`cross_validation_notes`, `Reflection.blocked_steps`+`failed_details` |
| `core/runner.py` | `_save_checkpoint()`, `_try_recover_checkpoint()`, `_synthesize_root_goal_report()`, checkpoint calls in step/goal loops, recovery call in `_pre_stream` |
| `cli/daemon.py` | `_detect_incomplete_threads()`, startup logging |
| `backends/planning/direct.py` | Enhanced `reflect()` |
| `backends/planning/claude.py` | Enhanced `reflect()` |
| `backends/planning/subagent.py` | Enhanced `reflect()` |
| `config.py` | `RecoveryConfig` with `progressive_checkpoints` and `auto_resume_on_start` |
| `config/config.yml` | `execution.recovery` section |
| Tests | New tests for checkpoint save/load, recovery flow, model fields |
