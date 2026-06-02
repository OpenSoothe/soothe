# IG-458: Workspace Host Convention (RFC-621)

## Summary

Implement prefix-based path mapping between client workspace paths and container paths for Docker deployments. When `workspace_mount` is configured, the daemon translates client paths at the `loop_new` boundary; the SDK translates container paths back for display. Non-container deployments are unaffected.

**RFC**: RFC-621
**Status**: In Progress

## Scope

- Add `workspace_mount` config model and YAML entries
- Add path translation functions in `soothe.core.workspace.resolution`
- Apply translation in daemon `loop_new` handler and loop isolation
- Add `WorkspaceMapping` to SDK and apply in CLI event rendering
- Update `deploy/docker-compose.yml` with workspace volume mount

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

**File**: `packages/soothe/src/soothe/config/settings.py`

Add after `filesystem_middleware` field (line ~326):

```python
workspace_mount: WorkspaceMountConfig = Field(default_factory=WorkspaceMountConfig)
"""Container workspace path mapping (RFC-621)."""
```

Add import for `WorkspaceMountConfig` in the import block (lines 13-36).

### Step 2: YAML Config Files

**File**: `config/config.template.yml`

Add after the WORKSPACE CONFIGURATION comments (after line 532):

```yaml
# Workspace mount mapping for container deployments (RFC-621).
# When the daemon runs inside a Docker container, client paths must be translated
# to container paths. Set both fields to enable; leave both unset for local runs.
# The Docker volume mount must match: -v <host_root>:<container_root>
workspace_mount:
  host_root: null           # e.g. /var/run/soothe/workspaces
  container_root: null      # e.g. /workspaces
```

**File**: `config/config.dev.yml`

Add the same section with both fields as `null` (disabled by default).

### Step 3: Path Translation Functions

**File**: `packages/soothe/src/soothe/core/workspace/resolution.py`

Add two functions after `validate_client_workspace()` (after line ~191):

```python
def translate_client_path_to_container(
    client_path: str | Path,
    *,
    host_root: str | Path | None = None,
    container_root: str | Path | None = None,
) -> Path:
    """Translate a client-side path to its container-side equivalent (RFC-621).

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
    """Translate a container-side path to its client-side equivalent (RFC-621).

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

### Step 4: Daemon `loop_new` Handler

**File**: `packages/soothe-daemon/src/soothe_daemon/protocol/router.py`

In `_handle_loop_new` (lines 1108-1227), after `resolved_workspace` is computed (line ~1181), add translation:

```python
# --- RFC-621: translate client path to container path ---
from soothe.core.workspace.resolution import translate_client_path_to_container

mount = d._config.workspace_mount
host_root = mount.host_root if mount and mount.is_configured else None
container_root = mount.container_root if mount and mount.is_configured else None

