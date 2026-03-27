"""Video tool events.

This module defines events for video tools (analyze_video, get_video_info).
Events are self-registered at module load time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from soothe.core.base_events import ToolEvent


class VideoUploadStartedEvent(ToolEvent):
    """Video upload started event."""

    type: Literal["soothe.tool.video.upload_started"] = "soothe.tool.video.upload_started"
    tool: str = "analyze_video"
    video_path: str = ""
    file_size_mb: float = 0.0

    model_config = ConfigDict(extra="allow")


class VideoUploadCompletedEvent(ToolEvent):
    """Video upload completed event."""

    type: Literal["soothe.tool.video.upload_completed"] = "soothe.tool.video.upload_completed"
    tool: str = "analyze_video"
    video_path: str = ""
    file_name: str = ""

    model_config = ConfigDict(extra="allow")


class VideoProcessingEvent(ToolEvent):
    """Video processing event."""

    type: Literal["soothe.tool.video.processing"] = "soothe.tool.video.processing"
    tool: str = "analyze_video"
    file_name: str = ""
    state: str = ""

    model_config = ConfigDict(extra="allow")


class VideoAnalysisStartedEvent(ToolEvent):
    """Video analysis started event."""

    type: Literal["soothe.tool.video.analysis_started"] = "soothe.tool.video.analysis_started"
    tool: str = "analyze_video"
    video_path: str = ""
    question: str = ""

    model_config = ConfigDict(extra="allow")


class VideoAnalysisCompletedEvent(ToolEvent):
    """Video analysis completed event."""

    type: Literal["soothe.tool.video.analysis_completed"] = "soothe.tool.video.analysis_completed"
    tool: str = "analyze_video"
    video_path: str = ""

    model_config = ConfigDict(extra="allow")


class VideoAnalysisFailedEvent(ToolEvent):
    """Video analysis failed event."""

    type: Literal["soothe.tool.video.analysis_failed"] = "soothe.tool.video.analysis_failed"
    tool: str = "analyze_video"
    video_path: str = ""
    error: str = ""

    model_config = ConfigDict(extra="allow")


# Register all video events with the global registry
from soothe.core.event_catalog import register_event  # noqa: E402

register_event(
    VideoUploadStartedEvent,
    verbosity="tool_activity",
    summary_template="Uploading video ({file_size_mb:.1f}MB)",
)
register_event(
    VideoUploadCompletedEvent,
    verbosity="tool_activity",
    summary_template="Video uploaded: {file_name}",
)
register_event(
    VideoProcessingEvent,
    verbosity="tool_activity",
    summary_template="Processing video: {state}",
)
register_event(
    VideoAnalysisStartedEvent,
    verbosity="tool_activity",
    summary_template="Analyzing video",
)
register_event(
    VideoAnalysisCompletedEvent,
    verbosity="tool_activity",
    summary_template="Video analysis complete",
)
register_event(
    VideoAnalysisFailedEvent,
    verbosity="tool_activity",
    summary_template="Analysis failed: {error}",
)

# Event type constants for convenient imports
TOOL_VIDEO_UPLOAD_STARTED = "soothe.tool.video.upload_started"
TOOL_VIDEO_UPLOAD_COMPLETED = "soothe.tool.video.upload_completed"
TOOL_VIDEO_PROCESSING = "soothe.tool.video.processing"
TOOL_VIDEO_ANALYSIS_STARTED = "soothe.tool.video.analysis_started"
TOOL_VIDEO_ANALYSIS_COMPLETED = "soothe.tool.video.analysis_completed"
TOOL_VIDEO_ANALYSIS_FAILED = "soothe.tool.video.analysis_failed"

__all__ = [
    # Constants first (alphabetically)
    "TOOL_VIDEO_ANALYSIS_COMPLETED",
    "TOOL_VIDEO_ANALYSIS_FAILED",
    "TOOL_VIDEO_ANALYSIS_STARTED",
    "TOOL_VIDEO_PROCESSING",
    "TOOL_VIDEO_UPLOAD_COMPLETED",
    "TOOL_VIDEO_UPLOAD_STARTED",
    # Event classes (alphabetically)
    "VideoAnalysisCompletedEvent",
    "VideoAnalysisFailedEvent",
    "VideoAnalysisStartedEvent",
    "VideoProcessingEvent",
    "VideoUploadCompletedEvent",
    "VideoUploadStartedEvent",
]
