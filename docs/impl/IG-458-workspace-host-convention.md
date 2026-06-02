# IG-458: Workspace Host Convention (RFC-621)

## Summary

Implement prefix-based path mapping between client workspace paths and container paths for Docker deployments. When `workspace_mount` is configured, the daemon translates client paths at the `loop_new` boundary; the SDK translates container paths back for display. Non-container deployments are unaffected.

Additionally, separate the persisted workspace directory from the Docker mount point, unify resolution chains under a shared core, consolidate ContextVar management, trust persisted `current_workspace` in loop isolation, and wire `WorkspaceAwareBackend` through the cache.

**RFC**: RFC-621
**Status**: In Progress

## Scope

- Add `workspace_mount` config model and YAML entries
- Add path translation functions in `soothe.core.workspace.resolution`
- Apply translation in daemon `loop_new` handler (guard: `client_workspace is not None`)
- Trust persisted `current_workspace` in `bind_execution_thread_for_loop`
- Move persisted workspaces from `$SOOTHE_HOME/workspaces/` to `$SOOTHE_HOME/data/workspaces/`
- Add one-time migration for existing workspace directories
- Add `WorkspaceMapping` to SDK with boundary-safe translation
- Create shared resolution core with pluggable precedence (`WorkspacePrecedence`)
- Create unified `WorkspaceContext` (single ContextVar replacing three)
- Wire `WorkspaceAwareBackend` through `get_workspace_backend()` cache
- Update deploy configs

## Implementation Steps

### Step 1: Config Model

**File**: `packages/soothe/src/soothe/config/models.py`

Add after `FilesystemMiddlewareConfig` (line ~1508):

```python
class WorkspaceMountConfig(BaseModel):
    """Path mapping for containerized daemon deployments (RFC-621)."""

    host_root: str | None = None
    """Parent directory on the host machine that is volume-mounted into the container."""

    container_root: str | None = None
    """Mount point inside the container where host_root is mounted."""

    @model_validator(mode="after")
    def _validate_pair(self) -> WorkspaceMountConfig:
        has_host = bool(self.host_root and self.host_root.strip())
        has_container = bool(self.container_root and self.container_root.strip())
        if has_host != has_container:
            msg = (
                "workspace_mount.host_root and workspace_mount.container_root "
                "must both be set or both be unset"
            )
            raise ValueError(msg)
        return self

    @property
    def is_configured(self) -> bool:
        return bool(self.host_root) and bool(self.container_root)
```

**File**: `packages/soothe/src/soothe/config/settings.py`

Add after `filesystem_middleware` field (line ~326):

```python
workspace_mount: WorkspaceMountConfig = Field(default_factory=WorkspaceMountConfig)
"""Container workspace path mapping (RFC-621)."""
```

Add import for `WorkspaceMountConfig` in the import block.

### Step 2: YAML Config Files

**File**: `config/config.template.yml`

Add `workspace_mount` section with `host_root: null` and `container_root: null`.

**File**: `config/config.dev.yml`

Add the same section with both fields as `null` (disabled by default).

**File**: `deploy/config.yml.example`

Add `workspace_mount` with example values:
```yaml
workspace_mount:
  host_root: /Users/xiamingchen/Workspace
  container_root: /var/lib/soothe/workspaces
```

### Step 3: Path Translation Functions

**File**: `packages/soothe/src/soothe/core/workspace/resolution.py`

Add `translate_client_path_to_container()` and `translate_container_path_to_client()` after `validate_client_workspace()` (per RFC-621 §4).

### Step 4: Move Persisted Workspaces to `$SOOTHE_HOME/data/workspaces/`

**File**: `packages/soothe/src/soothe/core/workspace/loop_workspace.py`

In `resolve_persisted_loop_workspace()`, change:
```python
workspace_path = home / "workspaces" / normalized_user / ws_name
```
to:
```python
workspace_path = home / "data" / "workspaces" / normalized_user / ws_name
```

Update docstrings to reference `$SOOTHE_HOME/data/workspaces/`.

**File**: `packages/soothe/src/soothe/core/workspace/resolution.py`

In `cleanup_anonymous_workspaces()`, change:
```python
workspaces_dir = Path(SOOTHE_HOME) / "workspaces"
```
to:
```python
workspaces_dir = Path(SOOTHE_HOME) / "data" / "workspaces"
```

