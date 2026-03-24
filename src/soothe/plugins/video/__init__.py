"""Video analysis plugin for video understanding.

This plugin provides tools for analyzing and understanding videos.
"""

from typing import Any

from soothe.tools.video import create_video_tools
from soothe_sdk import plugin


@plugin(
    name="video",
    version="1.0.0",
    description="Video analysis tools",
    trust_level="built-in",
)
class VideoPlugin:
    """Video analysis plugin.

    Provides video_analysis and video_info tools.
    """

    def __init__(self) -> None:
        """Initialize video plugin."""
        self._tools: list[Any] = []

    async def on_load(self, context: Any) -> None:
        """Initialize tools.

        Args:
            context: Plugin context with configuration.
        """
        self._tools = create_video_tools()
        context.logger.info("Loaded %s video tools", len(self._tools))

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools.

        Returns:
            List of video analysis tools.
        """
        return self._tools
