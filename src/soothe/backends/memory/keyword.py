"""KeywordMemory -- lightweight memory implementation using keyword matching with persistence."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from soothe.backends.persistence import PersistStore
from soothe.protocols.memory import MemoryItem

logger = logging.getLogger(__name__)


class KeywordMemory:
    """MemoryProtocol implementation using keyword matching with persistence.

    Lightweight memory with keyword-based recall. Supports JSON, RocksDB,
    or PostgreSQL persistence backends.

    Naming: Consistent with KeywordContext - both use keyword matching
    for retrieval and support the same persistence backends.
    """

    def __init__(self, persist_store: PersistStore | None = None) -> None:
        """Initialize KeywordMemory.

        Args:
            persist_store: Optional PersistStore instance for persistence.
                          None for in-memory only (no persistence).
        """
        self._items: dict[str, MemoryItem] = {}
        self._store = persist_store
        if self._store:
            self._load_all()

    async def remember(self, item: MemoryItem) -> str:
        """Store a memory item."""
        self._items[item.id] = item
        self._save_item(item)
        self._save_manifest()
        return item.id

    async def recall(self, query: str, limit: int = 5) -> list[MemoryItem]:
        """Retrieve items by keyword relevance."""
        query_tokens = set(re.findall(r"\w{3,}", query.lower()))
        scored: list[tuple[float, MemoryItem]] = []
        for item in self._items.values():
            item_tokens = set(re.findall(r"\w{3,}", item.content.lower()))
            item_tokens |= {t.lower() for t in item.tags}
            overlap = len(query_tokens & item_tokens)
            score = overlap / max(len(query_tokens), 1) + item.importance * 0.3
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:limit]]

    async def recall_by_tags(self, tags: list[str], limit: int = 10) -> list[MemoryItem]:
        """Retrieve items matching all specified tags."""
        tag_set = set(tags)
        matching = [item for item in self._items.values() if tag_set.issubset(set(item.tags))]
        matching.sort(key=lambda x: x.importance, reverse=True)
        return matching[:limit]

    async def forget(self, item_id: str) -> bool:
        """Remove a memory item."""
        if item_id in self._items:
            del self._items[item_id]
            if self._store:
                self._store.delete(f"memory_{item_id}")
            self._save_manifest()
            return True
        return False

    async def update(self, item_id: str, content: str) -> None:
        """Update an item's content."""
        if item_id not in self._items:
            msg = f"Memory item '{item_id}' not found"
            raise KeyError(msg)
        item = self._items[item_id]
        self._items[item_id] = item.model_copy(update={"content": content, "created_at": datetime.now(tz=UTC)})
        self._save_item(self._items[item_id])

    def _save_item(self, item: MemoryItem) -> None:
        if not self._store:
            return
        self._store.save(f"memory_{item.id}", item.model_dump(mode="json"))

    def _load_all(self) -> None:
        """Load all memory items from persistence.

        Items are stored individually with a manifest key tracking all IDs.
        """
        if not self._store:
            return
        manifest = self._store.load("memory__manifest")
        if manifest is None:
            return
        for item_id in manifest:
            data = self._store.load(f"memory_{item_id}")
            if data is not None:
                try:
                    self._items[item_id] = MemoryItem.model_validate(data)
                except (TypeError, ValueError):
                    logger.warning("Failed to load memory item %s", item_id)

    def _save_manifest(self) -> None:
        if self._store:
            self._store.save("memory__manifest", list(self._items.keys()))
