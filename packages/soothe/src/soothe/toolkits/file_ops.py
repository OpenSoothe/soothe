"""File operations toolkit -- surgical file manipulation plugin.

This module provides the `FileOpsPlugin` class, which supplies surgical file operation
tools (delete_file, file_info, edit_file_lines, insert_lines, delete_lines, apply_diff).

All tools are created via `SootheFilesystemMiddleware` from `soothe.middleware.filesystem`,
which implements them using `StructuredTool.from_function()` with proper Schema classes
for validation. This approach extends deepagents rather than reinventing file operations.

The plugin extracts only surgical tools (not basic read/write/list/search operations)
from the middleware, as those are provided by deepagents' FilesystemMiddleware.
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool
from soothe_sdk.plugin import plugin

from soothe.utils import expand_path

logger = logging.getLogger(__name__)


def _get_effective_work_dir(fallback_work_dir: str) -> str:
    """Get effective work directory, checking LangGraph config first (RFC-103).

    Priority:
    1. workspace from LangGraph configurable (passed through execution)
    2. ContextVar (for same-async-context operations)
    3. fallback_work_dir (daemon default)

    Args:
        fallback_work_dir: Fallback directory if no dynamic workspace set.

    Returns:
        Effective workspace directory path as string.
    """
    # Priority 1: Try to get workspace from LangGraph configurable
    try:
        from langgraph.config import get_config

        config = get_config()
        configurable = config.get("configurable", {})
        workspace = configurable.get("workspace")
        if workspace:
            return str(workspace)
    except Exception:  # noqa: S110
        pass

    # Priority 2: Try ContextVar
    from soothe.core import FrameworkFilesystem

    dynamic_workspace = FrameworkFilesystem.get_current_workspace()
    if dynamic_workspace:
        return str(dynamic_workspace)

    # Priority 3: Use fallback
    return fallback_work_dir


@plugin(
    name="file_ops", version="2.0.0", description="File system operations", trust_level="built-in"
)
class FileOpsPlugin:
    """File operations tools plugin.

    Provides delete_file, file_info, edit_file_lines, insert_lines, delete_lines, apply_diff.

    Tools are provided by SootheFilesystemMiddleware for consistent
    implementation patterns (schema validation, path validation, backend usage).
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[BaseTool] = []

    async def on_load(self, context) -> None:
        """Initialize tools with workspace from config.

        Args:
            context: Plugin context with config and logger.
        """
        from deepagents.backends.filesystem import FilesystemBackend

        from soothe.core.workspace.tool_path_resolution import (
            filesystem_virtual_mode_from_soothe_config,
            max_file_size_mb_for_filesystem_backend,
        )
        from soothe.middleware.filesystem import SootheFilesystemMiddleware

        sc = context.soothe_config
        workspace_root = context.config.get("workspace_root") or str(expand_path(sc.workspace_dir))
        fs_config = dict(context.config.get("filesystem_middleware", {}))
        if "virtual_mode" not in fs_config:
            fs_config["virtual_mode"] = filesystem_virtual_mode_from_soothe_config(sc)
        if "max_file_size_mb" not in fs_config:
            fs_config["max_file_size_mb"] = max_file_size_mb_for_filesystem_backend(sc)

        backend = FilesystemBackend(
            root_dir=workspace_root or None,
            virtual_mode=fs_config.get("virtual_mode", False),
            max_file_size_mb=fs_config.get("max_file_size_mb", 10),
        )

        middleware = SootheFilesystemMiddleware(
            backend=backend,
            backup_enabled=fs_config.get("backup_enabled", True),
            backup_dir=fs_config.get("backup_dir"),
            workspace_root=workspace_root or None,
            tool_token_limit_before_evict=fs_config.get("tool_token_limit_before_evict", 20000),
        )

        # Extract surgical tools only (not ls, read_file, etc. from FilesystemMiddleware)
        surgical_tool_names = [
            "delete_file",
            "file_info",
            "edit_file_lines",
            "insert_lines",
            "delete_lines",
            "apply_diff",
        ]
        self._tools = [t for t in middleware.tools if t.name in surgical_tool_names]

        context.logger.info(
            "Loaded %d file_ops tools via SootheFilesystemMiddleware (workspace=%s)",
            len(self._tools),
            workspace_root,
        )

    def get_tools(self) -> list[BaseTool]:
        """Get list of langchain tools.

        Returns:
            List of file operation tool instances.
        """
        return self._tools
