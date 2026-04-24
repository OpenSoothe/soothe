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
