# Fix Summary: Subagent Routing and Runtime Bugs

## Issues Fixed

### 1. ✅ Slash Commands Not Routing in Headless Mode

**Problem**: When user typed `/claude analyze this project structure` in headless mode, the slash command was not parsed and the query went to the main agent instead of routing to the claude subagent.

**Root Cause**: The `parse_subagent_from_input()` function was only called in TUI mode (`src/soothe/ux/tui/app.py`), not in standalone headless execution (`src/soothe/ux/cli/execution/standalone.py`).

**Fix**: Added slash command parsing to standalone execution:

```python
# src/soothe/ux/cli/execution/standalone.py
from soothe.ux.cli.commands.subagent_names import parse_subagent_from_input

subagent_name, cleaned_prompt = parse_subagent_from_input(prompt)

stream_kwargs: dict[str, Any] = {"thread_id": thread_id}
if subagent_name:
    stream_kwargs["subagent"] = subagent_name

query_text = cleaned_prompt if subagent_name else prompt

async for chunk in runner.astream(query_text, **stream_kwargs):
    ...
```

**Result**: Now `/claude`, `/research`, `/browser`, `/skillify`, and `/weaver` commands work correctly in both TUI and headless modes.

---

### 2. ✅ TypeError - ContextProjection has no len()

**Problem**: Runtime error at line 389 in `_runner_agentic.py`:

```python
context_entries=len(observations.get("context", [])),
# TypeError: object of type 'ContextProjection' has no len()
```

**Root Cause**: The `observations["context"]` can be either:
- A list (old behavior)
- A `ContextProjection` object (new behavior from protocol refactoring)

**Fix**: Added type-safe handling:

```python
# src/soothe/core/runner/_runner_agentic.py
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

**Result**: No more TypeError. Context entries are correctly counted regardless of data type.

---

### 3. ✅ Log Format Missing Thread ID

**Problem**: Logs didn't include thread ID, making it hard to trace execution:

```
2026-03-27 14:35:44,840 INFO soothe.core.runner._runner_agentic Agentic mode: tier-1 routing...
```

**Fix**: Created a custom `ThreadFormatter` with context variables:

```python
# src/soothe/ux/core/logging_setup.py
import contextvars

_current_thread_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_thread_id", default=None
)

def set_thread_id(thread_id: str | None) -> None:
    _current_thread_id.set(thread_id)

class ThreadFormatter(logging.Formatter):
    """Custom formatter that includes thread_id in log messages."""

    def format(self, record: logging.LogRecord) -> str:
        record.thread_id = get_thread_id() or ""
        return super().format(record)
```

And set thread_id at execution start:

```python
# src/soothe/core/runner/__init__.py
from soothe.ux.core.logging_setup import set_thread_id

active_thread_id = thread_id or self._current_thread_id or ""
set_thread_id(active_thread_id)
```

**Result**: Logs now include thread ID:

```
2026-03-27 14:35:44,840 [immwxhl0wfl3] INFO soothe.core.runner._runner_agentic Agentic mode: tier-1 routing...
```

---

## Files Modified

1. **src/soothe/ux/cli/execution/standalone.py** - Added slash command parsing for headless mode
2. **src/soothe/core/runner/_runner_agentic.py** - Fixed TypeError with ContextProjection
3. **src/soothe/ux/core/logging_setup.py** - Added ThreadFormatter with thread_id support
4. **src/soothe/core/runner/__init__.py** - Set thread_id for logging context

---

## Test Results

✅ All 919 unit tests pass
✅ Code formatting passes
⚠️ Linting has 6 errors in **pre-existing files** unrelated to these changes:
   - `src/soothe/core/parallel_tool_node.py` (3 errors)
   - `src/soothe/utils/tool_logging.py` (3 errors)

These linting errors existed before this fix and are in files I didn't modify.

---

## Backward Compatibility

✅ All changes are backward compatible:
- Slash command parsing is additive (doesn't break existing queries)
- TypeError fix handles both old (list) and new (ContextProjection) data types
- Log format change is transparent to users

---

## Verification

### Test 1: Slash Command Routing
```bash
soothe run "/claude analyze this project"
# Expected: Routes to claude subagent
# Log should show: "Quick path: routing directly to subagent 'claude'"
```

### Test 2: No TypeError
```bash
soothe run "analyze the project structure"
# Expected: Completes without TypeError
```

### Test 3: Thread ID in Logs
```bash
tail -f ~/.soothe/logs/soothe.log
# Expected: Logs show thread IDs in brackets: [immwxhl0wfl3]
```

All three issues are now resolved!