"""PaperScout data models.

Pydantic v2 models for paper data, email content, and notifications.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ArxivPaper(BaseModel):
    """ArXiv paper metadata."""

    model_config = ConfigDict(extra="allow")

    title: str
    summary: str
    authors: list[str]
    arxiv_id: str
    pdf_url: str
    published_date: datetime
    score: float = 0.0
    code_url: str | None = None
    affiliations: list[str] | None = None
    tldr: str | None = None
    tex: str | None = None  # LaTeX source content


class ZoteroPaper(BaseModel):
    """Zotero library paper metadata."""

    model_config = ConfigDict(extra="allow")

    zotero_item_key: str
    title: str
    authors: list[str]
    abstract: str | None = None
    url: str | None = None
    tags: list[str] = Field(default_factory=list)
    date_added: datetime | None = None
    collection_paths: list[str] = Field(default_factory=list)


class ScoredPaper(BaseModel):
    """Paper with relevance score."""

    model_config = ConfigDict(extra="allow")

    paper: ArxivPaper
    score: float
    relevance_factors: dict[str, float] = Field(default_factory=dict)


class EmailContent(BaseModel):
    """Email digest content."""

    model_config = ConfigDict(extra="allow")

    subject: str
    html_body: str
    text_body: str | None = None
    papers: list[ArxivPaper]


class NotificationRecord(BaseModel):
    """Record of a sent notification."""

    model_config = ConfigDict(extra="allow")

    date: date
    papers_count: int
    recipient: str
    arxiv_ids: list[str]
    sent_at: datetime
    success: bool = True
    error_message: str | None = None


class DateRange(BaseModel):
    """Processed date range for ArXiv queries."""

    model_config = ConfigDict(extra="allow")

    start_date: date
    end_date: date
    category: str
    processed_at: datetime = Field(default_factory=datetime.now)


__all__ = [
    "ArxivPaper",
    "DateRange",
    "EmailContent",
    "NotificationRecord",
    "ScoredPaper",
    "ZoteroPaper",
]
