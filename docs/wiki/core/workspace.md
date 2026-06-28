# Workspace Management

Unified workspace resolution, path validation, and sandbox boundaries.

---

## What This Module Is

The workspace module (`soothe.foundation.workspace`) resolves, validates, and isolates the directories where Soothe agents operate. It's the security boundary between agent file operations and the host filesystem. Every tool that reads, writes, or lists files goes through workspace-aware resolution.

The module provides: daemon workspace resolution (ephemeral fallback), client workspace validation, stream-scoped workspace resolution (RFC-103), the `FrameworkFilesystem` singleton, and a workspace-aware backend wrapper.

**Source**: `packages/soothe/src/soothe/foundation/workspace/` (`resolution.py`, `framework_filesystem.py`, `normalized_backend.py`, `loop_workspace.py`, `stream_resolution.py`)

---

## The Workspace Resolution Hierarchy

Workspaces resolve through a priority chain, depending on context:

### Daemon Workspace (Fallback)

`resolve_daemon_workspace()` is the **fallback** when no user workspace is resolved. Priority:

1. `SOOTHE_WORKSPACE` environment variable (absolute override).
2. TEMP directory: `$TEMP/soothe-daemon-workspace` (ephemeral — **not persisted across restarts**).

This is only for anonymous users without a `client_workspace`. The daemon workspace is intentionally ephemeral to avoid accumulating files from anonymous sessions.

### Client Workspace

Users can specify a `client_workspace` path. This is validated against `INVALID_WORKSPACE_DIRS` — a set of system directories (`/`, `/etc`, `/usr`, `/bin`, `/root`, etc.) that must never be used as a workspace. The validation raises `ValueError` if the resolved path matches a system directory.

### Loop-Scoped Workspace (RFC-103)

For daemon runs, `resolve_persisted_loop_workspace()` resolves `$SOOTHE_HOME/data/workspaces/<user>/ws_<hash>`. The hash is computed from `user_id` and a scope key (`client_workspace_id` or `loop_id`):

- **Anonymous users** (`user_id` is empty/None) → directory segment is `anonymous`, and the hash uses an empty user string.
- **Named users** → user_id is sanitized (`[^w-.@]+` → `_`) and used in the path and hash.

This creates per-loop isolation: each loop gets its own workspace directory, preventing cross-loop file contamination.

### Stream Workspace

`resolve_workspace_for_stream(stream_id, config)` resolves the workspace for a specific runner stream. This is what the runner calls in its pre-stream phase.

---

## FrameworkFilesystem — The Singleton

`FrameworkFilesystem` is a singleton (`_instance` class variable) initialized once with config and policy. It provides the consistent filesystem backend for:

- **Tool operations** (via middleware)
- **Framework operations** (reports, checkpoints, manifests)
- **CLI operations** (final reports, health checks)

### Virtual Mode — The Sandbox Switch

The critical design decision: `virtual_mode` controls whether paths are sandboxed.

- **`virtual_mode=True`** (default when `security.allow_paths_outside_workspace` is `False`) — all paths treated as virtual under `root_dir`. A path like `/etc/passwd` becomes `{root}/etc/passwd`. The agent cannot escape the workspace.
- **`virtual_mode=False`** — absolute paths used as-is. A path like `/etc/passwd` writes to the real `/etc/passwd`. Relative paths resolve under root.

This is not a "bug workaround" — it's the documented sandbox semantics. The default (`True`) ensures agents operate in a sandbox. Setting `allow_paths_outside_workspace=True` disables sandboxing, which is appropriate only for trusted local CLI usage.

### Workspace-Aware Backend

`FrameworkFilesystem.initialize()` creates a `WorkspaceAwareBackend` that reads the active workspace from a **ContextVar** (RFC-103). This means the workspace can change per-async-task without reinitializing the singleton. The backend reads the ContextVar on each operation, allowing concurrent loops with different workspaces to share the same singleton instance.

---

## Anonymous Workspace Cleanup