try:
    effective_workspace = translate_client_path_to_container(
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

Update `meta_updates` dict (line ~1197) — change `current_workspace` to use `effective_workspace` and add `workspace_mapping`:

```python
meta_updates: dict[str, Any] = {
    "is_ephemeral": is_ephemeral,
    "last_message_at": now,
    "current_workspace": str(effective_workspace),   # was resolved_workspace
}
if client_workspace is not None:
    meta_updates["client_workspace"] = client_workspace
if host_root is not None:
    meta_updates["workspace_mapping"] = {
        "host_root": host_root,
        "container_root": container_root,
    }
```

Update `loop_new_response` (line ~1218) to include mapping:

```python
response_msg: dict[str, Any] = {
    "type": "loop_new_response",
    "loop_id": loop_id,
    "success": True,
    "is_ephemeral": is_ephemeral,
    "request_id": request_id,
}
if host_root is not None:
    response_msg["workspace_mapping"] = {
        "host_root": host_root,
        "container_root": container_root,
        "client_workspace": client_workspace,
        "container_workspace": str(effective_workspace),
    }
await d._send_client_message(client_id, response_msg)
```

### Step 5: Loop Isolation Re-resolution

**File**: `packages/soothe-daemon/src/soothe_daemon/loop_isolation.py`

In `bind_execution_thread_for_loop` (lines 25-112), after `loop_workspace` is resolved (line ~97), add translation:

```python
# --- RFC-621: re-apply container path translation ---
from soothe.core.workspace.resolution import translate_client_path_to_container

mapping = metadata.get("workspace_mapping", {})
ws_host_root = mapping.get("host_root")
ws_container_root = mapping.get("container_root")

try:
    loop_workspace = translate_client_path_to_container(
        loop_workspace,
        host_root=ws_host_root,
        container_root=ws_container_root,
    )
except ValueError:
    pass  # fallback to unresolved workspace
```

This goes before `daemon._thread_registry.set_workspace(thread_id, loop_workspace)` (line ~99).

### Step 6: SDK WorkspaceMapping

**File**: `packages/soothe-sdk/src/soothe_sdk/client/session.py`

After extracting `loop_id` from `loop_new_response` (line ~108), parse the mapping:

```python
# --- RFC-621: store workspace mapping ---
from soothe_sdk.client.protocol import WorkspaceMapping

mapping_data = new_resp.get("workspace_mapping")
if mapping_data and mapping_data.get("host_root"):
    workspace_mapping = WorkspaceMapping(
        host_root=mapping_data["host_root"],
        container_root=mapping_data["container_root"],
    )
else:
    workspace_mapping = WorkspaceMapping(host_root=None, container_root=None)
```

Store on the session/client object so it's available for event translation. The exact storage location depends on the session architecture — likely as an attribute on the `DaemonSession` or `WebSocketClient`.

**File**: `packages/soothe-sdk/src/soothe_sdk/client/protocol.py`

Add `WorkspaceMapping` dataclass:

```python
from dataclasses import dataclass

@dataclass
class WorkspaceMapping:
    """Bidirectional path mapping for container deployments (RFC-621)."""

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
        """Translate a client path to a container path (outgoing messages)."""
        if not self.host_root or not self.container_root:
            return path
        if path.startswith(self.host_root):
            return self.container_root + path[len(self.host_root):]
        return path
```

### Step 7: CLI Event Path Translation

**File**: `packages/soothe-sdk/src/soothe_sdk/utils/formatting.py`

In `convert_and_abbreviate_path()` (lines 50-89), add workspace mapping translation before the existing abbreviation logic. The mapping needs to be accessible — either passed as a parameter or stored in a module-level context variable.

Simplest approach: add an optional `workspace_mapping` parameter:

```python
def convert_and_abbreviate_path(
    path: str,
    *,
    base_dir: str | None = None,
    workspace_mapping: WorkspaceMapping | None = None,
) -> str:
    if workspace_mapping and workspace_mapping.is_configured:
        path = workspace_mapping.translate_to_client(path)
    # ... existing abbreviation logic ...
```

**File**: `packages/soothe-cli/src/soothe_cli/tui/tool_display.py`

Where `convert_and_abbreviate_path` is called, pass the session's `workspace_mapping`.

### Step 8: Docker Compose

**File**: `deploy/docker-compose.yml`

Add workspace volume mount to `soothed` service:

```yaml
soothed:
  volumes:
    - soothe_daemon_data:/var/lib/soothe
    - ./config.yml:/var/lib/soothe/config/config.yml:ro
    # RFC-621: Workspace host convention — mount host workspace root
    # Adjust the host path to match workspace_mount.host_root in config.yml
    # - /var/run/soothe/workspaces:/workspaces
```

The mount is commented out by default (not all deployments use it). Uncomment and set the host path when enabling `workspace_mount` in config.

### Step 9: Tests

**File**: `packages/soothe/tests/unit/core/workspace/test_workspace_mount.py`

```python
"""Tests for workspace host convention path mapping (RFC-621, IG-458)."""

import pytest
from pathlib import Path

from soothe.core.workspace.resolution import (
    translate_client_path_to_container,
    translate_container_path_to_client,
)
from soothe.config.models import WorkspaceMountConfig


class TestTranslateClientPathToContainer:
    def test_identity_when_not_configured(self):
        assert translate_client_path_to_container("/foo/bar") == Path("/foo/bar")

    def test_valid_mapping(self):
        result = translate_client_path_to_container(
            "/var/run/soothe/workspaces/project-a",
            host_root="/var/run/soothe/workspaces",
            container_root="/workspaces",
        )
        assert result == Path("/workspaces/project-a")

    def test_nested_path(self):
        result = translate_client_path_to_container(
            "/var/run/soothe/workspaces/project-a/src/main.py",
            host_root="/var/run/soothe/workspaces",
            container_root="/workspaces",
        )
        assert result == Path("/workspaces/project-a/src/main.py")

    def test_workspace_outside_host_root_raises(self):
        with pytest.raises(ValueError, match="not under configured host_root"):
            translate_client_path_to_container(
                "/other/path/project",
                host_root="/var/run/soothe/workspaces",
                container_root="/workspaces",
            )

    def test_host_root_itself(self):
        result = translate_client_path_to_container(
            "/var/run/soothe/workspaces",
            host_root="/var/run/soothe/workspaces",
            container_root="/workspaces",
        )
        assert result == Path("/workspaces")


class TestTranslateContainerPathToClient:
    def test_identity_when_not_configured(self):
        assert translate_container_path_to_client("/foo/bar") == Path("/foo/bar")

    def test_valid_mapping(self):
        result = translate_container_path_to_client(
            "/workspaces/project-a",
            host_root="/var/run/soothe/workspaces",
            container_root="/workspaces",
        )
        assert result == Path("/var/run/soothe/workspaces/project-a")

    def test_path_outside_container_root_unchanged(self):
        result = translate_container_path_to_client(
            "/etc/config",
            host_root="/var/run/soothe/workspaces",
            container_root="/workspaces",
        )
        assert result == Path("/etc/config")


class TestWorkspaceMountConfig:
    def test_both_none_is_valid(self):
        cfg = WorkspaceMountConfig()
        assert not cfg.is_configured

    def test_both_set_is_valid(self):
        cfg = WorkspaceMountConfig(host_root="/host", container_root="/container")
        assert cfg.is_configured

    def test_only_one_set_raises(self):
        with pytest.raises(ValueError, match="must both be set"):
            WorkspaceMountConfig(host_root="/host")

    def test_only_container_set_raises(self):
        with pytest.raises(ValueError, match="must both be set"):
            WorkspaceMountConfig(container_root="/container")
```

**File**: `packages/soothe-sdk/tests/test_workspace_mapping.py`

```python
"""Tests for SDK WorkspaceMapping (RFC-621, IG-458)."""

from soothe_sdk.client.protocol import WorkspaceMapping


class TestWorkspaceMapping:
    def test_translate_to_client_when_not_configured(self):
        m = WorkspaceMapping(host_root=None, container_root=None)
        assert m.translate_to_client("/workspaces/foo") == "/workspaces/foo"

    def test_translate_to_client_valid(self):
        m = WorkspaceMapping(host_root="/host/ws", container_root="/workspaces")
        assert m.translate_to_client("/workspaces/project-a/src/main.py") == "/host/ws/project-a/src/main.py"

    def test_translate_to_client_path_outside_container_root(self):
        m = WorkspaceMapping(host_root="/host/ws", container_root="/workspaces")
        assert m.translate_to_client("/etc/config") == "/etc/config"

    def test_translate_to_container_valid(self):
        m = WorkspaceMapping(host_root="/host/ws", container_root="/workspaces")
        assert m.translate_to_container("/host/ws/project-a") == "/workspaces/project-a"

    def test_translate_to_container_path_outside_host_root(self):
        m = WorkspaceMapping(host_root="/host/ws", container_root="/workspaces")
        assert m.translate_to_container("/other/path") == "/other/path"
```

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
