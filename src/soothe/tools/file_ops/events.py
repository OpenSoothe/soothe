"""File operations tool events.

This module defines events for file_ops tools (read_file, write_file, delete_file, search_files, list_files, file_info).
Events are self-registered at module load time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from soothe.core.base_events import ToolEvent


class FileReadEvent(ToolEvent):
    """File read event."""

    type: Literal["soothe.tool.file_ops.read"] = "soothe.tool.file_ops.read"
    tool: str = "read_file"
    path: str = ""
    bytes_read: int = 0

    model_config = ConfigDict(extra="allow")


class FileWriteEvent(ToolEvent):
    """File write event."""

    type: Literal["soothe.tool.file_ops.write"] = "soothe.tool.file_ops.write"
    tool: str = "write_file"
    path: str = ""
    bytes_written: int = 0
    mode: str = "overwrite"

    model_config = ConfigDict(extra="allow")


class FileDeleteEvent(ToolEvent):
    """File delete event."""

    type: Literal["soothe.tool.file_ops.delete"] = "soothe.tool.file_ops.delete"
    tool: str = "delete_file"
    path: str = ""
    backup_created: bool = False

    model_config = ConfigDict(extra="allow")


class FileSearchStartedEvent(ToolEvent):
    """File search started event."""

    type: Literal["soothe.tool.file_ops.search_started"] = "soothe.tool.file_ops.search_started"
    tool: str = "search_files"
    pattern: str = ""
    path: str = ""

    model_config = ConfigDict(extra="allow")


class FileSearchCompletedEvent(ToolEvent):
    """File search completed event."""

    type: Literal["soothe.tool.file_ops.search_completed"] = "soothe.tool.file_ops.search_completed"
    tool: str = "search_files"
    matches_count: int = 0

    model_config = ConfigDict(extra="allow")


class BackupCreatedEvent(ToolEvent):
    """Backup created event."""

    type: Literal["soothe.tool.file_ops.backup_created"] = "soothe.tool.file_ops.backup_created"
    tool: str = "create_backup"
    original_path: str = ""
    backup_path: str = ""

    model_config = ConfigDict(extra="allow")


# Register all file_ops events with the global registry
from soothe.core.event_catalog import register_event  # noqa: E402

register_event(
    FileReadEvent,
    verbosity="tool_activity",
    summary_template="Read: {path} ({bytes_read} bytes)",
)
register_event(
    FileWriteEvent,
    verbosity="tool_activity",
    summary_template="Wrote: {path} ({bytes_written} bytes, {mode})",
)
register_event(
    FileDeleteEvent,
    verbosity="tool_activity",
    summary_template="Deleted: {path} (backup={backup_created})",
)
register_event(
    FileSearchStartedEvent,
    verbosity="tool_activity",
    summary_template="Searching: {pattern} in {path}",
)
register_event(
    FileSearchCompletedEvent,
    verbosity="tool_activity",
    summary_template="Search found {matches_count} matches",
)
register_event(
    BackupCreatedEvent,
    verbosity="tool_activity",
    summary_template="Backup: {backup_path}",
)

# Event type constants for convenient imports
TOOL_FILE_OPS_BACKUP_CREATED = "soothe.tool.file_ops.backup_created"
TOOL_FILE_OPS_DELETE = "soothe.tool.file_ops.delete"
TOOL_FILE_OPS_READ = "soothe.tool.file_ops.read"
TOOL_FILE_OPS_SEARCH_COMPLETED = "soothe.tool.file_ops.search_completed"
TOOL_FILE_OPS_SEARCH_STARTED = "soothe.tool.file_ops.search_started"
TOOL_FILE_OPS_WRITE = "soothe.tool.file_ops.write"

__all__ = [
    # Constants first (alphabetically)
    "TOOL_FILE_OPS_BACKUP_CREATED",
    "TOOL_FILE_OPS_DELETE",
    "TOOL_FILE_OPS_READ",
    "TOOL_FILE_OPS_SEARCH_COMPLETED",
    "TOOL_FILE_OPS_SEARCH_STARTED",
    "TOOL_FILE_OPS_WRITE",
    # Event classes (alphabetically)
    "BackupCreatedEvent",
    "FileDeleteEvent",
    "FileReadEvent",
    "FileSearchCompletedEvent",
    "FileSearchStartedEvent",
    "FileWriteEvent",
]
