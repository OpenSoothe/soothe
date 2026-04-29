"""Unit tests for tool-specific formatters (RFC-0020)."""

import pytest

from soothe_cli.shared.tool_formatters import (
    FileOpsFormatter,
    WebFormatter,
)
from soothe_cli.shared.tool_output_formatter import ToolBrief


class TestWebFormatter:
    """Tests for WebFormatter."""

    def test_search_web_success_with_numbered_results(self) -> None:
        """Test search_web with numbered results."""
        formatter = WebFormatter()
        result = "1. Example result\nURL: https://example.com\n2. Another result\nURL: https://another.com"

        brief = formatter.format("search_web", result)

        assert brief.icon == "✓"
        assert "Found" in brief.summary
        assert brief.metrics["count"] == 2

    def test_search_web_success_with_unstructured_results(self) -> None:
        """Test search_web with unstructured results."""
        formatter = WebFormatter()
        result = "Title: Example\nURL: https://example.com\nSnippet: Example snippet"

        brief = formatter.format("search_web", result)

        assert brief.icon == "✓"
        assert "Found" in brief.summary
        assert brief.metrics["count"] >= 1

    def test_search_web_error(self) -> None:
        """Test search_web with error."""
        formatter = WebFormatter()
        result = "Error: connection timeout"

        brief = formatter.format("search_web", result)

        assert brief.icon == "✗"
        assert "failed" in brief.summary.lower()
        assert brief.metrics.get("error") is True

    def test_crawl_web_success(self) -> None:
        """Test crawl_web with content."""
        formatter = WebFormatter()
        result = "This is a long article with many words and paragraphs. It contains substantial content for testing."

        brief = formatter.format("crawl_web", result)

        assert brief.icon == "✓"
        assert "Crawled" in brief.summary
        assert "words" in brief.detail
        assert brief.metrics["words"] > 0
        assert brief.metrics["size_bytes"] > 0

    def test_crawl_web_error(self) -> None:
        """Test crawl_web with error."""
        formatter = WebFormatter()
        result = "Error: URL not found"

        brief = formatter.format("crawl_web", result)

        assert brief.icon == "✗"
        assert "failed" in brief.summary.lower()
        assert brief.metrics.get("error") is True

    def test_web_formatter_unknown_tool_raises_error(self) -> None:
        """Test WebFormatter raises ValueError for unknown tool."""
        formatter = WebFormatter()

        with pytest.raises(ValueError, match="Unknown web tool"):
            formatter.format("unknown_web_tool", "some result")


class TestRFC0020Compliance:
    """Tests for RFC-0020 compliance (50/80 char limits)."""

    def test_summary_truncated_to_50_chars(self) -> None:
        """Test that ToolBrief summary respects 50-char limit."""
        formatter = FileOpsFormatter()
        # Create very long file content
        result = "x" * 10000

        brief = formatter.format("read_file", result)

        # Summary should be <= 50 chars (enforced by formatter)
        assert len(brief.summary) <= 50

    def test_detail_truncated_to_80_chars(self) -> None:
        """Test that ToolBrief detail respects 80-char limit."""
        formatter = WebFormatter()
        # Create very long error message
        result = "Error: " + "x" * 200

        brief = formatter.format("search_web", result)

        # Detail should be <= 80 chars (enforced by _truncate_text)
        if brief.detail:
            assert len(brief.detail) <= 80

    def test_to_display_format(self) -> None:
        """Test ToolBrief.to_display() format matches RFC-0020."""
        brief = ToolBrief(
            icon="✓",
            summary="Read 2.3 KB",
            detail="42 lines",
        )

        display = brief.to_display()

        # Should format as "icon summary (detail)"
        assert display == "✓ Read 2.3 KB (42 lines)"

    def test_to_display_without_detail(self) -> None:
        """Test ToolBrief.to_display() without detail."""
        brief = ToolBrief(
            icon="✓",
            summary="Found 3 items",
            detail=None,
        )

        display = brief.to_display()

        # Should format as "icon summary" without parentheses
        assert display == "✓ Found 3 items"

    def test_file_ops_formatter_metrics(self) -> None:
        """Test that FileOpsFormatter includes proper metrics."""
        formatter = FileOpsFormatter()
        result = "Line 1\nLine 2\nLine 3"  # 3 lines without trailing newline

        brief = formatter.format("read_file", result)

        # Should include size_bytes and lines metrics
        assert "size_bytes" in brief.metrics
        assert "lines" in brief.metrics
        assert brief.metrics["lines"] == 3

    def test_web_formatter_metrics(self) -> None:
        """Test that WebFormatter includes proper metrics."""
        formatter = WebFormatter()
        result = "1. Result 1\n2. Result 2\n3. Result 3"

        brief = formatter.format("search_web", result)

        # Should include count metric
        assert "count" in brief.metrics
        assert brief.metrics["count"] == 3


