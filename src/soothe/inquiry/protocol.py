"""InformationSource protocol and supporting models for the Inquiry Engine.

Defines the core abstraction for any queryable information source.
Implementations wrap existing Soothe tools (web_search, file_edit, cli, etc.)
behind a uniform interface so the InquiryEngine can orchestrate them
without knowing implementation details.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

SourceType = Literal[
    "web",
    "academic",
    "filesystem",
    "cli",
    "browser",
    "document",
]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class SourceResult(BaseModel):
    """A single result returned by an InformationSource.

    Args:
        content: The retrieved text content.
        source_ref: Origin reference (URL, file path, command, etc.).
        source_name: Name of the InformationSource that produced this result.
        confidence: Source-assigned confidence in relevance (0.0-1.0).
        metadata: Arbitrary extra data (e.g. title, line numbers, snippet).
    """

    content: str
    source_ref: str
    source_name: str
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class GatherContext(BaseModel):
    """Context passed to a source during the gather phase.

    Provides the source with enough information to tailor its query
    execution (e.g. avoid re-fetching already-known content).

    Args:
        topic: The overarching research topic.
        existing_summaries: Summaries gathered so far (for deduplication).
        knowledge_gaps: Identified gaps from the reflect phase.
        iteration: Current research loop iteration (0-based).
    """

    topic: str
    existing_summaries: list[str] = Field(default_factory=list)
    knowledge_gaps: list[str] = Field(default_factory=list)
    iteration: int = 0


class InquiryConfig(BaseModel):
    """Configuration for the InquiryEngine.

    Args:
        max_loops: Maximum research reflection loops before forced synthesis.
        max_sources_per_query: Maximum sources the router may select per query.
        parallel_queries: Execute queries against multiple sources in parallel.
        default_domain: Default source domain when caller doesn't specify.
        enabled_sources: Source types available to the engine.
        source_profiles: Named profiles mapping domain names to source type lists.
    """

    max_loops: int = Field(default=3, ge=1, le=10)
    max_sources_per_query: int = Field(default=3, ge=1, le=10)
    parallel_queries: bool = True
    default_domain: str = "auto"
    enabled_sources: list[SourceType] = Field(
        default_factory=lambda: ["web", "academic", "filesystem", "cli", "document"],
    )
    source_profiles: dict[str, list[SourceType]] = Field(
        default_factory=lambda: {
            "web": ["web", "academic"],
            "code": ["filesystem", "cli"],
            "deep": ["web", "academic", "filesystem", "cli", "browser", "document"],
        },
    )


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class InformationSource(Protocol):
    """Protocol for a queryable information source.

    Each implementation wraps one or more existing Soothe tools behind
    a uniform async interface.  The ``relevance_score`` method enables
    deterministic routing without an extra LLM call.
    """

    @property
    def name(self) -> str:
        """Human-readable source name (e.g. 'web_search', 'filesystem')."""
        ...

    @property
    def source_type(self) -> SourceType:
        """Canonical source type for profile-based filtering."""
        ...

    async def query(self, query: str, context: GatherContext) -> list[SourceResult]:
        """Execute a query against this source.

        Args:
            query: The search query or exploration directive.
            context: Contextual information about the research state.

        Returns:
            List of results, possibly empty if the source found nothing.
        """
        ...

    def relevance_score(self, query: str) -> float:
        """Score how well this source can handle the given query.

        Returns a value in ``[0.0, 1.0]``.  The SourceRouter uses this
        for deterministic source selection -- no LLM call required.

        A score of 0.0 means the source is irrelevant for this query.
        A score of 1.0 means the source is the ideal match.

        Args:
            query: The search query to evaluate.

        Returns:
            Relevance score between 0.0 and 1.0.
        """
        ...
