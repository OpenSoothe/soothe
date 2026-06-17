# Workspace Module Dead Code Analysis

**Generated**: 2026-06-17  
**Module**: `soothe.foundation.workspace`

---

## Executive Summary

The workspace module contains several categories of problematic code:
- 2 explicitly deprecated functions (still exported, minimal usage)
- 1 instance of duplicate/dead code (copy-paste error in cleanup function)
- 1 dead ContextVar replaced by WorkspaceContext
- Multiple backward compatibility shims that could be simplified
- Several underutilized exports in public API

---

## 1. Dead Code

### 1.1 `_current_workspace` ContextVar (framework_filesystem.py)

**Location**: `framework_filesystem.py:20`

```python
_current_workspace: ContextVar[Path | None] = ContextVar("soothe_workspace", default=None)
```

**Status**: DEAD - Never used anywhere

**Reason**: Replaced by `WorkspaceContext` (single ContextVar in `context.py`) as per RFC-103. The class methods `set_current_workspace()` and `get_current_workspace()` (lines 166-199) now delegate to `WorkspaceContext` instead of using this variable.

**Impact**: 
- This is a leftover from pre-RFC-103 implementation
- Safe to remove
- No imports or references found

**Recommendation**: Remove line 20 and the unused import of `Token` if only used for this.

---

### 1.2 Duplicate Code in `cleanup_anonymous_workspaces` (resolution.py)

**Location**: `resolution.py:110-171`

**Issue**: The function contains a copy-paste error where the cleanup logic appears twice:

```python
# Lines 121-147: First cleanup loop (correct)
for base in ("data/workspaces", "workspaces"):
    # ... cleanup logic ...

if cleaned > 0:
    logger.info("Cleaned %d anonymous workspace location(s)", cleaned)

# Lines 148-171: Dead code - unreachable/duplicate
if not workspaces_dir.exists():  # BUG: workspaces_dir may not be defined here
    return

cleaned = 0
anon_tree = workspaces_dir / normalize_user_id(None)
# ... same cleanup logic repeated ...
```

**Problem**: 
- After the `for` loop ends, `workspaces_dir` is the last iteration value
- The code after line 148 repeats the cleanup logic for a single directory
- This is dead/redundant code that was likely a copy-paste mistake

**Recommendation**: Remove lines 148-171 entirely. The for loop already handles both `data/workspaces` and `workspaces`.

---

## 2. Deprecated Functions

### 2.1 `compute_workspace_id` (resolution.py)

**Location**: `resolution.py:49-56`

**Docstring**: *"Compute legacy flat workspace dir name (deprecated). Prefer `compute_scoped_workspace_dir_name` and `resolve_loop_workspace`."*

**Usage**: 
- Defined in: `resolution.py`, `__init__.py` (exported)
- Imported by: **None** (no external usage found)

**Status**: Unused deprecated function

**Recommendation**: 
- Remove from `resolution.py`
- Remove from `__init__.py` exports
- Safe to delete immediately

---

### 2.2 `resolve_user_workspace` (resolution.py)

**Location**: `resolution.py:59-78`

**Docstring**: *"Resolve workspace when only a client path is available (deprecated layout). Delegates to `resolve_loop_workspace` with a synthetic loop scope."*

**Usage**:
- Defined in: `resolution.py`, `__init__.py` (exported)
- Imported by: **None** (no external usage found)

**Status**: Unused deprecated function

**Recommendation**:
- Remove from `resolution.py`
- Remove from `__init__.py` exports
- Safe to delete immediately

---

## 3. Backward Compatibility Shims

### 3.1 Virtual Home Delegation Functions (virtual_home.py)

These functions delegate to `WorkspaceContext` (consolidated per RFC-103):

| Function | Lines | Delegates To | External Usage |
|----------|-------|--------------|----------------|
| `set_virtual_mode_context` | 19-31 | `set_workspace_context` | 1 (middleware) |
| `get_virtual_home` | 34-53 | `get_workspace_context` | 2 files |
| `get_virtual_mode` | 56-64 | `get_workspace_context` | 0 |
| `clear_virtual_mode_context` | 67-74 | `reset_workspace_context` | 0 |
| `resolve_virtual_path` | 77-88 | `get_virtual_home` | 0 |
| `get_virtual_home_relative_path` | 91-100 | `get_virtual_home` | 2 files |

**Observation**: 
- `get_virtual_mode` and `clear_virtual_mode_context` have no external imports
- `resolve_virtual_path` has no external imports
- These could be inlined or removed

**Recommendation**: 
- Keep `set_virtual_mode_context`, `get_virtual_home`, `get_virtual_home_relative_path` (used)
- Consider removing unused: `get_virtual_mode`, `clear_virtual_mode_context`, `resolve_virtual_path`
- Or mark them as deprecated if they serve future use cases

---

### 3.2 Resolution Consolidation (core_resolution.py)

**Location**: `core_resolution.py`

**Context**: RFC-621 introduced unified `resolve_workspace()` with pluggable precedence.

| Function | Purpose | External Usage |
|----------|---------|----------------|
| `WorkspacePrecedence` | Enum for precedence levels | Tests only |
| `resolve_workspace` | Unified resolution dispatcher | Tests + 1 toolkit |