`cleanup_anonymous_workspaces()` runs at daemon shutdown. It removes:
- `$SOOTHE_HOME/data/workspaces/anonymous/` (current layout)
- Legacy flat `anon_*` directories (pre-migration layout)
- Old `$SOOTHE_HOME/workspaces/anonymous/` (pre-migration)

This prevents ephemeral anonymous workspaces from accumulating on disk across daemon restarts.

---

## Migration Support

The `migration.py` module handles workspace layout migrations between Soothe versions. The current layout is `$SOOTHE_HOME/data/workspaces/<user>/ws_<hash>`, but older versions used different paths. The migration code moves workspaces to the current layout transparently.

---

## Path Validation

Workspace validation checks:
- Path exists and is a directory
- Path is readable (and writable if required)
- Path is not in `INVALID_WORKSPACE_DIRS` (system directories)
- Path complies with the security policy (no forbidden patterns, appropriate permissions)

Security validation (`validate_workspace_security`) checks the path against the `PolicyProtocol` — ensuring the policy allows read/write/execute on that path.

---

## Integration Points

- **SootheRunner** — calls `resolve_workspace_for_stream()` in the pre-stream phase; passes workspace to StrangeLoop via `config.configurable`.
- **CoreAgent** — receives workspace via `config.configurable.workspace`; `WorkspaceContextMiddleware` injects it into tool context.
- **StrangeLoop** — receives workspace as a parameter; uses it for skill sync and `filesystem_virtual_mode` detection.
- **Tools** — all filesystem tools operate through `FrameworkFilesystem`, which enforces the workspace boundary.

### Tool Path Resolution

`tool_path_resolution.py` provides `filesystem_virtual_mode_from_soothe_config()` — the function StrangeLoop uses to determine whether paths should be sandboxed. This centralizes the virtual_mode decision so tools and the loop agree on sandboxing semantics.

---

## Minimal Usage

```python
from soothe.foundation.workspace import resolve_daemon_workspace, FrameworkFilesystem
from soothe.config import SootheConfig

config = SootheConfig.from_yaml_file("config.yml")
workspace = resolve_daemon_workspace()  # SOOTHE_WORKSPACE or TEMP fallback
FrameworkFilesystem.initialize(config, policy=resolve_policy(config))
# Singleton is now ready; tools use it via middleware
```

---

## Configuration

```yaml
security:
  allow_paths_outside_workspace: false  # true = disable sandbox (CLI only)

filesystem_middleware:
  max_file_size_mb: 10  # per-file size cap
```

The workspace directory itself is resolved at runtime (not from config) — it comes from the client, the environment, or the loop scope.

---

## Gotchas

- **The daemon workspace is ephemeral** — by default, it's a TEMP directory. Files written there vanish on daemon restart. For persistence, set `SOOTHE_WORKSPACE` or use client workspaces.
- **`virtual_mode` is a security boundary** — setting `allow_paths_outside_workspace: true` lets agents write anywhere on the host. Only do this for trusted local CLI usage, never for daemon deployments serving multiple users.
- **The ContextVar is per-async-task** — `WorkspaceAwareBackend` reads the workspace from a ContextVar, so it's scoped to the current async task. If you spawn tasks, they inherit the parent's workspace unless explicitly set.
- **Anonymous workspaces accumulate** — without `cleanup_anonymous_workspaces()` at shutdown, anonymous workspace directories persist indefinitely. The daemon calls this at shutdown; if you run the runner outside the daemon, you may need to call it yourself.
- **System directory validation is a blocklist** — `INVALID_WORKSPACE_DIRS` is checked by exact string match on the resolved path. Symlinks to system directories are not detected by this check (though the policy layer may catch them).

---

## Related

- **[Agent Factory](agent-factory.md)** — workspace middleware integration
- **[SootheRunner](runner.md)** — stream workspace resolution
- **[Security Policy](../architecture/security-policy.md)** — policy enforcement
- **[RFC-102](../../specs/RFC-102-security-filesystem-policy.md)** — security policy spec
- **[RFC-103](../../specs/RFC-103-thread-aware-workspace.md)** — thread workspace spec
