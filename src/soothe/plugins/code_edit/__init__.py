"""Code editing plugin for surgical code modifications.

This plugin provides tools for editing code files with line-based operations.
"""

from typing import Any

from soothe.tools.code_edit import create_code_edit_tools
from soothe_sdk import plugin


@plugin(
    name="code_edit",
    version="1.0.0",
    description="Code editing tools",
    trust_level="built-in",
)
class CodeEditPlugin:
    """Code editing plugin.

    Provides edit_file_lines, insert_lines, delete_lines, apply_diff tools.
    """

    def __init__(self) -> None:
        """Initialize code edit plugin."""
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

        self._tools = create_code_edit_tools(
            work_dir=work_dir,
            allow_outside_workdir=allow_outside,
        )

        context.logger.info(
            "Loaded %d code_edit tools (work_dir=%s, allow_outside=%s)", len(self._tools), work_dir, allow_outside
        )

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools.

        Returns:
            List of code editing tools.
        """
        return self._tools
