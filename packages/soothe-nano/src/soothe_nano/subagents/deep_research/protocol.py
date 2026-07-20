"""Configuration and types for the deep_research subagent."""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

DeepResearchEffortLevel = Literal["normal", "thorough"]

SourceType = Literal["web", "url"]


class SourceResult(BaseModel):
    """A single result returned by web search or URL crawl."""

    content: str
    source_ref: str
    source_name: str
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class GatherContext(BaseModel):
    """Context passed during the gather phase."""

    topic: str
    existing_summaries: list[str] = Field(default_factory=list)
    knowledge_gaps: list[str] = Field(default_factory=list)
    iteration: int = 0


class ResearchReference(BaseModel):
    """Structured source collected during research."""

    url: str | None = None
    title: str | None = None
    source_name: str
    source_ref: str
    query: str | None = None


SCOPE_BANNER = (
    "**Scope:** This report is based on public web sources only. "
    "Local repository files were not analyzed."
)


class DeepResearchConfig(BaseModel):
    """Configuration for the deep_research engine."""

    llm_role: str = Field(default="fast")
    synthesis_role: str = Field(default="fast")
    effort: DeepResearchEffortLevel = Field(default="normal")
    source_timeout_sec: float = Field(
        default=45.0,
        ge=1.0,
        le=120.0,
        description=(
            "Outer wait for one web search gather. Must exceed tools.wizsearch.timeout "
            "(default 30s); the engine raises this automatically when needed."
        ),
    )
    crawl_timeout_sec: float = Field(default=15.0, ge=1.0, le=60.0)
    enable_early_termination: bool = Field(default=True)
    min_results_for_termination: int = Field(default=3, ge=1, le=20)
    min_source_diversity: int = Field(default=2, ge=1, le=5)
    llm_timeout_sec: float = Field(default=30.0, ge=5.0, le=120.0)
    summarize_timeout_sec: float = Field(default=60.0, ge=10.0, le=180.0)
    synthesize_timeout_sec: float = Field(default=60.0, ge=10.0, le=180.0)
    save_reports: bool = Field(
        default=False,
        description=(
            "When true, write the full report under .soothe/agents/deep_research/ "
            "and return a short summary + path. When false (default), return the "
            "full report inline without writing a file."
        ),
    )
    enable_polite_concurrency: bool = Field(default=True)
    polite_retry_max: int = Field(default=3, ge=0, le=10)
    polite_retry_base_delay: float = Field(default=1.0, ge=0.1, le=10.0)
    polite_domain_overrides: dict[str, dict[str, float | int]] = Field(default_factory=dict)


@runtime_checkable
class WebSearchSourceProtocol(Protocol):
    """Protocol for the web search adapter."""

    @property
    def name(self) -> str: ...

    async def query(self, query: str, context: GatherContext) -> list[SourceResult]: ...
