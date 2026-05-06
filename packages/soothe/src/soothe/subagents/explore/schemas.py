"""Explore subagent schemas.

Defines the state, output, and configuration schemas for the explore agent (RFC-613).
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, NotRequired

from langchain.agents import AgentState
from pydantic import BaseModel, Field


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


class ExploreAgentState(AgentState[ExploreResult]):
    """State for LangChain ``create_agent`` explore subgraph."""

    workspace: NotRequired[str]
    search_target: NotRequired[str]
    thoroughness: NotRequired[str]
    findings: NotRequired[Annotated[list[dict[str, Any]], operator.add]]
    explore_wire_started: NotRequired[bool]
    explore_model_invocations: NotRequired[int]


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
        max_history_messages_for_model: Keep only recent N message turns in model request.
        max_tool_output_chars_per_turn: Truncate oversized tool outputs before sending back to model.
        early_stop_no_new_findings_turns: Force synthesis if N consecutive turns produce zero net-new findings.
        max_findings_for_synthesis: Max findings sent to synthesis model (default 15, configurable).
        enable_semantic_similarity: Use semantic similarity for relevance scoring (requires sentence_transformers).
    """

    thoroughness: str = "medium"
    max_iterations: dict[str, int] = Field(
        default_factory=lambda: {
            "quick": 12,
            "medium": 24,
            "thorough": 48,
        },
    )
    max_read_lines: int = 50
    max_matches_returned: int = 5

    # IG-399: context growth capping
    max_history_messages_for_model: int = 8
    """Keep only recent N message turns in model request."""

    max_tool_output_chars_per_turn: int = 2000
    """Truncate oversized tool outputs before sending back to model."""

    early_stop_no_new_findings_turns: int = 2
    """Force synthesis if N consecutive turns produce zero net-new findings."""

    # Performance optimization: configurable findings limit for synthesis
    max_findings_for_synthesis: int = 20
    """Max findings sent to synthesis (reduced payload for faster model processing)."""

    enable_semantic_similarity: bool = True
    """Enable semantic similarity for relevance scoring (requires sentence_transformers optional dependency)."""

    # Tool call limit overrides for explore subagent
    tool_call_limit_thread: int | None = None
    """Override global thread tool call limit for explore. None uses ExecutionConfig default."""

    tool_call_limit_run: int | None = None
    """Override global run tool call limit for explore. None uses ExecutionConfig default."""
