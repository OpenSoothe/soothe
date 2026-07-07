# IG-472: Fix await_clarification Routing Debug Logging

## Status: ✅ Completed

## Goal
Add debug logging to trace why the `await_clarification` node was not executed when the planner emitted an `ask_user` step, causing the TUI stream to end unexpectedly.

## Problem Analysis

From log analysis of loop `019e8d43-104f-76a0-b5c8-f140978861b3`:

1. `193524.845` - `execute_steps` correctly returned `pending_clarification` for routing
2. `193525.157` - Stream ended only 310ms later with NO `await_clarification` node execution
3. NO logs from `await_clarification` node (no entry, no policy deferred, no ClarificationRelay)

The routing logic `_pending_clarification(state)` should have returned `"await_clarification"` but the graph ended at `END` instead.

## Root Cause Hypothesis

LangGraph routing may be affected by:
1. State merge timing issue - routing function called before state merge completes
2. Exception silently swallowed in graph execution
3. Missing entry logging in `await_clarification` node
4. Graph state channel reducer behavior with `TypedDict(total=False)`

## Files Modified

1. `packages/soothe/src/soothe/core/loop/orchestrator/routing.py`
   - Added `logger` import and instance
   - Added debug logging to `_pending_clarification()` tracing state values
   - Added info/debug logging to `route_after_execute()` tracing routing decisions

2. `packages/soothe/src/soothe/core/loop/orchestrator/nodes/await_clarification.py`
   - Added entry logging at the very start of `node_await_clarification`

3. `packages/soothe/src/soothe/core/loop/orchestrator/runner.py`
   - Added `traceback` import
   - Added debug logging before and after `compiled.ainvoke()`
   - Added exception handling with full traceback logging

4. `packages/soothe/src/soothe/core/loop/engine/strange_loop.py`
   - Added exception handling in `pump_graph()` with `exc_info=True` logging
   - Added debug logging when graph sentinel is received

## Testing
All 474 tests passed: `./scripts/verify_finally.sh`

## Next Steps
1. Reproduce the issue with debug logging enabled (`SOOTHE_LOG_LEVEL=DEBUG`)
2. Analyze the new logs to identify the exact root cause
3. Implement a fix based on the diagnostic findings