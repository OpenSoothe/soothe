"""MemoryProtocol -- cross-thread long-term memory (RFC-0002 Module 2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, Field


class MemoryItem(BaseModel):
    """A unit of long-term knowledge.

    Args:
        id: Unique identifier.
        content: The knowledge content.
        source_thread: Thread that created this item.
        created_at: Creation timestamp.
        tags: Categorical tags for filtering and recall.
        importance: Priority weight from 0.0 to 1.0.
        metadata: Arbitrary key-value metadata.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    content: str
    source_thread: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    tags: list[str] = Field(default_factory=list)
    importance: float = 0.5
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class MemoryProtocol(Protocol):
    """Protocol for cross-thread long-term memory.

    Memory is explicitly populated (not auto-memorized) and semantically
    queryable. Separate from ContextProtocol (within-thread) and
    deepagents' MemoryMiddleware (static AGENTS.md files).
    """

    async def remember(self, item: MemoryItem) -> str:
        """Store a memory item.

        Args:
            item: The memory item to persist.

        Returns:
            The item's unique ID.
        """
        ...

    async def recall(self, query: str, limit: int = 5) -> list[MemoryItem]:
        """Retrieve items by semantic relevance.

        Args:
            query: The search query.
            limit: Maximum number of items to return.

        Returns:
            Matching items ordered by relevance.
        """
        ...

    async def recall_by_tags(self, tags: list[str], limit: int = 10) -> list[MemoryItem]:
        """Retrieve items matching all specified tags.

        Args:
            tags: Tags that items must match (AND logic).
            limit: Maximum number of items to return.

        Returns:
            Matching items ordered by importance.
        """
        ...

    async def forget(self, item_id: str) -> bool:
        """Remove a memory item.

        Args:
            item_id: The item's unique ID.

        Returns:
            True if the item was found and removed.
        """
        ...

    async def update(self, item_id: str, content: str) -> None:
        """Update an existing memory item's content.

        Args:
            item_id: The item's unique ID.
            content: New content to replace the existing content.

        Raises:
            KeyError: If no item with the given ID exists.
        """
        ...
