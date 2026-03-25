"""Audio tool events.

This module defines events for audio tools (transcribe_audio, audio_qa).
Events are self-registered at module load time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from soothe.core.base_events import ToolEvent


class AudioTranscriptionStartedEvent(ToolEvent):
    """Audio transcription started event."""

    type: Literal["soothe.tool.audio.transcription_started"] = "soothe.tool.audio.transcription_started"
    tool: str = "transcribe_audio"
    audio_path: str = ""
    is_url: bool = False

    model_config = ConfigDict(extra="allow")


class AudioTranscriptionCompletedEvent(ToolEvent):
    """Audio transcription completed event."""

    type: Literal["soothe.tool.audio.transcription_completed"] = "soothe.tool.audio.transcription_completed"
    tool: str = "transcribe_audio"
    audio_path: str = ""
    duration: float = 0.0
    language: str = ""

    model_config = ConfigDict(extra="allow")


class AudioTranscriptionFailedEvent(ToolEvent):
    """Audio transcription failed event."""

    type: Literal["soothe.tool.audio.transcription_failed"] = "soothe.tool.audio.transcription_failed"
    tool: str = "transcribe_audio"
    audio_path: str = ""
    error: str = ""

    model_config = ConfigDict(extra="allow")


class AudioCacheHitEvent(ToolEvent):
    """Audio cache hit event."""

    type: Literal["soothe.tool.audio.cache_hit"] = "soothe.tool.audio.cache_hit"
    tool: str = "transcribe_audio"
    audio_path: str = ""

    model_config = ConfigDict(extra="allow")


class AudioDownloadEvent(ToolEvent):
    """Audio download event."""

    type: Literal["soothe.tool.audio.download"] = "soothe.tool.audio.download"
    tool: str = "transcribe_audio"
    url: str = ""

    model_config = ConfigDict(extra="allow")


# Register all audio events with the global registry
from soothe.core.event_catalog import register_event  # noqa: E402

register_event(
    AudioTranscriptionStartedEvent,
    summary_template="Transcribing: {audio_path}",
)
register_event(
    AudioTranscriptionCompletedEvent,
    summary_template="Transcribed ({duration}s, {language})",
)
register_event(
    AudioTranscriptionFailedEvent,
    summary_template="Transcription failed: {error}",
)
register_event(
    AudioCacheHitEvent,
    summary_template="Using cached transcription",
)
register_event(
    AudioDownloadEvent,
    summary_template="Downloading audio from URL",
)

# Event type constants for convenient imports
TOOL_AUDIO_TRANSCRIPTION_STARTED = "soothe.tool.audio.transcription_started"
TOOL_AUDIO_TRANSCRIPTION_COMPLETED = "soothe.tool.audio.transcription_completed"
TOOL_AUDIO_TRANSCRIPTION_FAILED = "soothe.tool.audio.transcription_failed"
TOOL_AUDIO_CACHE_HIT = "soothe.tool.audio.cache_hit"
TOOL_AUDIO_DOWNLOAD = "soothe.tool.audio.download"

__all__ = [
    # Constants first (alphabetically)
    "TOOL_AUDIO_CACHE_HIT",
    "TOOL_AUDIO_DOWNLOAD",
    "TOOL_AUDIO_TRANSCRIPTION_COMPLETED",
    "TOOL_AUDIO_TRANSCRIPTION_FAILED",
    "TOOL_AUDIO_TRANSCRIPTION_STARTED",
    # Event classes (alphabetically)
    "AudioCacheHitEvent",
    "AudioDownloadEvent",
    "AudioTranscriptionCompletedEvent",
    "AudioTranscriptionFailedEvent",
    "AudioTranscriptionStartedEvent",
]
