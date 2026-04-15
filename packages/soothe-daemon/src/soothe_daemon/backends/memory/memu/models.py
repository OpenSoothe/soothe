"""Memory models for memU internal use."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class MemoryItem(BaseModel):
    """Internal memory item representation.

    Args:
        id: Unique identifier.
        content: Memory content.
        memory_type: Type of memory (profile, event, knowledge, etc.).
        user_id: User identifier.
        agent_id: Agent identifier.
        session_id: Session identifier.
        importance: Importance score 0.0-1.0.
        context: Additional context.
        metadata: Arbitrary metadata.
        tags: Categorical tags.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
        version: Version number for optimistic locking.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    content: str
    memory_type: str = "knowledge"
    user_id: str | None = None
    agent_id: str | None = None
    session_id: str | None = None
    importance: float = 0.5
    context: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None = None
    version: int = 1


class MemoryFilter(BaseModel):
    """Filter criteria for memory queries.

    Args:
        user_id: Filter by user ID.
        agent_id: Filter by agent ID.
        session_id: Filter by session ID.
        memory_type: Filter by memory type.
        tags: Filter by tags (AND logic).
        date_from: Filter by creation date (from).
        date_to: Filter by creation date (to).
        min_importance: Minimum importance threshold.
        metadata_filters: Additional metadata filters.
    """

    user_id: str | None = None
    agent_id: str | None = None
    session_id: str | None = None
    memory_type: str | None = None
    tags: list[str] | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    min_importance: float | None = None
    metadata_filters: dict[str, Any] = Field(default_factory=dict)


class SearchResult(BaseModel):
    """Search result with relevance score.

    Args:
        memory_item: The matching memory item.
        relevance_score: Relevance score 0.0-1.0.
        search_metadata: Additional search metadata.
    """

    memory_item: MemoryItem
    relevance_score: float = Field(ge=0.0, le=1.0)
    search_metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryStats(BaseModel):
    """Statistics about memory store.

    Args:
        total_items: Total number of memory items.
        items_by_type: Count of items by memory type.
        items_by_user: Count of items by user.
        oldest_item_date: Date of oldest item.
        newest_item_date: Date of newest item.
        average_importance: Average importance score.
        storage_size_bytes: Total storage size in bytes.
    """

    total_items: int = 0
    items_by_type: dict[str, int] = Field(default_factory=dict)
    items_by_user: dict[str, int] = Field(default_factory=dict)
    oldest_item_date: datetime | None = None
    newest_item_date: datetime | None = None
    average_importance: float = 0.0
    storage_size_bytes: int | None = None
