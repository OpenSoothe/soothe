# IG-065: Fix Loop Agent Output Capture

## Status: ✅ Completed

## Problem

Simple queries like "read first 10 lines of readme" run for 10 iterations without completion (0% progress reported).

## Root Cause Analysis

### Issue 1: Wrong Data Format Check in `_stream_and_collect`

**Location**: `src/soothe/cognition/agent_loop/executor.py:349`

The method checks `isinstance(data, list)` but the actual format from deepagents streaming is:
```python
# Actual format (tuple):
data = (msg, metadata)  # e.g., (ToolMessage(...), {"langgraph_node": "tools"})

# Current (wrong) check:
if mode == "messages" and not namespace and isinstance(data, list) and len(data) >= _LIST_MIN_LEN:
```

This condition never matches, so tool result content is never extracted.

### Issue 2: ToolMessage Content Not Extracted

Even if the format check is fixed, the code only extracts `msg_chunk.content` as string. But:
- Tool results come as `ToolMessage` objects
- ToolMessage content can be string, list, or dict

### Issue 3: Continue Strategy Reuses Exhausted Decision

**Location**: `src/soothe/cognition/agent_loop/loop_agent.py:238-244`

When judgment is "continue" but all steps are already completed:
- The executor says "No ready steps to execute"
- The decision is reused indefinitely
- No progress is made

## Solution Implemented

### Fix 1: Correct Data Format Handling

Updated `_stream_and_collect` to:
1. Check for tuple format `(msg, metadata)` with constant `_MSG_TUPLE_LEN`
2. Extract content from `AIMessage` (AI responses)
3. Extract content from `ToolMessage` (tool results)

### Fix 2: Force Replan on Empty Ready Steps

In `loop_agent.py`, after continue strategy, check if there are actually ready steps. If not, force a replan.

## Files Changed

- `src/soothe/cognition/agent_loop/executor.py` - Fixed message format handling
- `src/soothe/cognition/agent_loop/loop_agent.py` - Fixed continue strategy

## Verification

All 1048 unit tests pass. Ready for commit.