# RFC-621: Workspace Host Convention for Container Deployments

**RFC**: 621
**Title**: Workspace Host Convention: Path Mapping for Containerized Daemon
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-06-02
**Updated**: 2026-06-02
**Authors**: Platonic Coding Workflow
**Dependencies**: RFC-103, RFC-450

---

## Abstract

Introduce a prefix-based path mapping layer that translates client workspace paths to container paths when the daemon runs inside a Docker container. A `workspace_mount` configuration section declares the host and container root directories. The daemon applies the mapping at the `loop_new` handshake boundary so that all tool execution, filesystem operations, and LLM reasoning use container-native paths. The SDK performs reverse translation for display. Non-container deployments are unaffected (identity mapping when unconfigured).

Additionally, separate the daemon-generated persisted workspace directory from the Docker volume mount point, unify the workspace resolution chains under a shared core with pluggable precedence, consolidate ContextVar management, and eliminate redundant re-resolution in `bind_execution_thread_for_loop`.

---

## Motivation

When the Soothe daemon runs in a Docker container, the client and daemon operate on different filesystems. The current architecture assumes a shared filesystem: `loop_new` stores `client_workspace` as-is, and `NormalizedPathBackend` operates directly on that path. Inside a container, client paths like `/var/run/soothe/workspaces/project-a` do not exist, causing all filesystem tools, shell execution, and path resolution to fail.

Container deployments are already supported via `deploy/docker-compose.yml`, but no workspace path translation exists. The daemon can run, but it cannot operate on client files.

Beyond the container path problem, several architectural issues surfaced after the initial implementation:

1. **Directory collision**: `$SOOTHE_HOME/workspaces/` serves both as the Docker volume mount target for client paths and as the daemon-generated persisted workspace directory. These are different concerns.
2. **Re-resolution divergence**: `bind_execution_thread_for_loop` re-resolves workspace from scratch (calls `resolve_loop_workspace` + translate) even though `loop_new` already computed and persisted the correct container path as `current_workspace`.
3. **Error handling asymmetry**: `_handle_loop_new` sends an error on translation failure, but `bind_execution_thread_for_loop` silently falls back.
4. **Overlapping resolution chains**: Three chains (`resolve_loop_workspace`, `resolve_workspace_for_stream`, `resolve_workspace_for_tool_execution`) with different precedence rules, return types, and no shared core.
5. **ContextVar coupling**: `virtual_home.py` and `framework_filesystem.py` maintain separate ContextVars set by the same middleware.
6. **Backend waste**: `WorkspaceAwareBackend._get_backend()` creates a new `NormalizedPathBackend` on every call instead of using the module-level cache.

---

## Design Goals

1. **Transparent path mapping** — daemon tools and LLM see container-native paths, SDK translates back for display.
2. **Convention over configuration** — one host root, one container root, prefix-based swap. No per-client mapping tables.
3. **Zero impact on non-container deployments** — unconfigured `workspace_mount` means identity mapping (no translation).
4. **Multi-client compatible** — each client's workspace is a subdirectory under the shared mount point; existing virtual-mode sandboxing provides isolation.
5. **Extensible to remote filesystems** — the mapping abstraction supports future "proxy" mode where file ops are routed to the client over WebSocket.
6. **Directory separation** — Docker mount point and daemon-generated workspaces occupy distinct directories.
7. **Single source of truth** — persisted `current_workspace` is authoritative; no redundant re-resolution.
8. **Unified resolution core** — one core function with pluggable precedence, thin wrappers for each use case.

---

## Proposed Solution

### 1. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│  Client (host filesystem)                            │
│  /Users/xiamingchen/Workspace/project-a/src/main.py  │
└──────────────────────────┬───────────────────────────┘
                           │ loop_new { client_workspace: "/Users/xiamingchen/Workspace/project-a" }
                           ▼
