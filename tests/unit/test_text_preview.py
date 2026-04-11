"""Tests for the unified text preview utility."""

from __future__ import annotations

from soothe.utils.text_preview import (
    DEFAULT_MARKER_TEMPLATE,
    DEFAULT_PREVIEW_CHARS,
    DEFAULT_PREVIEW_LINES,
    log_preview,
    preview,
    preview_first,
    preview_full,
    preview_lines,
)


# ---------------------------------------------------------------------------
# preview() – char mode
# ---------------------------------------------------------------------------


class TestPreviewChars:
    """Char-based preview tests."""

    def test_short_text_not_truncated(self) -> None:
        assert preview("Hello", mode="chars", first=10) == "Hello"

    def test_exact_length_not_truncated(self) -> None:
        text = "A" * 200
        assert preview(text, mode="chars", first=200) == text

    def test_truncated_with_default_marker(self) -> None:
        text = "A" * 300
        result = preview(text, mode="chars", first=100)
        assert result.startswith("A" * 100)
        assert "[...200 chars abbr...]" in result

    def test_first_and_last(self) -> None:
        text = "A" * 300
        result = preview(text, mode="chars", first=50, last=30)
        assert result.startswith("A" * 50)
        assert result.endswith("A" * 30)
        assert "[...220 chars abbr...]" in result

    def test_first_and_last_overlap_returns_full(self) -> None:
        text = "Hello world"
        result = preview(text, mode="chars", first=6, last=6)
        assert result == "Hello world"

    def test_custom_marker(self) -> None:
        text = "A" * 100
        result = preview(text, mode="chars", first=10, marker="SNIP")
        assert result == "A" * 10 + "SNIP"

    def test_empty_marker(self) -> None:
        text = "A" * 100
        result = preview(text, mode="chars", first=10, marker="")
        assert result == "A" * 10

    def test_empty_string(self) -> None:
        assert preview("", mode="chars", first=10) == ""

    def test_default_first_value(self) -> None:
        text = "A" * 300
        result = preview(text, mode="chars")
        assert result.startswith("A" * DEFAULT_PREVIEW_CHARS)
        assert f"[...{300 - DEFAULT_PREVIEW_CHARS} chars abbr...]" in result

    def test_unicode_text(self) -> None:
        text = "你好世界" * 100
        result = preview(text, mode="chars", first=10)
        assert result.startswith("你好世界你好世界")
        assert "chars abbr" in result

    def test_first_and_last_with_custom_marker(self) -> None:
        text = "ABCDEFGHIJ" * 20  # 200 chars
        result = preview(text, mode="chars", first=10, last=10, marker="...")
        assert result.startswith("ABCDEFGHIJ")
        assert result.endswith("ABCDEFGHIJ")
        assert "..." in result


# ---------------------------------------------------------------------------
# preview() – line mode
# ---------------------------------------------------------------------------


class TestPreviewLines:
    """Line-based preview tests."""

    def test_few_lines_not_truncated(self) -> None:
        text = "Line1\nLine2\nLine3"
        assert preview(text, mode="lines", first=5) == text

    def test_truncated_with_default_marker(self) -> None:
        text = "\n".join(f"Line{i}" for i in range(10))
        result = preview(text, mode="lines", first=3)
        assert result.startswith("Line0\nLine1\nLine2\n")
        assert "[...7 lines abbr...]" in result
        # Marker should be on its own line
        assert "\n[...7 lines abbr...]" in result

    def test_first_and_last_lines(self) -> None:
        text = "\n".join(f"Line{i}" for i in range(10))
        result = preview(text, mode="lines", first=2, last=2)
        assert result.startswith("Line0\nLine1\n")
        assert result.endswith("Line8\nLine9")
        assert "[...6 lines abbr...]" in result
        # Marker should be on its own line between first and last
        assert "\n[...6 lines abbr...]\n" in result

    def test_first_and_last_overlap_returns_full(self) -> None:
        text = "Line1\nLine2\nLine3"
        result = preview(text, mode="lines", first=2, last=2)
        assert result == text

    def test_custom_marker(self) -> None:
        text = "\n".join(f"Line{i}" for i in range(10))
        result = preview(text, mode="lines", first=2, marker="MORE")
        assert result.startswith("Line0\nLine1\n")
        assert result.endswith("MORE")
        # Custom marker should also be on its own line
        assert "\nMORE" in result

    def test_empty_string(self) -> None:
        assert preview("", mode="lines", first=5) == ""

    def test_single_line(self) -> None:
        assert preview("Only line", mode="lines", first=5) == "Only line"

    def test_preserves_line_endings_in_first(self) -> None:
        text = "Line1\nLine2\nLine3\nLine4"
        result = preview(text, mode="lines", first=2)
        assert "Line1\nLine2\n" in result
        # Marker should be on its own line after first lines
        assert "\n[...2 lines abbr...]" in result

    def test_preserves_line_endings_first_and_last(self) -> None:
        text = "Line1\nLine2\nLine3\nLine4\nLine5"
        result = preview(text, mode="lines", first=1, last=1)
        assert "Line1" in result
        assert "Line5" in result
        # Marker should be on its own line between first and last
        assert "\n[...3 lines abbr...]\n" in result

    def test_default_first_value(self) -> None:
        lines = [f"Line{i}" for i in range(20)]
        text = "\n".join(lines)
        result = preview(text, mode="lines")
        assert result.startswith("Line0")
        assert f"[...{20 - DEFAULT_PREVIEW_LINES} lines abbr...]" in result
        # Marker should be on its own line
        assert "\n[...15 lines abbr...]" in result

    def test_trailing_newline_handled(self) -> None:
        text = "Line1\nLine2\nLine3\n"
        result = preview(text, mode="lines", first=2)
        assert "Line1\nLine2\n" in result
        # Marker should be on its own line after first lines
        assert "\n[...1 lines abbr...]" in result


