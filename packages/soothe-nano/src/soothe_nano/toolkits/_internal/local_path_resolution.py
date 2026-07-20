"""Resolve local toolkit paths using the same rules as filesystem tools (IG-316)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from soothe_deepagents.backends.utils import validate_path

from soothe_nano.workspace.workspace_paths import (
    filesystem_virtual_mode_from_soothe_config,
    max_file_size_mb_for_filesystem_backend,
    resolve_backend_os_path,
    workspace_path_for_tool_resolution,
)


def resolve_toolkit_local_path(file_path: str, *, config: Any | None) -> Path:
    """Resolve a local file path for data inspection tools.

    Callers must not pass ``http://`` or ``https://`` URIs.

    Args:
        file_path: User-supplied path.
        config: ``SootheConfig`` or ``None`` (legacy: expand user only).

    Returns:
        Absolute path on disk.

    Raises:
        ValueError: If ``validate_path`` or backend resolution rejects the path.
    """
    if config is None:
        return Path(file_path).expanduser().resolve()

    logical = validate_path(file_path)
    workspace = workspace_path_for_tool_resolution(config)
    return resolve_backend_os_path(
        logical,
        workspace=workspace,
        virtual_mode=filesystem_virtual_mode_from_soothe_config(config),
        max_file_size_mb=max_file_size_mb_for_filesystem_backend(config),
    )
