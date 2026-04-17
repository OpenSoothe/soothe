"""Goals processing tools plugin.

This plugin provides Goal management and tracking capabilities.
"""

from typing import Any

from soothe_sdk.plugin import plugin

from .implementation import (
    CompleteGoalTool,
    CreateGoalTool,
    FailGoalTool,
    ListGoalsTool,
    create_goals_tools,
)

__all__ = [
    "CompleteGoalTool",
    "CreateGoalTool",
    "FailGoalTool",
    "GoalsPlugin",
    "ListGoalsTool",
    "create_goals_tools",
]


@plugin(
    name="goals",
    version="1.0.0",
    description="Goals processing tools",
    trust_level="built-in",
)
class GoalsPlugin:
    """Goals tools plugin.

    Provides create_goal, list_goals, complete_goal, fail_goal tools.
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[Any] = []

    async def on_load(self, context: Any) -> None:
        """Initialize tools.

        Args:
            context: Plugin context with config and logger.
        """
        self._tools = create_goals_tools()
        context.logger.info("Loaded %d goals tools", len(self._tools))

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools.

        Returns:
            List of goals tool instances.
        """
        return self._tools
