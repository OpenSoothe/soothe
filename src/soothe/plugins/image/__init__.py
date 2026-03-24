"""Image analysis plugin for image understanding.

This plugin provides tools for analyzing and understanding images.
"""

from typing import Any

from soothe.tools.image import create_image_tools
from soothe_sdk import plugin


@plugin(
    name="image",
    version="1.0.0",
    description="Image analysis tools",
    trust_level="built-in",
)
class ImagePlugin:
    """Image analysis plugin.

    Provides image_analysis and extract_text_from_image tools.
    """

    def __init__(self) -> None:
        """Initialize image plugin."""
        self._tools: list[Any] = []

    async def on_load(self, context: Any) -> None:
        """Initialize tools.

        Args:
            context: Plugin context with configuration.
        """
        self._tools = create_image_tools()
        context.logger.info("Loaded %s image tools", len(self._tools))

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools.

        Returns:
            List of image analysis tools.
        """
        return self._tools
