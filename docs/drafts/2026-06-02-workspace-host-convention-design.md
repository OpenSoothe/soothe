# Workspace Host Convention for Container Deployments

**Date**: 2026-06-02
**Status**: Draft

## Problem

When the Soothe daemon runs in a Docker container, the client and daemon operate on different filesystems. Client paths (e.g. `/var/run/soothe/workspaces/project-a`) don't exist inside the container, so all filesystem tools, shell execution, and path resolution break.

The current architecture assumes a shared filesystem: `loop_new` stores `client_workspace` as-is, and `NormalizedPathBackend` operates directly on that path. There is no translation layer.

## Solution

A **prefix-based path mapping** between client paths and container paths, configured at daemon startup and applied at the `loop_new` handshake boundary. The convention: all client workspaces live under one host directory, which is volume-mounted into the container at a fixed mount point.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Client (host filesystem)                            │
│  /var/run/soothe/workspaces/project-a/src/main.py    │
│  /var/run/soothe/workspaces/project-b/README.md      │
└──────────────────────────┬───────────────────────────┘
                           │ loop_new { client_workspace: "/var/run/soothe/workspaces/project-a" }
                           ▼
┌─────────────────────────────────────────────────────┐
│  Daemon (container filesystem)                       │
│  Config: workspace_mount.host_root = /var/run/soothe/workspaces
│          workspace_mount.container_root = /workspaces │
│                                                      │
│  /workspaces/project-a/src/main.py  ← actual I/O    │
│  /workspaces/project-b/README.md                     │
│                                                      │
│  LLM sees: /workspaces/project-a/...                 │
│  Tools read/write: /workspaces/project-a/...         │
└──────────────────────────┬───────────────────────────┘
                           │ events contain /workspaces/... paths
                           ▼
┌─────────────────────────────────────────────────────┐
│  SDK (client side)                                   │
│  Translates /workspaces/... → /var/run/soothe/workspaces/...
│  User sees: /var/run/soothe/workspaces/project-a/... │
└─────────────────────────────────────────────────────┘
```

### Core Principle

The LLM and all tools inside the daemon only ever see **container paths**. The SDK transparently translates to **client paths** for display. This avoids the "phantom path" problem where the LLM reasons about paths that don't exist on its filesystem.

## Component Design

### 1. Daemon Configuration — `workspace_mount`

New config section:

```yaml
workspace_mount:
  host_root: /var/run/soothe/workspaces    # path on the Docker host
  container_root: /workspaces               # path inside the container
```

- **`host_root`**: The parent directory on the host machine that is volume-mounted into the container. All client workspaces must be under this directory.
- **`container_root`**: The mount point inside the container where `host_root` is mounted.

**Default behavior**: When `workspace_mount` is not configured (or both fields are empty/null), the mapping is identity — no translation. This means zero impact on existing non-container deployments.

**Docker Compose**:
```yaml
services:
  soothed:
    volumes:
      - /var/run/soothe/workspaces:/workspaces
```

### 2. Path Translation Functions

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
        return Path(client_path)

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
    If the path is not under container_root, returns it unchanged (not all paths
    need translation — e.g. /etc/config).
    """
    if not host_root or not container_root:
        return Path(container_path)

    host = Path(host_root).resolve()
    container = Path(container_root).resolve()
    resolved = Path(container_path).resolve()

    try:
        relative = resolved.relative_to(container)
    except ValueError:
        return resolved  # not a workspace path, no translation

    return host / relative
```

### 3. `loop_new` Handshake — Daemon-Side

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
host_root = d._config.workspace_mount.host_root if d._config.workspace_mount else None
container_root = d._config.workspace_mount.container_root if d._config.workspace_mount else None

try:
    container_workspace = translate_client_path_to_container(
        resolved_workspace,
        host_root=host_root,
        container_root=container_root,
    )
except ValueError as e:
    # Reject loop creation if workspace outside host_root
    await d._send_client_message(client_id, {
        "type": "error",
        "error": str(e),
        "request_id": request_id,
    })
    return

# Persist both paths
meta_updates = {
    "client_workspace": client_workspace,          # original client path
    "current_workspace": str(container_workspace), # container path for tool execution
    "workspace_mapping": {                         # NEW: for SDK reverse translation
        "host_root": str(host_root) if host_root else None,
        "container_root": str(container_root) if container_root else None,
    },
}
```

**Response** includes the mapping:

```python
await d._send_client_message(client_id, {
    "type": "loop_new_response",
    "loop_id": loop_id,
    "success": True,
    "is_ephemeral": is_ephemeral,
    "request_id": request_id,
    "workspace_mapping": {                         # NEW
        "host_root": str(host_root) if host_root else None,
        "container_root": str(container_root) if container_root else None,
        "client_workspace": client_workspace,
        "container_workspace": str(container_workspace),
    },
})
```

### 4. `NormalizedPathBackend` — No Changes

The backend already works with whatever `root_dir` it's given. The daemon passes the container path as `root_dir`. No modification needed.

### 5. Loop Isolation Re-resolution

In `bind_execution_thread_for_loop` (loop_isolation.py), the same translation must be applied when re-resolving workspace from persisted metadata:

```python
# Existing code reads client_workspace from metadata
raw_client_ws = metadata.get("client_workspace")
# ...
resolved = resolve_loop_workspace(...)

