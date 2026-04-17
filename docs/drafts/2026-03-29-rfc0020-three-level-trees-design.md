# Design: RFC-501 Three-Level Tree Extension

**Date**: 2026-03-29
**Status**: Draft
**Extends**: RFC-501 Event Display Architecture

## Summary

Extend RFC-501's two-level tree display to support three levels, enabling proper display of agentic loop execution progress with goal → step → result hierarchy.

## Motivation

RFC-501 defines a two-level tree structure:
```
Level 1 (Summary):  ● EventSummary
Level 2 (Details):    └ Additional context
```

The agentic loop execution model has a natural three-level hierarchy:
- **Goal** - What we're trying to accomplish
- **Step** - Individual actions toward the goal
- **Result** - Outcome metrics and status

Current implementation only emits `AgenticLoopStartedEvent` and `AgenticLoopCompletedEvent`, providing no visibility into intermediate progress. Users see:
```
● Goal started
[silence for 20-200 seconds]
● Goal completed
```

This design extends RFC-501 to display meaningful progress during execution.

## Design Principle: Maximum Three Levels

**Rule**: Display hierarchy is limited to 3 levels maximum.

**Rationale**: Deeper nesting degrades user experience and terminal readability. Three levels provide sufficient structure to show goal → step → result without overwhelming users.

## Level Definitions

| Level | Name | Content | Icon |
|-------|------|---------|------|
| **1** | Summary | Goal or phase description | `●` |
| **2** | Step | Individual action description | `└` |
| **3** | Result | Outcome, metrics, status | `└ ✓/✗` |

## Display Pattern

### Example: File Listing Task

```
● Listing all README.md files
  └ Find files using glob
     └ ✓ Found 42 files in 1.2s
  └ Count and summarize
     └ ✓ 42 total, 8 directories
● Done: listed all README.md files
```

### Example: Code Analysis Task

```
● Analyzing project code structure
  └ Scan source directories
     └ ✓ Scanned 156 files (2.3s)
  └ Identify module boundaries
     └ ✓ Found 12 modules
  └ Generate structure report
     └ ✓ Report generated
● Done: analysis complete
```

## What Gets Hidden (Internal Details)

The following are implementation details NOT shown to end users:

| Hidden Detail | Reason |
|---------------|--------|
| Iteration count | Internal loop mechanics |
| Step IDs | Implementation artifact |
| DAG dependencies | Too technical for normal view |
| Planning decisions | Internal reasoning |
| Judge confidence scores | Internal metrics |
| Execution mode (parallel/sequential) | Implementation detail |

## Event Structure

### New Events

```
AgenticLoopStartedEvent     → Level 1: Goal summary
AgenticStepStartedEvent     → Level 2: Step description
AgenticStepCompletedEvent   → Level 3: Result metrics
AgenticLoopCompletedEvent   → Level 1: Goal conclusion
```

### Event Fields

**AgenticLoopStartedEvent** (existing, update display):
```python
type: "soothe.agentic.loop.started"
thread_id: str
goal: str              # Level 1 summary text
max_iterations: int    # Not displayed
```

**AgenticStepStartedEvent** (new):
```python
type: "soothe.agentic.step.started"
step_id: str           # Internal, not displayed
description: str       # Level 2 text
```

**AgenticStepCompletedEvent** (new):
```python
type: "soothe.agentic.step.completed"
step_id: str           # Internal reference
success: bool          # Determines ✓/✗ icon
summary: str           # Level 3 result text (e.g., "Found 42 files")
duration_ms: int       # Appended to summary
```

**AgenticLoopCompletedEvent** (existing):
```python
type: "soothe.agentic.loop.completed"
status: str            # "done", "replan", "continue"
goal_progress: float   # Not displayed to user
evidence_summary: str  # Optional Level 1 conclusion
```

## Verbosity Behavior