class TestFormatterRouting:
    """Tests for formatter routing in ToolOutputFormatter."""

    def test_file_ops_route_to_file_formatter(self) -> None:
        """Test that file_ops tools route to FileOpsFormatter."""
        from soothe_cli.shared.tool_output_formatter import ToolOutputFormatter

        formatter = ToolOutputFormatter()

        brief = formatter.format("read_file", "content")

        assert brief.icon == "✓"
        assert "Read" in brief.summary

    def test_grep_routes_to_file_ops_without_error(self) -> None:
        """grep is file_ops in SDK metadata; FileOpsFormatter must handle it."""
        from soothe_cli.shared.tool_output_formatter import ToolOutputFormatter

        formatter = ToolOutputFormatter()
        brief = formatter.format("grep", "a.py:1:match\nb.py:2:match")

        assert brief.icon == "✓"
        assert brief.metrics.get("count") == 2
        assert "match" in brief.summary.lower()

    def test_web_tools_route_to_web_formatter(self) -> None:
        """Test that web tools are routed to WebFormatter."""
        from soothe_cli.shared.tool_output_formatter import ToolOutputFormatter

        formatter = ToolOutputFormatter()

        # Test search_web
        brief = formatter.format("search_web", "1. Result\n2. Result")
        assert brief.icon in ("✓", "✗")
        assert brief.metrics.get("count") is not None

        # Test crawl_web
        brief = formatter.format("crawl_web", "Article content")
        assert brief.icon in ("✓", "✗")
        assert brief.metrics.get("words") is not None

    def test_execution_tools_route_to_execution_formatter(self) -> None:
        """Test that execution tools route to ExecutionFormatter."""
        from soothe_cli.shared.tool_output_formatter import ToolOutputFormatter

        formatter = ToolOutputFormatter()

        brief = formatter.format("run_command", "Done")

        assert brief.icon in ("✓", "✗")

    def test_unknown_category_falls_back(self) -> None:
        """Test that unknown tool category uses FallbackFormatter."""
        from soothe_cli.shared.tool_output_formatter import ToolOutputFormatter

        formatter = ToolOutputFormatter()

        # Unknown tool should still produce a brief (via fallback)
        brief = formatter.format("unknown_tool", "some result")

        assert brief.icon in ("✓", "✗", "⚠")


class TestToolBrief:
    """Tests for ToolBrief dataclass."""

    def test_icon_values(self) -> None:
        """Test that ToolBrief accepts valid icons."""
        valid_icons = ["✓", "✗", "⚠"]

        for icon in valid_icons:
            brief = ToolBrief(icon=icon, summary="Test")
            assert brief.icon == icon

    def test_metrics_default_empty_dict(self) -> None:
        """Test that metrics defaults to empty dict."""
        brief = ToolBrief(icon="✓", summary="Test")

        assert brief.metrics == {}

    def test_metrics_can_be_set(self) -> None:
        """Test that metrics can be set."""
        brief = ToolBrief(
            icon="✓",
            summary="Test",
            metrics={"count": 10, "size": 1024},
        )

        assert brief.metrics["count"] == 10
        assert brief.metrics["size"] == 1024


class TestFormatterErrorHandling:
    """Tests for formatter error handling."""

    def test_file_ops_handles_error_in_result(self) -> None:
        """Test that FileOpsFormatter handles error strings."""
        formatter = FileOpsFormatter()
        result = "Error: File not found"

        brief = formatter.format("read_file", result)

        assert brief.icon == "✗"
        assert "failed" in brief.summary.lower()
        assert brief.metrics.get("error") is True

    def test_web_formatter_handles_empty_result(self) -> None:
        """Test that WebFormatter handles empty results."""
        formatter = WebFormatter()
        result = ""

        brief = formatter.format("search_web", result)

        # Should still produce valid brief (with count=0 or minimal count)
        assert brief.icon == "✓"
        assert "Found" in brief.summary

    def test_file_ops_handles_empty_file(self) -> None:
        """Test that FileOpsFormatter handles empty files."""
        formatter = FileOpsFormatter()
        result = ""

        brief = formatter.format("read_file", result)

        assert brief.icon == "✓"
        assert "Read" in brief.summary
        assert brief.detail == "empty file"
        assert brief.metrics["lines"] == 0
