"""File operations plugin for file system operations.

This plugin provides tools for reading, writing, deleting, and searching files.
"""

from typing import Any

from soothe.tools.file_ops import create_file_ops_tools
from soothe_sdk import plugin


@plugin(
    name="file_ops",
    version="1.0.0",
    description="File operation tools",
    trust_level="built-in",
)
class FileOpsPlugin:
    """File operations plugin.

    Provides read_file, write_file, delete_file, search_files, list_files, file_info tools.
    """

    def __init__(self) -> None:
        """Initialize file ops plugin."""
        self._tools: list[Any] = []

    async def on_load(self, context: Any) -> None:
        """Initialize tools with workspace from config.

        Args:
            context: Plugin context with configuration.
        """
        work_dir = context.config.get("work_dir", context.soothe_config.workspace_dir)
        allow_outside = context.config.get(
            "allow_outside_workdir",
            context.soothe_config.security.allow_paths_outside_workspace,
        )

        self._tools = create_file_ops_tools(
            work_dir=work_dir,
            allow_outside_workdir=allow_outside,
        )

        context.logger.info(
            "Loaded %d file_ops tools (work_dir=%s, allow_outside=%s)", len(self._tools), work_dir, allow_outside
        )

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools.

        Returns:
            List of file operation tools.
        """
        return self._tools
