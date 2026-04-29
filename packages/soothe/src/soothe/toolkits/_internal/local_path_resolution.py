"""Resolve local toolkit paths using the same rules as filesystem tools (IG-316)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deepagents.backends.utils import validate_path

from soothe.core.workspace.tool_path_resolution import (
    filesystem_virtual_mode_from_soothe_config,
    max_file_size_mb_for_filesystem_backend,
    resolve_backend_os_path,
)
from soothe.utils import expand_path


def resolve_toolkit_local_path(file_path: str, *, config: Any | None) -> Path:
    """Resolve a local file path for tabular/media tools.

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
    workspace = expand_path(config.workspace_dir)
    return resolve_backend_os_path(
        logical,
        workspace=workspace,
        virtual_mode=filesystem_virtual_mode_from_soothe_config(config),
        max_file_size_mb=max_file_size_mb_for_filesystem_backend(config),
    )
