"""Explore subagent schemas.

Defines the state, output, and configuration schemas for the
LLM-orchestrated iterative filesystem search agent (RFC-613).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class ExploreState(TypedDict):
    """State schema for the explore engine graph."""

    messages: Annotated[list, add_messages]
    search_target: str
    workspace: str
    thoroughness: Literal["quick", "medium", "thorough"]
    findings: list[dict[str, Any]]  # [{path, snippet, relevance}]
    iterations_used: int
    max_iterations: int
    assessment_decision: Literal["continue", "adjust", "finish"]


class MatchEntry(BaseModel):
    """A single match result from the explore agent."""

    path: str
    relevance: Literal["high", "medium", "low"]
    description: str  # One-line description (~50 chars)
    snippet: str | None = None  # Relevant content (if read during search)


class ExploreResult(BaseModel):
    """Final output of the explore agent."""

    target: str
    thoroughness: str
    matches: list[MatchEntry]  # Top matches, sorted by relevance
    summary: str  # Brief answer to the search target
    suggested_next_actions: str = Field(
        default="",
        description="Markdown bullets: concrete next steps for parent (read_file/grep paths)",
    )
    coverage_gaps: str = Field(
        default="",
        description="What was not searched, limits, assumptions",
    )
    architecture_notes: str = Field(
        default="",
        description="Optional bullets for broad architecture-style targets; empty if N/A",
    )


def _md_single_line(text: str, max_len: int) -> str:
    """Collapse whitespace for safe single-line markdown fields."""
    one = " ".join(text.split()).strip()
    if len(one) > max_len:
        return one[: max_len - 1] + "…"
    return one


def format_explore_result_markdown(result: ExploreResult) -> str:
    """Render structured explore output as user-facing markdown (IG-356).

    Used as the subgraph final AIMessage so headless and planner paths receive
    prose comparable to other delegate finals, not JSON-only payloads.

    Args:
        result: Structured synthesis output from the explore graph.

    Returns:
        Markdown string for the delegate final message body.
    """
    lines: list[str] = [
        "# Explore results",
        "",
        f"**Search target:** {_md_single_line(result.target, 400)}",
        f"**Thoroughness:** {result.thoroughness}",
        "",
        "## Summary",
        "",
        (result.summary.strip() or "_No summary._"),
        "",
        "## Matches",
        "",
    ]
    if not result.matches:
        lines.append("_No ranked matches returned._")
    else:
        for i, m in enumerate(result.matches, 1):
            lines.append(f"### {i}. `{m.path}`")
            lines.append("")
            lines.append(f"- **Relevance:** {m.relevance}")
            lines.append(f"- **Description:** {_md_single_line(m.description, 400)}")
            if m.snippet and m.snippet.strip():
                lines.append("")
                lines.append("```text")
                snippet = m.snippet.strip()
                if len(snippet) > 4000:
                    snippet = snippet[:3999] + "…"
                lines.append(snippet)
                lines.append("```")
            lines.append("")
    if (result.suggested_next_actions or "").strip():
        lines.extend(
            [
                "## Suggested next actions",
                "",
                result.suggested_next_actions.strip(),
                "",
            ]
        )
    if (result.coverage_gaps or "").strip():
        lines.extend(
            [
                "## Coverage and gaps",
                "",
                result.coverage_gaps.strip(),
                "",
            ]
        )
    if (result.architecture_notes or "").strip():
        lines.extend(
            [
                "## Architecture notes",
                "",
                result.architecture_notes.strip(),
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


class ExploreSubagentConfig(BaseModel):
    """Explore-specific configuration, stored inside SubagentConfig.config.

    Args:
        thoroughness: Default thoroughness level.
        max_iterations: Per-level iteration caps.
        max_read_lines: Max lines per read_file call.
        max_matches_returned: Max matches in final result.
    """

    thoroughness: str = "medium"
    max_iterations: dict[str, int] = Field(
        default_factory=lambda: {
            "quick": 2,
            "medium": 4,
            "thorough": 6,
        },
    )
    max_read_lines: int = 50
    max_matches_returned: int = 5
