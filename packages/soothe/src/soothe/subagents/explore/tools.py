"""Explore subagent filesystem tools (RFC-613).

Uses ``SootheFilesystemMiddleware`` with a curated read-only subset: filesystem
reconnaissance only (no shell, no write tools).

IG-328: Backend uses callable pattern to resolve workspace from thread state at runtime,
not from static resolver context.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from soothe.core.workspace.backend import NormalizedPathBackend, get_workspace_backend
from soothe.middleware.filesystem import SootheFilesystemMiddleware

logger = logging.getLogger(__name__)


def _create_thread_workspace_backend(
    initial_workspace: str,
    allow_paths_outside_workspace: bool = False,
) -> Any:
    """Create callable backend that resolves workspace from thread state at runtime (IG-328).

    Returns a callable that:
    1. Checks ToolRuntime.state["workspace"] (thread workspace from runner)
    2. Falls back to initial_workspace (resolver workspace)
    3. Returns ``NormalizedPathBackend`` so host-absolute paths inside the workspace
       map to the same paths as ``grep``/``glob`` virtual ``/...`` strings (IG-300).

    This allows explore to search the thread workspace (e.g., client cwd) instead
    of the static daemon workspace.

    Args:
        initial_workspace: Fallback workspace from resolver context.
        allow_paths_outside_workspace: Security setting from config.

    Returns:
        Callable backend function for FilesystemMiddleware.
    """

    def _resolve_backend(runtime: Any | None) -> NormalizedPathBackend:
        """Resolve backend with thread workspace from state."""
        # Thread workspace injected by runner via state.workspace (IG-328)
        thread_workspace = None
        if runtime is not None and hasattr(runtime, "state"):
            thread_workspace = runtime.state.get("workspace")

        # Use thread workspace if available, else fallback to resolver workspace
        # When runtime is None (direct tool invocation), use initial_workspace
        effective_workspace = thread_workspace or initial_workspace

        # NormalizedPathBackend: host paths under workspace match virtual_mode tool paths
        virtual_mode = not allow_paths_outside_workspace
        return get_workspace_backend(
            Path(effective_workspace),
            virtual_mode=virtual_mode,
            max_file_size_mb=10,
        )

    return _resolve_backend


def get_explore_tools(
    workspace: str | None = None,
    *,
    virtual_mode: bool | None = None,
    allow_paths_outside_workspace: bool | None = None,
) -> list[Any]:
    """Get explore tools: read-only filesystem surface only.

    Exposed tools (mutation and shell tools from middleware are filtered out):
    - glob, grep, ls, read_file: deepagents (via middleware base)
    - file_info: Soothe (metadata)

    IG-328: Backend is callable so workspace resolves from thread state at runtime,
    not from static resolver workspace.

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

    # Create callable backend that resolves workspace from thread state (IG-328)
    callable_backend = _create_thread_workspace_backend(
        initial_workspace=root,
        allow_paths_outside_workspace=not virtual_mode,
    )

    middleware = SootheFilesystemMiddleware(
        backend=callable_backend,  # Callable backend for dynamic workspace resolution
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
