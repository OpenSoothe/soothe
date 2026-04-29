"""Explore subagent read-only filesystem tools (RFC-613).

Reuses existing tools from deepagents FilesystemMiddleware to avoid duplication.
"""

from __future__ import annotations

import os
from typing import Any

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemMiddleware


def get_explore_tools(
    workspace: str | None = None,
    *,
    virtual_mode: bool | None = None,
    allow_paths_outside_workspace: bool | None = None,
) -> list[Any]:
    """Get filesystem tools for explore subagent.

    Reuses deepagents FilesystemMiddleware tools instead of duplicating:
    - glob: Find files matching glob patterns
    - grep: Search text in files
    - ls: List directory contents
    - read_file: Read file content

    Args:
        workspace: Optional workspace root path.
        virtual_mode: When set, forces FilesystemBackend ``virtual_mode``.
        allow_paths_outside_workspace: When ``virtual_mode`` is omitted, sets
            ``virtual_mode`` to ``not allow_paths_outside_workspace`` (IG-300).

    Returns:
        List of langchain tool instances (glob, grep, ls, read_file).
    """
    if virtual_mode is None:
        if allow_paths_outside_workspace is None:
            virtual_mode = False
        else:
            virtual_mode = not allow_paths_outside_workspace

    # Create filesystem backend with workspace boundary
    backend = FilesystemBackend(
        root_dir=workspace or os.getcwd(),
        virtual_mode=virtual_mode,
        max_file_size_mb=10,  # Limit file reads
    )

    # Create middleware (provides glob, grep, ls, read_file, write_file, edit_file)
    middleware = FilesystemMiddleware(backend=backend)

    # Return only read-only tools (exclude write_file, edit_file)
    read_only_tools = ["glob", "grep", "ls", "read_file"]
    tools = [t for t in middleware.tools if t.name in read_only_tools]

    return tools
