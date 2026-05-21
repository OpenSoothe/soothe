"""Public information source protocol for the Tacitus subagent."""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

CapabilityId = Literal[
    "web_search",
    "wikipedia",
    "academic_search",
    "url_crawl",
]

SourceType = Literal[
    "web",
    "encyclopedia",
    "academic",
    "url",
]


class SourceResult(BaseModel):
    """A single result returned by a public information source."""

    content: str
    source_ref: str
    source_name: str
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class GatherContext(BaseModel):
    """Context passed to a source during the gather phase."""

    topic: str
    existing_summaries: list[str] = Field(default_factory=list)
    knowledge_gaps: list[str] = Field(default_factory=list)
    iteration: int = 0


class TacitusRoutingConfig(BaseModel):
    """Semantic routing configuration."""

    semantic_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    fallback_score: float = Field(default=0.5, ge=0.0, le=1.0)


class TacitusConfig(BaseModel):
    """Configuration for the Tacitus engine."""

    llm_role: str = Field(
        default="fast",
        description="Router role for loop LLM steps (analyze, queries, summarize, reflect).",
    )
    synthesis_role: str = Field(
        default="think",
        description="Router role for final synthesis (defaults to think; set fast for lower latency).",
    )
    max_loops: int = Field(default=3, ge=1, le=10)
    max_sources_per_query: int = Field(default=3, ge=1, le=10)
    parallel_queries: bool = True
    default_domain: str = "public"
    enabled_capabilities: list[CapabilityId] = Field(
        default_factory=lambda: [
            "web_search",
            "wikipedia",
            "academic_search",
            "url_crawl",
        ],
    )
    capability_profiles: dict[str, list[CapabilityId]] = Field(
        default_factory=lambda: {
            "public": ["web_search", "wikipedia", "academic_search", "url_crawl"],
            "web": ["web_search", "wikipedia", "url_crawl"],
            "academic": ["academic_search", "wikipedia"],
        },
    )
    routing: TacitusRoutingConfig = Field(default_factory=TacitusRoutingConfig)


@runtime_checkable
class PublicInformationSource(Protocol):
    """Protocol for a public-domain queryable source."""

    @property
    def name(self) -> str:
        """Human-readable source name."""
        ...

    @property
    def capability_id(self) -> CapabilityId:
        """Stable capability id for routing."""
        ...

    @property
    def source_type(self) -> SourceType:
        """Canonical source type."""
        ...

    @property
    def capability_description(self) -> str:
        """Fixed English description embedded for semantic routing."""
        ...

    async def query(self, query: str, context: GatherContext) -> list[SourceResult]:
        """Execute a query against this source."""
        ...


InformationSource = PublicInformationSource
