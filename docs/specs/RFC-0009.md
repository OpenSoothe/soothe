# RFC-0009: DAG-Based Execution and Unified Concurrency

**RFC**: 0009
**Title**: DAG-Based Execution and Unified Concurrency
**Status**: Draft
**Created**: 2026-03-18
**Updated**: 2026-03-18
**Related**: RFC-0001, RFC-0002, RFC-0003, RFC-0007, RFC-0008

## Abstract

This RFC introduces DAG-based execution for both plan steps and autonomous goals, a unified concurrency hierarchy with a `ConcurrencyController`, and progressive result recording. It fixes the current broken step execution (only step[0] is tracked), activates the orphaned `ConcurrencyPolicy` data model, and enables parallel execution of independent steps/goals within configurable limits.

## Motivation

### Problem 1: Plan steps are never iterated

The planner creates multi-step plans but the runner ignores them:

- `_run_single_pass` calls `_stream_phase` exactly once, treating the entire LangGraph agent run as "step 1".
- `_post_stream` hardcodes `state.plan.steps[0].status = "completed"` and never loops.
- A 4-step plan results in "Reflected: 1/4 steps completed" -- the remaining 3 steps are discarded.

### Problem 2: ConcurrencyPolicy is orphaned

`ConcurrencyPolicy` is defined in `protocols/concurrency.py`, carried on `Plan.concurrency`, configured in `SootheConfig.execution.concurrency` and `config.yml` -- but no execution code ever reads its values. The fields `max_parallel_steps`, `max_parallel_subagents`, `max_parallel_tools`, and `step_parallelism` are dead configuration.

### Problem 3: No parallel goal execution

RFC-0007's `GoalEngine` schedules goals serially via `next_goal()`. Independent goals cannot run concurrently. The `Goal.parent_id` field exists for hierarchy but has no DAG scheduling support.

### Problem 4: No global resource accounting

If parallel goals and steps multiply, there is no protection against API rate-limit exhaustion. The system needs a circuit breaker.

### Design Goals

1. **Execute all plan steps** via a runner-driven step loop, not just step[0].
2. **Activate ConcurrencyPolicy** -- make the orphaned data model actually control execution.
3. **DAG-based scheduling** for both steps (within a plan) and goals (across plans in autonomous mode).
4. **Parallel execution** of independent steps and goals within configurable limits.
5. **Progressive recording** -- each step/goal records intermediate results immediately.
6. **Global LLM budget** -- a circuit breaker that caps total concurrent LLM calls.
7. **Backward compatible** -- 1-step plans behave identically to current single-pass.

## Concurrency Audit

### Five Uncoordinated Layers (current state)

| Layer | What | Status |
|-------|------|--------|
| L0: Pre-Stream IO | `asyncio.gather` for memory + context | Working (RFC-0008) |
| L1: Goal Scheduling | `GoalEngine.next_goal()` | Serial only |
| L2: Step Execution | `_post_stream` marks `steps[0]` | BROKEN -- other steps ignored |
| L3: Agent Turn | Single `_stream_phase` call | No step loop |
| L4: Tool/Subagent | LangGraph-native parallel `tool_calls` | Uncontrolled by Soothe |
| Data Model | `ConcurrencyPolicy` | ORPHANED -- never read |

### Concurrency Hierarchy (target state)

```
Level 0: Pre-Stream IO          -- asyncio.gather (memory + context) [unchanged]
Level 1: Goal Scheduling        -- ConcurrencyController.goal_semaphore [autonomous only]
  Level 2: Step Scheduling      -- ConcurrencyController.step_semaphore
    Level 3: Agent Turn         -- ConcurrencyController.llm_semaphore (global budget)
      Level 4a: Tool Calls      -- LangGraph-native (reserved for future middleware)
      Level 4b: Subagent Calls  -- LangGraph-native (reserved for future middleware)
```

Each level nests inside the one above. The `global_max_llm_calls` semaphore acts as a cross-level circuit breaker: even if `max_parallel_goals=3` and `max_parallel_steps=3`, total concurrent LLM calls never exceed the global limit.

## Architecture

### Step Parallelism vs Goal Parallelism

| Dimension | Step Parallelism | Goal Parallelism |
|-----------|-----------------|-----------------|
| Scope | Within a single goal's plan | Across independent goals |
| Mode | Both autonomous and non-autonomous | Autonomous mode only |
| Thread model | Parallel steps: `{tid}__step_{sid}`; sequential steps: shared main thread | Each goal: `{tid}__goal_{gid}` (isolated) |
| DAG source | `PlanStep.depends_on` (planner creates) | `Goal.depends_on` (agent/engine creates) |
| State isolation | Shared context within goal; step results feed dependents | Isolated context per goal; results merged on completion |
| Typical scale | 1-5 parallel steps | 1-3 parallel goals |
| Config knob | `max_parallel_steps`, `step_parallelism` | `max_parallel_goals` |
| Resource cost | Each step = 1 LangGraph invocation | Each goal = N step invocations |

### Autonomous vs Non-Autonomous Mode

