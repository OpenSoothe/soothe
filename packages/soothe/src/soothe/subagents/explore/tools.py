"""Explore subagent read-only filesystem tools (RFC-613).

Uses ``SootheFilesystemMiddleware`` so explore shares the same built-in filesystem
tool surface as the main agent, while exposing only a read-only subset.
"""

from __future__ import annotations

import os
from typing import Any

from deepagents.backends.filesystem import FilesystemBackend

from soothe.middleware.filesystem import SootheFilesystemMiddleware


def get_explore_tools(
    workspace: str | None = None,
    *,
    virtual_mode: bool | None = None,
    allow_paths_outside_workspace: bool | None = None,
) -> list[Any]:
    """Get read-only filesystem tools for the explore subagent.

    Tools (all read-only, workspace-scoped via backend):
    - glob, grep, ls, read_file: from deepagents (via middleware base)
    - file_info: Soothe extension (metadata only)

    Args:
        workspace: Optional workspace root path.
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
    backend = FilesystemBackend(
        root_dir=root,
        virtual_mode=virtual_mode,
        max_file_size_mb=10,
    )

    middleware = SootheFilesystemMiddleware(
        backend=backend,
        backup_enabled=True,
        workspace_root=root,
    )

    read_only_tool_names = ("glob", "grep", "ls", "read_file", "file_info")
    by_name = {t.name: t for t in middleware.tools}
    tools = [by_name[name] for name in read_only_tool_names if name in by_name]

    return tools
