# IG-073: Fix Subagent Routing in Headless Mode and Runtime Bugs

**Date**: 2026-03-27
**Status**: ✅ Completed
**Impact**: Critical bug fixes

## Summary

Fixed three critical issues:
1. Slash commands not routing to subagents in headless mode
2. TypeError when counting context entries
3. Log format missing thread ID for traceability

## Issue 1: Slash Commands Not Routing in Headless Mode

### Problem
When user types `/claude analyze this project structure` in headless mode, the slash command is not parsed and the query is not routed to the claude subagent.

**Root Cause**: `parse_subagent_from_input()` is only called in TUI mode, not in standalone headless execution.

### Solution
Added slash command parsing to `src/soothe/ux/cli/execution/standalone.py`:

```python
# Parse slash commands for subagent routing (IG-072)
from soothe.ux.cli.commands.subagent_names import parse_subagent_from_input

subagent_name, cleaned_prompt = parse_subagent_from_input(prompt)

stream_kwargs: dict[str, Any] = {"thread_id": thread_id}
if autonomous:
    stream_kwargs["autonomous"] = True
    if max_iterations is not None:
        stream_kwargs["max_iterations"] = max_iterations
if subagent_name:
    stream_kwargs["subagent"] = subagent_name

# Use cleaned prompt if subagent was extracted, otherwise use original
query_text = cleaned_prompt if subagent_name else prompt

async for chunk in runner.astream(query_text, **stream_kwargs):
    ...
```

### Result
Now `/claude`, `/research`, `/browser`, `/skillify`, and `/weaver` commands work in headless mode.

## Issue 2: TypeError - ContextProjection has no len()

### Problem
Runtime error:
```
TypeError: object of type 'ContextProjection' has no len()
```

At line 389 in `_runner_agentic.py`:
```python
context_entries=len(observations.get("context", [])),
```

**Root Cause**: The `observations["context"]` can be either:
- A list (old behavior)
- A `ContextProjection` object (new behavior from protocol refactoring)

### Solution
Added type-safe handling in `src/soothe/core/runner/_runner_agentic.py`:

```python
# Handle context entries (can be list or ContextProjection object)
context_data = observations.get("context")
if context_data is None:
    context_entries = 0
elif isinstance(context_data, list):
    context_entries = len(context_data)
elif hasattr(context_data, "entries"):
    context_entries = len(context_data.entries)
else:
    context_entries = 0
```

### Result
No more TypeError. Context entries are correctly counted regardless of data type.

## Issue 3: Log Format Missing Thread ID

### Problem
Logs don't include thread ID, making it hard to trace execution flows:
```
2026-03-27 14:35:44,840 INFO soothe.core.runner._runner_agentic Agentic mode: tier-1 routing...
```

**Root Cause**: Log format in `logging_setup.py` doesn't include thread_id field:
```python
file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s %(message)s"))
```

### Solution
Created a custom ThreadFormatter that adds thread_id from a context variable.

**File**: `src/soothe/ux/core/logging_setup.py`

Added thread context management:
```python
import contextvars

# Thread-local storage for thread_id
_current_thread_id: contextvars.ContextVar[str | None] = contextvars.ContextVar('current_thread_id', default=None)

def set_thread_id(thread_id: str | None) -> None:
    """Set the current thread ID for logging."""
    _current_thread_id.set(thread_id)

def get_thread_id() -> str | None:
    """Get the current thread ID for logging."""
    return _current_thread_id.get()
```

Created custom formatter:
```python
class ThreadFormatter(logging.Formatter):
    """Custom formatter that includes thread_id in log messages."""

    def format(self, record: logging.LogRecord) -> str:
        # Add thread_id to the record
        record.thread_id = get_thread_id() or ""
        return super().format(record)
```

Updated log format:
```python
file_handler.setFormatter(ThreadFormatter(
    "%(asctime)s [%(thread_id)s] %(levelname)-8s %(name)s %(message)s"
))
```

### Thread ID Propagation
The thread_id needs to be set at the start of execution:

**File**: `src/soothe/core/runner/__init__.py`
```python
async def astream(self, user_input: str, *, thread_id: str | None = None, ...):
    # Set thread_id for logging
    from soothe.ux.core.logging_setup import set_thread_id
    set_thread_id(thread_id or self._current_thread_id or "")
    ...
```

### Result
Logs now include thread ID:
```
2026-03-27 14:35:44,840 [immwxhl0wfl3] INFO soothe.core.runner._runner_agentic Agentic mode: tier-1 routing...
```

## Files Modified

1. `src/soothe/ux/cli/execution/standalone.py` - Added slash command parsing
2. `src/soothe/core/runner/_runner_agentic.py` - Fixed TypeError
3. `src/soothe/ux/core/logging_setup.py` - Added thread ID to log format
4. `src/soothe/core/runner/__init__.py` - Set thread_id for logging

## Verification

### Test 1: Slash Command Routing
```bash
soothe run "/claude analyze this project"
# Should route to claude subagent
# Should see: "Quick path: routing directly to subagent 'claude'"
```

### Test 2: No TypeError
```bash
soothe run "analyze the project structure"
# Should complete without TypeError
```

### Test 3: Thread ID in Logs
```bash
tail -f ~/.soothe/logs/soothe.log
# Should see thread IDs in brackets: [immwxhl0wfl3]
```

## Backward Compatibility

✅ All changes are backward compatible:
- Slash command parsing is additive (won't break existing queries)
- TypeError fix handles both old and new data types
- Log format change is transparent to users

## Related Work

- **IG-071**: Research subagent slash command integration
- **IG-072**: Quick path optimization for subagent routing
- **RFC-101**: Unified classifier and routing architecture