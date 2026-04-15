"""Code editing tools plugin.

This plugin provides code editing capabilities.
"""

from typing import Any

from soothe_sdk import plugin

from .implementation import (
    ApplyDiffTool,
    DeleteLinesTool,
    EditFileLinesTool,
    InsertLinesTool,
    create_code_edit_tools,
)

__all__ = [
    "ApplyDiffTool",
    "CodeEditPlugin",
    "DeleteLinesTool",
    "EditFileLinesTool",
    "InsertLinesTool",
    "create_code_edit_tools",
]


@plugin(
    name="code_edit",
    version="1.0.0",
    description="Code editing and manipulation tools",
    trust_level="built-in",
)
class CodeEditPlugin:
    """Code editing tools plugin."""

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[Any] = []

    async def on_load(self, context: Any) -> None:
        """Initialize tools.

        Args:
            context: Plugin context with config and logger.
        """
        self._tools = create_code_edit_tools()
        context.logger.info("Loaded %d code_edit tools", len(self._tools))

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools."""
        return self._tools
