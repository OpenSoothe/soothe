"""MemoryProtocol adapter for memU memory store."""

from __future__ import annotations

import logging
from pathlib import Path

from soothe.config import SootheConfig

from soothe_daemon.backends.memory.memu.langchain_adapter import LangChainLLMAdapter
from soothe_daemon.backends.memory.memu.memory_store import MemuMemoryStore
from soothe_daemon.protocols.memory import MemoryItem as SootheMemoryItem
from soothe_daemon.protocols.memory import MemoryProtocol

logger = logging.getLogger(__name__)


class MemUMemory(MemoryProtocol):
    """MemoryProtocol implementation wrapping MemuMemoryStore.

    Adapts the new internal memU implementation to the MemoryProtocol interface.
    """

    def __init__(
        self,
        config: SootheConfig,
    ) -> None:
        """Initialize MemU memory backend.

        Args:
            config: Soothe configuration.
        """
        # Create LLM adapter from LangChain models
        chat_model = config.create_chat_model(config.protocols.memory.llm_chat_role)
        embedding_model = config.create_embedding_model()

        llm_adapter = LangChainLLMAdapter(
            chat_model=chat_model,
            embedding_model=embedding_model,
        )

        # Resolve memory directory
        memory_dir = Path(config.protocols.memory.persist_dir or "~/.soothe/memory")
        memory_dir = memory_dir.expanduser()

        # Create MemuMemoryStore
        self._store = MemuMemoryStore(
            memory_dir=str(memory_dir),
            agent_id=config.assistant_name,  # Use assistant name as agent identifier
            user_id="default_user",  # Will be overridden per-request
            llm_client=llm_adapter,
            enable_embeddings=True,
        )

        logger.info(
            "MemU memory backend initialized at %s",
            memory_dir,
        )

    async def remember(self, item: SootheMemoryItem) -> str:
        """Store a memory item.

        Args:
            item: The memory item to persist.

        Returns:
            The item's unique ID.
        """
        # Update user_id for scoping
        self._store.user_id = item.source_thread or "default_user"

        # Convert to internal MemoryItem format
        from soothe_daemon.backends.memory.memu.models import MemoryItem as MemuMemoryItem

        memu_item = MemuMemoryItem(
            content=item.content,
            memory_type="knowledge",  # Default
            user_id=item.source_thread,
            importance=item.importance,
            tags=item.tags,
            metadata=item.metadata,
            created_at=item.created_at,
        )

        return await self._store.add(memu_item)

    async def recall(self, query: str, limit: int = 5) -> list[SootheMemoryItem]:
        """Retrieve items by semantic relevance.

        Args:
            query: The search query.
            limit: Maximum number of items to return.

        Returns:
            Matching items ordered by relevance.
        """
        results = await self._store.search(query=query, limit=limit)

        soothe_items = []
        for result in results:
            soothe_item = SootheMemoryItem(
                id=result.memory_item.id,
                content=result.memory_item.content,
                source_thread=result.memory_item.user_id,
                created_at=result.memory_item.created_at,
                tags=result.memory_item.tags or [],
                importance=result.memory_item.importance,
                metadata=result.memory_item.metadata or {},
            )
            soothe_items.append(soothe_item)

        return soothe_items

    async def recall_by_tags(self, tags: list[str], limit: int = 10) -> list[SootheMemoryItem]:
        """Retrieve items matching all specified tags.

        Args:
            tags: Tags that items must match (AND logic).
            limit: Maximum number of items to return.

        Returns:
            Matching items ordered by importance.
        """
        from soothe_daemon.backends.memory.memu.models import MemoryFilter

        # Use get_all with tag filter
        filter_obj = MemoryFilter(tags=tags)
        items = await self._store.get_all(filters=filter_obj, limit=limit)

        # Convert and sort by importance
        soothe_items = []
        for item in items:
            soothe_item = SootheMemoryItem(
                id=item.id,
                content=item.content,
                source_thread=item.user_id,
                created_at=item.created_at,
                tags=item.tags or [],
                importance=item.importance,
                metadata=item.metadata or {},
            )
            soothe_items.append(soothe_item)

        # Sort by importance (descending)
        soothe_items.sort(key=lambda x: x.importance, reverse=True)
        return soothe_items[:limit]

    async def forget(self, item_id: str) -> bool:
        """Remove a memory item.

        Args:
            item_id: The item's unique ID.

        Returns:
            True if the item was found and removed.
        """
        return await self._store.delete(item_id)

    async def update(self, item_id: str, content: str) -> None:
        """Update an existing memory item's content.

        Args:
            item_id: The item's unique ID.
            content: New content to replace the existing content.

        Raises:
            KeyError: If no item with the given ID exists.
        """
        success = await self._store.update(
            item_id,
            updates={"content": content},
        )
        if not success:
            msg = f"Memory item '{item_id}' not found"
            raise KeyError(msg)
