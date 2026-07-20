"""Workspace path helpers for tool and filesystem operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from soothe_nano.config import SootheConfig
from soothe_nano.workspace.workspace_runtime import resolve_process_workspace_root

_UNIX_HOST_ROOT_TOP_NAMES: frozenset[str] = frozenset(
    {
        "Applications",
        "bin",
        "cores",
        "dev",
        "etc",
        "home",
        "Library",
        "opt",
        "private",
        "sbin",
        "sys",
        "System",
        "tmp",
        "usr",
        "Users",
        "var",
        "Volumes",
    }
)


def config_workspace_root(config: Any | None) -> str | None:
    """Return configured ``filesystem_middleware.workspace_root`` when set."""
    if config is None:
        return None
    fs = getattr(config, "filesystem_middleware", None)
    root = getattr(fs, "workspace_root", None) if fs is not None else None
    if isinstance(root, str) and root.strip():
        return root
    return None


def static_tool_workspace_fallback(config: Any | None = None) -> Path:
    """Static workspace when no stream ContextVar or RunnableConfig is bound."""
    root = config_workspace_root(config)
    if root:
        return Path(root).expanduser().resolve()
    return resolve_process_workspace_root()


def resolve_effective_tool_workspace(
    config: Any | None = None,
    *,
    runtime: Any | None = None,
) -> Path:
    """Resolve workspace for tool construction and filesystem operations."""
    from soothe_nano.workspace.workspace_policy import resolve_workspace_for_tool_execution

    fallback = static_tool_workspace_fallback(config)
    resolved = resolve_workspace_for_tool_execution(
        runtime=runtime,
        fallback=fallback,
        use_langgraph_config=True,
    )
    if resolved is not None:
        return resolved.resolve()
    return fallback


def workspace_path_for_tool_resolution(
    config: Any | None = None,
    *,
    runtime: Any | None = None,
) -> Path:
    """Workspace root for toolkit path resolution."""
    return resolve_effective_tool_workspace(config, runtime=runtime)


def _posix_first_segment_name(expanded: Path) -> str | None:
    parts = expanded.parts
    if not parts or parts[0] != "/":
        return None
    if len(parts) < 2:
        return None
    return parts[1]


def should_use_virtual_path_resolution(file_path: str, workspace_root: Path) -> bool:
    """True when a leading-``/`` path should use virtual sandbox resolution."""
    if not file_path.strip().startswith("/"):
        return False
    expanded = Path(file_path.strip()).expanduser()
    try:
        expanded.resolve().relative_to(workspace_root.resolve())
    except ValueError:
        pass
    else:
        return False
    first = _posix_first_segment_name(expanded)
    if first is None:
        return True
    return first not in _UNIX_HOST_ROOT_TOP_NAMES


def resolve_backend_os_path(
    path: str,
    *,
    workspace: Path,
    virtual_mode: bool,
    max_file_size_mb: int = 10,
) -> Path:
    """Resolve *path* to the on-disk path the unified filesystem would use."""
    from soothe_nano.workspace.workspace_filesystem import NormalizedPathBackend

    backend = NormalizedPathBackend(
        root_dir=workspace.resolve(),
        virtual_mode=virtual_mode,
        max_file_size_mb=max_file_size_mb,
    )
    return backend.resolve_os_path(path)


def join_workspace_normalized_path(workspace: Path, normalized: str) -> Path:
    """Convert a validator-normalized logical path to an on-disk path."""
    path = Path(normalized)
    if path.is_absolute():
        return path.resolve()
    return (workspace / normalized).resolve()


def filesystem_virtual_mode_from_soothe_config(config: SootheConfig) -> bool:
    """Return ``FilesystemBackend.virtual_mode`` from security settings."""
    return not config.security.allow_paths_outside_workspace


def max_file_size_mb_for_filesystem_backend(config: SootheConfig) -> int:
    """Return max file size (MB) for filesystem backends."""
    max_file_size_mb = 10
    if hasattr(config, "filesystem_middleware") and hasattr(
        config.filesystem_middleware, "max_file_size_mb"
    ):
        max_file_size_mb = int(config.filesystem_middleware.max_file_size_mb)
    return max_file_size_mb
