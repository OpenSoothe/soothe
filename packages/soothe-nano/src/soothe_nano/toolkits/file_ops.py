"""File operations toolkit -- surgical file manipulation plugin.

This module provides the `FileOpsPlugin` class, which supplies surgical file operation
tools (delete, file_info, edit_lines, insert_lines, delete_lines, apply_diff).
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool
from soothe_sdk.plugin import plugin

from soothe_nano.toolkits.file_ops_catalog import build_surgical_file_ops_tools

logger = logging.getLogger(__name__)


@plugin(
    name="file_ops", version="2.0.0", description="File system operations", trust_level="built-in"
)
class FileOpsPlugin:
    """File operations tools plugin.

    Provides delete, file_info, edit_lines, insert_lines, delete_lines, apply_diff.

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
        from soothe_deepagents.backends.filesystem import FilesystemBackend

        from soothe_nano.workspace.workspace_paths import (
            filesystem_virtual_mode_from_soothe_config,
            max_file_size_mb_for_filesystem_backend,
        )
        from soothe_nano.workspace.workspace_runtime import resolve_process_workspace_root

        sc = context.soothe_config
        workspace_root = context.config.get("workspace_root") or str(
            resolve_process_workspace_root()
        )
        fs_config = dict(context.config.get("filesystem_middleware", {}))
        virtual_mode = filesystem_virtual_mode_from_soothe_config(sc)
        max_file_size_mb = fs_config.get(
            "max_file_size_mb", max_file_size_mb_for_filesystem_backend(sc)
        )

        backend = FilesystemBackend(
            root_dir=workspace_root or None,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )

        self._tools = build_surgical_file_ops_tools(
            backend=backend,
            backup_enabled=fs_config.get("backup_enabled", True),
            backup_dir=fs_config.get("backup_dir"),
            workspace_root=workspace_root or None,
            tool_token_limit_before_evict=fs_config.get("tool_token_limit_before_evict", 20000),
        )

        context.logger.info(
            "Loaded %d file_ops surgical tools (workspace=%s)",
            len(self._tools),
            workspace_root,
        )

    def get_tools(self) -> list[BaseTool]:
        """Get list of langchain tools.

        Returns:
            List of file operation tool instances.
        """
        return self._tools
