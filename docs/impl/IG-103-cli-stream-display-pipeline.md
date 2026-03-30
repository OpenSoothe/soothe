# IG-103: CLI Stream Display Pipeline Implementation

**Status**: Draft
**Created**: 2026-03-30
**RFC**: RFC-0020 (CLI Stream Display Pipeline section)
**Dependencies**: RFC-0024 (VerbosityTier)

## Overview

Implement a unified stream display pipeline for CLI progress output that shows goal/step/tool context in a streaming narrative format at NORMAL verbosity.

## Goals

1. Show goal context persisting during execution
2. Display tool calls and results at NORMAL verbosity
3. Indicate parallel execution clearly
4. Use compact hybrid format for subagent activity
5. Integrate verbosity filtering into the pipeline

## File Structure

```
src/soothe/ux/cli/
  stream/
    __init__.py           # Public exports
    display_line.py       # DisplayLine dataclass
    context.py            # PipelineContext, ToolCallInfo
    pipeline.py           # StreamDisplayPipeline
    formatter.py          # Event-to-line formatting
  renderer.py             # CliStreamRenderer (updated)
```

## Implementation Tasks

### Task 1: Create DisplayLine dataclass

**File**: `src/soothe/ux/cli/stream/display_line.py`

```python
@dataclass
class DisplayLine:
    level: int  # 1=goal, 2=step/tool, 3=result
    content: str
    icon: str  # "●", "└", "⚙", "✓", "✗"
    indent: str  # computed from level
    status: str | None = None  # "running" for parallel
    duration_ms: int | None = None
```

**Indent mapping**:
- Level 1: `""`
- Level 2: `"  └ "`
- Level 3: `"     └ "`

### Task 2: Create PipelineContext

**File**: `src/soothe/ux/cli/stream/context.py`

```python
@dataclass
class ToolCallInfo:
    name: str
    args_summary: str
    start_time: float

@dataclass
class PipelineContext:
    # Goal state
    current_goal: str | None = None
    goal_start_time: float | None = None
    steps_total: int = 0
    steps_completed: int = 0

    # Step state
    current_step_id: str | None = None
    current_step_description: str | None = None
    step_start_time: float | None = None

    # Parallel tool tracking
    pending_tool_calls: dict[str, ToolCallInfo] = field(default_factory=dict)
    parallel_mode: bool = False

    # Subagent tracking
    subagent_name: str | None = None
    subagent_milestones: list[str] = field(default_factory=list)
```

### Task 3: Create StreamDisplayPipeline

**File**: `src/soothe/ux/cli/stream/pipeline.py`

Key methods:
- `process(event: dict, verbosity: VerbosityLevel) -> list[DisplayLine]`
- `_classify_event(event_type: str) -> VerbosityTier`
- `_format_event(event: dict) -> list[DisplayLine]`

Event handlers:
- `_on_goal_started(event)` → Level 1 header
- `_on_step_started(event)` → Level 2 header
- `_on_tool_call_started(event)` → Level 2 tool line
- `_on_tool_call_completed(event)` → Level 3 result line
- `_on_subagent_step(event)` → Level 3 milestone (if query/analyze)
- `_on_subagent_completed(event)` → Level 3 done line
- `_on_step_completed(event)` → Level 2 completion
- `_on_goal_completed(event)` → Level 1 completion

### Task 4: Create formatter functions

**File**: `src/soothe/ux/cli/stream/formatter.py`

Functions:
- `format_goal_header(goal: str) -> DisplayLine`
- `format_step_header(step_num: int, description: str, parallel: bool) -> DisplayLine`
- `format_tool_call(name: str, args: str, running: bool) -> DisplayLine`
- `format_tool_result(summary: str, duration_ms: int, is_error: bool) -> DisplayLine`
- `format_subagent_milestone(brief: str) -> DisplayLine`
- `format_subagent_done(summary: str, duration_s: float) -> DisplayLine`
- `format_step_done(step_num: int, duration_s: float) -> DisplayLine`
- `format_goal_done(goal: str, steps: int, total_s: float) -> DisplayLine`

### Task 5: Update CliStreamRenderer

**File**: `src/soothe/ux/cli/renderer.py`

Changes:
1. Add `write_lines(lines: list[DisplayLine])` method
2. Simplify existing callbacks to delegate to pipeline
3. Keep assistant text output to stdout

### Task 6: Update EventProcessor

**File**: `src/soothe/ux/core/event_processor.py`

Changes:
1. Create `StreamDisplayPipeline` instance
2. Replace direct renderer calls with `pipeline.process(event)`
3. Pass resulting lines to `renderer.write_lines()`

### Task 7: Remove redundant code

Files to update/remove:
- `src/soothe/ux/cli/progress.py` - logic moves to pipeline
- `CliRenderer.on_plan_created()` - replaced by pipeline
- `CliRenderer.on_plan_step_started()` - replaced by pipeline
- `CliRenderer.on_plan_step_completed()` - replaced by pipeline
- `CliRenderer.on_tool_call()` - replaced by pipeline
- `CliRenderer.on_tool_result()` - replaced by pipeline

## Verbosity Classification

| Event Type | VerbosityTier |
|------------|---------------|
| `soothe.agentic.loop.started` | NORMAL |
| `soothe.cognition.plan.created` | NORMAL |
| `soothe.cognition.plan.step_started` | NORMAL |
| `soothe.cognition.plan.step_completed` | NORMAL |
| `soothe.tool.*.call_started` | NORMAL |
| `soothe.tool.*.call_completed` | NORMAL |
| `soothe.subagent.*.dispatched` | NORMAL |
| `soothe.subagent.*.step` | NORMAL (query/analyze only) |
| `soothe.subagent.*.completed` | NORMAL |
| `soothe.agentic.loop.completed` | QUIET |
| Internal events | INTERNAL |

## Parallel Detection Logic

```python
def _on_tool_call_started(self, event) -> list[DisplayLine]:
    tool_call_id = event.get("tool_call_id")
    self._context.pending_tool_calls[tool_call_id] = ToolCallInfo(...)

    # Check for parallel mode
    if len(self._context.pending_tool_calls) > 1:
        self._context.parallel_mode = True
        # Re-emit step header with (parallel) suffix
        ...

def _on_tool_call_completed(self, event) -> list[DisplayLine]:
    tool_call_id = event.get("tool_call_id")
    self._context.pending_tool_calls.pop(tool_call_id, None)

    if not self._context.pending_tool_calls:
        self._context.parallel_mode = False
```

## Subagent Compact Hybrid

Show only:
- `subagent.step` events where type is "query" or "analyze"
- `subagent.completed` event

Hide:
- Internal reasoning
- Result parsing
- Synthesis steps

## Testing

1. **Unit tests**: Event → DisplayLine transformation
2. **Context tests**: Parallel detection, step transitions
3. **Verbosity tests**: Filtering at quiet/normal/detailed
4. **Integration tests**: Full goal execution output
5. **Snapshot tests**: Compare output format

## Migration Path

1. Create `stream/` package with new components
2. Create `StreamDisplayPipeline` class
3. Update `EventProcessor` to use pipeline
4. Update `CliStreamRenderer` with `write_lines()`
5. Remove redundant code from `progress.py` and `renderer.py`
6. Update tests

## Success Criteria

- [ ] Goal header shows at start of execution
- [ ] Step headers show with description
- [ ] Tool calls visible at NORMAL verbosity
- [ ] Tool results show with duration
- [ ] Parallel tools show `[running]` indicator
- [ ] Subagent shows milestones only
- [ ] Step completion shows with duration
- [ ] Goal completion shows with summary
- [ ] Verbosity filtering works correctly