┌─────────────────────────────────────────────────────┐
│  Daemon (container filesystem)                       │
│  workspace_mount.host_root = /Users/xiamingchen/Workspace
│  workspace_mount.container_root = /var/lib/soothe/workspaces
│                                                      │
│  /var/lib/soothe/workspaces/project-a/src/main.py    │
│  LLM sees: /var/lib/soothe/workspaces/project-a/...  │
│                                                      │
│  $SOOTHE_HOME/                                       │
│    workspaces/           ← Docker volume mount       │
│      project-a/                                      │
│    data/                                             │
│      workspaces/         ← daemon-generated          │
│        anonymous/                                    │
│          ws_a1b2c3d4/                                │
│        bob_smith/                                    │
│          ws_e5f6g7h8/                                │
└──────────────────────────┬───────────────────────────┘
                           │ events contain /var/lib/soothe/workspaces/... paths
                           ▼
┌─────────────────────────────────────────────────────┐
│  SDK (client side)                                   │
│  Translates /var/lib/soothe/workspaces/...           │
│  → /Users/xiamingchen/Workspace/...                  │
│  User sees: /Users/xiamingchen/Workspace/project-a/...│
└─────────────────────────────────────────────────────┘
```

**Core principle**: The LLM and all tools inside the daemon only ever see container paths. The SDK transparently translates to client paths for display. This avoids the "phantom path" problem where the LLM reasons about paths that do not exist on its filesystem.

**Directory separation**: `$SOOTHE_HOME/workspaces/` is reserved for the Docker volume mount (host paths). `$SOOTHE_HOME/data/workspaces/` is for daemon-generated persisted workspaces when no `client_workspace` is provided.

### 2. Configuration — `workspace_mount`

New config section in `SootheConfig`:

```yaml
workspace_mount:
  host_root: /Users/xiamingchen/Workspace    # path on the Docker host
  container_root: /var/lib/soothe/workspaces  # path inside the container
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host_root` | `str \| None` | `None` | Parent directory on the host machine that is volume-mounted. All client workspaces must be under this directory. |
| `container_root` | `str \| None` | `None` | Mount point inside the container where `host_root` is mounted. |

**Default behavior**: When `workspace_mount` is not configured (both fields `None`), the mapping is identity — no translation occurs. Existing non-container deployments are unaffected.

**Docker Compose volume declaration** (operator responsibility):

```yaml
services:
  soothed:
    volumes:
      - /Users/xiamingchen/Workspace:/var/lib/soothe/workspaces
```

The `workspace_mount` config must match the Docker volume declaration. Mismatch is detected at daemon startup (see §5 Validation).

**Invariant**: `$SOOTHE_HOME/workspaces/` is the mount point. `$SOOTHE_HOME/data/workspaces/` is for daemon-generated workspaces. These never overlap because a Docker mount populates `workspaces/` with host content, while `data/workspaces/` is the daemon's own directory tree.

### 3. Config Model

```python
class WorkspaceMountConfig(BaseModel):
    """Path mapping for containerized daemon deployments."""

    host_root: str | None = None
    container_root: str | None = None

    @model_validator(mode="after")
    def _validate_pair(self) -> WorkspaceMountConfig:
        """Both fields must be set together, or neither."""
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

Note: `is_configured` uses `bool()` (not `is not None`) so empty strings count as unset.

### 4. Path Translation Functions

Add to `soothe/core/workspace/resolution.py`:

```python
def translate_client_path_to_container(
    client_path: str | Path,
    *,
    host_root: str | Path | None = None,
    container_root: str | Path | None = None,
) -> Path:
    """Translate a client-side path to its container-side equivalent.

    When host_root/container_root are not configured, returns the path unchanged.
    Raises ValueError if client_path is not under host_root.
    """
    if not host_root or not container_root:
        return Path(client_path).resolve()

    host = Path(host_root).resolve()
    container = Path(container_root).resolve()
    resolved = Path(client_path).resolve()

    try:
        relative = resolved.relative_to(host)
    except ValueError:
        msg = (
            f"Client workspace {resolved} is not under configured "
            f"host_root {host}. All workspaces must reside under the "
            f"configured host_root for container deployments."
        )
        raise ValueError(msg) from None

    return container / relative


def translate_container_path_to_client(
    container_path: str | Path,
    *,
    host_root: str | Path | None = None,
    container_root: str | Path | None = None,
) -> Path:
    """Translate a container-side path to its client-side equivalent.

    When host_root/container_root are not configured, returns the path unchanged.
    If the path is not under container_root, returns it unchanged.
    """
    if not host_root or not container_root:
        return Path(container_path).resolve()

    host = Path(host_root).resolve()
    container = Path(container_root).resolve()
    resolved = Path(container_path).resolve()

    try:
        relative = resolved.relative_to(container)
    except ValueError:
        return resolved

    return host / relative
```

