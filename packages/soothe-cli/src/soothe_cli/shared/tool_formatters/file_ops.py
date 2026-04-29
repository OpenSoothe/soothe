"""Formatter for file operation tools."""

from __future__ import annotations

from typing import Any

from soothe_cli.shared.tool_formatters.base import BaseFormatter
from soothe_cli.shared.tool_output_formatter import ToolBrief


class FileOpsFormatter(BaseFormatter):
    """Formatter for file operation tools.

    Handles: read_file, write_file, delete_file, list_files, search_files, glob,
    grep, ls

    Provides semantic summaries with size, line count, and item count metrics.
    """

    def format(self, tool_name: str, result: Any) -> ToolBrief:
        r"""Format file operation tool result.

        Args:
            tool_name: Name of the file operation tool.
            result: Tool result (typically string for file operations).

        Returns:
            ToolBrief with file operation summary.

        Raises:
            ValueError: If tool_name is not a recognized file operation.

        Example:
            >>> formatter = FileOpsFormatter()
            >>> brief = formatter.format("read_file", "Hello\nWorld\n")
            >>> brief.to_display()
            '✓ Read 12 B (2 lines)'
        """
        # Normalize tool name
        normalized = tool_name.lower().replace("-", "_").replace(" ", "_")

        # Route to specific formatter
        if normalized == "read_file":
            return self._format_read_file(result)
        if normalized == "write_file":
            return self._format_write_file(result)
        if normalized == "delete_file":
            return self._format_delete_file(result)
        if normalized in ("list_files", "ls"):
            return self._format_list_files(result)
        if normalized == "search_files":
            return self._format_search_files(result)
        if normalized == "glob":
            return self._format_glob(result)
        if normalized == "grep":
            return self._format_search_files(result)
        msg = f"Unknown file operation tool: {tool_name}"
        raise ValueError(msg)

    def _format_read_file(self, result: str) -> ToolBrief:
        r"""Format read_file result.

        Shows file size and line count.

        Args:
            result: File contents as string.

        Returns:
            ToolBrief with size and line count.

        Example:
            >>> brief = formatter._format_read_file("Line 1\nLine 2\nLine 3")
            >>> brief.summary
            'Read 18 B'
            >>> brief.detail
            '3 lines'
        """
        # Check for error
        if result.startswith("Error:"):
            error_msg = result[6:].strip()  # Remove "Error:" prefix
            return ToolBrief(
                icon="✗",
                summary="Read failed",
                detail=self._truncate_text(error_msg, 80),
                metrics={"error": True},
            )

        # Calculate size
        size_bytes = len(result.encode("utf-8"))
        size_str = self._format_size(size_bytes)

        # Count lines
        lines = self._count_lines(result)

        # Build summary
        summary = f"Read {size_str}"

        # Build detail
        if lines == 0:
            detail = "empty file"
        elif lines == 1:
            detail = "1 line"
        else:
            detail = f"{lines} lines"

        return ToolBrief(
            icon="✓",
            summary=summary,
            detail=detail,
            metrics={"size_bytes": size_bytes, "lines": lines},
        )

    def _format_write_file(self, result: str) -> ToolBrief:
        """Format write_file result.

        Shows bytes written or success message.

        Args:
            result: Success message or error string.

        Returns:
            ToolBrief with write status.

        Example:
            >>> brief = formatter._format_write_file("Successfully wrote to file")
            >>> brief.summary
            'Wrote 0 B'
        """
        # Check for error
        if "error" in result.lower() or "failed" in result.lower():
            return ToolBrief(
                icon="✗",
                summary="Write failed",
                detail=self._truncate_text(result, 80),
                metrics={"error": True},
            )

        # Try to extract size from result (if available)
        # Common patterns: "Wrote X bytes", "Successfully wrote X"
        # For now, show simple success
        return ToolBrief(
            icon="✓",
            summary="Wrote file",
            detail=None,
            metrics={},
        )

    def _format_delete_file(self, result: str) -> ToolBrief:
        """Format delete_file result.

        Shows deletion status.

        Args:
            result: Success message or error string.

        Returns:
            ToolBrief with deletion status.

        Example:
            >>> brief = formatter._format_delete_file("File deleted successfully")
            >>> brief.summary
            'Deleted'
        """
        # Check for error
        if "error" in result.lower() or "failed" in result.lower():
            return ToolBrief(
                icon="✗",
                summary="Delete failed",
                detail=self._truncate_text(result, 80),
                metrics={"error": True},
            )

        return ToolBrief(
            icon="✓",
            summary="Deleted",
            detail=None,
            metrics={},
        )

    def _format_list_files(self, result: str) -> ToolBrief:
        r"""Format list_files/ls result.

        Shows count of items listed.

        Args:
            result: List of files as string (newline-separated).

        Returns:
            ToolBrief with item count.

        Example:
            >>> brief = formatter._format_list_files("file1.py\nfile2.py\nfile3.py")
            >>> brief.summary
            'Found 3 items'
        """
        # Check for error
        if "error" in result.lower() or "failed" in result.lower():
            return ToolBrief(
                icon="✗",
                summary="List failed",
                detail=self._truncate_text(result, 80),
                metrics={"error": True},
            )

        # Count items (non-empty lines)
        lines = [line for line in result.split("\n") if line.strip()]
        count = len(lines)

        # Build summary
        summary = f"Found {count} item{'s' if count != 1 else ''}"

        return ToolBrief(
            icon="✓",
            summary=summary,
            detail=None,
            metrics={"count": count},
        )

    def _format_search_files(self, result: str) -> ToolBrief:
        r"""Format search_files result.

        Shows count of matches found.

        Args:
            result: Search results as string (with line numbers and content).

        Returns:
            ToolBrief with match count.

        Example:
            >>> brief = formatter._format_search_files("file.py:1:TODO\nfile.py:5:TODO")
            >>> brief.summary
            'Found 2 matches'
        """
        # Check for error
        if "error" in result.lower() or "failed" in result.lower():
            return ToolBrief(
                icon="✗",
                summary="Search failed",
                detail=self._truncate_text(result, 80),
                metrics={"error": True},
            )

        # Check for "No matches found" or similar
        if "no matches" in result.lower() or result.strip() == "":
            return ToolBrief(
                icon="✓",
                summary="Found 0 matches",
                detail=None,
                metrics={"count": 0},
            )

        # Count matches (non-empty lines)
        lines = [line for line in result.split("\n") if line.strip()]
        count = len(lines)

        summary = f"Found {count} match{'es' if count != 1 else ''}"

        return ToolBrief(
            icon="✓",
            summary=summary,
            detail=None,
            metrics={"count": count},
        )

    def _format_glob(self, result: str) -> ToolBrief:
        r"""Format glob result.

        Shows count of files matching pattern.

        Args:
            result: List of file paths as string (newline-separated).

        Returns:
            ToolBrief with file count.

        Example:
            >>> brief = formatter._format_glob("file1.py\nfile2.py")
            >>> brief.summary
            'Found 2 files'
        """
        # Check for error
        if "error" in result.lower() or "failed" in result.lower():
            return ToolBrief(
                icon="✗",
                summary="Glob failed",
                detail=self._truncate_text(result, 80),
                metrics={"error": True},
            )

        # Count files (non-empty lines)
        lines = [line for line in result.split("\n") if line.strip()]
        count = len(lines)

        summary = f"Found {count} file{'s' if count != 1 else ''}"

        return ToolBrief(
            icon="✓",
            summary=summary,
            detail=None,
            metrics={"count": count},
        )
