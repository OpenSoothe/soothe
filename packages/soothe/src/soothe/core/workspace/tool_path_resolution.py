"""Resolve tool paths using the same backend rules as the runtime (IG-316).

``strict_workspace_path`` in ``path_normalization`` is for real OS paths under a
workspace. Virtual absolute paths (for example ``/src/foo.py`` under
``virtual_mode=True``) must use this module so resolution matches
``FilesystemBackend._resolve_path``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from soothe.config import SootheConfig
from soothe.core.workspace.refactored_backend import NormalizedPathBackend
from soothe.core.workspace.resolution import resolve_daemon_workspace


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


def resolve_backend_os_path(
    path: str,
    *,
    workspace: Path,
    virtual_mode: bool,
    max_file_size_mb: int = 10,
) -> Path:
    """Resolve *path* to the on-disk path ``FilesystemBackend`` would use.

    Instantiates a fresh ``NormalizedPathBackend`` (does not use the global
    ``get_workspace_backend`` cache) so ``virtual_mode`` is never mixed across
    callers.

    Args:
        path: Path string (typically after ``validate_path`` from the middleware).
        workspace: Workspace root directory.
        virtual_mode: Same semantics as ``FilesystemBackend.virtual_mode``.
        max_file_size_mb: Passed to the backend constructor.

    Returns:
        Resolved absolute path on the host filesystem.

    Raises:
        ValueError: If the path is rejected by the backend (traversal, outside root).
    """
    backend = NormalizedPathBackend(
        root_dir=workspace.resolve(),
        virtual_mode=virtual_mode,
        max_file_size_mb=max_file_size_mb,
    )
    return backend._resolve_path(path)


def filesystem_virtual_mode_from_soothe_config(config: SootheConfig) -> bool:
    """Return ``FilesystemBackend.virtual_mode`` from security settings.

    Matches ``FrameworkFilesystem.initialize`` (``not allow_paths_outside_workspace``).
    """
    return not config.security.allow_paths_outside_workspace


def max_file_size_mb_for_filesystem_backend(config: SootheConfig) -> int:
    """Return max file size (MB) for filesystem backends, mirroring FrameworkFilesystem."""
    max_file_size_mb = 10
    if hasattr(config, "filesystem_middleware") and hasattr(
        config.filesystem_middleware, "max_file_size_mb"
    ):
        max_file_size_mb = int(config.filesystem_middleware.max_file_size_mb)
    return max_file_size_mb
