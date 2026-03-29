# RFC-0007: Autonomous Iteration Loop

**RFC**: 0007
**Title**: Autonomous Iteration Loop
**Status**: Accepted
**Created**: 2026-03-15
**Updated**: 2026-03-15
**Related**: RFC-0001, RFC-0002, RFC-0003

## Abstract

This RFC defines the architecture for autonomous iterative execution in Soothe. The implementation now combines the original runner-level outer loop with later DAG-aware goal scheduling, step-loop execution, checkpoint-backed recovery, and dynamic goal directives. In current Soothe, autonomous mode executes batches of ready goals, reflects on results, may revise plans or mutate the goal graph, and continues without requiring human input at each step.

## Motivation

Soothe's current execution model is single-pass: `SootheRunner.astream()` runs pre-stream, stream, post-stream, then stops. The `PlannerProtocol` already provides `reflect()` (which returns `should_revise`) and `revise_plan()`, but the runner never closes the loop. This makes Soothe unable to handle tasks that require iterative refinement -- such as simulation parameter sweeps, multi-phase research, or any workflow where results from one cycle inform the next.

RFC-0001 Principle 6 states "Plan-driven execution: complex goals decompose into plans with steps." This RFC extends that principle with iterative plan execution, where plans are revised based on reflection and new goals emerge from completed work.

### Target Use Case

Given a complex problem like "optimize a fluid simulation across a large parameter space", the agent should autonomously:

1. Design initial experiments and write simulation code
2. Run the simulation and analyze results
3. Reflect on findings and propose refined experiments
4. Execute the refined experiments
5. Repeat until the goal is achieved or a maximum iteration limit is reached

## Design Principles

### Runner outer loop, not graph modification

The iteration loop lives in `SootheRunner`, wrapping the existing deepagents LangGraph graph. The graph itself is unchanged. This respects RFC-0001 Principle 2: "Extend deepagents, don't fork it."

### Goal lifecycle is state management, not reasoning

The GoalEngine manages goal creation, scheduling, retry, and completion. It does not reason about what to do -- that remains the responsibility of the LLM agent and the PlannerProtocol. Inspired by NoeAgent's separation of GoalEngine from AgentKernel.

### Structured iteration history

Each iteration produces an `IterationRecord` stored in the context ledger. This gives the agent structured "what I've tried and what happened" memory that survives context projection into subsequent iterations.

### Graceful degradation with retry

Failed iterations retry with exponential backoff before marking a goal as failed. The agent moves to the next goal rather than crashing. This implements RFC-0001 Principle 10: "Graceful degradation -- partial results over hard failure."

## Architecture

### Execution Flow

```text
User Input
    |
    v
GoalEngine.create_goal(user_input)
    |
    v
while total_iterations < max_iterations and not GoalEngine.is_complete():
    |
    v
    ready_goals = GoalEngine.ready_goals(limit=max_parallel_goals)
    |
    +-- if multiple ready goals:
    |      execute goals in parallel batches
    |
    +-- for each executing goal:
           |
           +-- Pre-goal recall/projection
           |
           +-- PlannerProtocol.create_plan(...) if needed
           |
           +-- if plan has multiple steps:
           |      StepScheduler / step loop executes the plan DAG
           |   else:
           |      deepagents Graph Stream (unchanged)
           |
           +-- Post-goal ingest / memory store
           |
           +-- PlannerProtocol.reflect(..., goal_context)
           |
           +-- Apply goal directives if present
           |
           +-- Store IterationRecord in ContextProtocol
           |
           +-- if should_revise:
           |      PlannerProtocol.revise_plan()
           |      continue on next autonomous iteration
           |
           +-- else:
                  synthesize goal report
                  GoalEngine.complete_goal()
```

Current implementation note: autonomous execution is no longer purely serial. Goal batching, goal dependencies, step scheduling, and progressive checkpoints from later RFCs are part of the implemented runtime.

### Components

#### 1. GoalEngine (`cognition/goal_engine.py`)

Goal lifecycle manager driven synchronously by the runner.

**Current Goal Model**:
- `id`: 8-char hex identifier
- `description`: human-readable goal text
- `status`: pending | active | completed | failed
- `priority`: 0-100, higher = first
- `parent_id`: optional parent for hierarchical goals
- `depends_on`: prerequisite goal IDs for DAG scheduling
- `plan_count`: counter used for revised plan IDs
- `retry_count` / `max_retries`: retry policy
- `report`: optional structured `GoalReport`
- `created_at` / `updated_at`: timestamps

**Current GoalEngine Interface**:
- `create_goal(description, priority, parent_id)` -- create a new goal
- `next_goal()` -- backward-compatible single-goal helper
- `ready_goals(limit)` -- return dependency-satisfied goals, activating them for execution
- `complete_goal(goal_id)` -- mark goal completed
- `fail_goal(goal_id, error, allow_retry)` -- fail with optional retry/reset
- `list_goals(status)` / `get_goal(goal_id)` -- inspect goal state
- `snapshot()` / `restore_from_snapshot()` -- checkpoint-oriented persistence
- dependency helpers such as `add_dependencies()` and `validate_dependency()`

Persistence: current autonomous persistence is checkpoint-backed. The runner stores `GoalEngine.snapshot()` inside checkpoint state and restores via `restore_from_snapshot()` rather than calling RFC-0007's older `persist(thread_id)` / `restore(thread_id)` methods.

#### 2. Runner Iteration Loop (`core/runner/*`)

`SootheRunner.astream()` still accepts autonomous execution parameters:

```python
async def astream(
    self,
    user_input: str,
    *,
    thread_id: str | None = None,
    autonomous: bool = False,
    max_iterations: int = 10,
) -> AsyncGenerator[StreamChunk, None]:
```

