"""Explore subagent filesystem tools (RFC-613).

Uses ``SootheFilesystemMiddleware`` with a curated read-only subset: filesystem
reconnaissance only (no shell, no write tools).

IG-328: Backend resolves workspace from thread state at runtime via
workspace_backend_factory pattern (not deprecated callable backend).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from soothe_nano.middleware.filesystem import SootheFilesystemMiddleware
from soothe_nano.workspace.workspace_filesystem import (
    NormalizedPathBackend,
    get_workspace_backend,
)

logger = logging.getLogger(__name__)


def _create_workspace_backend_factory(
    virtual_mode: bool = False,
) -> Any:
    """Create factory for workspace backends (IG-328).

    Returns a factory function that:
    1. Takes a workspace path string
    2. Returns NormalizedPathBackend for that workspace

    This factory is passed to SootheFilesystemMiddleware which uses it
    to resolve thread workspace from runtime.state["workspace"] without
    the deprecated callable backend pattern.

    Args:
        virtual_mode: Whether to sandbox paths to workspace.

    Returns:
        Factory function for creating workspace backends.
    """

    def _create_backend(workspace_path: str) -> NormalizedPathBackend:
        """Create backend for a specific workspace."""
        return get_workspace_backend(
            Path(workspace_path),
            virtual_mode=virtual_mode,
            max_file_size_mb=10,
        )

    return _create_backend


def get_explore_tools(
    workspace: str | None = None,
    *,
    virtual_mode: bool | None = None,
    allow_paths_outside_workspace: bool | None = None,
) -> list[Any]:
    """Get explore tools: read-only filesystem surface only.

    Exposed tools (mutation and shell tools from middleware are filtered out):
    - glob, grep, ls, read_file: via middleware base
    - file_info: Soothe (metadata)

    IG-328: Uses workspace_backend_factory pattern for thread workspace resolution
    without deprecated callable backend pattern.

    Args:
        workspace: Initial/resolver workspace (fallback when state lacks workspace).
        virtual_mode: When set, forces FilesystemBackend ``virtual_mode``.
        allow_paths_outside_workspace: When ``virtual_mode`` is omitted, sets
            ``virtual_mode`` to ``not allow_paths_outside_workspace``.

    Returns:
        Ordered list of langchain tool instances.
    """
    if virtual_mode is None:
        if allow_paths_outside_workspace is None:
            virtual_mode = False
        else:
            virtual_mode = not allow_paths_outside_workspace

    root = workspace or os.getcwd()

    # Create initial backend for the resolver workspace (IG-328)
    initial_backend = get_workspace_backend(
        Path(root),
        virtual_mode=virtual_mode,
        max_file_size_mb=10,
    )

    # Create factory for thread workspace resolution (IG-328)
    backend_factory = _create_workspace_backend_factory(virtual_mode=virtual_mode)

    middleware = SootheFilesystemMiddleware(
        backend=initial_backend,  # BackendProtocol instance (not callable)
        workspace_backend_factory=backend_factory,  # Factory for thread workspace
        backup_enabled=True,
        workspace_root=root,  # Fallback for non-tool operations
    )

    filesystem_tool_names: tuple[str, ...] = (
        "glob",
        "grep",
        "ls",
        "read_file",
        "file_info",
    )
    by_name = {t.name: t for t in middleware.tools}
    return [by_name[name] for name in filesystem_tool_names if name in by_name]
