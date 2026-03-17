# IG-021: DAG-Based Execution and Unified Concurrency

**Implements**: RFC-0009
**Status**: In Progress
**Created**: 2026-03-18

## Overview

This guide implements DAG-based step/goal execution, the ConcurrencyController, and progressive result recording. The implementation is ordered to minimize breakage: protocol models first, then new modules, then runner refactor, then UI.

## Phase 1: Protocol and Data Model Updates

### 1.1 Update `protocols/concurrency.py`

Add `max_parallel_goals` and `global_max_llm_calls`:

```python
class ConcurrencyPolicy(BaseModel):
    max_parallel_goals: int = 1
    max_parallel_steps: int = 1
    max_parallel_subagents: int = 1
    max_parallel_tools: int = 3
    global_max_llm_calls: int = 5
    step_parallelism: Literal["sequential", "dependency", "max"] = "dependency"
```

### 1.2 Update `protocols/planner.py`

Add `StepReport` and `GoalReport` models:

```python
class StepReport(BaseModel):
    """Report from a single executed step.

    Args:
        step_id: The step that was executed.
        description: Step description.
        status: Final step status.
        result: Output text (truncated).
        duration_ms: Execution time in milliseconds.
    """

    step_id: str
    description: str
    status: Literal["completed", "failed", "skipped"]
    result: str
    duration_ms: int = 0


class GoalReport(BaseModel):
    """Aggregate report from a completed goal.

    Args:
        goal_id: Goal identifier.
        description: Goal description.
        step_reports: Reports from all steps.
        summary: LLM-generated summary of results.
        status: Final goal status.
        duration_ms: Total execution time.
    """

    goal_id: str
    description: str
    step_reports: list[StepReport] = Field(default_factory=list)
    summary: str = ""
    status: Literal["completed", "failed"] = "completed"
    duration_ms: int = 0
```

Update `protocols/__init__.py` to export `StepReport`, `GoalReport`.

### 1.3 Update `config.py` and `config.yml`

In `config.yml`, add:

```yaml
execution:
  concurrency:
    max_parallel_goals: 1
    max_parallel_steps: 1
    max_parallel_subagents: 1
    max_parallel_tools: 3
    global_max_llm_calls: 5
    step_parallelism: dependency
```

`config.py` needs no changes -- `ExecutionConfig.concurrency` is already `ConcurrencyPolicy`, which picks up the new fields automatically via Pydantic.

## Phase 2: New Modules

### 2.1 Create `core/concurrency.py`

```python
"""ConcurrencyController -- hierarchical concurrency enforcement (RFC-0009)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncGenerator

if TYPE_CHECKING:
    from soothe.protocols.concurrency import ConcurrencyPolicy

logger = logging.getLogger(__name__)


class ConcurrencyController:
    """Hierarchical concurrency enforcement via semaphores.

    Controls parallel execution at three levels:
    - Goal level (autonomous mode)
    - Step level (within a goal's plan)
    - LLM call level (global circuit breaker)

    Args:
        policy: Concurrency limits configuration.
    """

    def __init__(self, policy: ConcurrencyPolicy) -> None:
        self._policy = policy
        self._goal_sem = asyncio.Semaphore(policy.max_parallel_goals)
        self._step_sem = asyncio.Semaphore(policy.max_parallel_steps)
        self._llm_sem = asyncio.Semaphore(policy.global_max_llm_calls)

    @asynccontextmanager
    async def acquire_goal(self) -> AsyncGenerator[None, None]:
        """Acquire a goal execution slot."""
        async with self._goal_sem:
            yield

    @asynccontextmanager
    async def acquire_step(self) -> AsyncGenerator[None, None]:
        """Acquire a step execution slot."""
        async with self._step_sem:
            yield

    @asynccontextmanager
    async def acquire_llm_call(self) -> AsyncGenerator[None, None]:
        """Acquire a global LLM call slot (circuit breaker)."""
        async with self._llm_sem:
            yield

    @property
    def policy(self) -> ConcurrencyPolicy:
        """The active concurrency policy."""
        return self._policy

    @property
    def step_parallelism(self) -> str:
        """The step parallelism mode."""
        return self._policy.step_parallelism

    @property
    def max_parallel_steps(self) -> int:
        """Maximum parallel steps allowed."""
        return self._policy.max_parallel_steps

    @property
    def max_parallel_goals(self) -> int:
        """Maximum parallel goals allowed."""
        return self._policy.max_parallel_goals
```

