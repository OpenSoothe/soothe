# RFC-621: Workspace Host Convention for Container Deployments

**RFC**: 621
**Title**: Workspace Host Convention: Path Mapping for Containerized Daemon
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-06-02
**Authors**: Platonic Coding Workflow
**Dependencies**: RFC-103, RFC-450

---

## Abstract

Introduce a prefix-based path mapping layer that translates client workspace paths to container paths when the daemon runs inside a Docker container. A new `workspace_mount` configuration section declares the host and container root directories. The daemon applies the mapping at the `loop_new` handshake boundary so that all tool execution, filesystem operations, and LLM reasoning use container-native paths. The SDK performs reverse translation for display. Non-container deployments are unaffected (identity mapping when unconfigured).

---

## Motivation

When the Soothe daemon runs in a Docker container, the client and daemon operate on different filesystems. The current architecture assumes a shared filesystem: `loop_new` stores `client_workspace` as-is, and `NormalizedPathBackend` operates directly on that path. Inside a container, client paths like `/var/run/soothe/workspaces/project-a` do not exist, causing all filesystem tools, shell execution, and path resolution to fail.

Container deployments are already supported via `deploy/docker-compose.yml`, but no workspace path translation exists. The daemon can run, but it cannot operate on client files.

---

## Design Goals

1. **Transparent path mapping** — daemon tools and LLM see container-native paths, SDK translates back for display.
2. **Convention over configuration** — one host root, one container root, prefix-based swap. No per-client mapping tables.
3. **Zero impact on non-container deployments** — unconfigured `workspace_mount` means identity mapping (no translation).
4. **Multi-client compatible** — each client's workspace is a subdirectory under the shared mount point; existing virtual-mode sandboxing provides isolation.
5. **Extensible to remote filesystems** — the mapping abstraction supports future "proxy" mode where file ops are routed to the client over WebSocket.

---

## Proposed Solution

### 1. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│  Client (host filesystem)                            │
│  /var/run/soothe/workspaces/project-a/src/main.py    │
└──────────────────────────┬───────────────────────────┘
                           │ loop_new { client_workspace: "/var/run/soothe/workspaces/project-a" }
                           ▼
┌─────────────────────────────────────────────────────┐
│  Daemon (container filesystem)                       │
│  workspace_mount.host_root = /var/run/soothe/workspaces
│  workspace_mount.container_root = /workspaces        │
│                                                      │
│  /workspaces/project-a/src/main.py  ← actual I/O    │
│  LLM sees: /workspaces/project-a/...                 │
└──────────────────────────┬───────────────────────────┘
                           │ events contain /workspaces/... paths
                           ▼
┌─────────────────────────────────────────────────────┐
│  SDK (client side)                                   │
│  Translates /workspaces/... → /var/run/soothe/workspaces/...
│  User sees: /var/run/soothe/workspaces/project-a/... │
└─────────────────────────────────────────────────────┘
```

**Core principle**: The LLM and all tools inside the daemon only ever see container paths. The SDK transparently translates to client paths for display. This avoids the "phantom path" problem where the LLM reasons about paths that do not exist on its filesystem.

### 2. Configuration — `workspace_mount`

New config section in `SootheConfig`:

```yaml
workspace_mount:
  host_root: /var/run/soothe/workspaces    # path on the Docker host
  container_root: /workspaces               # path inside the container
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
      - /var/run/soothe/workspaces:/workspaces
```

The `workspace_mount` config must match the Docker volume declaration. Mismatch is detected at daemon startup (see §5 Validation).

### 3. Config Model

```python
class WorkspaceMountConfig(BaseModel):
    """Path mapping for containerized daemon deployments."""

    host_root: str | None = None
    container_root: str | None = None

    @model_validator(mode="after")
    def _validate_pair(self) -> WorkspaceMountConfig:
        """Both fields must be set together, or neither."""
        if bool(self.host_root) != bool(self.container_root):
            msg = (
                "workspace_mount.host_root and workspace_mount.container_root "
                "must both be set or both be unset"
            )
            raise ValueError(msg)
        return self

    @property
    def is_configured(self) -> bool:
        return self.host_root is not None and self.container_root is not None
```

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
```

**Persisted metadata** (expanded):

```python
meta_updates = {
    "client_workspace": client_workspace,          # original client path
    "current_workspace": str(container_workspace), # container path for tool execution
    "workspace_mapping": {                         # NEW
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
    "workspace_mapping": {                         # NEW
        "host_root": host_root,
        "container_root": container_root,
        "client_workspace": client_workspace,
        "container_workspace": str(container_workspace),
    },
}
```

### 7. Loop Isolation Re-resolution

In `bind_execution_thread_for_loop` (loop_isolation.py), the same translation is applied when re-resolving workspace from persisted metadata:

```python
# Read mapping from persisted metadata (fallback to daemon config)
mapping = metadata.get("workspace_mapping", {})
host_root = mapping.get("host_root")
container_root = mapping.get("container_root")

container_workspace = translate_client_path_to_container(
    resolved,
    host_root=host_root,
    container_root=container_root,
)
daemon._thread_registry.set_workspace(thread_id, container_workspace)
```

The `workspace_mapping` is persisted in loop metadata so that re-resolution works even if the daemon config changes between restarts (unlikely but defensive). The daemon config values are the primary source; metadata serves as fallback.

