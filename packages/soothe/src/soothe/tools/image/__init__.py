"""Image processing tools plugin.

This plugin provides Image analysis and understanding capabilities.
"""

from typing import Any

from soothe_sdk.plugin import plugin

from .implementation import create_image_tools

__all__ = ["ImagePlugin", "create_image_tools"]


@plugin(
    name="image",
    version="1.0.0",
    description="Image processing tools",
    trust_level="built-in",
)
class ImagePlugin:
    """Image tools plugin.

    Provides image_analysis and extract_text_from_image tools.
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[Any] = []

    async def on_load(self, context: Any) -> None:
        """Initialize tools.

        Args:
            context: Plugin context with config and logger.
        """
        self._tools = create_image_tools()
        context.logger.info("Loaded %d image tools", len(self._tools))

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools.

        Returns:
            List of image tool instances.
        """
        return self._tools