When `autonomous=False` (default), behavior is unchanged.

When `autonomous=True`, the current runner:
1. Creates the initial root goal from `user_input`
2. Repeatedly fetches dependency-satisfied goal batches via `ready_goals(limit=max_parallel_goals)`
3. Executes one goal or a parallel batch of goals until total autonomous iterations are exhausted
4. For each goal: performs recall/projection, creates or reuses a plan, executes either a step loop or a single stream pass, stores iteration records, reflects, and possibly revises the plan
5. On `should_revise=True`: keeps the goal active for a later autonomous iteration and stores the revised plan
6. On completion: synthesizes a structured goal report, marks the goal completed, and checkpoints state
7. On error: retries with exponential backoff, then permanently fails the goal when retries are exhausted

Current implementation note: the helper for continuation prompt synthesis still exists, but the active autonomous loop does not currently feed a synthesized continuation prompt back into `current_input` between iterations.

#### 3. IterationRecord (journal)

After each iteration, a structured record is stored via `ContextProtocol.ingest()`:

```python
class IterationRecord(BaseModel):
    iteration: int
    goal_id: str
    plan_summary: str
    actions_summary: str
    reflection_assessment: str
    outcome: Literal["continue", "goal_complete", "failed"]
```

Stored as a `ContextEntry` with tag `"iteration_record"` and high importance (0.9) to ensure it survives context projection into subsequent iterations.

#### 4. Continuation Synthesizer

A helper still exists for generating a concise next-iteration instruction using `SootheConfig.create_chat_model("fast")` (falling back to `default`). It uses the original goal, iteration history, and revised plan. However, in the current autonomous runner this synthesizer is not actively wired into iteration input updates between revisions.

#### 5. Goal Management Tools

The current implementation exposes separate langchain tools rather than a single `manage_goals` tool:
- `create_goal`
- `list_goals`
- `complete_goal`
- `fail_goal`

These tools are bound to the active `GoalEngine` and allow autonomous execution to manage goal state explicitly.

## Stream Events

Current autonomous-mode observability uses RFC-0015-style event names:

| Type | Fields | Description |
|------|--------|-------------|
| `soothe.lifecycle.iteration.started` | `iteration`, `goal_id`, `goal_description`, `parallel_goals` | Autonomous goal iteration began |
| `soothe.lifecycle.iteration.completed` | `iteration`, `goal_id`, `outcome`, `duration_ms` | Autonomous goal iteration finished |
| `soothe.cognition.goal.created` | `goal_id`, `description`, `priority` | Goal created |
| `soothe.cognition.goal.batch_started` | `goal_ids`, `parallel_count` | Parallel batch of ready goals began |
| `soothe.cognition.goal.completed` | `goal_id` | Goal completed |
| `soothe.cognition.goal.failed` | `goal_id`, `error`, `retry_count` | Goal failed |
| `soothe.cognition.goal.directives_applied` | `goal_id`, `directives_count`, `changes` | Reflection directives mutated the goal graph |
| `soothe.cognition.goal.deferred` | `goal_id`, `reason`, `plan_preserved` | Current goal was deferred after DAG changes |
| `soothe.cognition.goal.report` | `goal_id`, `step_count`, `completed`, `failed`, `summary` | Structured goal report emitted |
| `soothe.output.autonomous.final_report` | `goal_id`, `description`, `status`, `summary` | Final autonomous report for the root goal |

## Configuration

Current autonomous configuration lives under the nested `autonomous` section:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `autonomous.enabled_by_default` | `bool` | `false` | Whether new threads default to autonomous mode |
| `autonomous.max_iterations` | `int` | `10` | Max autonomous iterations per thread |
| `autonomous.max_retries` | `int` | `2` | Max retries per goal before permanent failure |
| `autonomous.max_total_goals` | `int` | `50` | Max goals allowed during dynamic goal management |
| `autonomous.max_goal_depth` | `int` | `5` | Max hierarchical goal depth |
| `autonomous.enable_dynamic_goals` | `bool` | `true` | Enable/disable dynamic goal directives |

Autonomous execution also depends on execution-level concurrency and recovery settings such as `execution.concurrency.max_parallel_goals`, `execution.concurrency.max_parallel_steps`, and `execution.recovery.progressive_checkpoints`.

## CLI Integration

Current CLI/autonomous entry surfaces are:
- `soothe autopilot run <prompt>`
- `--max-iterations` on the autopilot command
- TUI `/autopilot` command parsing for autonomous execution

The runner and daemon protocol still accept `autonomous=True` and `max_iterations`, but the primary CLI surface is now the dedicated `autopilot` command group rather than `soothe run --autonomous`.

## Constraints

- No modifications to deepagents internals or the LangGraph graph
- No new protocols -- GoalEngine is a plain class, not a protocol
- All persistence uses existing DurabilityProtocol and ContextProtocol
- Backward compatible -- `autonomous=False` preserves current behavior exactly

## Dependencies

- RFC-0001 (System Conceptual Design) -- Principles 2, 6, 10
- RFC-0002 (Core Modules Architecture Design) -- PlannerProtocol, DurabilityProtocol, ContextProtocol
- RFC-0003 (CLI TUI Architecture Design) -- Stream events, SootheRunner

## Related Documents

- [RFC-0001](./RFC-0001.md) - System Conceptual Design
- [RFC-0002](./RFC-0002.md) - Core Modules Architecture Design
- [RFC-0003](./RFC-0003.md) - CLI TUI Architecture Design
- [RFC-0009](./RFC-0009.md) - DAG-Based Execution and Unified Concurrency
- [RFC-0011](./RFC-0011.md) - Dynamic Goal Management During Reflection
- [IG-018](../impl/018-autonomous-iteration-loop.md) - Implementation Guide
