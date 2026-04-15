"""Base formatter interface for tool output summarization."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from soothe_cli.shared.tool_output_formatter import ToolBrief

# Byte size thresholds
_KB = 1024
_MB = _KB * 1024
_GB = _MB * 1024


class BaseFormatter(ABC):
    """Abstract base class for tool-specific formatters.

    Each formatter implements semantic summarization for a category of tools
    (file operations, execution, media, goals, etc.).
    """

    @abstractmethod
    def format(self, tool_name: str, result: Any) -> ToolBrief:
        """Format tool result into semantic summary.

        Args:
            tool_name: Name of the tool (e.g., "read_file", "run_command").
            result: Tool result (can be str, dict, ToolOutput, or other).

        Returns:
            ToolBrief with semantic summary.

        Raises:
            NotImplementedError: If not implemented by subclass.
        """
        raise NotImplementedError

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format byte size as human-readable string.

        Args:
            size_bytes: Size in bytes.

        Returns:
            Human-readable size string (e.g., "2.3 KB", "1.5 MB").

        Example:
            >>> BaseFormatter._format_size(1024)
            '1.0 KB'
            >>> BaseFormatter._format_size(1536)
            '1.5 KB'
            >>> BaseFormatter._format_size(1048576)
            '1.0 MB'
        """
        if size_bytes < _KB:
            return f"{size_bytes} B"
        if size_bytes < _MB:
            size_kb = size_bytes / _KB
            return f"{size_kb:.1f} KB"
        if size_bytes < _GB:
            size_mb = size_bytes / _MB
            return f"{size_mb:.1f} MB"
        size_gb = size_bytes / _GB
        return f"{size_gb:.1f} GB"

    @staticmethod
    def _count_lines(text: str) -> int:
        r"""Count number of lines in text.

        Args:
            text: Text to count lines in.

        Returns:
            Number of lines (minimum 1 for non-empty text, 0 for empty text).

        Example:
            >>> BaseFormatter._count_lines("Hello\nWorld\n")
            2
            >>> BaseFormatter._count_lines("")
            0
            >>> BaseFormatter._count_lines("Single line")
            1
        """
        if not text or not text.strip():
            return 0
        return text.count("\n") + 1 if text.strip() else 0

    @staticmethod
    def _truncate_text(text: str, max_length: int = 80) -> str:
        """Truncate text to maximum length with ellipsis.

        Args:
            text: Text to truncate.
            max_length: Maximum length (default 80).

        Returns:
            Truncated text with "..." if longer than max_length.

        Example:
            >>> BaseFormatter._truncate_text("Short text", max_length=10)
            'Short text'
            >>> BaseFormatter._truncate_text("Very long text that needs truncation", max_length=20)
            'Very long text tha...'
        """
        if len(text) <= max_length:
            return text
        return text[: max_length - 3] + "..."
