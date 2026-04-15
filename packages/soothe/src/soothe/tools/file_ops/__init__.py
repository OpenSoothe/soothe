"""File operations tools plugin.

This plugin provides file system operation capabilities.
"""

from typing import Any

from soothe_sdk import plugin

from .implementation import (
    DeleteFileTool,
    FileInfoTool,
    ListFilesTool,
    ReadFileTool,
    SearchFilesTool,
    WriteFileTool,
    create_file_ops_tools,
)

__all__ = [
    "DeleteFileTool",
    "FileInfoTool",
    "FileOpsPlugin",
    "ListFilesTool",
    "ReadFileTool",
    "SearchFilesTool",
    "WriteFileTool",
    "create_file_ops_tools",
]


@plugin(
    name="file_ops",
    version="1.0.0",
    description="File system operations tools",
    trust_level="built-in",
)
class FileOpsPlugin:
    """File operations tools plugin.

    Provides ls, read_file, write_file, edit_file, glob, grep tools.
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[Any] = []

    async def on_load(self, context: Any) -> None:
        """Initialize tools with workspace from config.

        Args:
            context: Plugin context with config and logger.
        """
        workspace_root = context.config.get("workspace_root", "")
        self._tools = create_file_ops_tools(work_dir=workspace_root)

        context.logger.info(
            "Loaded %d file_ops tools (workspace=%s)",
            len(self._tools),
            workspace_root,
        )

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools.

        Returns:
            List of file operation tool instances.
        """
        return self._tools
