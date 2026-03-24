"""Audio transcription plugin for audio processing.

This plugin provides tools for transcribing and analyzing audio.
"""

from typing import Any

from soothe.tools.audio import create_audio_tools
from soothe_sdk import plugin


@plugin(
    name="audio",
    version="1.0.0",
    description="Audio transcription and analysis tools",
    trust_level="built-in",
)
class AudioPlugin:
    """Audio transcription plugin.

    Provides audio_transcription and audio_qa tools.
    """

    def __init__(self) -> None:
        """Initialize audio plugin."""
        self._tools: list[Any] = []

    async def on_load(self, context: Any) -> None:
        """Initialize tools.

        Args:
            context: Plugin context with configuration.
        """
        self._tools = create_audio_tools()
        context.logger.info("Loaded %s audio tools", len(self._tools))

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools.

        Returns:
            List of audio tools.
        """
        return self._tools
