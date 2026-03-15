# IG-018: Autonomous Iteration Loop

## Objective

Implement the autonomous iteration loop (RFC-0007) enabling Soothe to run
multi-iteration, self-driven agent sessions. The agent executes a plan, reflects,
revises, and continues without human input at each step.

## Scope

1. **GoalEngine**: New `core/goal_engine.py` with `Goal` model and `GoalEngine` class.
2. **manage_goals tool**: New `tools/goals.py` with `ManageGoalsTool` langchain tool.
3. **Runner iteration loop**: Enhance `SootheRunner.astream()` with outer loop,
   iteration journal, and continuation synthesizer.
4. **Config**: Add `autonomous_max_iterations` and `autonomous_max_retries` to `SootheConfig`.
5. **Wiring**: Connect GoalEngine through `resolver.py` and `agent.py`.
6. **CLI**: Add `--autonomous` and `--max-iterations` flags.
7. **Events**: Render `soothe.iteration.*` and `soothe.goal.*` events.

## Changes

### 1. GoalEngine (`core/goal_engine.py` -- NEW)

| Component | Description |
|-----------|-------------|
| `Goal(BaseModel)` | id, description, status, priority, parent_id, retry_count, max_retries, timestamps |
| `GoalEngine` | create_goal, next_goal, complete_goal, fail_goal, list_goals, persist, restore |

Persistence via `DurabilityProtocol.save_state()` under `goals:{thread_id}` key.
Priority-sorted in-memory queue. Retry: reset to pending if retries remain.

### 2. manage_goals Tool (`tools/goals.py` -- NEW)

| Component | Description |
|-----------|-------------|
| `ManageGoalsTool(BaseTool)` | Actions: create, list, complete, fail. Bound to GoalEngine instance. |
| `create_goal_tools(goal_engine)` | Factory function returning tool list. |

### 3. Runner Iteration Loop (`core/runner.py` -- EDIT)

| Component | Description |
|-----------|-------------|
| `astream()` new params | `autonomous: bool = False`, `max_iterations: int = 10` |
| `IterationRecord(BaseModel)` | iteration, goal_id, plan_summary, actions_summary, reflection_assessment, outcome |
| `_run_autonomous()` | Outer goal loop + inner iteration loop |
| `_store_iteration_record()` | Ingest IterationRecord via ContextProtocol |
| `_synthesize_continuation()` | LLM call to generate next iteration's input |

### 4. Config (`config.py` -- EDIT)

| Field | Type | Default |
|-------|------|---------|
| `autonomous_max_iterations` | `int` | `10` |
| `autonomous_max_retries` | `int` | `2` |

### 5. Wiring (`resolver.py`, `agent.py` -- EDIT)

| File | Change |
|------|--------|
| `resolver.py` | Add `"goals"` to `_resolve_single_tool_group()` |
| `agent.py` | Create GoalEngine, attach as `agent.soothe_goal_engine` |

### 6. CLI (`cli/main.py` -- EDIT)

| Change | Description |
|--------|-------------|
| `run` command | Add `--autonomous`/`-a` and `--max-iterations` options |
| `_run_headless()` | Pass `autonomous` and `max_iterations` to `runner.astream()` |

### 7. Events (`tui_shared.py`, `progress_verbosity.py` -- EDIT)

| File | Change |
|------|--------|
| `progress_verbosity.py` | Classify `soothe.iteration.*` and `soothe.goal.*` as protocol events |
| `tui_shared.py` | Render iteration/goal events in activity panel |
| `cli/main.py` | Render iteration/goal events in headless progress |

## Non-Goals

- Modifying the deepagents LangGraph graph structure.
- Adding new protocols (GoalEngine is a plain class).
- Implementing a CognitiveLoop-style tick-based autonomous mode.
- Experiment tracking / MLOps integration.
