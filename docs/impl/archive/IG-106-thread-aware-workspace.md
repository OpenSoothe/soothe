# IG-106: Thread-Aware Workspace Implementation

**Implementation Guide**: IG-106
**RFC**: RFC-103 (Thread-Aware Workspace)
**Status**: Draft
**Created**: 2026-03-31
**Estimated Scope**: 6-7 files, ~150-200 lines

## Overview

Implement thread-aware workspace support so that WebSocket clients connecting from different project directories have their file operations resolve against their specific workspace, rather than the daemon's startup workspace.

## Implementation Steps

### Step 1: Add ContextVar to FrameworkFilesystem

**File**: `src/soothe/safety/filesystem.py`

Add ContextVar definition and methods for dynamic workspace:

```python
from contextvars import ContextVar
from pathlib import Path

# Thread-safe workspace context for async execution
_current_workspace: ContextVar[Path | None] = ContextVar("soothe_workspace", default=None)
```

Add methods to `FrameworkFilesystem` class:

- `set_current_workspace(workspace: Path | str) -> None`
- `get_current_workspace() -> Path | None`
- `resolve_path_dynamic(file_path: str) -> Path`

### Step 2: Create WorkspaceContextMiddleware

**File**: `src/soothe/middleware/workspace_context.py` (new)

Create middleware that:
- Reads workspace from `config.configurable["workspace"]`
- Sets ContextVar at stream start
- Mirrors workspace in `state["workspace"]`
- Clears ContextVar at stream end

### Step 3: Register Middleware in Agent Factory

**File**: `src/soothe/core/agent.py`

Add `WorkspaceContextMiddleware` to the middleware stack after `ExecutionHintsMiddleware`.

### Step 4: Add Workspace Parameter to SootheRunner.astream()

**File**: `src/soothe/core/runner/_runner_phases.py`

Modify `astream()` signature:
- Add `workspace: str | None = None` parameter
- Inject into `config["configurable"]["workspace"]` if provided

### Step 5: Pass Workspace from Daemon Handler

**File**: `src/soothe/daemon/_handlers.py`

In `handle_client_message()`:
- Get `thread_workspace = self._thread_workspaces.get(thread_id, self._daemon_workspace)`
- Pass to `runner.astream(workspace=str(thread_workspace))`

### Step 6: Update Tool Path Resolution

**Files**:
- `src/soothe/tools/file_ops/implementation.py`
- `src/soothe/tools/execution/implementation.py`
- `src/soothe/tools/code_edit/implementation.py`

Modify `_resolve_path()` methods to:
- Call `FrameworkFilesystem.get_current_workspace()` first
- If set, use `FrameworkFilesystem.resolve_path_dynamic()`
- Otherwise, fall back to existing `self.work_dir` logic

### Step 7: Add Tests

**File**: `tests/unit/test_thread_aware_workspace.py`

Test cases:
- ContextVar set/get/clear lifecycle
- Path resolution with/without ContextVar
- Middleware configurable/state handling
- Concurrent threads isolation

## Verification

Run `./scripts/verify_finally.sh` after implementation to ensure:
- Format check passes
- Linting passes (zero errors)
- All unit tests pass (1000+)

## File Changes Summary

| File | Action | Lines |
|------|--------|-------|
| `src/soothe/safety/filesystem.py` | Modify | +30 |
| `src/soothe/middleware/workspace_context.py` | Create | +40 |
| `src/soothe/core/agent.py` | Modify | +3 |
| `src/soothe/core/runner/_runner_phases.py` | Modify | +10 |
| `src/soothe/daemon/_handlers.py` | Modify | +5 |
| `src/soothe/tools/file_ops/implementation.py` | Modify | +15 |
| `src/soothe/tools/execution/implementation.py` | Modify | +10 |
| `src/soothe/tools/code_edit/implementation.py` | Modify | +10 |
| `tests/unit/test_thread_aware_workspace.py` | Create | +80 |

## Dependencies

- RFC-102 (Security Filesystem Policy) - existing `FrameworkFilesystem`
- RFC-400 (Daemon Communication) - daemon message handling
- RFC-402 (Thread Management) - `_thread_workspaces` storage

## Success Criteria

- [ ] WebSocket client workspace correctly passed to tools
- [ ] Concurrent threads with different workspaces operate in isolation
- [ ] Fallback to daemon default when no workspace specified
- [ ] ContextVar properly cleared after stream completion
- [ ] All existing tests continue to pass
- [ ] New test coverage for thread workspace isolation