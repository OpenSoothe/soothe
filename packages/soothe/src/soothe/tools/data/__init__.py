"""Data processing tools plugin.

This plugin provides Data inspection and analysis capabilities.
"""

from typing import Any

from soothe_sdk.plugin import plugin

from .implementation import (
    AskAboutFileTool,
    CheckDataQualityTool,
    ExtractTextTool,
    GetDataInfoTool,
    InspectDataTool,
    SummarizeDataTool,
    create_data_tools,
)

__all__ = [
    "AskAboutFileTool",
    "CheckDataQualityTool",
    "DataPlugin",
    "ExtractTextTool",
    "GetDataInfoTool",
    "InspectDataTool",
    "SummarizeDataTool",
    "create_data_tools",
]


@plugin(
    name="data",
    version="1.0.0",
    description="Data processing tools",
    trust_level="built-in",
)
class DataPlugin:
    """Data tools plugin.

    Provides inspect_data, summarize_data, check_data_quality tools.
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[Any] = []

    async def on_load(self, context: Any) -> None:
        """Initialize tools.

        Args:
            context: Plugin context with config and logger.
        """
        self._tools = create_data_tools()
        context.logger.info("Loaded %d data tools", len(self._tools))

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools.

        Returns:
            List of data tool instances.
        """
        return self._tools
