"""Tests for Explore structured-result markdown formatting (IG-356)."""

from __future__ import annotations

from soothe.subagents.explore.schemas import (
    ExploreResult,
    MatchEntry,
    format_explore_result_markdown,
)


def test_format_explore_result_markdown_includes_summary_and_matches() -> None:
    """Final markdown exposes summary and match sections for delegate parity."""
    result = ExploreResult(
        target="find auth helpers",
        thoroughness="medium",
        summary="Two modules implement JWT validation.",
        matches=[
            MatchEntry(
                path="src/auth/jwt.py",
                relevance="high",
                description="Validates bearer tokens",
                snippet="def verify(...):\n    return True\n",
            ),
        ],
    )
    md = format_explore_result_markdown(result)
    assert "# Explore results" in md
    assert "find auth helpers" in md
    assert "Two modules" in md
    assert "`src/auth/jwt.py`" in md
    assert "```text" in md
