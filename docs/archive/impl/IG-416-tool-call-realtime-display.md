# IG-416: Tool Call Real-time Display Optimization

## Summary

Optimize tool call display timing in TUI by augmenting `AGENT_LOOP_STEP_TOOL_BINDING` events with accumulated args from daemon, reducing TUI-side buffering complexity and improving real-time visibility.

## Motivation

**Current Problem**:
- Tool calls appear delayed in TUI cards
- TUI must coordinate multiple events: `step_started`, `messages` chunks, `tool_binding`, `tool_result`
- `_defer_tool_card_for_empty_streaming_args` waits for `chunk_position=="last"` before mounting
- Pending buffer logic (`step_task_routing.py`) adds complexity and latency

**Root Cause Analysis**:
1. Events arrive via same asyncio.Queue but order doesn't match display requirements
2. `tool_binding` event only carries `step_id` and `tool_call_id`, no args
3. TUI must wait for args to accumulate from subsequent messages chunks
4. Parallel execution interleaves events from multiple steps

## Design: Hybrid Buffering

**Core Idea**: Daemon accumulates args as chunks arrive and includes them in `TOOL_BINDING` event when available. TUI can render immediately if args are complete.

### Event Flow Changes

```
Before:
  Executor → messages chunk → TUI accumulates args
  Executor → TOOL_BINDING (no args) → TUI buffers pending
  → TUI waits for chunk_position=="last" → renders

After:
  Executor accumulates args internally
  Executor → TOOL_BINDING (with name + args if available) → TUI renders immediately
  Executor → messages chunk → TUI updates args (refinement)
```

### Modification Points

#### 1. Executor: Augment TOOL_BINDING Event

**File**: `executor.py` line 1652-1667

Add to TOOL_BINDING event payload:
- `tool_name`: extracted from chunk
- `args`: accumulated args dict (if complete)
- `args_status`: "complete" | "partial" | "pending"

#### 2. TUI: Direct Rendering from Binding Event

**File**: `_turn.py` line 1401-1418

When TOOL_BINDING arrives with complete args:
- Skip pending buffer
- Directly mount tool row on step card
- Avoid defer logic for this tool_call_id

#### 3. TUI: Simplify Deferred Mount Logic

**File**: `_turn.py` line 1034-1045, 1112-1123

Check if binding already mounted before deferring:
- If step card has tool row, update args only
- Remove redundant pending buffer entries

### Implementation Steps

1. [ ] Add helper `_extract_tool_name_and_args_from_ai_chunk()` in executor.py
2. [ ] Modify TOOL_BINDING yield to include name, args, args_status
3. [ ] Update TUI `_turn.py` TOOL_BINDING handler for direct rendering
4. [ ] Update TUI defer logic to check existing mounts
5. [ ] Add unit tests for augmented binding events
6. [ ] Run verification script

## Test Plan

- Unit test: executor yields binding with args when chunk has complete JSON
- Unit test: TUI renders tool row from binding event alone
- Integration test: parallel steps show tool calls immediately
- Manual test: observe TUI cards during multi-tool execution

## Files to Modify

- `packages/soothe/src/soothe/core/loop/engine/executor.py`
- `packages/soothe-cli/src/soothe_cli/tui/textual_adapter/_turn.py`
- `packages/soothe-cli/tests/unit/ux/tui/test_step_task_routing.py` (update tests)

## Backward Compatibility

- Existing clients that ignore new fields still work
- TUI falls back to messages chunk accumulation if args_status="pending"
- No changes to daemon WebSocket protocol schema

## Risks

- Args may be partial if provider sends chunked JSON
- Mitigation: include `args_status` flag, TUI handles "partial" same as before

## Status

- [ ] Draft
- [x] Implementation Started
- [x] Tests Passing
- [x] Verified

## History

- 2025-05-15: Initial design from tool call display timing investigation
- 2025-05-15: Implementation completed, all tests passing