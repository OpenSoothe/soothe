"""Tool-specific formatters for semantic result summarization.

This package provides tool-specific formatters that transform raw tool outputs
into concise, semantic summaries following RFC-0020 event display architecture.
"""

from __future__ import annotations

from soothe.ux.core.tool_formatters.base import BaseFormatter
from soothe.ux.core.tool_formatters.execution import ExecutionFormatter
from soothe.ux.core.tool_formatters.fallback import FallbackFormatter
from soothe.ux.core.tool_formatters.file_ops import FileOpsFormatter
from soothe.ux.core.tool_formatters.goal_formatter import GoalFormatter
from soothe.ux.core.tool_formatters.media import MediaFormatter
from soothe.ux.core.tool_formatters.structured import StructuredFormatter

__all__ = [
    "BaseFormatter",
    "ExecutionFormatter",
    "FallbackFormatter",
    "FileOpsFormatter",
    "GoalFormatter",
    "MediaFormatter",
    "StructuredFormatter",
]
