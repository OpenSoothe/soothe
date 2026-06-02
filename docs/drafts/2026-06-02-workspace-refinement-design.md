# Workspace Refinement Design

Refine the workspace system considering IG-458 (RFC-621 Workspace Host Convention) integration gaps and broader architecture issues.

## Problem

Two categories of issues surfaced after IG-458 implementation:

**IG-458 integration gaps:**
1. `bind_execution_thread_for_loop` re-resolves workspace from scratch (calls `resolve_loop_workspace` + translate again), even though `loop_new` already computed and persisted the correct container path as `current_workspace`. This creates divergence risk.
2. Error handling asymmetry: `_handle_loop_new` sends error on translation failure, `bind_execution_thread_for_loop` silently falls back.
3. `$SOOTHE_HOME/workspaces/` directory is used for both daemon-generated persisted workspaces and Docker volume mount targets. These are different concerns that should have separate directories.

**Broader architecture issues:**
4. Three overlapping resolution chains (`resolve_loop_workspace`, `resolve_workspace_for_stream`, `resolve_workspace_for_tool_execution`) with different precedence rules, return types, and no shared core.
5. `virtual_home.py` and `framework_filesystem.py` maintain separate ContextVars set by the same middleware.
6. `WorkspaceAwareBackend._get_backend()` creates a new `NormalizedPathBackend` on every call instead of using the module-level `get_workspace_backend()` cache.

## Solution

### 1. Move persisted workspaces to `$SOOTHE_HOME/data/workspaces/`

Change `resolve_persisted_loop_workspace()` to use `$SOOTHE_HOME/data/workspaces/<user>/ws_<hash>` instead of `$SOOTHE_HOME/workspaces/<user>/ws_<hash>`.

This frees `$SOOTHE_HOME/workspaces/` to serve purely as the Docker volume mount target for client paths, with no collision risk between daemon-generated workspaces and mounted host directories.

**New directory layout:**

```
$SOOTHE_HOME/
  workspaces/              # Docker mount: host paths mapped here (RFC-621)
    xiamingchen/           # mirrors host /Users/xiamingchen/Workspace/xiamingchen/
      project-a/
  data/
    workspaces/            # daemon-generated: no client_workspace fallback
      anonymous/
        ws_a1b2c3d4/
      bob_smith/
        ws_e5f6g7h8/
```

**Files to change:**
- `loop_workspace.py`: `resolve_persisted_loop_workspace` line 80: `home / "workspaces"` → `home / "data" / "workspaces"`
- `resolution.py`: `cleanup_anonymous_workspaces` line 120: `Path(SOOTHE_HOME) / "workspaces"` → `Path(SOOTHE_HOME) / "data" / "workspaces"`
- `loop_workspace.py` docstrings: update path references
- Tests: update path expectations
- Migration: `cleanup_anonymous_workspaces` already runs on daemon shutdown; add a one-time migration to move existing `$SOOTHE_HOME/workspaces/<user>/ws_*` dirs to `$SOOTHE_HOME/data/workspaces/<user>/ws_*` (skip `anonymous/` dir which is cleaned up anyway)

### 2. Trust persisted `current_workspace` in `bind_execution_thread_for_loop`

Instead of re-resolving from scratch, read `current_workspace` from persisted loop metadata and use it directly. Only fall back to full re-resolution if the metadata field is missing (legacy loop or corruption).

**Current flow:**
```
metadata → resolve_loop_workspace() → translate_client_path_to_container() → set_workspace()
```

**New flow:**
```
metadata → if current_workspace exists: use it directly
         → else: resolve_loop_workspace() → set_workspace()
```

This eliminates:
- The stale-metadata-vs-current-config divergence risk
- The translation step in `bind_execution_thread_for_loop` entirely
- The error handling asymmetry (translation only happens at `loop_new` boundary)

**Files to change:**
- `loop_isolation.py`: Replace the full re-resolution block with a `current_workspace` lookup from metadata, falling back to `resolve_loop_workspace()` only when missing.
- `loop_isolation.py`: Remove the `workspace_mapping` / `translate_client_path_to_container` block (translation is already baked into the persisted `current_workspace`).

### 3. Shared resolution core with pluggable precedence

Create a unified `resolve_workspace()` core function with a `WorkspacePrecedence` enum. Each existing chain becomes a thin wrapper that delegates with the appropriate precedence.

```python
class WorkspacePrecedence(Enum):
    LOOP = "loop"            # client_workspace > persisted > daemon fallback
    STREAM = "stream"        # explicit > thread > daemon_default > cwd
    TOOL_EXECUTION = "tool"  # config > state > messages > ContextVar > fallback

def resolve_workspace(
    precedence: WorkspacePrecedence,
    **sources: Any,
) -> ResolvedWorkspace:
    ...
```

Each precedence level defines an ordered list of source checkers. The core iterates and returns the first match as a `ResolvedWorkspace(path, source)`.

**Return type unification:** All three chains return `ResolvedWorkspace` (the dataclass from `stream_resolution.py`). The `LOOP` chain currently returns `Path`; wrap it to return `ResolvedWorkspace(path=str(p), source="client_workspace"|"persisted"|"daemon_fallback")`.

