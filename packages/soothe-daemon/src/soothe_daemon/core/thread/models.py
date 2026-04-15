"""Thread management models for RFC-402."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ThreadStats(BaseModel):
    """Thread execution statistics (calculated on demand)."""

    message_count: int = 0
    event_count: int = 0
    artifact_count: int = 0
    total_tokens_used: int = 0
    total_cost: float = 0.0
    avg_response_time_ms: float = 0.0
    error_count: int = 0
    last_error: str | None = None


class ExecutionContext(BaseModel):
    """Current execution state for running threads."""

    current_goal: str | None = None
    current_step: str | None = None
    iteration: int = 0
    started_at: datetime
    estimated_completion: datetime | None = None


class EnhancedThreadInfo(BaseModel):
    """Complete thread information with statistics."""

    thread_id: str
    status: Literal["idle", "running", "suspended", "archived", "error"]
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    stats: ThreadStats = Field(default_factory=ThreadStats)
    execution_context: ExecutionContext | None = None
    last_human_message: str | None = None


class ThreadFilter(BaseModel):
    """Thread filtering criteria.

    Note: This is a duplicate of soothe.protocols.durability.ThreadFilter.
    Prefer importing from protocols.durability for canonical usage.
    This model exists for compatibility with existing daemon imports.
    """

    status: Literal["idle", "running", "suspended", "archived", "error"] | None = None
    tags: list[str] | None = None
    labels: list[str] | None = None
    priority: Literal["low", "normal", "high"] | None = None
    category: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    updated_after: datetime | None = None
    updated_before: datetime | None = None


class ThreadMessage(BaseModel):
    """Single message in thread conversation."""

    timestamp: datetime
    kind: Literal["conversation", "event", "tool_call", "tool_result"]
    role: Literal["user", "assistant", "system"] | None = None
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactEntry(BaseModel):
    """Thread artifact metadata."""

    filename: str
    size_bytes: int
    created_at: datetime
    artifact_type: Literal["file", "report", "checkpoint", "other"]
    download_url: str
