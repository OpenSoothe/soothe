# IG-212: Claude Subagent Detailed DEBUG Logging

**Status**: ✅ Completed
**Created**: 2026-04-19
**Scope**: `packages/soothe/src/soothe/subagents/claude/implementation.py`

---

## Objective

Add comprehensive DEBUG-level logging for Claude subagent tool execution to aid debugging and observability. Current logging is INFO-level via event emission only. Need detailed DEBUG logs with:

- Tool inputs/arguments
- Tool outputs/results
- Message state details
- Session/resume context
- Options configuration
- Performance metrics

---

## Current State

Tool execution logged at INFO level via `ClaudeToolUseEvent`:

```python
elif isinstance(block, ToolUseBlock):
    _emit(
        ClaudeToolUseEvent(tool=block.name).to_dict(),
        logger,
    )
```

Event emission uses INFO level through `emit_progress`. Need DEBUG logs before/after with more context.

---

## Implementation Plan

### 1. Add DEBUG Logging for Tool Execution

**Location**: `implementation.py:212` (ToolUseBlock handling)

**Changes**:
- Log tool name and input arguments before execution
- Log tool result/output after execution (if available)
- Use `logger.debug()` not `_emit()` for DEBUG logs

**Challenge**: ToolUseBlock from SDK may not expose input/output directly. Need to check SDK structure or use available attributes.

### 2. Add DEBUG Logging for Message State

**Location**: `implementation.py:149-167` (_run_claude_async start)

**Changes**:
- Log incoming messages count
- Log task content preview (truncated)
- Log state keys/values

### 3. Add DEBUG Logging for Options

**Location**: `implementation.py:164-189` (options setup)

**Changes**:
- Log all configured options (model, cwd, resume, permissions, tools)
- Log resolved cwd path
- Log thread_id and session resume context

### 4. Add DEBUG Logging for Results

**Location**: `implementation.py:217-232` (ResultMessage handling)

**Changes**:
- Log cost, duration, session_id
- Log final text length
- Log completion status

---

## Key Considerations

1. **SDK Structure Unknown**: ToolUseBlock attributes unclear without SDK docs
   - Use `getattr()` with defaults for safety
   - Log what's available, don't assume structure

2. **Sensitive Data**: Avoid logging secrets/credentials
   - Filter out `api_key`, `token`, `password` fields
   - Truncate long inputs/outputs to reasonable length

3. **Performance**: DEBUG logs should not impact INFO-level performance
   - Use lazy formatting: `logger.debug("msg %s", var)` not `logger.debug(f"msg {var}")`
   - Skip expensive computations in DEBUG messages

4. **Verbosity**: DEBUG logs are hidden at NORMAL verbosity
   - Current event system already respects verbosity
   - DEBUG logs are additional, don't replace INFO events

---

## Verification

Run existing tests:
```bash
./scripts/verify_finally.sh
```

No new tests needed - DEBUG logging is internal observability.

---

## Out of Scope

- Changing INFO-level event emission (that's TUI display)
- Adding new events (DEBUG logs are not events)
- Modifying SDK integration logic

---

## Implementation Summary

**Changes Made**:
1. Added DEBUG log at subagent start with message count and task preview (line 164-168)
2. Added DEBUG log for Claude options configuration (line 196-207)
3. Added DEBUG log for text blocks with length and preview (line 227-231)
4. Added DEBUG log for tool use with tool name and input preview (line 236-241)
5. Added DEBUG log for result message with cost, duration, session_id (line 253-263)
6. Added DEBUG log for session recording (line 274-281)
7. Added DEBUG log for completion with result length and total cost (line 289-293)

**Verification**: All 1330 tests passed ✅

**Logging Output Examples**:
- Start: `Claude subagent starting: messages=1, task_preview=<preview>`
- Options: `Claude options: model=sonnet, cwd=/path, resume=<id>, ...`
- Tool: `Claude tool use: tool=Bash, input=<input preview>`
- Result: `Claude result: cost_usd=0.0012, duration_ms=500, ...`

---

## References

- Current implementation: `packages/soothe/src/soothe/subagents/claude/implementation.py`
- Events: `packages/soothe/src/soothe/subagents/claude/events.py`
- RFC-403: Unified Event Naming (established `soothe.capability.claude.tool.running`)
- IG-089: Claude subagent internal events at DETAILED verbosity