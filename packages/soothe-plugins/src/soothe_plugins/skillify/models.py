"""Skillify data models (RFC-0004)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class SkillRecord(BaseModel):
    """Metadata for a single indexed skill."""

    id: str
    name: str
    description: str
    path: str
    tags: list[str] = Field(default_factory=list)
    status: Literal["indexed", "stale", "error"] = "indexed"
    indexed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""


class SkillSearchResult(BaseModel):
    """A single result from a retrieval query."""

    record: SkillRecord
    score: float


class SkillBundle(BaseModel):
    """Response payload for a retrieval request."""

    query: str
    results: list[SkillSearchResult] = Field(default_factory=list)
    total_indexed: int = 0