### 5. Daemon Startup Validation

On daemon startup, when `workspace_mount` is configured:

1. Verify `container_root` exists and is a directory (the volume mount must be active).
2. If `container_root` does not exist, log a warning: the volume mount may not be configured in Docker.

This is a soft check — the daemon can still start (the volume may be attached after startup in some orchestration environments), but every `loop_new` with a client workspace outside `host_root` will be rejected.

### 6. `loop_new` Handshake — Daemon-Side

In `_handle_loop_new` (router.py), after resolving the client workspace:

```python
# Existing resolution
resolved_workspace = resolve_loop_workspace(
    loop_id=loop_id,
    client_workspace=client_workspace,
    user_id=user,
    client_workspace_id=client_workspace_id,
)

# NEW: translate client path to container path
mount = d._config.workspace_mount
host_root = mount.host_root if mount and mount.is_configured else None
container_root = mount.container_root if mount and mount.is_configured else None

# Only translate when client_workspace was provided — daemon-fallback
# workspaces ($SOOTHE_HOME/data/workspaces/) are container-local.
if client_workspace is not None and host_root is not None:
    try:
        container_workspace = translate_client_path_to_container(
            resolved_workspace,
            host_root=host_root,
            container_root=container_root,
        )
    except ValueError as e:
        await d._send_client_message(client_id, {
            "type": "error",
            "error": str(e),
            "request_id": request_id,
        })
        return
else:
    container_workspace = resolved_workspace
```

**Persisted metadata** (expanded):

```python
meta_updates = {
    "client_workspace": client_workspace,              # original client path
    "current_workspace": str(container_workspace),     # container path for tool execution
    "workspace_mapping": {                             # NEW
        "host_root": host_root,
        "container_root": container_root,
    },
}
```

**Response** (expanded):

```python
{
    "type": "loop_new_response",
    "loop_id": loop_id,
    "success": True,
    "is_ephemeral": is_ephemeral,
    "request_id": request_id,
    "workspace_mapping": {                             # NEW
        "host_root": host_root,
        "container_root": container_root,
        "client_workspace": client_workspace,
        "container_workspace": str(container_workspace),
    },
}
```

### 7. Loop Isolation — Trust Persisted `current_workspace`

In `bind_execution_thread_for_loop` (loop_isolation.py), read `current_workspace` from persisted loop metadata and use it directly. Only fall back to full re-resolution if the metadata field is missing (legacy loop or corruption).

**Previous flow (removed):**
```
metadata → resolve_loop_workspace() → translate_client_path_to_container() → set_workspace()
```

**New flow:**
```
metadata → current_workspace exists?
  → yes: use it directly (already contains container path from loop_new)
  → no: resolve_loop_workspace() → set_workspace()
```

This eliminates:
- The stale-metadata-vs-current-config divergence risk
- The translation step in `bind_execution_thread_for_loop` entirely
- The error handling asymmetry (translation only happens at `loop_new` boundary)

Translation is baked into `current_workspace` at `loop_new` time and never re-applied.

```python
# Trust persisted current_workspace — already contains container path
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

### 8. Persisted Workspace Directory — `$SOOTHE_HOME/data/workspaces/`

`resolve_persisted_loop_workspace()` now uses `$SOOTHE_HOME/data/workspaces/<user>/ws_<hash>` instead of `$SOOTHE_HOME/workspaces/<user>/ws_<hash>`.

```
$SOOTHE_HOME/
  workspaces/              # Docker mount: host paths mapped here
    xiamingchen/           # mirrors host /Users/xiamingchen/Workspace/xiamingchen/
      project-a/
  data/
    workspaces/            # daemon-generated: no client_workspace fallback
      anonymous/
        ws_a1b2c3d4/
      bob_smith/
        ws_e5f6g7h8/
