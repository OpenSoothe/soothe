"""Execution tools plugin.

This plugin provides shell and Python execution capabilities.
"""

from typing import Any

from soothe.config.constants import DEFAULT_EXECUTE_TIMEOUT
from soothe_sdk import plugin

from .implementation import (
    KillProcessTool,
    RunBackgroundTool,
    RunCommandTool,
    RunPythonTool,
    create_execution_tools,
)

__all__ = [
    "DEFAULT_EXECUTE_TIMEOUT",
    "ExecutionPlugin",
    "KillProcessTool",
    "RunBackgroundTool",
    "RunCommandTool",
    "RunPythonTool",
    "create_execution_tools",
]


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
        """Initialize the plugin."""
        self._tools: list[Any] = []

    async def on_load(self, context: Any) -> None:
        """Initialize tools with workspace from config.

        Args:
            context: Plugin context with config and logger.
        """
        workspace_root = context.config.get("workspace_root", "")
        timeout = context.config.get("timeout", 60)

        self._tools = create_execution_tools(
            workspace_root=workspace_root,
            timeout=timeout,
        )

        context.logger.info(
            "Loaded %d execution tools (workspace=%s, timeout=%ds)",
            len(self._tools),
            workspace_root,
            timeout,
        )

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools.

        Returns:
            List of execution tool instances.
        """
        return self._tools
