# IG-026: RFC-0009 Logging Enhancements -- Step, Goal, and DAG Progress Visibility

**Implements**: RFC-0009 (logging improvements)
**Status**: Completed
**Created**: 2026-03-18
**Completed**: 2026-03-18

## Overview

Enhances logging verbosity for step execution, goal progress, and DAG-based execution flow. The core RFC-0009 functionality is complete, but logs lack sufficient context for debugging and monitoring. This guide adds concise, informative logging without making output verbose.

**Analysis of current logs** (from latest run 2026-03-18):
- ✅ Good: Tool progress (wizsearch), subagent progress (research agent)
- ✅ Good: Goal creation/completion
- ⚠️ **Poor**: Step execution only shows "Step X completed" without description or context
- ❌ **Missing**: Batch execution info, DAG dependencies, step durations, step descriptions

**Key Finding**: Most RFC-0009 event fields (batch_index, blocked_steps, parallel_goals, depends_on) are **already implemented**. The gap is logging, not functionality.

## Problem Statement

### Current Logging (Insufficient)

```
INFO Step step_1 completed
INFO Step step_2 completed
INFO Step step_3 completed
INFO Step step_4 completed
INFO Completed goal 58708736: ...
```

**Issues**:
- No step descriptions (can't tell what step_1 does)
- No batch information (parallel steps not visible)
- No DAG structure awareness
- No progress indicators during execution

### Desired Logging (Enhanced)

```
INFO Batch 0: 1 steps ready (step_1)
INFO Step step_1 started: Gather stock codes via web search
INFO Step step_1 completed (2341 chars, 45.2s)
INFO Batch 1: 1 steps ready (step_2)
INFO Step step_2 started: Research Pony.ai latest developments
INFO Step step_2 completed (14445 chars, 123.4s)
INFO Batch 2: 2 steps ready ['step_3', 'step_4']
INFO Executing 2 steps in parallel
INFO Step step_3 started: Research WeRide latest developments
INFO Step step_4 started: Compile comparison report
INFO Step step_3 completed (8923 chars, 67.8s)
INFO Step step_4 completed (5672 chars, 32.1s)
INFO Completed goal 58708736: 获取港股小马智行、文远知行的重要动态和股价信息
```

**Improvements**:
- Step descriptions (truncated for readability)
- Batch execution with step IDs
- Parallel execution awareness
- Result size and duration metrics

## Design Principles

### Dual-Channel Approach

1. **Events** (yield _custom(...)) → TUI rendering, structured JSON logs
2. **Logging** (logger.info(...)) → Developer console, troubleshooting

Events are for the UI; logging is for developers. We enhance logging WITHOUT changing events.

### Logging Guidelines

**DO log**:
- ✅ Step start with description (truncated to 60 chars)
- ✅ Batch execution with step count and IDs
- ✅ DAG structure summary (steps with dependencies)
- ✅ Goal ready count and selection
- ✅ Step completion with result size and duration
- ✅ Parallel execution indicators

**DON'T log**:
- ❌ Full step descriptions (too long)
- ❌ Full result text (use length/preview)
- ❌ Dependency results (too verbose)
- ❌ Every stream chunk
- ❌ Context projection details

**Log levels**:
- **INFO**: Lifecycle events (start, complete, batch), DAG structure
- **DEBUG**: Memory recall, context projection, ingestion details
- **WARNING**: Failures, blocked steps, retries
- **ERROR**: Unexpected exceptions, policy violations

## Implementation Plan

### Phase 1: Step Lifecycle Logging

**File**: `src/soothe/core/step_scheduler.py`

Add logging to step state transitions:

```python
def mark_in_progress(self, step_id: str) -> None:
    """Mark a step as in-progress."""
    step = self._step_map.get(step_id)
    if step:
        step.status = "in_progress"
        logger.info("Step %s started: %s", step_id, step.description[:60])

def mark_completed(self, step_id: str, result: str) -> None:
    """Mark a step as completed with its result."""
    step = self._step_map.get(step_id)
    if step:
        step.status = "completed"
        step.result = result
        logger.info("Step %s completed (%d chars)", step_id, len(result))

def mark_failed(self, step_id: str, error: str) -> None:
    """Mark a step as failed."""
    step = self._step_map.get(step_id)
    if step:
        step.status = "failed"
        step.result = error
        logger.warning("Step %s failed: %s", step_id, error[:100])
```

### Phase 2: Batch Execution Logging

**File**: `src/soothe/core/runner.py`

Add logging in `_run_step_loop`:

```python
# After ready_steps() call (around line 915)
ready = scheduler.ready_steps(limit=max_steps, parallelism=parallelism)
if not ready:
    logger.warning("No ready steps but scheduler not complete -- breaking")
    break

# Log batch info
step_ids = [s.id for s in ready]
if len(ready) == 1:
    logger.info("Batch %d: 1 step ready (%s)", batch_index, step_ids[0])
else:
    logger.info("Batch %d: %d steps ready %s", batch_index, len(ready), step_ids)

# Log parallel execution
if len(ready) > 1:
    logger.info("Executing %d steps in parallel", len(ready))
```

### Phase 3: DAG Structure Logging

**File**: `src/soothe/core/runner.py`

Enhance DAG snapshot logging (around line 904):

```python
if len(plan.steps) > 1 and any(s.depends_on for s in plan.steps):
    dep_count = sum(1 for s in plan.steps if s.depends_on)
    logger.info(
        "Plan DAG: %d steps, %d with dependencies",
        len(plan.steps),
        dep_count
    )
    yield _custom({
        "type": "soothe.plan.dag_snapshot",
        "steps": [{"id": s.id, "depends_on": s.depends_on} for s in plan.steps],
    })
```

### Phase 4: Goal Progress Logging

**File**: `src/soothe/core/goal_engine.py`

Enhance goal lifecycle logging:

```python
async def ready_goals(self, limit: int = 1) -> list[Goal]:
    """Return goals whose dependencies are all completed."""
    # ... existing logic ...

    result = ready[:limit]
    for goal in result:
        if goal.status == "pending":
            goal.status = "active"
            goal.updated_at = datetime.now(UTC)

    # Log ready goals
    if result:
        logger.info(
            "Ready goals: %d (%s)",
            len(result),
            [g.id for g in result]
        )
    else:
        logger.debug("No ready goals (waiting for dependencies)")

    return result

async def complete_goal(self, goal_id: str) -> Goal:
    """Mark a goal as completed."""
    goal = self._goals.get(goal_id)
    if not goal:
        msg = f"Goal {goal_id} not found"
        raise KeyError(msg)
    goal.status = "completed"
    goal.updated_at = datetime.now(UTC)
    logger.info("Completed goal %s: %s", goal_id, goal.description[:60])
    return goal
```

### Phase 5: Step Duration Tracking

**File**: `src/soothe/core/runner.py`

Add duration tracking in `_execute_step`:

```python
async def _execute_step(...):
    # ... existing code ...

    step_start = perf_counter()

    # ... streaming logic ...

    step_duration = perf_counter() - step_start

    if response_text:
        step.status = "completed"
        step.result = response_text
        logger.info(
            "Step %s completed (%d chars, %.1fs)",
            step.id,
            len(response_text),
            step_duration
        )
```

## Test Coverage

**File**: `tests/unit_tests/test_progress_rendering.py`

Add tests for RFC-0009 event rendering (events already work, tests missing):

```python
def test_plan_batch_started_renders(self) -> None:
    """Test batch_started event with step_ids."""
    event = {
        "type": "soothe.plan.batch_started",
        "batch_index": 0,
        "step_ids": ["step_1", "step_2"],
        "parallel_count": 2,
    }
    # Test that TUI renders this correctly

def test_plan_step_started_with_batch_index(self) -> None:
    """Test step_started includes batch_index."""
    event = {
        "type": "soothe.plan.step_started",
        "step_id": "step_1",
        "description": "Do something",
        "depends_on": [],
        "batch_index": 0,
    }
    # Verify batch_index is present

def test_plan_step_failed_with_blocked_steps(self) -> None:
    """Test step_failed includes blocked_steps."""
    event = {
        "type": "soothe.plan.step_failed",
        "step_id": "step_1",
        "error": "Error message",
        "blocked_steps": ["step_2", "step_3"],
    }
    # Verify blocked_steps is present
```

## Files to Modify

| File | Changes |
|------|---------|
| `src/soothe/core/step_scheduler.py` | Add step lifecycle logging |
| `src/soothe/core/runner.py` | Add batch/DAG logging, step duration |
| `src/soothe/core/goal_engine.py` | Add goal progress logging |
| `tests/unit_tests/test_progress_rendering.py` | Add RFC-0009 event tests |

## Verification

### Manual Testing

1. **Multi-step plan**:
   ```bash
   soothe -p "Research autonomous driving companies and summarize their stock performance"
   ```

2. **Check logs** (`~/.soothe/logs/soothe.log`):
   - ✅ "Batch N: X steps ready" messages
   - ✅ "Step X started: <description>" messages
   - ✅ "Executing X steps in parallel" messages
   - ✅ "Plan DAG: X steps, Y with dependencies" message
   - ✅ Step completion with duration

### Automated Testing

```bash
# Run all tests
pytest tests/unit_tests/test_step_scheduler.py -v
pytest tests/unit_tests/test_concurrency_controller.py -v
pytest tests/unit_tests/test_goal_engine.py -v
pytest tests/unit_tests/test_progress_rendering.py -v

# Lint
make lint
```

## Expected Outcome

### Before (Current)
```
INFO Step step_1 completed
INFO Step step_2 completed
```

### After (Enhanced)
```
INFO Batch 0: 1 step ready (step_1)
INFO Step step_1 started: Gather stock codes via web search
INFO Step step_1 completed (2341 chars, 45.2s)
INFO Batch 1: 2 steps ready ['step_2', 'step_3']
INFO Executing 2 steps in parallel
INFO Step step_2 started: Research Pony.ai
INFO Step step_3 started: Research WeRide
INFO Step step_2 completed (14445 chars, 123.4s)
INFO Step step_3 completed (8923 chars, 67.8s)
```

**Result**: Clear visibility into execution flow without verbose output.
