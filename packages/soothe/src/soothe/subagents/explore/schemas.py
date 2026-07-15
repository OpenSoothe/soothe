"""Explore subagent schemas.

Defines the state, output, and configuration schemas for the explore agent (RFC-613).
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, NotRequired

from langchain.agents import AgentState
from pydantic import BaseModel, Field


def _last_wins(left: str | None, right: str | None) -> str | None:
    """Reducer for workspace: last non-empty value wins (IG-328, LangGraph InvalidUpdateError fix).

    LangGraph's ``LastValue`` channel rejects multiple writes per step. When both
    ``WorkspaceContextMiddleware`` and ``ExploreWireMiddleware`` write ``workspace``
    in the same tick, ``InvalidUpdateError`` is raised. This reducer allows multiple
    writes, with the last non-empty value winning.

    Args:
        left: Previous workspace value (or None).
        right: New workspace value (or None).

    Returns:
        ``right`` if non-empty, else ``left``.
    """
    if right is not None and str(right).strip():
        return right
    return left


class MatchEntry(BaseModel):
    """A single match result from the explore agent."""

    path: str
    relevance: Literal["high", "medium", "low"]
    description: str  # One-line description (~50 chars)
    snippet: str | None = None  # Relevant content (if read during search)


class ExploreResult(BaseModel):
    """Final output of the explore agent."""

    target: str
    thoroughness: str = "medium"  # Optional; defaults when LLM omits
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


_MAX_MARKDOWN_SNIPPET_CHARS = 2500


class ExploreAgentState(AgentState[ExploreResult]):
    """State for LangChain ``create_agent`` explore subgraph."""

    workspace: NotRequired[Annotated[str, _last_wins]]
    search_target: NotRequired[str]
    thoroughness: NotRequired[str]  # Optional; defaults to "medium" in ExploreResult
    findings: NotRequired[Annotated[list[dict[str, Any]], operator.add]]
    explore_wire_started: NotRequired[bool]
    explore_started_at_monotonic: NotRequired[float]
    explore_model_invocations: NotRequired[int]
    prev_findings_count: NotRequired[int]
    findings_stall_counter: NotRequired[int]
    explore_completion_status: NotRequired[str]
    explore_failure_reason: NotRequired[str]


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
                if len(snippet) > _MAX_MARKDOWN_SNIPPET_CHARS:
                    snippet = snippet[: _MAX_MARKDOWN_SNIPPET_CHARS - 1] + "…"
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
        recursion_limit: LangGraph recursion limit for explorer graph execution.
        max_iterations: Per-level iteration caps.
        max_read_lines: Max lines per read_file call.
        max_matches_returned: Max matches in final result.
        max_history_messages_for_model: Keep only recent N message turns in model request.
        max_tool_output_chars_per_turn: Truncate oversized tool outputs before sending back to model.
        early_stop_no_new_findings_turns: Force synthesis if N consecutive turns produce zero net-new findings.
        max_findings_for_synthesis: Max findings sent to synthesis model (default 15, configurable).
        enable_semantic_similarity: Use semantic similarity for relevance scoring (requires fastembed).
        semantic_similarity_timeout_seconds: Wall-clock cap for async synthesis relevance scoring (embedding + rank).
        synthesis_timeout_seconds: Wall-clock cap for LLM structured synthesis before partial fallback.
        synthesis_validation_retries: Additional retries after structured validation failure.
        synthesis_fallback_to_primary_model: Retry synthesis on primary model when fast model fails.
    """

    thoroughness: str = "medium"
    recursion_limit: int = Field(
        default=999,
        ge=1,
        description="LangGraph recursion limit for explorer subagent graph execution.",
    )
    max_iterations: dict[str, int] = Field(
        default_factory=lambda: {
            "quick": 8,
            "medium": 14,
            "thorough": 24,
        },
    )
    max_read_lines: int = 80
    max_matches_returned: int = 8

    # IG-399: context growth capping
    max_history_messages_for_model: int = 12
    """Keep only recent N message turns in model request."""

    max_tool_output_chars_per_turn: int = 4000
    """Truncate oversized tool outputs before sending back to model."""

    early_stop_no_new_findings_turns: int = 3
    """Force synthesis if N consecutive turns produce zero net-new findings."""

    # Performance optimization: configurable findings limit for synthesis
    max_findings_for_synthesis: int = 30
    """Max findings sent to synthesis (reduced payload for faster model processing)."""

    enable_semantic_similarity: bool = True
    """Enable semantic similarity for relevance scoring (requires fastembed optional dependency)."""

    semantic_similarity_timeout_seconds: float = Field(
        default=10.0,
        ge=1.0,
        le=120.0,
        description="Async synthesis: max seconds for semantic relevance scoring before keyword fallback.",
    )

    synthesis_timeout_seconds: float = Field(
        default=120.0,
        ge=5.0,
        le=600.0,
        description="Max seconds for LLM structured synthesis; partial fallback uses findings on timeout/error.",
    )

    synthesis_validation_retries: int = Field(
        default=1,
        ge=0,
        le=3,
        description="Additional retries for synthesis when structured schema validation fails.",
    )

    synthesis_fallback_to_primary_model: bool = Field(
        default=True,
        description="Retry synthesis on primary explorer model when fast synthesis model fails.",
    )

    # Tool call limit overrides for explore subagent
    tool_call_limit_thread: int | None = None
    """Override global thread tool call limit for explore. None uses loop.tool_call_limit default."""

    tool_call_limit_run: int | None = None
    """Override global run tool call limit for explore. None uses loop.tool_call_limit default."""