### 2.2 Create `core/step_scheduler.py`

```python
"""StepScheduler -- DAG-based plan step scheduling (RFC-0009)."""

from __future__ import annotations

import logging
from typing import Any

from soothe.protocols.planner import Plan, PlanStep

logger = logging.getLogger(__name__)


class StepScheduler:
    """DAG-based step scheduler for a single plan.

    Resolves step dependencies and provides ready steps
    for parallel execution within concurrency limits.

    Args:
        plan: The plan whose steps to schedule.
    """

    def __init__(self, plan: Plan) -> None:
        self._plan = plan
        self._step_map: dict[str, PlanStep] = {s.id: s for s in plan.steps}
        self._validate_dag()

    def _validate_dag(self) -> None:
        """Validate no cycles exist in step dependencies."""
        visited: set[str] = set()
        in_stack: set[str] = set()

        def _dfs(sid: str) -> None:
            if sid in in_stack:
                msg = f"Cycle detected in step dependencies involving {sid}"
                raise ValueError(msg)
            if sid in visited:
                return
            in_stack.add(sid)
            step = self._step_map.get(sid)
            if step:
                for dep_id in step.depends_on:
                    _dfs(dep_id)
            in_stack.discard(sid)
            visited.add(sid)

        for step in self._plan.steps:
            _dfs(step.id)

    def ready_steps(self, limit: int = 0, parallelism: str = "dependency") -> list[PlanStep]:
        """Return steps whose dependencies are all completed.

        Args:
            limit: Max steps to return (0 = no limit).
            parallelism: Scheduling mode -- "sequential", "dependency", or "max".

        Returns:
            List of ready steps.
        """
        if parallelism == "sequential":
            limit = 1

        ready: list[PlanStep] = []
        for step in self._plan.steps:
            if step.status != "pending":
                continue
            if self._has_failed_dependency(step):
                step.status = "failed"
                step.result = "Blocked by failed dependency"
                logger.info("Step %s blocked by failed dependency", step.id)
                continue
            deps_met = all(
                self._step_map[dep_id].status == "completed"
                for dep_id in step.depends_on
                if dep_id in self._step_map
            )
            if deps_met:
                ready.append(step)

        if limit > 0:
            ready = ready[:limit]
        return ready

    def _has_failed_dependency(self, step: PlanStep) -> bool:
        """Check if any transitive dependency has failed."""
        for dep_id in step.depends_on:
            dep = self._step_map.get(dep_id)
            if dep and dep.status == "failed":
                return True
        return False

    def mark_completed(self, step_id: str, result: str) -> None:
        """Mark a step as completed with its result.

        Args:
            step_id: Step to mark.
            result: Step output text.
        """
        step = self._step_map.get(step_id)
        if step:
            step.status = "completed"
            step.result = result
            logger.info("Step %s completed", step_id)

    def mark_failed(self, step_id: str, error: str) -> None:
        """Mark a step as failed.

        Args:
            step_id: Step to mark.
            error: Error description.
        """
        step = self._step_map.get(step_id)
        if step:
            step.status = "failed"
            step.result = error
            logger.warning("Step %s failed: %s", step_id, error)

    def mark_in_progress(self, step_id: str) -> None:
        """Mark a step as in-progress.

        Args:
            step_id: Step to mark.
        """
        step = self._step_map.get(step_id)
        if step:
            step.status = "in_progress"

    def is_complete(self) -> bool:
        """Check if all steps are completed or failed (no pending work)."""
        return all(s.status in ("completed", "failed") for s in self._plan.steps)

    def get_dependency_results(self, step: PlanStep) -> list[tuple[str, str]]:
        """Get results from a step's completed dependencies.

        Args:
            step: Step whose dependency results to collect.

        Returns:
            List of (step_description, result) tuples.
        """
        results = []
        for dep_id in step.depends_on:
            dep = self._step_map.get(dep_id)
            if dep and dep.status == "completed" and dep.result:
                results.append((dep.description, dep.result))
        return results

    def summary(self) -> dict[str, Any]:
        """Return a summary of step statuses."""
        counts: dict[str, int] = {"pending": 0, "in_progress": 0, "completed": 0, "failed": 0}
        for step in self._plan.steps:
            counts[step.status] = counts.get(step.status, 0) + 1
        return {
            "total": len(self._plan.steps),
            **counts,
            "is_complete": self.is_complete(),
        }
```