| Dimension | Non-Autonomous | Autonomous |
|-----------|---------------|------------|
| Goal creation | Implicit single goal from user input | Explicit via GoalEngine; agent can self-create goals |
| Iteration | Single pass: pre-stream, step-loop, post-stream | Outer goal loop with reflect/revise per iteration |
| Step execution | Step DAG with parallel batches | Same StepScheduler, but per-goal per-iteration |
| Goal parallelism | N/A (single implicit goal) | Parallel via GoalDAG `ready_goals()` |
| Reflection | Post-stream reflection (informational only) | Reflection drives revision and new goal creation |
| Thread model | Single thread throughout | Parent thread + isolated child threads per goal |
| Active concurrency layers | L0 + L2 + L3 + L4 | L0 + L1 + L2 + L3 + L4 |

### Execution Flow: Non-Autonomous Mode

```
User Input
    |
    v
Pre-Stream (unchanged: thread, context, memory, policy, plan creation)
    |
    v
StepScheduler.init(plan)
    |
    v
while not scheduler.is_complete():
    |
    +-- ready = scheduler.ready_steps(limit=max_parallel_steps)
    |
    +-- if len(ready) == 1 and step_parallelism != "max":
    |       Execute on main thread (sequential, conversation continuity)
    |
    +-- else:
    |       Execute batch in parallel:
    |       asyncio.gather(*[
    |           _execute_step(step, thread_id=f"{tid}__step_{step.id}")
    |           for step in ready
    |       ])
    |
    +-- For each completed step:
    |       scheduler.mark_completed(step.id, result)
    |       Ingest StepResult into ContextProtocol
    |       Emit soothe.plan.step_completed event
    |
    +-- For each failed step:
            scheduler.mark_failed(step.id, error)
            Emit soothe.plan.step_failed event
            (dependent steps become blocked)
    |
    v
Post-Stream (reflect on ALL steps, persist)
```

### Execution Flow: Autonomous Mode

```
User Input
    |
    v
Pre-Stream (unchanged)
    |
    v
GoalEngine.create_goal(user_input)
    |
    v
while not goal_engine.is_complete() and iterations < max:
    |
    +-- ready_goals = goal_engine.ready_goals(limit=max_parallel_goals)
    |
    +-- if len(ready_goals) == 1:
    |       Execute on parent thread
    |   else:
    |       Execute batch in parallel:
    |       asyncio.gather(*[
    |           _execute_goal(goal, thread_id=f"{tid}__goal_{goal.id}")
    |           for goal in ready_goals
    |       ])
    |
    +-- For each goal:
    |       1. Create plan via PlannerProtocol
    |       2. Run StepScheduler loop (same as non-autonomous)
    |       3. Reflect on results
    |       4. If should_revise: revise plan, continue
    |       5. Else: complete goal, generate GoalReport
    |
    +-- Merge GoalReports into parent context
    +-- iterations++
    |
    v
Persist final state
```

## Components

### 1. ConcurrencyController (`core/concurrency.py`)

Central concurrency coordinator using `asyncio.Semaphore`. Created once in `SootheRunner.__init__` from `SootheConfig.execution.concurrency`.

**Interface**:

```python
class ConcurrencyController:
    def __init__(self, policy: ConcurrencyPolicy) -> None: ...

    @asynccontextmanager
    async def acquire_goal(self) -> AsyncGenerator[None, None]: ...

    @asynccontextmanager
    async def acquire_step(self) -> AsyncGenerator[None, None]: ...

    @asynccontextmanager
    async def acquire_llm_call(self) -> AsyncGenerator[None, None]: ...

    @property
    def max_parallel_steps(self) -> int: ...

    @property
    def max_parallel_goals(self) -> int: ...
```

### 2. StepScheduler (`core/step_scheduler.py`)

DAG-based step scheduler. Created per plan execution (one per goal in autonomous mode).

**Interface**:

```python
class StepScheduler:
    def __init__(self, plan: Plan) -> None: ...

    def ready_steps(self, limit: int = 0) -> list[PlanStep]: ...
    def mark_completed(self, step_id: str, result: str) -> None: ...
    def mark_failed(self, step_id: str, error: str) -> None: ...
    def is_complete(self) -> bool: ...
    def summary(self) -> dict[str, Any]: ...
```

**DAG resolution**: Topological ordering based on `PlanStep.depends_on`. `ready_steps()` returns steps whose dependencies are all `completed`. Steps with failed dependencies are marked `failed` transitively.

**Parallelism modes** (from `ConcurrencyPolicy.step_parallelism`):

- `"sequential"`: `ready_steps()` always returns at most 1 step, regardless of DAG.
- `"dependency"`: `ready_steps()` returns all steps whose deps are met, up to `limit`.
- `"max"`: Same as `"dependency"` but ignores ordering (all non-blocked steps are eligible).

### 3. Enhanced GoalEngine (`core/goal_engine.py`)

**New fields on `Goal`**:

```python
class Goal(BaseModel):
    # ... existing fields ...
    depends_on: list[str] = Field(default_factory=list)
    report: GoalReport | None = None
```

**New methods on `GoalEngine`**:

```python
async def ready_goals(self, limit: int = 1) -> list[Goal]: ...
def is_complete(self) -> bool: ...
```

