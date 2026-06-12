"""Public information source protocol for the Tacitus subagent."""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

TacitusEffortLevel = Literal["normal", "high", "xhigh"]

CapabilityId = Literal[
    "web_search",
    "academic_search",
    "url_crawl",
]

SourceType = Literal[
    "web",
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


class ResearchReference(BaseModel):
    """Structured source collected during Tacitus gather."""

    url: str | None = None
    title: str | None = None
    source_name: str
    source_ref: str
    query: str | None = None


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
        default="fast",
        description="Router role for final synthesis (defaults to fast for lower latency; set think for higher quality).",
    )
    effort: TacitusEffortLevel = Field(
        default="normal",
        description="Research depth: normal (fast), high, or xhigh.",
    )
    max_loops: int = Field(default=3, ge=1, le=10)
    max_sources_per_query: int = Field(default=3, ge=1, le=10)
    parallel_queries: bool = True
    default_domain: str = "public"
    enabled_capabilities: list[CapabilityId] = Field(
        default_factory=lambda: [
            "web_search",
            "academic_search",
            "url_crawl",
        ],
    )
    capability_profiles: dict[str, list[CapabilityId]] = Field(
        default_factory=lambda: {
            "public": ["web_search", "academic_search", "url_crawl"],
            "web": ["web_search", "url_crawl"],
            "academic": ["academic_search"],
        },
    )
    routing: TacitusRoutingConfig = Field(default_factory=TacitusRoutingConfig)

    # Latency control options (IG-432)
    source_timeout_sec: float = Field(
        default=10.0,
        ge=1.0,
        le=60.0,
        description="Per-source query timeout in seconds.",
    )
    enable_parallel_sources: bool = Field(
        default=True,
        description="Query sources in parallel (vs sequential).",
    )
    enable_early_termination: bool = Field(
        default=True,
        description="Enable adaptive loop termination based on result quality.",
    )
    min_results_for_termination: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Minimum results before considering early termination.",
    )
    min_source_diversity: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Minimum distinct sources for early termination.",
    )
    llm_timeout_sec: float = Field(
        default=30.0,
        ge=5.0,
        le=120.0,
        description="LLM invocation timeout in seconds (used by analyze, generate, reflect).",
    )
    summarize_timeout_sec: float = Field(
        default=60.0,
        ge=10.0,
        le=180.0,
        description="Timeout for summarize LLM calls (higher due to larger input).",
    )
    synthesize_timeout_sec: float = Field(
        default=60.0,
        ge=10.0,
        le=180.0,
        description="Timeout for final synthesis LLM call (higher due to larger input).",
    )

    # Politeness controls (IG-432 Phase 6)
    enable_polite_concurrency: bool = Field(
        default=True,
        description="Enable polite rate limiting for external HTTP requests.",
    )
    polite_rate_limit_rps: float = Field(
        default=1.0,
        ge=0.1,
        le=10.0,
        description="Default requests per second for rate limiting.",
    )
    polite_burst_size: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Default burst size for token bucket rate limiter.",
    )
    polite_max_concurrent: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Default max concurrent requests per domain.",
    )
    polite_retry_max: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Max retries for failed HTTP requests.",
    )
    polite_retry_base_delay: float = Field(
        default=1.0,
        ge=0.1,
        le=10.0,
        description="Base delay in seconds for exponential backoff.",
    )
    polite_circuit_breaker_threshold: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Failures before circuit breaker opens.",
    )
    polite_circuit_breaker_reset_sec: float = Field(
        default=60.0,
        ge=5.0,
        le=300.0,
        description="Seconds before circuit breaker attempts reset.",
    )
    polite_domain_overrides: dict[str, dict[str, float | int]] = Field(
        default_factory=dict,
        description="Per-domain rate limit overrides. Keys: domain, values: {rps, burst, concurrent}.",
    )


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
