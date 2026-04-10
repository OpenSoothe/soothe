"""Tool output formatter for semantic result summarization (RFC-0020).

This module provides a formatter-based pipeline that transforms raw tool outputs
into concise, semantic summaries following RFC-0020 event display architecture.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ToolBrief:
    """Structured summary of tool execution result.

    Follows RFC-0020 two-level tree display pattern with maximum lengths
    enforced for terminal display.

    Attributes:
        icon: Status indicator (✓, ✗, ⚠).
        summary: One-line summary (max 50 characters).
        detail: Optional detail line (max 80 characters).
        metrics: Optional metadata (size, duration, count, etc.).
    """

    icon: str
    summary: str
    detail: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_display(self) -> str:
        """Format as RFC-0020 display string.

        Returns:
            Formatted string: "icon summary (detail)" or "icon summary".

        Example:
            >>> brief = ToolBrief(icon="✓", summary="Read 2.3 KB", detail="42 lines")
            >>> brief.to_display()
            '✓ Read 2.3 KB (42 lines)'
        """
        result = f"{self.icon} {self.summary}"
        if self.detail:
            result += f" ({self.detail})"
        return result

    def __post_init__(self) -> None:
        """Enforce RFC-0020 length constraints."""
        # Maximum summary length: 50 characters
        max_summary_len = 50
        if len(self.summary) > max_summary_len:
            self.summary = self.summary[: max_summary_len - 3] + "..."

        # Maximum detail length: 80 characters
        max_detail_len = 80
        if self.detail and len(self.detail) > max_detail_len:
            self.detail = self.detail[: max_detail_len - 3] + "..."


# Tool category mapping for classifier
TOOL_CATEGORIES: dict[str, str] = {
    # File operations
    "read_file": "file_ops",
    "write_file": "file_ops",
    "delete_file": "file_ops",
    "list_files": "file_ops",
    "search_files": "file_ops",
    "glob": "file_ops",
    "ls": "file_ops",
    # Execution
    "run_command": "execution",
    "run_python": "execution",
    "run_background": "execution",
    "kill_process": "execution",
    # Media
    "transcribe_audio": "media",
    "get_video_info": "media",
    "analyze_image": "media",
    # Goals
    "create_goal": "goals",
    "list_goals": "goals",
    "complete_goal": "goals",
    "fail_goal": "goals",
    # Web
    "search_web": "web",
    "crawl_web": "web",
}


def classify_tool(tool_name: str) -> str:
    """Classify tool into category based on name.

    Args:
        tool_name: Name of the tool (e.g., "read_file", "run_command").

    Returns:
        Tool category (e.g., "file_ops", "execution", "media", "goals", "web", "unknown").

    Example:
        >>> classify_tool("read_file")
        'file_ops'
        >>> classify_tool("unknown_tool")
        'unknown'
    """
    # Normalize tool name to snake_case (handle variations)
    normalized = tool_name.lower().replace("-", "_").replace(" ", "_")

    # Look up in category mapping
    return TOOL_CATEGORIES.get(normalized, "unknown")


def detect_result_type(result: Any) -> str:
    """Detect result type for routing to appropriate formatter.

    Args:
        result: Tool result (can be str, dict, ToolOutput, or other).

    Returns:
        Result type string: "tool_output", "dict", "str", or "unknown".

    Example:
        >>> detect_result_type("some string")
        'str'
        >>> detect_result_type({"success": True})
        'dict'
    """
    # Check for ToolOutput (from agentic loop)
    # Import here to avoid circular imports
    try:
        from soothe.cognition.agent_loop.core.schemas import ToolOutput

        if isinstance(result, ToolOutput):
            return "tool_output"
    except ImportError:
        pass  # ToolOutput not available, skip check

    # Check standard types
    if isinstance(result, dict):
        return "dict"
    if isinstance(result, str):
        return "str"
    return "unknown"


class ToolOutputFormatter:
    """Main formatter for tool output summarization.

    Coordinates classification and routing to tool-specific formatters
    with fallback handling for unknown tools.
    """

    def format(self, tool_name: str, result: Any) -> ToolBrief:
        r"""Format tool result into semantic summary.

        Args:
            tool_name: Name of the tool (e.g., "read_file", "run_command").
            result: Tool result (can be str, dict, ToolOutput, or other).

        Returns:
            ToolBrief with semantic summary.

        Example:
            >>> formatter = ToolOutputFormatter()
            >>> brief = formatter.format("read_file", "Hello\nWorld\n")
            >>> brief.to_display()
            '✓ Read 12 B (2 lines)'
        """
        # Classify tool
        category = classify_tool(tool_name)

        # Detect result type
        result_type = detect_result_type(result)

        # Route to appropriate formatter
        try:
            # Import formatters (lazy import to avoid circular dependencies)
            from soothe.ux.shared.tool_formatters import (
                ExecutionFormatter,
                FallbackFormatter,
                FileOpsFormatter,
                GoalFormatter,
                MediaFormatter,
                StructuredFormatter,
                WebFormatter,
            )

            # Handle ToolOutput first (highest priority)
            if result_type == "tool_output":
                formatter = StructuredFormatter()
                return formatter.format(tool_name, result)

            # Route by category
            if category == "file_ops":
                formatter = FileOpsFormatter()
                return formatter.format(tool_name, result)
            if category == "execution":
                formatter = ExecutionFormatter()
                return formatter.format(tool_name, result)
            if category == "media":
                formatter = MediaFormatter()
                return formatter.format(tool_name, result)
            if category == "goals":
                formatter = GoalFormatter()
                return formatter.format(tool_name, result)
            if category == "web":
                formatter = WebFormatter()
                return formatter.format(tool_name, result)
            # Unknown category - use fallback
            formatter = FallbackFormatter()
            return formatter.format(tool_name, result)

        except Exception as e:
            # Log error and fallback to simple formatting
            logger.warning(
                "Formatter error for tool %s: %s. Using fallback.",
                tool_name,
                e,
                exc_info=True,
            )
            from soothe.ux.shared.tool_formatters import FallbackFormatter

            formatter = FallbackFormatter()
            return formatter.format(tool_name, result)