`ready_goals()` returns goals whose `depends_on` are all `completed`, sorted by `(-priority, created_at)`, limited to `limit`. This replaces serial `next_goal()` for DAG scheduling. `next_goal()` is kept for backward compatibility and delegates to `ready_goals(1)`.

### 4. Updated ConcurrencyPolicy

```python
class ConcurrencyPolicy(BaseModel):
    max_parallel_goals: int = 1
    max_parallel_steps: int = 1
    max_parallel_subagents: int = 1      # Reserved for future middleware
    max_parallel_tools: int = 3          # Reserved for future middleware
    global_max_llm_calls: int = 5        # Cross-level circuit breaker
    step_parallelism: Literal["sequential", "dependency", "max"] = "dependency"
```

### 5. Result Recording Models

```python
class StepReport(BaseModel):
    step_id: str
    description: str
    status: Literal["completed", "failed", "skipped"]
    result: str
    duration_ms: int

class GoalReport(BaseModel):
    goal_id: str
    description: str
    step_reports: list[StepReport]
    summary: str
    status: Literal["completed", "failed"]
    duration_ms: int
```

### 6. Progressive Recording

After each step completion:
1. `PlanStep.result` and `PlanStep.status` updated in-place.
2. `ContextProtocol.ingest()` with `tags=["step_result", f"step:{step_id}"]` and `importance=0.85`.
3. `soothe.plan.step_completed` event emitted with result preview.
4. Dependent steps receive predecessor results as enriched context.

After each goal completion (autonomous mode):
1. `GoalReport` assembled from all step reports.
2. `ContextProtocol.ingest()` with `tags=["goal_report", f"goal:{goal_id}"]` and `importance=0.9`.
3. `soothe.goal.completed` event emitted with report summary.
4. Report merged into parent thread's context for downstream goals.

## Stream Events

### New Events

| Type | Fields | Description |
|------|--------|-------------|
| `soothe.plan.step_started` | `step_id`, `description`, `depends_on`, `batch_index` | Step execution began |
| `soothe.plan.step_completed` | `step_id`, `success`, `result_preview`, `duration_ms` | Step finished |
| `soothe.plan.step_failed` | `step_id`, `error`, `blocked_steps` | Step failed |
| `soothe.plan.batch_started` | `batch_index`, `step_ids`, `parallel_count` | Parallel step batch launched |
| `soothe.goal.batch_started` | `goal_ids`, `parallel_count` | Parallel goal batch launched (autonomous) |
| `soothe.goal.report` | `goal_id`, `step_count`, `completed`, `failed`, `summary` | Goal report (autonomous) |

### Updated Events

| Type | Change |
|------|--------|
| `soothe.plan.step_completed` (existing `index`-based) | Replaced by `step_id`-based version above |
| `soothe.iteration.started` | Add `parallel_goals` field |

## Configuration

New fields in `execution.concurrency`:

```yaml
execution:
  concurrency:
    max_parallel_goals: 1        # Max goals running simultaneously (autonomous)
    max_parallel_steps: 1        # Max plan steps running simultaneously
    max_parallel_subagents: 1    # Reserved for future middleware
    max_parallel_tools: 3        # Reserved for future middleware
    global_max_llm_calls: 5      # Cross-level circuit breaker
    step_parallelism: dependency # sequential | dependency | max
```

## Backward Compatibility

- When `max_parallel_steps=1` and `step_parallelism="sequential"`, the step loop degrades to executing one step at a time on the main thread -- functionally equivalent to the current single-pass but now iterating through all steps.
- When `max_parallel_goals=1`, autonomous mode executes goals serially, matching current behavior.
- 1-step plans (trivial/simple queries from RFC-0008) pass through the step loop with a single iteration, producing identical behavior to current single-pass.
- `autonomous=False` (default) skips the goal DAG layer entirely.

## Constraints

- No modifications to deepagents internals or the LangGraph graph.
- Step execution reuses existing `_stream_phase()` -- each step is a standard LangGraph invocation.
- Thread isolation for parallel steps/goals uses LangGraph's native `thread_id` branching.
- `max_parallel_tools` and `max_parallel_subagents` are reserved for future `ConcurrencyMiddleware` and NOT enforced in this RFC.

## Dependencies

- RFC-0001 (System Conceptual Design) -- Principles 6, 8, 10
- RFC-0002 (Core Modules Architecture Design) -- PlannerProtocol, ConcurrencyPolicy
- RFC-0003 (CLI TUI Architecture Design) -- Stream events, SootheRunner
- RFC-0007 (Autonomous Iteration Loop) -- GoalEngine, IterationRecord
- RFC-0008 (Request Processing) -- Query classification, template planning

## Related Documents

- [RFC-0001](./RFC-0001.md) - System Conceptual Design
- [RFC-0002](./RFC-0002.md) - Core Modules Architecture Design
- [RFC-0007](./RFC-0007.md) - Autonomous Iteration Loop
- [RFC-0008](./RFC-0008.md) - Request Processing Workflow
- [IG-021](../impl/021-dag-execution-unified-concurrency.md) - Implementation Guide
