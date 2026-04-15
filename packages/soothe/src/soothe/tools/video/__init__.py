"""Video processing tools plugin.

This plugin provides Video analysis and understanding capabilities.
"""

from typing import Any

from soothe_sdk import plugin

from .implementation import VideoAnalysisTool, VideoInfoTool, create_video_tools

__all__ = ["VideoAnalysisTool", "VideoInfoTool", "VideoPlugin", "create_video_tools"]


@plugin(
    name="video",
    version="1.0.0",
    description="Video processing tools",
    trust_level="built-in",
)
class VideoPlugin:
    """Video tools plugin.

    Provides video_analysis and video_info tools.
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[Any] = []

    async def on_load(self, context: Any) -> None:
        """Initialize tools.

        Args:
            context: Plugin context with config and logger.
        """
        self._tools = create_video_tools()
        context.logger.info("Loaded %d video tools", len(self._tools))

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools.

        Returns:
            List of video tool instances.
        """
        return self._tools
