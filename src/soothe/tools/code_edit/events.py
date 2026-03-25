"""Code editing tool events.

This module defines events for code editing tools.
Events are self-registered at module load time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from soothe.core.base_events import ToolEvent


class FileEditStartedEvent(ToolEvent):
    """File edit started event."""

    type: Literal["soothe.tool.code_edit.edit_started"] = "soothe.tool.code_edit.edit_started"
    tool: str = "edit_file_lines"
    path: str = ""
    operation: str = ""

    model_config = ConfigDict(extra="allow")


class FileEditCompletedEvent(ToolEvent):
    """File edit completed event."""

    type: Literal["soothe.tool.code_edit.edit_completed"] = "soothe.tool.code_edit.edit_completed"
    tool: str = "edit_file_lines"
    path: str = ""
    lines_removed: int = 0
    lines_added: int = 0

    model_config = ConfigDict(extra="allow")


class FileEditFailedEvent(ToolEvent):
    """File edit failed event."""

    type: Literal["soothe.tool.code_edit.edit_failed"] = "soothe.tool.code_edit.edit_failed"
    tool: str = "edit_file_lines"
    path: str = ""
    error: str = ""

    model_config = ConfigDict(extra="allow")


class DiffAppliedEvent(ToolEvent):
    """Diff applied event."""

    type: Literal["soothe.tool.code_edit.diff_applied"] = "soothe.tool.code_edit.diff_applied"
    tool: str = "apply_diff"
    path: str = ""

    model_config = ConfigDict(extra="allow")


# Register all code_edit events with the global registry
from soothe.core.event_catalog import register_event  # noqa: E402

register_event(
    FileEditStartedEvent,
    summary_template="Editing: {path}",
)
register_event(
    FileEditCompletedEvent,
    summary_template="Edited: +{lines_added}/-{lines_removed} lines",
)
register_event(
    FileEditFailedEvent,
    summary_template="Edit failed: {error}",
)
register_event(
    DiffAppliedEvent,
    summary_template="Applied diff to {path}",
)

# Event type constants for convenient imports
TOOL_CODE_EDIT_EDIT_STARTED = "soothe.tool.code_edit.edit_started"
TOOL_CODE_EDIT_EDIT_COMPLETED = "soothe.tool.code_edit.edit_completed"
TOOL_CODE_EDIT_EDIT_FAILED = "soothe.tool.code_edit.edit_failed"
TOOL_CODE_EDIT_DIFF_APPLIED = "soothe.tool.code_edit.diff_applied"

__all__ = [
    # Constants first (alphabetically)
    "TOOL_CODE_EDIT_DIFF_APPLIED",
    "TOOL_CODE_EDIT_EDIT_COMPLETED",
    "TOOL_CODE_EDIT_EDIT_FAILED",
    "TOOL_CODE_EDIT_EDIT_STARTED",
    # Event classes (alphabetically)
    "DiffAppliedEvent",
    "FileEditCompletedEvent",
    "FileEditFailedEvent",
    "FileEditStartedEvent",
]