### Step 5: One-Time Migration

**File**: `packages/soothe/src/soothe/core/workspace/migration.py` (NEW)

```python
def migrate_workspaces_to_data_dir() -> None:
    """One-time migration: move persisted workspaces to $SOOTHE_HOME/data/workspaces/."""
    from soothe.config import SOOTHE_HOME

    home = Path(SOOTHE_HOME)
    old_dir = home / "workspaces"
    new_dir = home / "data" / "workspaces"

    if not old_dir.exists() or new_dir.exists():
        return  # nothing to migrate or already done

    # Check if old_dir looks like a Docker mount (contains non-workspace content)
    workspace_indicators = {"anonymous"} | {d for d in old_dir.iterdir() if d.name.startswith("ws_")}
    has_non_workspace = any(d not in workspace_indicators for d in old_dir.iterdir() if d.is_dir())

    if has_non_workspace:
        logger.info("workspaces/ appears to be a Docker mount; skipping migration")
        return

    # Move anonymous/ and ws_* user dirs
    new_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for item in old_dir.iterdir():
        if item.is_dir() and (item.name == "anonymous" or item.name.startswith("ws_")):
            dest = new_dir / item.name
            if not dest.exists():
                shutil.move(str(item), str(dest))
                moved += 1

    if moved:
        logger.info("Migrated %d workspace directories to %s", moved, new_dir)
```

Call from `server.py` daemon startup, before other initialization.

### Step 6: Daemon `loop_new` Handler

**File**: `packages/soothe-daemon/src/soothe_daemon/protocol/router.py`

In `_handle_loop_new`, after `resolved_workspace` is computed, add translation with guard:

```python
effective_workspace = resolved_workspace
if client_workspace is not None and host_root is not None:
    try:
        effective_workspace = translate_client_path_to_container(
            resolved_workspace, host_root=host_root, container_root=container_root,
        )
    except ValueError as e:
        # send error response and return
```

Update `meta_updates` to use `effective_workspace` for `current_workspace` and add `workspace_mapping` when `host_root is not None`. Include `workspace_mapping` in the `loop_new_response`.

### Step 7: Trust Persisted `current_workspace` in Loop Isolation

**File**: `packages/soothe-daemon/src/soothe_daemon/loop_isolation.py`

Replace the full re-resolution block in `bind_execution_thread_for_loop` with:

```python
# Trust persisted current_workspace — already contains container path from loop_new
persisted_workspace = metadata.get("current_workspace")
if persisted_workspace and str(persisted_workspace).strip():
    loop_workspace = Path(persisted_workspace)
else:
    # Legacy/corrupt metadata — full re-resolution
    loop_workspace = resolve_loop_workspace(
        loop_id=loop_id,
        client_workspace=client_ws,
        user_id=user,
        client_workspace_id=client_ws_id,
    )

daemon._thread_registry.set_workspace(thread_id, loop_workspace)
```

Remove the `workspace_mapping` / `translate_client_path_to_container` block entirely. Translation is baked into `current_workspace` at `loop_new` time.

### Step 8: Shared Resolution Core

**File**: `packages/soothe/src/soothe/core/workspace/core_resolution.py` (NEW)

```python
class WorkspacePrecedence(Enum):
    LOOP = "loop"
    STREAM = "stream"
    TOOL_EXECUTION = "tool"

@dataclass(frozen=True, slots=True)
class ResolvedWorkspace:
    path: str
    source: str

def resolve_workspace(precedence: WorkspacePrecedence, **sources: Any) -> ResolvedWorkspace:
    ...
```

Each precedence level has an ordered list of source checkers. The core iterates and returns the first match.

**Existing functions become thin wrappers:**
- `loop_workspace.py`: `resolve_loop_workspace` → `resolve_workspace(WorkspacePrecedence.LOOP, ...)`
- `stream_resolution.py`: `resolve_workspace_for_stream` → `resolve_workspace(WorkspacePrecedence.STREAM, ...)`
- `runtime_resolution.py`: `resolve_workspace_for_tool_execution` → `resolve_workspace(WorkspacePrecedence.TOOL_EXECUTION, ...)`