```

This separation ensures:
- `$SOOTHE_HOME/workspaces/` is a clean Docker mount target — no daemon-generated files
- `$SOOTHE_HOME/data/workspaces/` is the daemon's own persisted workspace tree
- No collision risk between mounted host content and daemon-generated directories

**Migration**: On daemon startup, if `$SOOTHE_HOME/workspaces/` contains `ws_*` or `anonymous/` directories (indicating old persisted workspaces), move them to `$SOOTHE_HOME/data/workspaces/`. Skip if `$SOOTHE_HOME/workspaces/` is a Docker mount (heuristic: contains files/dirs not matching `ws_*` or `anonymous`). Migration only runs once (presence of `$SOOTHE_HOME/data/workspaces/` suppresses it).

**Stale `current_workspace` paths**: Loops created before migration have `current_workspace` pointing to old `$SOOTHE_HOME/workspaces/<user>/ws_<hash>`. After migration, these paths won't exist on disk. `bind_execution_thread_for_loop` handles this naturally: when the persisted path is missing from disk, the path still exists in metadata and the daemon uses it — but filesystem operations would fail. The fallback (re-resolve via `resolve_loop_workspace`) produces the correct new path and persists it. This is a transient state (one re-bind per affected loop).

### 9. SDK Path Translation

The SDK receives `workspace_mapping` from the `loop_new_response` and stores it on the session.

```python
@dataclass
class WorkspaceMapping:
    host_root: str | None
    container_root: str | None

    @property
    def is_configured(self) -> bool:
        return bool(self.host_root) and bool(self.container_root)

    def translate_to_client(self, path: str) -> str:
        """Translate a container path to a client path for display."""
        if not self.is_configured:
            return path
        # Boundary-safe: exact match or slash-delimited prefix
        if path == self.container_root:
            return self.host_root
        if path.startswith(self.container_root + "/"):
            return self.host_root + path[len(self.container_root):]
        return path

    def translate_to_container(self, path: str) -> str:
        """Translate a client path to a container path (outgoing messages)."""
        if not self.is_configured:
            return path
        if path == self.host_root:
            return self.container_root
        if path.startswith(self.host_root + "/"):
            return self.container_root + path[len(self.host_root):]
        return path
```

The SDK applies `translate_to_client()` on:
- Tool output paths in event data
- File path references in streaming events
- Log messages containing container paths (best-effort)

Translation is a **boundary-safe prefix swap**: exact match or slash-delimited prefix. This prevents partial matches (e.g., `/workspaces-extra` is not matched by container_root `/workspaces`).

### 10. Shared Resolution Core with Pluggable Precedence

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

**Return type unification**: All three chains return `ResolvedWorkspace` (the dataclass from `stream_resolution.py`). The `LOOP` chain currently returns `Path`; wrap it to return `ResolvedWorkspace(path=str(p), source="client_workspace"|"persisted"|"daemon_fallback")`.

Existing functions (`resolve_loop_workspace`, `resolve_workspace_for_stream`, `resolve_workspace_for_tool_execution`) become thin wrappers that call `resolve_workspace(precedence=..., **sources)` with the appropriate source dict. Their public API does not change.

### 11. WorkspaceContext — Unified ContextVar

Create a single `WorkspaceContext` dataclass stored in one ContextVar, replacing the three separate ContextVars:

```python
@dataclass
class WorkspaceContext:
    workspace: Path | None = None
    virtual_mode: bool = False
    virtual_home: Path | None = None
