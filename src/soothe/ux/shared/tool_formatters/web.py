"""Formatter for web search and crawl tools."""

from __future__ import annotations

from typing import Any

from soothe.ux.shared.tool_formatters.base import BaseFormatter
from soothe.ux.shared.tool_output_formatter import ToolBrief


class WebFormatter(BaseFormatter):
    """Formatter for web operation tools.

    Handles: search_web, crawl_web

    Provides semantic summaries with result counts, URLs, and content metrics.
    """

    def format(self, tool_name: str, result: Any) -> ToolBrief:
        r"""Format web tool result.

        Args:
            tool_name: Name of the web tool.
            result: Tool result (typically string with search results or crawled content).

        Returns:
            ToolBrief with web operation summary.

        Raises:
            ValueError: If tool_name is not a recognized web tool.

        Example:
            >>> formatter = WebFormatter()
            >>> brief = formatter.format("search_web", "1. Result\n2. Result")
            >>> brief.summary
            'Found 2 results'
        """
        # Normalize tool name
        normalized = tool_name.lower().replace("-", "_").replace(" ", "_")

        # Route to specific formatter
        if normalized == "search_web":
            return self._format_search_web(result)
        if normalized == "crawl_web":
            return self._format_crawl_web(result)

        msg = f"Unknown web tool: {tool_name}"
        raise ValueError(msg)

    def _format_search_web(self, result: str) -> ToolBrief:
        r"""Format search_web result.

        Shows count of search results found.

        Args:
            result: Search results string with titles, URLs, snippets.

        Returns:
            ToolBrief with result count.

        Example:
            >>> brief = formatter._format_search_web("1. Example\n2. Another")
            >>> brief.summary
            'Found 2 results'
        """
        # Check for error
        if "error" in result.lower() or "failed" in result.lower():
            return ToolBrief(
                icon="✗",
                summary="Search failed",
                detail=self._truncate_text(result, 80),
                metrics={"error": True},
            )

        # Count results (non-empty lines or result sections)
        lines = [line for line in result.split("\n") if line.strip()]

        # Try to detect result count patterns
        # Pattern: numbered results "1. Title" "2. Title"
        numbered_results = [line for line in lines if len(line) > 0 and line[0].isdigit() and "." in line[:3]]
        count = len(numbered_results) if numbered_results else max(1, len(lines) // 3)

        summary = f"Found {count} result{'s' if count != 1 else ''}"

        # Show first URL or title as detail if available
        first_line = lines[0] if lines else ""
        detail = self._truncate_text(first_line, 80) if first_line else None

        return ToolBrief(
            icon="✓",
            summary=summary,
            detail=detail,
            metrics={"count": count},
        )

    def _format_crawl_web(self, result: str) -> ToolBrief:
        """Format crawl_web result.

        Shows content size and word/line count.

        Args:
            result: Crawled content string.

        Returns:
            ToolBrief with content metrics.

        Example:
            >>> brief = formatter._format_crawl_web("Article content...")
            >>> brief.summary
            'Crawled 2.3 KB'
            >>> brief.detail
            '450 words'
        """
        # Check for error
        if "error" in result.lower() or "failed" in result.lower():
            return ToolBrief(
                icon="✗",
                summary="Crawl failed",
                detail=self._truncate_text(result, 80),
                metrics={"error": True},
            )

        # Calculate metrics
        size_bytes = len(result.encode("utf-8"))
        size_str = self._format_size(size_bytes)

        # Count words and lines
        words = len(result.split())
        lines = self._count_lines(result)

        summary = f"Crawled {size_str}"

        # Show word count as detail
        detail = f"{words} words"

        return ToolBrief(
            icon="✓",
            summary=summary,
            detail=detail,
            metrics={"size_bytes": size_bytes, "words": words, "lines": lines},
        )