## Phase 3: GoalEngine DAG Enhancement

### 3.1 Update `core/goal_engine.py`

Add `depends_on` to `Goal`, add `ready_goals()` and `is_complete()`:

```python
class Goal(BaseModel):
    # ... existing fields ...
    depends_on: list[str] = Field(default_factory=list)
    report: str | None = None  # JSON-serialized GoalReport


class GoalEngine:
    # ... existing methods ...

    async def ready_goals(self, limit: int = 1) -> list[Goal]:
        """Return goals whose dependencies are all completed.

        Args:
            limit: Max goals to return.

        Returns:
            List of ready goals, sorted by priority.
        """
        ready: list[Goal] = []
        for goal in self._goals.values():
            if goal.status not in ("pending", "active"):
                continue
            deps_met = all(
                self._goals.get(dep_id, Goal(description="")).status == "completed"
                for dep_id in goal.depends_on
            )
            if not deps_met:
                continue
            ready.append(goal)

        ready.sort(key=lambda g: (-g.priority, g.created_at))

        for goal in ready[:limit]:
            if goal.status == "pending":
                goal.status = "active"
                goal.updated_at = datetime.now(UTC)

        return ready[:limit]

    def is_complete(self) -> bool:
        """Check if all goals are completed or failed."""
        return all(g.status in ("completed", "failed") for g in self._goals.values())
```

Update `next_goal()` to delegate:

```python
    async def next_goal(self) -> Goal | None:
        goals = await self.ready_goals(limit=1)
        return goals[0] if goals else None
```

## Phase 4: Runner Refactor

### 4.1 Runner `__init__` changes

Add ConcurrencyController initialization:

```python
from soothe.core.concurrency import ConcurrencyController

class SootheRunner:
    def __init__(self, config: SootheConfig | None = None) -> None:
        # ... existing init ...
        self._concurrency = ConcurrencyController(self._config.execution.concurrency)
```

### 4.2 New `_execute_step()` method

```python
async def _execute_step(
    self,
    step: PlanStep,
    *,
    goal_description: str,
    dependency_results: list[tuple[str, str]],
    thread_id: str,
    state: RunnerState,
) -> AsyncGenerator[StreamChunk, None]:
    """Execute a single plan step as a LangGraph invocation."""
    from time import perf_counter

    step_start = perf_counter()

    # Build step-specific input with dependency context
    parts = [f"Goal: {goal_description}", f"Current step: {step.description}"]
    if dependency_results:
        dep_text = "\n".join(
            f"- [{desc}]: {result[:300]}" for desc, result in dependency_results
        )
        parts.append(f"Results from prior steps:\n{dep_text}")
    step_input = "\n\n".join(parts)

    yield _custom({
        "type": "soothe.plan.step_started",
        "step_id": step.id,
        "description": step.description,
        "depends_on": step.depends_on,
    })

    # Create isolated state for this step
    step_state = RunnerState()
    step_state.thread_id = thread_id

    # Memory + context for step
    if self._memory:
        try:
            items = await self._memory.recall(step.description, limit=3)
            step_state.recalled_memories = items
        except Exception:
            logger.debug("Memory recall failed for step %s", step.id, exc_info=True)

    if self._context:
        try:
            projection = await self._context.project(step.description, token_budget=3000)
            step_state.context_projection = projection
        except Exception:
            logger.debug("Context projection failed for step %s", step.id, exc_info=True)

    # Run LangGraph
    async with self._concurrency.acquire_llm_call():
        async for chunk in self._stream_phase(step_input, step_state):
            yield chunk

    response_text = "".join(step_state.full_response)
    duration_ms = int((perf_counter() - step_start) * 1000)

    # Record result
    if response_text.strip():
        step.status = "completed"
        step.result = response_text[:2000]
        yield _custom({
            "type": "soothe.plan.step_completed",
            "step_id": step.id,
            "success": True,
            "result_preview": response_text[:200],
            "duration_ms": duration_ms,
        })
    else:
        step.status = "failed"
        step.result = "No response from agent"
        yield _custom({
            "type": "soothe.plan.step_failed",
            "step_id": step.id,
            "error": "No response from agent",
        })

    # Ingest step result into context
    if self._context and step.result:
        try:
            await self._context.ingest(
                ContextEntry(
                    source="step_result",
                    content=f"[Step {step.id}: {step.description}]\n{step.result[:1500]}",
                    tags=["step_result", f"step:{step.id}"],
                    importance=0.85,
                )
            )
        except Exception:
            logger.debug("Step result ingestion failed", exc_info=True)
```

