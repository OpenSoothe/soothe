"""Goals plugin for goal management.

This plugin provides tools for creating and managing goals.
"""

from typing import Any

from soothe.tools.goals import create_goals_tools
from soothe_sdk import plugin


@plugin(
    name="goals",
    version="1.0.0",
    description="Goal management tools",
    trust_level="built-in",
)
class GoalsPlugin:
    """Goals plugin.

    Provides create_goal, list_goals, complete_goal, fail_goal tools.

    Note: This plugin requires GoalEngine to be injected via PluginContext.
    """

    def __init__(self) -> None:
        """Initialize goals plugin."""
        self._tools: list[Any] = []

    async def on_load(self, context: Any) -> None:
        """Initialize tools with GoalEngine from context.

        Args:
            context: Plugin context with goal_engine injected.

        Raises:
            ValueError: If goal_engine is not available in context.
        """
        goal_engine = getattr(context, "goal_engine", None)
        if not goal_engine:
            raise ValueError("GoalsPlugin requires goal_engine to be injected in PluginContext")

        self._tools = create_goals_tools(goal_engine)
        context.logger.info("Loaded %s goals tools", len(self._tools))

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools.

        Returns:
            List of goal management tools.
        """
        return self._tools
