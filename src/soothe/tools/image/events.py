"""Image tool events.

This module defines events for image tools (analyze_image, extract_text_from_image).
Events are self-registered at module load time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from soothe.core.base_events import ToolEvent


class ImageAnalysisStartedEvent(ToolEvent):
    """Image analysis started event."""

    type: Literal["soothe.tool.image.analysis_started"] = "soothe.tool.image.analysis_started"
    image_path: str = ""
    prompt: str = ""

    model_config = ConfigDict(extra="allow")


class ImageAnalysisCompletedEvent(ToolEvent):
    """Image analysis completed event."""

    type: Literal["soothe.tool.image.analysis_completed"] = "soothe.tool.image.analysis_completed"
    image_path: str = ""

    model_config = ConfigDict(extra="allow")


class ImageOCREvent(ToolEvent):
    """Image OCR started event."""

    type: Literal["soothe.tool.image.ocr_started"] = "soothe.tool.image.ocr_started"
    image_path: str = ""

    model_config = ConfigDict(extra="allow")


class ImageOCRCompletedEvent(ToolEvent):
    """Image OCR completed event."""

    type: Literal["soothe.tool.image.ocr_completed"] = "soothe.tool.image.ocr_completed"
    image_path: str = ""
    text_length: int = 0

    model_config = ConfigDict(extra="allow")


# Register all image events with the global registry
from soothe.core.event_catalog import register_event  # noqa: E402
from soothe.core.verbosity_tier import VerbosityTier  # noqa: E402

register_event(
    ImageAnalysisStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Analyzing image: {image_path}",
)
register_event(
    ImageAnalysisCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Image analysis complete",
)
register_event(
    ImageOCREvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Extracting text from image: {image_path}",
)
register_event(
    ImageOCRCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="OCR complete: {text_length} characters extracted",
)

# Event type constants for convenient imports
TOOL_IMAGE_ANALYSIS_STARTED = "soothe.tool.image.analysis_started"
TOOL_IMAGE_ANALYSIS_COMPLETED = "soothe.tool.image.analysis_completed"
TOOL_IMAGE_OCR_STARTED = "soothe.tool.image.ocr_started"
TOOL_IMAGE_OCR_COMPLETED = "soothe.tool.image.ocr_completed"

__all__ = [
    # Constants first (alphabetically)
    "TOOL_IMAGE_ANALYSIS_COMPLETED",
    "TOOL_IMAGE_ANALYSIS_STARTED",
    "TOOL_IMAGE_OCR_COMPLETED",
    "TOOL_IMAGE_OCR_STARTED",
    # Event classes (alphabetically)
    "ImageAnalysisCompletedEvent",
    "ImageAnalysisStartedEvent",
    "ImageOCRCompletedEvent",
    "ImageOCREvent",
]