# ---------------------------------------------------------------------------
# preview() – full mode
# ---------------------------------------------------------------------------


class TestPreviewFull:
    """Full output mode tests."""

    def test_returns_text_as_is(self) -> None:
        text = "A" * 1000
        assert preview(text, mode="full") == text

    def test_empty_string(self) -> None:
        assert preview("", mode="full") == ""

    def test_ignores_first_and_last(self) -> None:
        text = "Hello"
        assert preview(text, mode="full", first=2, last=2) == "Hello"


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


class TestPreviewFirstFunc:
    """preview_first() convenience function tests."""

    def test_default_chars(self) -> None:
        text = "A" * 300
        result = preview_first(text)
        assert len(result) > DEFAULT_PREVIEW_CHARS  # includes marker
        assert result.startswith("A" * DEFAULT_PREVIEW_CHARS)

    def test_custom_chars(self) -> None:
        text = "A" * 100
        result = preview_first(text, chars=50)
        assert result.startswith("A" * 50)
        assert "chars abbr" in result

    def test_short_text(self) -> None:
        assert preview_first("Short") == "Short"


class TestPreviewLinesFunc:
    """preview_lines() convenience function tests."""

    def test_default_lines(self) -> None:
        text = "\n".join(f"Line{i}" for i in range(20))
        result = preview_lines(text)
        assert "Line0" in result
        assert "lines abbr" in result
        # Marker should be on its own line
        assert "\n[...15 lines abbr...]" in result

    def test_with_last(self) -> None:
        text = "\n".join(f"Line{i}" for i in range(10))
        result = preview_lines(text, first=2, last=2)
        assert "Line0" in result
        assert "Line9" in result
        # Marker should be on its own line between first and last
        assert "\n[...6 lines abbr...]\n" in result

    def test_last_zero_means_no_last(self) -> None:
        text = "\n".join(f"Line{i}" for i in range(10))
        result = preview_lines(text, first=3, last=0)
        assert "Line0" in result
        assert "Line9" not in result


class TestPreviewFullFunc:
    """preview_full() convenience function tests."""

    def test_returns_text_as_is(self) -> None:
        assert preview_full("Anything") == "Anything"


class TestLogPreview:
    """log_preview() convenience function tests."""

    def test_truncated_with_ellipsis_marker(self) -> None:
        text = "A" * 100
        result = log_preview(text, chars=10)
        assert result == "A" * 10 + "..."

    def test_short_text_not_truncated(self) -> None:
        assert log_preview("Short", chars=10) == "Short"

    def test_default_chars(self) -> None:
        text = "A" * 300
        result = log_preview(text)
        assert result.startswith("A" * DEFAULT_PREVIEW_CHARS)
        assert result.endswith("...")

    def test_replaces_printf_style(self) -> None:
        """Verify log_preview works as drop-in for %.Ns patterns."""
        goal = "A" * 100
        result = f"goat={log_preview(goal, 80)}"
        assert result.startswith("goat=" + "A" * 80)
        assert result.endswith("...")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case and boundary condition tests."""

    def test_very_short_limit(self) -> None:
        result = preview("Hello world", mode="chars", first=1)
        assert result.startswith("H")
        assert "chars abbr" in result

    def test_limit_of_one(self) -> None:
        text = "A" * 5
        result = preview(text, mode="chars", first=1)
        assert result.startswith("A")
        assert "[...4 chars abbr...]" in result

    def test_last_only(self) -> None:
        """When first is 0 and last is set, should show only last portion."""
        text = "A" * 100
        result = preview(text, mode="chars", first=0, last=10)
        # first=0 means 0 chars from start, so full last portion
        assert result.endswith("A" * 10)
        # first_n=0, total=100, last_n=10 -> omitted = 100-0-10 = 90
        assert "[...90 chars abbr...]" in result

    def test_newlines_in_char_mode(self) -> None:
        """Char mode counts newlines as characters."""
        text = "Line1\nLine2\nLine3"
        result = preview(text, mode="chars", first=6)
        assert result.startswith("Line1\n")
        assert "chars abbr" in result

    def test_multiline_string_in_lines_mode(self) -> None:
        text = "Line1\n\nLine3\n\nLine5"
        result = preview(text, mode="lines", first=2)
        # Empty lines are valid lines
        assert "Line1" in result
        # Marker should be on its own line after first lines
        assert "\n[...3 lines abbr...]" in result

    def test_marker_template_constants(self) -> None:
        """Verify the marker template produces expected output."""
        marker = DEFAULT_MARKER_TEMPLATE.format(count=42, unit="chars")
        assert marker == "[...42 chars abbr...]"

    def test_exact_boundary_char(self) -> None:
        """Text exactly at the limit should not be truncated."""
        text = "A" * 50
        assert preview(text, mode="chars", first=50) == text

    def test_one_over_boundary_char(self) -> None:
        """Text one char over the limit should be truncated."""
        text = "A" * 51
        result = preview(text, mode="chars", first=50)
        assert "[...1 chars abbr...]" in result

    def test_exact_boundary_lines(self) -> None:
        """Lines exactly at the limit should not be truncated."""
        text = "\n".join(f"Line{i}" for i in range(5))
        assert preview(text, mode="lines", first=5) == text

    def test_one_over_boundary_lines(self) -> None:
        """One line over the limit should be truncated."""
        text = "\n".join(f"Line{i}" for i in range(6))
        result = preview(text, mode="lines", first=5)
        assert "[...1 lines abbr...]" in result
        # Marker should be on its own line after first lines
        assert "\n[...1 lines abbr...]" in result
