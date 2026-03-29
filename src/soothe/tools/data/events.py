"""Data tool events.

This module defines events for data tools (inspect_data, summarize_data, check_data_quality, extract_text).
Events are self-registered at module load time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from soothe.core.base_events import ToolEvent


class DataInspectionStartedEvent(ToolEvent):
    """Data inspection started event."""

    type: Literal["soothe.tool.data.inspection_started"] = "soothe.tool.data.inspection_started"
    tool: str = "inspect_data"
    file_path: str = ""
    domain: str = ""

    model_config = ConfigDict(extra="allow")


class DataInspectionCompletedEvent(ToolEvent):
    """Data inspection completed event."""

    type: Literal["soothe.tool.data.inspection_completed"] = "soothe.tool.data.inspection_completed"
    tool: str = "inspect_data"
    file_path: str = ""
    result_summary: str = ""

    model_config = ConfigDict(extra="allow")


class DataQualityCheckEvent(ToolEvent):
    """Data quality check event."""

    type: Literal["soothe.tool.data.quality_check"] = "soothe.tool.data.quality_check"
    tool: str = "check_data_quality"
    file_path: str = ""
    issues_found: int = 0

    model_config = ConfigDict(extra="allow")


class TextExtractionStartedEvent(ToolEvent):
    """Text extraction started event."""

    type: Literal["soothe.tool.data.text_extraction_started"] = "soothe.tool.data.text_extraction_started"
    tool: str = "extract_text"
    file_path: str = ""

    model_config = ConfigDict(extra="allow")


class TextExtractionCompletedEvent(ToolEvent):
    """Text extraction completed event."""

    type: Literal["soothe.tool.data.text_extraction_completed"] = "soothe.tool.data.text_extraction_completed"
    tool: str = "extract_text"
    file_path: str = ""
    char_count: int = 0

    model_config = ConfigDict(extra="allow")


# Register all data events with the global registry
from soothe.core.event_catalog import register_event  # noqa: E402
from soothe.core.verbosity_tier import VerbosityTier  # noqa: E402

register_event(
    DataInspectionStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Inspecting: {file_path} ({domain})",
)
register_event(
    DataInspectionCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Inspection complete: {result_summary}",
)
register_event(
    DataQualityCheckEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Quality check: {issues_found} issues found",
)
register_event(
    TextExtractionStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Extracting text from: {file_path}",
)
register_event(
    TextExtractionCompletedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Extracted {char_count} characters",
)

# Event type constants for convenient imports
TOOL_DATA_INSPECTION_STARTED = "soothe.tool.data.inspection_started"
TOOL_DATA_INSPECTION_COMPLETED = "soothe.tool.data.inspection_completed"
TOOL_DATA_QUALITY_CHECK = "soothe.tool.data.quality_check"
TOOL_DATA_TEXT_EXTRACTION_STARTED = "soothe.tool.data.text_extraction_started"
TOOL_DATA_TEXT_EXTRACTION_COMPLETED = "soothe.tool.data.text_extraction_completed"

__all__ = [
    # Constants first (alphabetically)
    "TOOL_DATA_INSPECTION_COMPLETED",
    "TOOL_DATA_INSPECTION_STARTED",
    "TOOL_DATA_QUALITY_CHECK",
    "TOOL_DATA_TEXT_EXTRACTION_COMPLETED",
    "TOOL_DATA_TEXT_EXTRACTION_STARTED",
    # Event classes (alphabetically)
    "DataInspectionCompletedEvent",
    "DataInspectionStartedEvent",
    "DataQualityCheckEvent",
    "TextExtractionCompletedEvent",
    "TextExtractionStartedEvent",
]
