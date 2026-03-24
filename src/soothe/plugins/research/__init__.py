"""Research plugin for deep research capabilities.

This plugin provides tools for conducting deep research on topics.
"""

from typing import Any

from soothe.tools.research import create_research_tools
from soothe_sdk import plugin


@plugin(
    name="research",
    version="1.0.0",
    description="Deep research tools",
    trust_level="built-in",
)
class ResearchPlugin:
    """Research plugin.

    Provides research tool for comprehensive topic investigation.
    """

    def __init__(self) -> None:
        """Initialize research plugin."""
        self._tools: list[Any] = []

    async def on_load(self, context: Any) -> None:
        """Initialize tools with config and workspace.

        Args:
            context: Plugin context with configuration.
        """
        work_dir = context.config.get("work_dir", context.soothe_config.workspace_dir)

        self._tools = create_research_tools(
            config=context.soothe_config,
            work_dir=work_dir,
        )
        context.logger.info("Loaded %s research tools", len(self._tools))

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools.

        Returns:
            List of research tools.
        """
        return self._tools