| Level | quiet | normal | detailed |
|-------|-------|--------|----------|
| Loop started | ✗ | ✓ | ✓ |
| Step started | ✗ | ✗ | ✓ |
| Step completed | ✗ | ✓ | ✓ |
| Loop completed | ✓ | ✓ | ✓ |

**Rationale**:
- `quiet`: Only show final result
- `normal`: Show goal summary and step results (hide step starts)
- `detailed`: Show everything including step starts

## Component Changes

### 1. Event Catalog (`core/event_catalog.py`)

Register new events with verbosity categories:

```python
register_event(
    AgenticStepStartedEvent,
    verbosity="detailed",  # Only in detailed/debug mode
    summary_template="Step: {description}",
)

register_event(
    AgenticStepCompletedEvent,
    verbosity="normal",  # Visible in normal mode
    summary_template="{summary} ({duration_ms}ms)",
)
```

### 2. AgentLoop (`cognition/agent_loop/loop_agent.py`)

Add `run_with_progress()` generator:

```python
async def run_with_progress(
    self,
    goal: str,
    thread_id: str,
    max_iterations: int = 8,
) -> AsyncGenerator[tuple[str, dict], None]:
    """Run loop yielding progress events.

    Yields:
        (event_type, event_data) tuples for display
    """
    # ... existing logic ...

    for step in decision.steps:
        yield ("step_started", {"description": step.description})
        result = await self._execute_step(step, state)
        yield ("step_completed", {
            "success": result.success,
            "summary": self._summarize_result(result),
            "duration_ms": result.duration_ms,
        })
```

### 3. Runner (`core/runner/_runner_agentic.py`)

Use `run_with_progress()` and yield events:

```python
async for event_type, event_data in loop_agent.run_with_progress(goal, tid):
    if event_type == "step_started":
        yield _custom(AgenticStepStartedEvent(**event_data).to_dict())
    elif event_type == "step_completed":
        yield _custom(AgenticStepCompletedEvent(**event_data).to_dict())
```

### 4. Event Processor (`ux/core/event_processor.py`)

Handle new events and render as three-level tree:

```python
def _handle_agentic_step_started(self, data: dict) -> None:
    if should_show("protocol", self._verbosity):
        self._renderer.on_step_started(data["description"])

def _handle_agentic_step_completed(self, data: dict) -> None:
    if should_show("milestone", self._verbosity):
        icon = "✓" if data["success"] else "✗"
        summary = data["summary"]
        duration = data["duration_ms"]
        self._renderer.on_step_completed(icon, summary, duration)
```

### 5. Renderer Protocol (`ux/core/renderer_protocol.py`)

Add new methods:

```python
def on_step_started(self, description: str) -> None: ...
def on_step_completed(self, icon: str, summary: str, duration_ms: int) -> None: ...
```

### 6. CLI Renderer (`ux/cli/renderer.py`)

Implement three-level display:

```python
def on_step_started(self, description: str) -> None:
    print(f"  └ {description}")

def on_step_completed(self, icon: str, summary: str, duration_ms: int) -> None:
    duration_str = self._format_duration(duration_ms)
    print(f"     └ {icon} {summary} ({duration_str})")
```

## Migration Path

1. **Phase 1**: Add new events, keep existing behavior
2. **Phase 2**: Update runner to emit step events
3. **Phase 3**: Update renderers for three-level display
4. **Phase 4**: Register events with verbosity categories

## Success Criteria

1. **Progress visibility**: Users see step-by-step progress during execution
2. **RFC-501 compliance**: Display follows three-level tree pattern
3. **Verbosity respect**: quiet/normal/detailed work correctly
4. **No hang perception**: Progress events prevent appearance of frozen state
5. **Clean output**: Internal details (iterations, IDs) hidden from users

## Related Documents

- [RFC-501 Event Display Architecture](../specs/RFC-501-event-display-architecture.md)
- [RFC-200 Agentic Loop Execution](../specs/RFC-200-agentic-loop-execution.md)