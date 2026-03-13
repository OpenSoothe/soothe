"""Skillify data models (RFC-0004)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class SkillRecord(BaseModel):
    """Metadata for a single indexed skill.

    Args:
        id: Deterministic identifier (SHA-256 of absolute path).
        name: Skill name from SKILL.md frontmatter.
        description: Skill description from SKILL.md frontmatter.
        path: Absolute filesystem path to the skill directory.
        tags: Optional tags from SKILL.md frontmatter.
        status: Indexing status.
        indexed_at: Timestamp of last successful indexing.
        content_hash: SHA-256 hex digest of SKILL.md content.
    """

    id: str
    name: str
    description: str
    path: str
    tags: list[str] = Field(default_factory=list)
    status: Literal["indexed", "stale", "error"] = "indexed"
    indexed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""


class SkillSearchResult(BaseModel):
    """A single result from a retrieval query.

    Args:
        record: The matched skill record.
        score: Cosine similarity score in [0, 1].
    """

    record: SkillRecord
    score: float


class SkillBundle(BaseModel):
    """Response payload for a retrieval request.

    Args:
        query: The original retrieval query.
        results: Ranked list of matching skills.
        total_indexed: Total number of skills in the index.
    """

    query: str
    results: list[SkillSearchResult] = Field(default_factory=list)
    total_indexed: int = 0