**Files to change:**
- New file `workspace/core_resolution.py`: `WorkspacePrecedence`, `resolve_workspace()`, source checker registry.
- `loop_workspace.py`: `resolve_loop_workspace` becomes a thin wrapper calling `resolve_workspace(WorkspacePrecedence.LOOP, ...)`.
- `stream_resolution.py`: `resolve_workspace_for_stream` becomes a thin wrapper.
- `runtime_resolution.py`: `resolve_workspace_for_tool_execution` becomes a thin wrapper.
- `__init__.py`: Export new types.

### 4. Decouple ContextVar setup with `WorkspaceContext`

Create a single `WorkspaceContext` dataclass stored in one ContextVar, replacing the three separate ContextVars:

```python
@dataclass
class WorkspaceContext:
    workspace: Path | None = None
    virtual_mode: bool = False
    virtual_home: Path | None = None
```

One ContextVar: `_workspace_context: ContextVar[WorkspaceContext] = ContextVar(...)`

The middleware sets/clears one object instead of coordinating across three modules.

**Files to change:**
- New file `workspace/context.py`: `WorkspaceContext`, ContextVar, set/get/clear helpers.
- `framework_filesystem.py`: `set_current_workspace` / `get_current_workspace` / `clear_current_workspace` delegate to `WorkspaceContext`.
- `virtual_home.py`: `set_virtual_mode_context` / `get_virtual_home` / `clear_virtual_mode_context` delegate to `WorkspaceContext`.
- Middleware that calls both: simplify to single set/clear.

### 5. Wire `WorkspaceAwareBackend` through `get_workspace_backend()` cache

Both `__call__` and `_get_backend()` currently create new `NormalizedPathBackend` instances. Route them through the module-level `get_workspace_backend()` cache instead.

**Files to change:**
- `normalized_backend.py`: `WorkspaceAwareBackend.__call__` and `_get_backend` use `get_workspace_backend()`.

## Scope Boundary (YAGNI)

Not included:
- `translate_container_path_to_client` in daemon (no current consumer)
- Removing deprecated `compute_workspace_id` / `resolve_user_workspace` (separate cleanup)
- `_backend_cache` thread-safety (minor, existing pattern works)
- Config-level env-var interpolation for `workspace_mount`
- `tool_path_resolution.py` dead branch cleanup (separate concern)

## Migration Plan

The `$SOOTHE_HOME/workspaces/` → `$SOOTHE_HOME/data/workspaces/` move requires a one-time migration on daemon startup:

1. Check if `$SOOTHE_HOME/workspaces/` contains any `ws_*` or `anonymous/` directories (indicating old persisted workspaces).
2. If so, create `$SOOTHE_HOME/data/workspaces/` and move those directories.
3. Skip any directory that is a volume mount point (heuristic: contains files/dirs not matching `ws_*` or `anonymous` pattern).
4. Log migration actions.

**Post-migration cleanup for persisted `current_workspace` values:** Existing loop metadata may contain `current_workspace` paths pointing to the old `$SOOTHE_HOME/workspaces/<user>/ws_<hash>`. After the directory migration, these paths would be broken. Two options:

- **Option A (lazy):** Do nothing. When `bind_execution_thread_for_loop` reads a stale `current_workspace`, the path won't exist on disk, so the fallback to `resolve_loop_workspace()` will produce the correct new path (under `data/workspaces/`) and persist it.
- **Option B (eager):** During migration, scan loop metadata for `current_workspace` values under old paths and update them.

Recommend **Option A** — it's simpler and the `bind_execution_thread_for_loop` fallback handles it naturally. The stale path scenario is transient (one re-bind per affected loop).

This is safe because:
- Anonymous workspaces are ephemeral (cleaned on shutdown)
- Named-user `ws_<hash>` dirs are stable and just need to move
- The migration only runs once (presence of `$SOOTHE_HOME/data/workspaces/` suppresses it)
- If `$SOOTHE_HOME/workspaces/` is a Docker mount, it won't contain `ws_*` dirs, so migration is a no-op

## Files to Modify

| File | Change |
|------|--------|
| `workspace/loop_workspace.py` | Path change to `data/workspaces`, thin wrapper for core |
| `workspace/resolution.py` | Path change in cleanup, thin wrapper for core |
| `workspace/stream_resolution.py` | Thin wrapper for core |
| `workspace/runtime_resolution.py` | Thin wrapper for core |
| `workspace/core_resolution.py` | **New**: `WorkspacePrecedence`, `resolve_workspace()` |
| `workspace/context.py` | **New**: `WorkspaceContext` dataclass + ContextVar |
| `workspace/framework_filesystem.py` | Delegate to `WorkspaceContext` |
| `workspace/virtual_home.py` | Delegate to `WorkspaceContext` |
| `workspace/normalized_backend.py` | Use `get_workspace_backend()` cache |
| `workspace/__init__.py` | Export new types |
| `loop_isolation.py` | Trust persisted `current_workspace` |
| `workspace/migration.py` | **New**: one-time directory migration |
| Tests | Update path expectations, add migration tests |

## Testing

1. Unit tests for `resolve_workspace()` with each precedence level
2. Unit tests for `WorkspaceContext` set/get/clear
3. Unit tests for `$SOOTHE_HOME/data/workspaces/` path computation
4. Migration tests: old layout → new layout, Docker mount no-op
5. Integration test: `bind_execution_thread_for_loop` uses persisted `current_workspace`
6. Existing workspace tests updated for new paths