### 4.3 Refactored `_run_single_pass()` with step loop

```python
async def _run_single_pass(
    self,
    user_input: str,
    *,
    thread_id: str | None = None,
) -> AsyncGenerator[StreamChunk, None]:
    """Single-pass execution with step-loop (RFC-0009)."""
    state = RunnerState()
    state.thread_id = thread_id or self._current_thread_id or ""
    self._current_thread_id = state.thread_id or None

    # Pre-stream: thread, context, memory, policy, plan
    async for chunk in self._pre_stream(user_input, state):
        yield chunk

    # Step loop
    if state.plan and len(state.plan.steps) > 1:
        async for chunk in self._run_step_loop(
            user_input, state, state.plan
        ):
            yield chunk
    else:
        # Single step or no plan -- original behavior
        async for chunk in self._stream_phase(user_input, state):
            yield chunk

    # Post-stream
    async for chunk in self._post_stream(user_input, state):
        yield chunk


async def _run_step_loop(
    self,
    goal_description: str,
    state: RunnerState,
    plan: Plan,
) -> AsyncGenerator[StreamChunk, None]:
    """Execute plan steps respecting DAG dependencies."""
    import asyncio

    scheduler = StepScheduler(plan)
    parallelism = self._concurrency.step_parallelism
    max_steps = self._concurrency.max_parallel_steps
    batch_index = 0

    while not scheduler.is_complete():
        ready = scheduler.ready_steps(limit=max_steps, parallelism=parallelism)
        if not ready:
            logger.warning("No ready steps but scheduler not complete -- breaking")
            break

        yield _custom({
            "type": "soothe.plan.batch_started",
            "batch_index": batch_index,
            "step_ids": [s.id for s in ready],
            "parallel_count": len(ready),
        })

        for s in ready:
            scheduler.mark_in_progress(s.id)

        if len(ready) == 1:
            # Sequential: use main thread
            step = ready[0]
            dep_results = scheduler.get_dependency_results(step)
            async for chunk in self._execute_step(
                step,
                goal_description=goal_description,
                dependency_results=dep_results,
                thread_id=state.thread_id,
                state=state,
            ):
                yield chunk
            if step.status == "completed":
                scheduler.mark_completed(step.id, step.result or "")
            else:
                scheduler.mark_failed(step.id, step.result or "failed")
        else:
            # Parallel: isolated threads
            async def _run_one(s: PlanStep) -> list[StreamChunk]:
                chunks: list[StreamChunk] = []
                dep_results = scheduler.get_dependency_results(s)
                step_tid = f"{state.thread_id}__step_{s.id}"
                async with self._concurrency.acquire_step():
                    async for chunk in self._execute_step(
                        s,
                        goal_description=goal_description,
                        dependency_results=dep_results,
                        thread_id=step_tid,
                        state=state,
                    ):
                        chunks.append(chunk)
                return chunks

            results = await asyncio.gather(
                *[_run_one(s) for s in ready],
                return_exceptions=True,
            )
            for s, result in zip(ready, results):
                if isinstance(result, Exception):
                    scheduler.mark_failed(s.id, str(result))
                    yield _custom({
                        "type": "soothe.plan.step_failed",
                        "step_id": s.id,
                        "error": str(result),
                    })
                else:
                    for chunk in result:
                        yield chunk
                    if s.status == "completed":
                        scheduler.mark_completed(s.id, s.result or "")
                    else:
                        scheduler.mark_failed(s.id, s.result or "failed")

        batch_index += 1

    # Update state with final step results
    state.full_response = [
        s.result or "" for s in plan.steps if s.status == "completed"
    ]
```

