# IG-405: Virtual File System Backend Integration for File Tools

**Status**: In Progress
**Started**: 2026-05-07
**RFC Reference**: RFC-103 (Thread-Specific Workspace Isolation)

## Goal

In virtual mode (`allow_paths_outside_workspace=False`), map `SOOTHE_HOME` to virtual `/.soothe` (virtual absolute under workspace) rather than host-absolute `~/.soothe`. Ensure all file operations route through the backend for proper workspace isolation.

## Background

Current architecture has several gaps:
1. `SOOTHE_HOME` is static host path (`~/.soothe` or `$SOOTHE_HOME`)
2. Browser profiles stored under host `$SOOTHE_HOME/agents/browser/profiles/`
3. Wizsearch results stored under host `$SOOTHE_HOME/data/threads/{thread_id}/`
4. Internal tools use direct `Path()` operations after path resolution
5. Cache directories bypass backend

When `virtual_mode=True`, paths like `~/.soothe` get expanded to `/home/user/.soothe` then sandboxed to `{workspace}/home/user/.soothe`. The correct behavior should be: `.soothe` → `/.soothe` (virtual absolute under workspace).

## Implementation Steps

### Step 1: Create Virtual Home Module

**File**: `soothe/core/workspace/virtual_home.py` (NEW)

ContextVars:
- `_current_virtual_mode`: bool (default=False)
- `_virtual_home_path`: Path | None (default=None)

Functions:
- `set_virtual_mode_context(virtual_mode, workspace)` - set context
- `get_virtual_home()` - return `/.soothe` when virtual, else host `SOOTHE_HOME`
- `get_virtual_mode()` - check virtual mode status
- `clear_virtual_mode_context()` - cleanup

### Step 2: Enhance WorkspaceContextMiddleware

**File**: `soothe/middleware/workspace_context.py`

- `abefore_agent`: call `set_virtual_mode_context(virtual_mode, workspace)`
- `aafter_agent`: call `clear_virtual_mode_context()`

### Step 3: Adapt Browser Runtime

**File**: `soothe/utils/runtime.py`

- `get_subagent_runtime_dir()` → use `get_virtual_home() / "agents" / name`
- `get_browser_runtime_dir()` → virtual-aware
- `get_browser_user_data_dir()` → virtual-aware
- `cleanup_browser_temp_files()` → use backend for deletion

### Step 4: Adapt Wizsearch Storage

**File**: `soothe/toolkits/_internal/wizsearch.py`

- `_save_raw_results()` → use virtual home and backend

### Step 5: Adapt Internal Tools

**Files**: `toolkits/_internal/document.py`, `tabular.py`, `audio.py`, `video.py`

Create backend-aware file operation helper:
- `_backend_file_op(path, operation, content, config)` → route through backend when virtual mode

### Step 6: Update Artifact Store

**File**: `soothe/core/artifacts/artifact_store.py`

- `run_dir` computation → use `get_virtual_home()` when virtual mode

## Files Changed

| File | Change |
|------|--------|
| `soothe/core/workspace/virtual_home.py` | NEW |
| `soothe/middleware/workspace_context.py` | Add virtual mode context |
| `soothe/utils/runtime.py` | Virtual-aware runtime paths |
| `soothe/toolkits/_internal/wizsearch.py` | Virtual-aware storage |
| `soothe/toolkits/_internal/document.py` | Backend file ops |
| `soothe/toolkits/_internal/tabular.py` | Backend file ops |
| `soothe/toolkits/audio.py` | Backend file ops |
| `soothe/toolkits/video.py` | Backend file ops |
| `soothe/core/artifacts/artifact_store.py` | Virtual-aware run_dir |

## Testing

1. Unit tests for virtual home resolution
2. Integration tests for browser with virtual workspace
3. Integration tests for wizsearch storage in virtual `/.soothe`
4. Backward compatibility tests when `virtual_mode=False`

## Verification

Run `./scripts/verify_finally.sh` after all changes.