**Current State**: 
- `resolve_workspace()` is used in 1 toolkit (`execution.py`) and tests
- Most code still calls specific functions (`resolve_loop_workspace`, `resolve_workspace_for_stream`)
- This is a partial migration, not complete backward compat

**Recommendation**: 
- Keep for now - this is the future direction per RFC-621
- Document migration plan for callers to switch to unified API

---

## 4. Underutilized Public API Exports

### Exports with Zero External Usage

| Export | Module Source | Recommendation |
|--------|---------------|----------------|
| `compute_workspace_id` | resolution.py | Remove (deprecated) |
| `resolve_user_workspace` | resolution.py | Remove (deprecated) |
| `get_virtual_mode` | virtual_home.py | Consider removing |
| `clear_virtual_mode_context` | virtual_home.py | Consider removing |
| `resolve_virtual_path` | virtual_home.py | Consider removing |
| `WorkspacePrecedence` | core_resolution.py | Keep (future API) |
| `resolve_workspace` | core_resolution.py | Keep (future API) |

### Exports with Minimal External Usage

| Export | Usage Count | Files |
|--------|-------------|-------|
| `get_git_status` | 4 | runner, prompts, tests |
| `translate_client_path_to_container` | 1 | router.py |
| `translate_container_path_to_client` | 1 | router.py |
| `cleanup_legacy_per_loop_workspaces` | 1 | daemon server |
| `cleanup_anonymous_workspaces` | 1 | daemon server |

---

## 5. Private Functions (Internal Use Only)

These are internal helpers not exported, but worth noting:

| Function | Module | Used By |
|----------|--------|---------|
| `user_id_for_hash` | loop_workspace.py | `compute_scoped_workspace_dir_name` only |
| `_coerce_fs_grep_to_da_matches` | normalized_backend.py | `NormalizedPathBackend` only |
| `_read_result_for_path` | normalized_backend.py | `NormalizedPathBackend` only |
| `config_workspace_root` | tool_path_resolution.py | `workspace_path_for_tool_resolution` only |
| `_posix_first_segment_name` | tool_path_resolution.py | `should_use_virtual_path_resolution` only |
| `_validate_workspace_dir` | resolution.py | `resolve_daemon_workspace` only |

**Status**: All correctly private, no action needed.

---

## 6. Recommended Cleanup Actions

### Priority 1 - Remove Dead Code Immediately

1. **Remove `_current_workspace` ContextVar** in `framework_filesystem.py:20`
   - No usage, replaced by WorkspaceContext

2. **Remove duplicate block** in `cleanup_anonymous_workspaces` (lines 148-171)
   - Copy-paste error, redundant logic

3. **Remove deprecated functions** from public API:
   - `compute_workspace_id` (resolution.py + __init__.py)
   - `resolve_user_workspace` (resolution.py + __init__.py)

### Priority 2 - Evaluate Backward Compatibility Shims

4. **Review virtual_home.py delegation functions**:
   - Remove unused: `get_virtual_mode`, `clear_virtual_mode_context`, `resolve_virtual_path`
   - Keep used: `set_virtual_mode_context`, `get_virtual_home`, `get_virtual_home_relative_path`

5. **Update __init__.py exports** after removals:
   - Remove from `__all__` and `_LAZY_EXPORTS`

### Priority 3 - Document Migration Paths

6. **Document RFC-621 migration**:
   - Add deprecation notices for specific resolution functions
   - Encourage use of unified `resolve_workspace()` API

---

## 7. Test Coverage Impact

After removing dead code, verify tests:

| Test File | Potentially Affected |
|-----------|---------------------|
| `test_core_resolution.py` | Tests `WorkspacePrecedence`, `resolve_workspace` - KEEP |
| `test_loop_workspace_resolution.py` | Tests `resolve_loop_workspace`, `normalize_user_id` - KEEP |
| `test_runtime_resolution.py` | Tests `resolve_workspace_for_tool_execution` - KEEP |
| `test_migration.py` | Tests `migrate_workspaces_to_data_dir` - KEEP |
| `test_workspace_mount.py` | Tests translate functions - KEEP |

**Note**: Tests for deprecated functions (`compute_workspace_id`, `resolve_user_workspace`) should also be removed if they exist.

---

## Appendix A: Module Structure

```
packages/soothe/src/soothe/foundation/workspace/
├── __init__.py              # Public API exports (42 items)
├── context.py               # WorkspaceContext dataclass + ContextVar
├── core_resolution.py       # Unified resolution (RFC-621)
├── framework_filesystem.py  # Singleton filesystem backend
├── loop_workspace.py        # Loop-scoped workspace resolution
├── migration.py             # One-time directory migration
├── normalized_backend.py    # Workspace-aware backend wrapper
├── resolution.py            # Core resolution utilities
├── runtime_resolution.py    # Tool execution resolution
├── stream_resolution.py     # Stream-level resolution
├── tool_path_resolution.py  # Path validation helpers
└── virtual_home.py          # Virtual home delegation
```

**Total**: 12 Python files, ~800 lines