"""Resolve tool and policy paths using unified filesystem rules (IG-316, IG-366).

Virtual absolute paths (for example ``/README.md`` under ``virtual_mode=True``) must
use ``resolve_backend_os_path`` so resolution matches ``NormalizedPathBackend`` /
``LocalFilesystem`` — not ``workspace / normalized`` joins.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from soothe.config import SootheConfig
from soothe.core.workspace.normalized_backend import NormalizedPathBackend
from soothe.core.workspace.resolution import resolve_daemon_workspace

# First path segment after ``/`` for absolute POSIX paths that usually denote host
# roots (not virtual sandbox paths like ``/README.md``).
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


def workspace_path_for_tool_resolution(config: Any | None) -> Path:
    """Workspace root for toolkit path resolution (config override, else daemon default)."""
    root = config_workspace_root(config)
    if root:
        return Path(root).expanduser().resolve()
    return resolve_daemon_workspace()


def _posix_first_segment_name(expanded: Path) -> str | None:
    """Return first path segment for a POSIX absolute path, or None."""
    parts = expanded.parts
    if not parts or parts[0] != "/":
        return None
    if len(parts) < 2:
        return None
    return parts[1]


def should_use_virtual_path_resolution(file_path: str, workspace_root: Path) -> bool:
    """True when a leading-``/`` path should use virtual sandbox resolution (IG-366).

    Host-style absolutes outside the workspace (for example ``/tmp/other``) must not
    be remapped into the workspace; virtual absolutes (``/README.md``, ``/``) must
    align with ``NormalizedPathBackend``.
    """
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
    backend = NormalizedPathBackend(
        root_dir=workspace.resolve(),
        virtual_mode=virtual_mode,
        max_file_size_mb=max_file_size_mb,
    )
    return backend.resolve_os_path(path)


def join_workspace_normalized_path(workspace: Path, normalized: str) -> Path:
    """Convert a validator-normalized logical path to an on-disk path.

    Prefer ``resolve_backend_os_path`` when ``virtual_mode`` applies; this helper
    is for the optional security layer where paths are already validated as
    workspace-relative or host-absolute.
    """
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
