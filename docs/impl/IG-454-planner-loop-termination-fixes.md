# IG-454: Planner Loop Termination and Error Detection Fixes

## Status
✅ Completed

## Summary
Fix infinite loop caused by planner not detecting failed tool calls and repeating identical actions indefinitely.

## Problem Analysis

### Observed Behavior
Query `"read the first 10 lines of README.md"` caused infinite loop (19+ iterations) with:
- Tool calls with wrong path (`/README.md` instead of `README.md`)
- Planner returning `status=continue prog=none` despite tool errors
- Identical plan "Execute head -n 10 README.md" generated every iteration
- Step marked as "completed successfully" despite error

### Root Causes
1. **Path resolution**: Virtual paths like `/README.md` were joined incorrectly (`root / "/README.md"` → filesystem root)
2. **Success flag**: `StepResult.success=True` even when `ToolMessage.status="error"`
3. **Assess stuck detection**: No detection of repeated errors or identical actions

## Implementation

### Phase 1: Fix StepResult Success Flag ✅
**File**: `packages/soothe/src/soothe/core/loop/engine/executor.py`

- Centralize tool error detection in `generate_outcome_metadata()` (`tool_status` + `Error:` prefix)
- Derive `has_tool_error` from outcome metadata at end of `_stream_and_collect`
- Set `StepResult.success=False` with first `error_preview` when tools fail

### Phase 2: Add Assess Stuck Detection ✅
**File**: `packages/soothe/src/soothe/core/loop/planning/planner.py`

- `_detect_stuck_loop()` for repeated actions and consecutive failed steps
- Forces `status="replan"` when stuck pattern detected

### Phase 3: Improve Evidence Summary for Errors ✅
**File**: `packages/soothe/src/soothe/core/loop/engine/metadata_generator.py`

- Set `outcome["has_error"]` and `error_preview` from tool status or `Error:` content

### Phase 4: Fix Workspace Path Normalization ✅
**Files**: `normalized_backend.py`, `tool_path_resolution.py`, `middleware/filesystem.py`

- `NormalizedPathBackend.resolve_os_path()` delegates to `LocalFilesystem.resolve_path()`
- Virtual-mode normalization returns workspace-relative paths (no leading `/`)

## Files Modified
- `packages/soothe/src/soothe/core/loop/engine/executor.py`
- `packages/soothe/src/soothe/core/loop/planning/planner.py`
- `packages/soothe/src/soothe/core/loop/engine/metadata_generator.py`
- `packages/soothe/src/soothe/core/workspace/normalized_backend.py`
- `packages/soothe/src/soothe/core/workspace/tool_path_resolution.py`
- `packages/soothe/src/soothe/middleware/filesystem.py`
- `packages/soothe/src/soothe/core/filesystem/local.py` (insert via `edit_lines`)

## Verification
- `./scripts/verify_finally.sh` passes
- `soothe --no-tui -p "read the last 20 lines of README.md"` succeeds
