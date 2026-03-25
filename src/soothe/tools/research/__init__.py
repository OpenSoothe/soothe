"""Research tool package."""

from typing import Any

from soothe_sdk import plugin

from .events import (
    ResearchAnalyzeEvent,
    ResearchCompletedEvent,
    ResearchGatherDoneEvent,
    ResearchGatherEvent,
    ResearchQueriesGeneratedEvent,
    ResearchReflectEvent,
    ResearchReflectionDoneEvent,
    ResearchSubQuestionsEvent,
    ResearchSummarizeEvent,
    ResearchSynthesizeEvent,
)
from .implementation import ResearchTool, create_research_tools

__all__ = [
    "ResearchAnalyzeEvent",
    "ResearchCompletedEvent",
    "ResearchGatherDoneEvent",
    "ResearchGatherEvent",
    "ResearchPlugin",
    "ResearchQueriesGeneratedEvent",
    "ResearchReflectEvent",
    "ResearchReflectionDoneEvent",
    "ResearchSubQuestionsEvent",
    "ResearchSummarizeEvent",
    "ResearchSynthesizeEvent",
    "ResearchTool",
    "create_research_tools",
]


@plugin(
    name="research",
    version="1.0.0",
    description="Deep research tool with multi-source synthesis",
    trust_level="built-in",
)
class ResearchPlugin:
    """Research tools plugin.

    Provides deep research capability using InquiryEngine.
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[Any] = []

    async def on_load(self, context: Any) -> None:
        """Initialize research tool.

        Args:
            context: Plugin context with config and logger.
        """
        self._tools = create_research_tools()
        context.logger.info("Loaded research tool")

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools.

        Returns:
            List containing research tool instance.
        """
        return self._tools