### 4.4 Refactored `_run_autonomous()` with goal DAG

The key changes to `_run_autonomous`:

1. Replace `while goal := goal_engine.next_goal()` with `ready_goals = goal_engine.ready_goals(limit=max_parallel_goals)`.
2. When multiple goals are ready, execute in parallel with isolated threads.
3. Each parallel goal runs its own step loop.
4. Merge goal reports into parent context on completion.

The structure mirrors the step loop: single goal uses parent thread, parallel goals get `{tid}__goal_{gid}`.

### 4.5 Update `_post_stream()`

Remove the hardcoded `steps[0]` logic. Instead, reflect on ALL steps:

```python
# In _post_stream: replace steps[0] hardcode with full plan reflection
if self._planner and state.plan and response_text:
    try:
        step_results = [
            StepResult(
                step_id=s.id,
                output=s.result or "",
                success=s.status == "completed",
            )
            for s in state.plan.steps
            if s.status in ("completed", "failed")
        ]
        reflection = await self._planner.reflect(state.plan, step_results)
        yield _custom({
            "type": "soothe.plan.reflected",
            "should_revise": reflection.should_revise,
            "assessment": reflection.assessment[:200],
        })
    except Exception:
        logger.debug("Plan reflection failed", exc_info=True)
```

## Phase 5: TUI Rendering Updates

### 5.1 Update `cli/tui_shared.py`

Handle new events in the activity rendering:

```python
# In _handle_custom_event or equivalent:
if event_type == "soothe.plan.batch_started":
    step_ids = data.get("step_ids", [])
    parallel = data.get("parallel_count", 1)
    if parallel > 1:
        activity_text = f"Executing {parallel} steps in parallel: {', '.join(step_ids)}"
    else:
        activity_text = f"Executing step {step_ids[0]}" if step_ids else "Executing step"

elif event_type == "soothe.plan.step_started":
    step_id = data.get("step_id", "")
    desc = data.get("description", "")[:80]
    activity_text = f"Step {step_id}: {desc}"

elif event_type == "soothe.plan.step_completed":
    step_id = data.get("step_id", "")
    duration = data.get("duration_ms", 0)
    activity_text = f"Step {step_id}: done ({duration}ms)"

elif event_type == "soothe.plan.step_failed":
    step_id = data.get("step_id", "")
    error = data.get("error", "")[:80]
    activity_text = f"Step {step_id}: FAILED - {error}"
```

## Phase 6: Spec Updates

### 6.1 Update RFC-0007

Add "Superseded by RFC-0009" note for goal scheduling. Reference DAG-based goal management.

### 6.2 Update RFC-0002

Update Module 7 (ConcurrencyPolicy) with new fields. Add ConcurrencyController reference. Update Module 3 with step DAG execution note.

### 6.3 Update AGENTS.md

Add RFC-0009 to the RFC table.

## Testing Checklist

- [ ] Single-step plan (trivial query): behaves identically to current single-pass
- [ ] Multi-step plan without dependencies: steps execute sequentially when `step_parallelism="sequential"`
- [ ] Multi-step plan with dependencies: DAG respected, independent steps run in parallel
- [ ] `max_parallel_steps` limit enforced
- [ ] `global_max_llm_calls` circuit breaker works
- [ ] Autonomous mode: single goal works as before
- [ ] Autonomous mode: parallel goals with isolated threads
- [ ] Failed step blocks dependents
- [ ] Progressive recording: step results visible in context
- [ ] TUI shows step-level progress
