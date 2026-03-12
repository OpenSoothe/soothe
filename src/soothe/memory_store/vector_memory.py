"""VectorMemory -- semantic memory implementation using vector store."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from soothe.protocols.memory import MemoryItem

if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings

    from soothe.protocols.vector_store import VectorStoreProtocol

logger = logging.getLogger(__name__)


class VectorMemory:
    """MemoryProtocol implementation using VectorStoreProtocol + Embeddings.

    Embeds items on remember for semantic recall. All data lives in the
    vector store -- no separate persistence needed.
    """

    def __init__(
        self,
        vector_store: VectorStoreProtocol,
        embeddings: Embeddings,
    ) -> None:
        """Initialize VectorMemory.

        Args:
            vector_store: Vector database for storing embedded memory items.
            embeddings: Langchain embeddings model for generating vectors.
        """
        self._store = vector_store
        self._embeddings = embeddings

    async def remember(self, item: MemoryItem) -> str:
        """Embed and store a memory item."""
        vectors = await self._embeddings.aembed_documents([item.content])
        payload = item.model_dump(mode="json")
        await self._store.insert(
            vectors=vectors,
            payloads=[payload],
            ids=[item.id],
        )
        return item.id

    async def recall(self, query: str, limit: int = 5) -> list[MemoryItem]:
        """Retrieve items by semantic similarity."""
        query_vector = await self._embeddings.aembed_query(query)
        results = await self._store.search(
            query=query,
            vector=query_vector,
            limit=limit,
        )
        items: list[MemoryItem] = []
        for record in results:
            try:
                items.append(MemoryItem.model_validate(record.payload))
            except (TypeError, ValueError):
                logger.debug("Skipping invalid memory record %s", record.id)
        return items

    async def recall_by_tags(self, tags: list[str], limit: int = 10) -> list[MemoryItem]:
        """Retrieve items matching tags via vector store filters.

        Falls back to listing all records and filtering in-memory if
        the vector store doesn't support tag filtering natively.
        """
        records = await self._store.list_records(limit=limit * 5)
        tag_set = set(tags)
        matching: list[MemoryItem] = []
        for record in records:
            try:
                item = MemoryItem.model_validate(record.payload)
            except (TypeError, ValueError):
                continue
            if tag_set.issubset(set(item.tags)):
                matching.append(item)
                if len(matching) >= limit:
                    break
        matching.sort(key=lambda x: x.importance, reverse=True)
        return matching[:limit]

    async def forget(self, item_id: str) -> bool:
        """Remove a memory item from the vector store."""
        try:
            await self._store.delete(item_id)
        except Exception:
            return False
        else:
            return True

    async def update(self, item_id: str, content: str) -> None:
        """Re-embed and update an item's content."""
        existing = await self._store.get(item_id)
        if existing is None:
            msg = f"Memory item '{item_id}' not found"
            raise KeyError(msg)

        try:
            item = MemoryItem.model_validate(existing.payload)
        except (TypeError, ValueError) as exc:
            msg = f"Corrupt memory record for '{item_id}'"
            raise KeyError(msg) from exc

        updated = item.model_copy(update={"content": content, "created_at": datetime.now(tz=UTC)})
        vectors = await self._embeddings.aembed_documents([content])
        await self._store.update(
            record_id=item_id,
            vector=vectors[0],
            payload=updated.model_dump(mode="json"),
        )
