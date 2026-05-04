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


def test_format_explore_result_markdown_includes_ig380_sections_when_set() -> None:
    """IG-380 optional sections render when non-empty."""
    result = ExploreResult(
        target="map cli package",
        thoroughness="thorough",
        summary="Entry is soothe_cli/main.py.",
        matches=[],
        suggested_next_actions="- read_file packages/soothe-cli/src/soothe_cli/main.py",
        coverage_gaps="Did not scan node_modules.",
        architecture_notes="- CLI entry: Typer app\n- TUI: Textual",
    )
    md = format_explore_result_markdown(result)
    assert "## Suggested next actions" in md
    assert "soothe_cli/main.py" in md
    assert "## Coverage and gaps" in md
    assert "node_modules" in md
    assert "## Architecture notes" in md
    assert "Typer" in md