### 8. SDK Path Translation

The SDK receives `workspace_mapping` from the `loop_new_response` and stores it on the session.

```python
@dataclass
class WorkspaceMapping:
    host_root: str | None
    container_root: str | None

    def translate_to_client(self, path: str) -> str:
        """Translate a container path to a client path for display."""
        if not self.host_root or not self.container_root:
            return path
        if path.startswith(self.container_root):
            return self.host_root + path[len(self.container_root):]
        return path

    def translate_to_container(self, path: str) -> str:
        """Translate a client path to a container path (for outgoing messages)."""
        if not self.host_root or not self.container_root:
            return path
        if path.startswith(self.host_root):
            return self.container_root + path[len(self.host_root):]
        return path
```

The SDK applies `translate_to_client()` on:
- Tool output paths in event data
- File path references in streaming events
- Log messages containing container paths (best-effort)

Translation is a **prefix swap**: when a path starts with `container_root`, replace that prefix with `host_root`. Paths outside `container_root` are left unchanged.

### 9. NormalizedPathBackend — No Changes

The backend already works with whatever `root_dir` it is given. The daemon passes the container path as `root_dir`. No modification needed.

### 10. Shell Execution — No Changes

The LLM sees container paths (e.g. `/workspaces/project-a`), so shell commands it generates naturally reference container paths. The existing `_translate_virtual_paths_in_command()` handles virtual mode rewriting; container path mapping operates at a higher level (the workspace root itself) and does not conflict.

### 11. Multi-Client Isolation

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
| `workspace_mapping.host_root` | `str \| null` | Stored for re-resolution on thread bind |
| `workspace_mapping.container_root` | `str \| null` | Stored for re-resolution on thread bind |

---

## Edge Cases

| Case | Handling |
|------|----------|
| Client workspace outside `host_root` | Daemon rejects `loop_new` with error explaining the constraint |
| `workspace_mount` not configured | Identity mapping — no translation, current behavior unchanged |
| Paths in command output (`grep`, `find`) | Contain container paths; SDK translates back to client paths via prefix swap |
| Shell `cd /host/path` | LLM will not generate this — it sees `/workspaces/...` as the workspace |
| Symlinks crossing mount boundary | Virtual mode sandbox prevents traversal outside workspace root |
| Paths embedded in log text | SDK best-effort prefix swap; some paths in freeform text may not translate (acceptable) |
| `soothe loop new` CLI without workspace | No translation needed — daemon uses persisted layout under `$SOOTHE_HOME` |
| Only one of host_root/container_root set | Config validation rejects at startup (both must be set or neither) |

---

## Backward Compatibility

- **Non-container deployments**: `workspace_mount` defaults to unconfigured. All code paths check `is_configured` before applying translation. Zero behavioral change.
- **Existing loop metadata**: Loops created before this RFC have no `workspace_mapping` field. Re-resolution falls back to daemon config, and if that is also unconfigured, identity mapping applies.
- **SDK versioning**: Older SDK clients that do not parse `workspace_mapping` will simply display container paths. This is functional but not ideal — SDK upgrade is recommended for container deployments.

---

## Files to Modify

| File | Change |
|------|--------|
| `config/config.template.yml` | Add `workspace_mount` section with `host_root` and `container_root` |
| `config/config.dev.yml` | Add `workspace_mount` (disabled by default, both null) |
| `soothe/config/models.py` | Add `WorkspaceMountConfig` model |
| `soothe/core/workspace/resolution.py` | Add `translate_client_path_to_container()` and `translate_container_path_to_client()` |
| `soothe-daemon/protocol/router.py` | Apply mapping in `_handle_loop_new`, add mapping to response, validate workspace under host_root |
| `soothe-daemon/loop_isolation.py` | Apply mapping in `bind_execution_thread_for_loop` when re-resolving workspace |
| `soothe-daemon/server.py` | Add startup validation for `workspace_mount` config |
| `soothe-sdk/client/session.py` | Parse `workspace_mapping` from `loop_new_response`, store `WorkspaceMapping` on session |
| `soothe-sdk/client/protocol.py` | Add `WorkspaceMapping` dataclass and path translation helpers |
| `soothe-cli/` (event display) | Apply client-path translation when rendering events in TUI and headless mode |
| `deploy/docker-compose.yml` | Add workspace volume mount with comments explaining the convention |

---

## Testing

- Unit tests for `translate_client_path_to_container()` — identity mapping, valid mapping, workspace outside host_root, relative paths
- Unit tests for `translate_container_path_to_client()` — identity mapping, valid mapping, paths not under container_root
- Unit tests for `WorkspaceMountConfig` — valid pair, invalid single-field, both null
- Integration test: `loop_new` with `workspace_mount` configured → response contains mapping → workspace metadata stores container path
- Integration test: `loop_new` with workspace outside `host_root` → error response
- Integration test: `bind_execution_thread_for_loop` with persisted `workspace_mapping` → re-resolves to container path
- SDK unit test: `WorkspaceMapping.translate_to_client()` prefix swap
- SDK unit test: `WorkspaceMapping.translate_to_container()` reverse swap
- SDK integration test: event path translation end-to-end

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
