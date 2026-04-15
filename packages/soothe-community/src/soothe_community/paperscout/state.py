"""PaperScout configuration and state models.

Pydantic v2 models for configuration and LangGraph agent state.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field

from soothe_community.paperscout.models import (
    ArxivPaper,
    EmailContent,
    ScoredPaper,
)


class SmtpConfig(BaseModel):
    """SMTP server configuration."""

    model_config = ConfigDict(extra="forbid")

    host: str
    port: int = 587
    user: str
    password: str
    use_tls: bool = True


class ZoteroConfig(BaseModel):
    """Zotero API configuration."""

    model_config = ConfigDict(extra="forbid")

    api_key: str
    library_id: str
    library_type: str = "user"  # "user" or "group"


class PaperScoutConfig(BaseModel):
    """PaperScout subagent configuration."""

    model_config = ConfigDict(extra="forbid")

    # ArXiv query settings
    arxiv_categories: list[str] = Field(
        default=["cs.AI", "cs.CV", "cs.LG", "cs.CL"],
        description="ArXiv categories to query",
    )
    max_papers: int = Field(
        default=25,
        ge=1,
        le=100,
        description="Maximum papers to include in digest",
    )
    max_papers_queried: int = Field(
        default=500,
        ge=10,
        le=1000,
        description="Maximum papers to query from ArXiv",
    )

    # Email settings
    send_email: bool = Field(
        default=True,
        description="Whether to send email notifications",
    )
    send_empty: bool = Field(
        default=False,
        description="Send email even if no relevant papers found",
    )
    recipient_email: str | None = Field(
        default=None,
        description="Email recipient (defaults to SMTP user)",
    )

    # Date range settings
    lookback_days: int = Field(
        default=7,
        ge=1,
        le=30,
        description="Days to look back for papers",
    )
    big_bang_date: date | None = Field(
        default=None,
        description="Earliest valid notification date",
    )

    # Notification settings
    gap_window_days: int = Field(
        default=7,
        ge=1,
        le=30,
        description="Window to check for missed notifications",
    )
    emailed_papers_retention_days: int = Field(
        default=30,
        ge=7,
        le=90,
        description="Days to keep emailed papers in cache",
    )

    # Service configurations
    smtp: SmtpConfig | None = None
    zotero: ZoteroConfig | None = None

    # LLM settings
    tldr_max_tokens: int = Field(
        default=150,
        ge=50,
        le=300,
        description="Max tokens for TLDR generation",
    )
    tldr_language: str = Field(
        default="English",
        description="Language for TLDR summaries",
    )


class AgentState(dict):
    """LangGraph agent state for PaperScout workflow.

    This state flows through the workflow nodes:
    profile_analysis → data_collection → relevance_assessment →
    content_generation → communication
    """

    # LangGraph message history
    messages: Annotated[list[Any], add_messages]

    # Configuration
    config: PaperScoutConfig
    user_id: str

    # Discovered papers
    discovered_papers: list[ArxivPaper] = Field(default_factory=list)

    # Zotero corpus
    zotero_papers: list[Any] = Field(default_factory=list)  # ZoteroPaper objects

    # Scored papers
    scored_papers: list[ScoredPaper] = Field(default_factory=list)

    # Email content
    email_content: EmailContent | None = None

    # Error tracking
    errors: Annotated[list[str], "add"] = Field(default_factory=list)

    # Info messages
    info: Annotated[list[str], "add"] = Field(default_factory=list)

    # Metrics
    metrics: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AgentState",
    "PaperScoutConfig",
    "SmtpConfig",
    "ZoteroConfig",
]