# NEW: re-apply container translation
container_workspace = translate_client_path_to_container(
    resolved,
    host_root=host_root,
    container_root=container_root,
)
daemon._thread_registry.set_workspace(thread_id, container_workspace)
```

The `host_root` and `container_root` values come from the daemon config (which is static for the daemon's lifetime). They can also be read from the loop's persisted `workspace_mapping` metadata as a fallback.

### 6. SDK Path Translation

The SDK receives `workspace_mapping` from the `loop_new_response` and stores it on the session.

Add translation in `soothe_sdk/client/session.py`:

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
```

The SDK applies `translate_to_client()` on:
- Tool output paths in event data
- File path references in streaming events
- Log messages containing container paths

**Translation is a prefix swap**: when a path starts with `container_root`, replace that prefix with `host_root`. Paths outside `container_root` are left unchanged.

### 7. Multi-Client Isolation

Each client's workspace is a subdirectory under the shared mount point. The existing virtual mode sandboxing (`NormalizedPathBackend` with `virtual_mode=True`) restricts each loop's file operations to its `current_workspace` root. No new isolation mechanism is needed.

### 8. Shell Execution

The LLM sees container paths (e.g. `/workspaces/project-a`), so shell commands it generates naturally reference container paths. No additional translation is needed in `execution.py`.

The existing `_translate_virtual_paths_in_command()` handles virtual mode rewriting. Container path mapping operates at a higher level (the workspace root itself), so it doesn't conflict.

## Edge Cases

| Case | Handling |
|------|----------|
| Client workspace outside `host_root` | Daemon rejects `loop_new` with error: "workspace must be under configured host_root" |
| `workspace_mount` not configured | Identity mapping — no translation, current behavior unchanged |
| Paths in command output (`grep`, `find`) | Contain container paths; SDK translates back to client paths via prefix swap |
| Shell `cd /host/path` | LLM won't generate this — it sees `/workspaces/...` as the workspace |
| Symlinks crossing mount boundary | Virtual mode sandbox prevents traversal outside workspace root |
| Paths embedded in log text | SDK best-effort prefix swap; some paths in freeform text may not translate (acceptable) |
| `soothe loop new` CLI without workspace | No translation needed — daemon uses persisted layout under `$SOOTHE_HOME` |

## Files to Modify

| File | Change |
|------|--------|
| `config/config.template.yml` | Add `workspace_mount` section with `host_root` and `container_root` |
| `config/config.dev.yml` | Add `workspace_mount` (disabled by default, both null) |
| `soothe/config/models.py` | Add `WorkspaceMountConfig` model with `host_root` and `container_root` fields |
| `soothe/core/workspace/resolution.py` | Add `translate_client_path_to_container()` and `translate_container_path_to_client()` |
| `soothe-daemon/protocol/router.py` | Apply mapping in `_handle_loop_new`, add mapping to response, validate workspace under host_root |
| `soothe-daemon/loop_isolation.py` | Apply mapping in `bind_execution_thread_for_loop` when re-resolving workspace |
| `soothe-sdk/client/session.py` | Parse `workspace_mapping` from `loop_new_response`, store `WorkspaceMapping` on session |
| `soothe-sdk/client/protocol.py` | Add `WorkspaceMapping` dataclass and path translation helpers |
| `soothe-cli/` (event display) | Apply client-path translation when rendering events in TUI and headless mode |
| `deploy/docker-compose.yml` | Add workspace volume mount with comments explaining the convention |

## Testing

- Unit tests for `translate_client_path_to_container()` and `translate_container_path_to_client()` (identity mapping, valid mapping, workspace outside host_root, paths not under container_root)
- Integration test: `loop_new` with `workspace_mount` config → response contains mapping → workspace metadata has container path
- Integration test: `loop_new` with workspace outside `host_root` → error response
- SDK test: `WorkspaceMapping.translate_to_client()` prefix swap
- SDK test: event path translation end-to-end

## Future Extension

This design is compatible with a future "proxy" mode where file ops are routed to the client over WebSocket. The `workspace_mount` config can gain an `access_mode` field:

```yaml
workspace_mount:
  access_mode: mount    # mount (current) | proxy (future)
```

In proxy mode, the daemon would use the same `WorkspaceMapping` but route file operations to the client instead of reading from a local filesystem. The SDK translation layer stays the same.
