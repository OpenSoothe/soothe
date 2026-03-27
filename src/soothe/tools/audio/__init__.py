"""Audio processing tools plugin.

This plugin provides Audio transcription and analysis capabilities.
"""

from typing import Any

from soothe_sdk import plugin

from .implementation import AudioQATool, AudioTranscriptionTool, create_audio_tools

__all__ = ["AudioPlugin", "AudioQATool", "AudioTranscriptionTool", "create_audio_tools"]


@plugin(
    name="audio",
    version="1.0.0",
    description="Audio processing tools",
    trust_level="built-in",
)
class AudioPlugin:
    """Audio tools plugin.

    Provides audio_transcription and audio_qa tools.
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[Any] = []

    async def on_load(self, context: Any) -> None:
        """Initialize tools.

        Args:
            context: Plugin context with config and logger.
        """
        # Extract config from plugin context if available
        config = getattr(context, "config", None) if context else None
        self._tools = create_audio_tools(config=config)
        context.logger.info("Loaded %d audio tools", len(self._tools))

    def get_tools(self) -> list[Any]:
        """Get list of langchain tools.

        Returns:
            List of audio tool instances.
        """
        return self._tools