```

One ContextVar: `_workspace_context: ContextVar[WorkspaceContext] = ContextVar(...)`

The middleware sets/clears one object instead of coordinating across three modules. `framework_filesystem.py` and `virtual_home.py` delegate their get/set/clear methods to `WorkspaceContext`.

### 12. WorkspaceAwareBackend Cache Wiring

Both `__call__` and `_get_backend()` on `WorkspaceAwareBackend` currently create new `NormalizedPathBackend` instances. Route them through the module-level `get_workspace_backend()` cache instead.

### 13. NormalizedPathBackend — No Changes

The backend already works with whatever `root_dir` it is given. The daemon passes the container path as `root_dir`. No modification needed.

### 14. Shell Execution — No Changes

The LLM sees container paths (e.g., `/var/lib/soothe/workspaces/project-a`), so shell commands it generates naturally reference container paths. The existing `_translate_virtual_paths_in_command()` handles virtual mode rewriting; container path mapping operates at a higher level (the workspace root itself) and does not conflict.

### 15. Multi-Client Isolation

Each client's workspace is a subdirectory under the shared mount point. The existing virtual mode sandboxing (`NormalizedPathBackend` with `virtual_mode=True`) restricts each loop's file operations to its `current_workspace` root. No new isolation mechanism is needed.

---

## Protocol Changes

### `loop_new` Request — No Changes

The client still sends `client_workspace` with its native path. The daemon handles translation internally.

### `loop_new` Response — New Field

| Field | Type | Description |
|-------|------|-------------|
| `workspace_mapping.host_root` | `str \| null` | Host root path (null when not configured) |
| `workspace_mapping.container_root` | `str \| null` | Container root path (null when not configured) |
| `workspace_mapping.client_workspace` | `str \| null` | Original client workspace path |
| `workspace_mapping.container_workspace` | `str \| null` | Translated container workspace path |

When `workspace_mount` is not configured, all four fields are `null`.

### Loop Metadata — New Field

| Field | Type | Description |
|-------|------|-------------|
| `workspace_mapping.host_root` | `str \| null` | Stored for reference (no longer used by re-resolution) |
| `workspace_mapping.container_root` | `str \| null` | Stored for reference (no longer used by re-resolution) |

Note: `workspace_mapping` in metadata is retained for debugging and SDK use, but `bind_execution_thread_for_loop` no longer reads it for re-resolution. It trusts `current_workspace` directly.

---

## Edge Cases

| Case | Handling |
|------|----------|
| Client workspace outside `host_root` | Daemon rejects `loop_new` with error explaining the constraint |
| `workspace_mount` not configured | Identity mapping — no translation, current behavior unchanged |
| Paths in command output (`grep`, `find`) | Contain container paths; SDK translates back to client paths via prefix swap |
| Shell `cd /host/path` | LLM will not generate this — it sees container paths as the workspace |
| Symlinks crossing mount boundary | Virtual mode sandbox prevents traversal outside workspace root |
| Paths embedded in log text | SDK best-effort prefix swap; some paths in freeform text may not translate (acceptable) |
| `soothe loop new` CLI without workspace | No translation needed — daemon uses persisted layout under `$SOOTHE_HOME/data/workspaces/` |
| Only one of host_root/container_root set | Config validation rejects at startup (both must be set or neither) |
| `loop_new` without `client_workspace` (Go client) | Translation is skipped; daemon-fallback workspace (`$SOOTHE_HOME/data/workspaces/`) is container-local |
| Stale `current_workspace` after migration | Path won't exist on disk; `bind_execution_thread_for_loop` detects and re-resolves |

---

## Backward Compatibility

- **Non-container deployments**: `workspace_mount` defaults to unconfigured. All code paths check `is_configured` before applying translation. Zero behavioral change.
- **Existing loop metadata**: Loops created before this RFC have no `workspace_mapping` field. `bind_execution_thread_for_loop` reads `current_workspace` from metadata; if missing, falls back to full re-resolution.
- **Pre-migration persisted workspaces**: `$SOOTHE_HOME/workspaces/<user>/ws_*` directories are migrated to `$SOOTHE_HOME/data/workspaces/` on daemon startup. Post-migration, `current_workspace` paths in metadata may be stale; the fallback in `bind_execution_thread_for_loop` handles this.
- **SDK versioning**: Older SDK clients that do not parse `workspace_mapping` will simply display container paths. This is functional but not ideal — SDK upgrade is recommended for container deployments.

---

## Files to Modify

| File | Change |
|------|--------|
| `config/config.template.yml` | Add `workspace_mount` section with `host_root` and `container_root` |
| `config/develop/nano.yml` | Add `workspace_mount` (disabled by default, both null) |
| `soothe/config/models.py` | Add `WorkspaceMountConfig` model |
| `soothe/core/workspace/resolution.py` | Add translation functions; update `cleanup_anonymous_workspaces` to use `data/workspaces` |
| `soothe/core/workspace/loop_workspace.py` | Change path to `data/workspaces`; thin wrapper for core resolution |
| `soothe/core/workspace/stream_resolution.py` | Thin wrapper for core resolution |
| `soothe/core/workspace/runtime_resolution.py` | Thin wrapper for core resolution |
| `soothe/core/workspace/core_resolution.py` | **New**: `WorkspacePrecedence`, `resolve_workspace()`, source checker registry |
| `soothe/core/workspace/context.py` | **New**: `WorkspaceContext` dataclass + ContextVar |
| `soothe/core/workspace/migration.py` | **New**: one-time directory migration `workspaces/` → `data/workspaces/` |
| `soothe/core/workspace/framework_filesystem.py` | Delegate to `WorkspaceContext` |
| `soothe/core/workspace/virtual_home.py` | Delegate to `WorkspaceContext` |
| `soothe/core/workspace/normalized_backend.py` | Use `get_workspace_backend()` cache |
| `soothe/core/workspace/__init__.py` | Export new types |
| `soothe-daemon/protocol/router.py` | Apply mapping in `_handle_loop_new`, guard translation on `client_workspace is not None` |
| `soothe-daemon/loop_isolation.py` | Trust persisted `current_workspace`; remove re-resolution and translation |
| `soothe-daemon/server.py` | Add startup validation for `workspace_mount`; add migration call |
| `soothe-sdk/client/session.py` | Parse `workspace_mapping` from `loop_new_response`, store `WorkspaceMapping` on session |
| `soothe-sdk/client/protocol.py` | Add `WorkspaceMapping` dataclass with boundary-safe translation |
| `soothe-cli/` (event display) | Apply client-path translation when rendering events in TUI and headless mode |
| `deploy/docker-compose.yml` | Add workspace volume mount |
| `deploy/config.yml.example` | Add `workspace_mount` section |

---

## Testing

- Unit tests for `translate_client_path_to_container()` — identity mapping, valid mapping, workspace outside host_root, boundary-safe prefix
- Unit tests for `translate_container_path_to_client()` — identity mapping, valid mapping, paths not under container_root
- Unit tests for `WorkspaceMountConfig` — valid pair, invalid single-field, both null, empty strings
- Unit tests for `$SOOTHE_HOME/data/workspaces/` path computation
- Unit tests for `resolve_workspace()` with each precedence level
- Unit tests for `WorkspaceContext` set/get/clear
- Integration test: `loop_new` with `workspace_mount` configured → response contains mapping → workspace metadata stores container path
- Integration test: `loop_new` without `client_workspace` → no translation → persisted workspace under `data/workspaces/`
- Integration test: `loop_new` with workspace outside `host_root` → error response
- Integration test: `bind_execution_thread_for_loop` uses persisted `current_workspace` (no re-resolution)
- Integration test: `bind_execution_thread_for_loop` falls back when `current_workspace` missing
- Migration tests: old layout → new layout, Docker mount no-op
- SDK unit test: `WorkspaceMapping.translate_to_client()` boundary-safe prefix swap
- SDK unit test: `WorkspaceMapping.translate_to_container()` reverse swap
- Existing workspace tests updated for new paths

---

## Future Extensions

### Proxy Access Mode

This design is compatible with a future "proxy" mode where file ops are routed to the client over WebSocket. The `workspace_mount` config can gain an `access_mode` field:

```yaml
workspace_mount:
  access_mode: mount    # mount (current) | proxy (future)
```

In proxy mode, the daemon would use the same `WorkspaceMapping` but route file operations to the client instead of reading from a local filesystem. The SDK translation layer remains the same.

### Arbitrary Client Paths

The current convention requires all client workspaces to live under `host_root`. For deployments where client paths are arbitrary (no common parent), the proxy mode would be the appropriate solution. Volume mounting cannot cover arbitrary paths without mounting `/` (security risk).

---

## Open Questions

_None at this time._