Public API of existing functions does not change.

### Step 9: WorkspaceContext — Unified ContextVar

**File**: `packages/soothe/src/soothe/core/workspace/context.py` (NEW)

```python
@dataclass
class WorkspaceContext:
    workspace: Path | None = None
    virtual_mode: bool = False
    virtual_home: Path | None = None

_workspace_context: ContextVar[WorkspaceContext] = ContextVar(
    "soothe_workspace_context", default=WorkspaceContext()
)

def set_workspace_context(workspace: Path, virtual_mode: bool = False) -> None: ...
def get_workspace_context() -> WorkspaceContext: ...
def clear_workspace_context() -> None: ...
```

**Files to update:**
- `framework_filesystem.py`: `set_current_workspace` / `get_current_workspace` / `clear_current_workspace` delegate to `WorkspaceContext`.
- `virtual_home.py`: `set_virtual_mode_context` / `get_virtual_home` / `clear_virtual_mode_context` delegate to `WorkspaceContext`.

### Step 10: WorkspaceAwareBackend Cache Wiring

**File**: `packages/soothe/src/soothe/core/workspace/normalized_backend.py`

In `WorkspaceAwareBackend.__call__` and `_get_backend`, replace `NormalizedPathBackend(...)` with `get_workspace_backend(...)`.

### Step 11: SDK WorkspaceMapping

**File**: `packages/soothe-sdk/src/soothe_sdk/client/protocol.py`

Add `WorkspaceMapping` dataclass with boundary-safe `translate_to_client` and `translate_to_container` methods (per RFC-621 §9).

**File**: `packages/soothe-sdk/src/soothe_sdk/client/session.py`

Parse `workspace_mapping` from `loop_new_response`, create `WorkspaceMapping`, store on session.

### Step 12: CLI Event Path Translation

**File**: `packages/soothe-sdk/src/soothe_sdk/utils/formatting.py`

Add optional `workspace_mapping` parameter to `convert_and_abbreviate_path()`.

**File**: `packages/soothe-cli/src/soothe_cli/tui/tool_display.py`

Pass the session's `workspace_mapping` to formatting calls.

### Step 13: Docker Compose and Deploy Config

**File**: `deploy/docker-compose.yml`

Add workspace volume mount:
```yaml
- /Users/xiamingchen/Workspace:/var/lib/soothe/workspaces
```

**File**: `deploy/config.yml.example`

Add `workspace_mount` section with `host_root` and `container_root`.

### Step 14: Tests

**File**: `packages/soothe/tests/unit/core/workspace/test_workspace_mount.py`

Tests for translation functions, config model, boundary-safe prefix matching.

**File**: `packages/soothe/tests/unit/core/workspace/test_workspace_context.py` (NEW)

Tests for `WorkspaceContext` set/get/clear.

**File**: `packages/soothe/tests/unit/core/workspace/test_core_resolution.py` (NEW)

Tests for `resolve_workspace()` with each precedence level.

**File**: `packages/soothe/tests/unit/core/workspace/test_migration.py` (NEW)

Tests for one-time directory migration: old layout → new layout, Docker mount no-op.

**File**: `packages/soothe-sdk/tests/unit/test_workspace_mapping.py`

Tests for SDK `WorkspaceMapping` boundary-safe translation.

**File**: existing workspace tests

Update path expectations from `$SOOTHE_HOME/workspaces/` to `$SOOTHE_HOME/data/workspaces/`.

## Verification

After implementation, run:

```bash
./scripts/verify_finally.sh
```

Additionally, test with a Docker deployment:

1. Set `workspace_mount.host_root` and `workspace_mount.container_root` in `deploy/config.yml`
2. Add the matching volume mount in `deploy/docker-compose.yml`
3. Start the daemon container
4. Connect a client with a workspace under `host_root`
5. Verify `loop_new_response` contains `workspace_mapping`
6. Verify file tools operate on container paths
7. Verify TUI displays client paths (SDK translation)
8. Verify `bind_execution_thread_for_loop` uses persisted `current_workspace` (no re-resolution)
9. Verify persisted workspaces go to `$SOOTHE_HOME/data/workspaces/`
10. Verify migration moves old workspace directories on startup
