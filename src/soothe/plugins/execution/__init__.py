"""Execution tools plugin for shell and Python execution.

This plugin provides tools for executing shell commands and Python code.
"""

from typing import Any

from soothe.tools.execution import create_execution_tools
from soothe_sdk import plugin


@plugin(
    name="execution",
    version="1.0.0",
    description="Shell and Python execution tools",
    trust_level="built-in",
)
class ExecutionPlugin:
    """Execution tools plugin.

    Provides run_command, run_python, run_background, and kill_process tools.
    """

    def __init__(self) -> None:
        """Initialize execution plugin."""
        self._tools: list[Any] = []

    async def on_load(self, context: Any) -> None:
        """Initialize tools with workspace from config.

        Args:
            context: Plugin context with configuration.
        """
        workspace_root = context.config.get("workspace_root")
        timeout = context.config.get("timeout", 120)

        self._tools = create_execution_tools(
            workspace_root=workspace_root,
            timeout=timeout,
        )

        context.logger.info(
            "Loaded %d execution tools (workspace=%s, timeout=%ds)", len(self._tools), workspace_root, timeout
        )

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools.

        Returns:
            List of execution tools.
        """
        return self._tools
