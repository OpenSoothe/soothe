"""MemU-based memory store implementation.

This module provides a concrete implementation of the BaseMemoryStore interface
using the MemU memory agent system. It bridges the action-based MemU architecture
with the standard memory store API.
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .llm_client import BaseLLMClient
from .memory import MemoryAgent
from .models import MemoryFilter, MemoryItem, MemoryStats, SearchResult

logger = logging.getLogger(__name__)


class MemuMemoryStore:
    """MemU-based implementation of the memory store interface.

    This implementation uses the MemU memory agent system for storage and retrieval,
    providing file-based memory management with function calling capabilities.
    """

    def __init__(
        self,
        memory_dir: str,
        agent_id: str = "default_agent",
        user_id: str = "default_user",
        llm_client: BaseLLMClient | None = None,
        *,
        enable_embeddings: bool = True,
    ) -> None:
        """Initialize the MemU memory store.

        Args:
            memory_dir: Directory to store memory files
            agent_id: Agent identifier for memory organization
            user_id: User identifier for memory organization
            llm_client: LLM client for memory operations
            enable_embeddings: Whether to enable embedding-based similarity search
            **kwargs: Additional parameters
        """
        self.memory_dir = Path(memory_dir)
        self.agent_id = agent_id
        self.user_id = user_id
        self.enable_embeddings = enable_embeddings

        # Initialize LLM client if not provided
        if llm_client is None:
            try:
                from .llm_adapter import _get_llm_client_memu_compatible

                llm_client = _get_llm_client_memu_compatible()
            except Exception:
                logger.warning("Failed to initialize default LLM client", exc_info=True)
                # Continue without LLM client for basic file operations

        self.llm_client = llm_client

        # Initialize MemU memory agent
        self.memory_agent = MemoryAgent(
            llm_client=llm_client,
            agent_id=agent_id,
            user_id=user_id,
            memory_dir=str(memory_dir),
            enable_embeddings=enable_embeddings,
        )

        logger.info(
            "MemuMemoryStore initialized: agent=%s, user=%s, dir=%s", agent_id, user_id, memory_dir
        )

    # ==========================================
    # Core CRUD Operations
    # ==========================================

    async def add(self, memory_item: MemoryItem) -> str:
        """Add a new memory item to the store."""
        try:
            # Convert memory item to conversation format for MemU
            conversation_content = self._memory_item_to_content(memory_item)

            # Use MemU's add_activity_memory action
            result = self.memory_agent.call_function(
                "add_activity_memory",
                {
                    "character_name": memory_item.user_id or "User",
                    "content": conversation_content,
                    "session_date": (
                        memory_item.created_at.strftime("%Y-%m-%d")
                        if memory_item.created_at
                        else None
                    ),
                },
            )

            if result.get("success"):
                # Store the memory item ID in metadata for retrieval
                memory_items = result.get("memory_items", [])
                if memory_items:
                    # Use the provided ID or generate a new one
                    memory_id = memory_item.id or str(uuid.uuid4())

                    # Store mapping in a tracking file
                    self._store_memory_mapping(memory_id, memory_item, memory_items)

                    return memory_id
                msg = "No memory items were created"
                raise ValueError(msg)
            msg = f"Failed to add memory: {result.get('error', 'Unknown error')}"
            raise ValueError(msg)

        except Exception:
            logger.exception("Error adding memory item")
            raise

    async def get(self, memory_id: str) -> MemoryItem | None:
        """Retrieve a memory item by its unique identifier."""
        try:
            # Get memory mapping
            mapping = self._get_memory_mapping(memory_id)
            if not mapping:
                return None

            # Reconstruct memory item from stored data
            return self._reconstruct_memory_item(memory_id, mapping)

        except Exception:
            logger.exception("Error retrieving memory item %s", memory_id)
            return None

    async def update(self, memory_id: str, updates: dict[str, Any]) -> bool:
        """Update an existing memory item."""
        try:
            # Get existing memory item
            existing_item = await self.get(memory_id)
            if not existing_item:
                return False

            # Apply updates
            for key, value in updates.items():
                if hasattr(existing_item, key):
                    setattr(existing_item, key, value)

            existing_item.updated_at = datetime.now(datetime.UTC)
            existing_item.version += 1

            # Store updated mapping
            mapping = self._get_memory_mapping(memory_id)
            if mapping:
                mapping.update(
                    {
                        "content": existing_item.content,
                        "metadata": existing_item.metadata,
                        "tags": existing_item.tags,
                        "importance": existing_item.importance,
                        "updated_at": existing_item.updated_at.isoformat(),
                        "version": existing_item.version,
                    }
                )
                self._store_memory_mapping(
                    memory_id, existing_item, mapping.get("memory_items", [])
                )
                return True
        except Exception:
            logger.exception("Error updating memory item %s", memory_id)
            return False
        else:
            return False

    async def delete(self, memory_id: str) -> bool:
        """Delete a memory item from the store."""
        try:
            # Remove memory mapping
            return self._remove_memory_mapping(memory_id)

        except Exception:
            logger.exception("Error deleting memory item %s", memory_id)
            return False

    # ==========================================
    # Batch Operations
    # ==========================================

    async def add_many(self, memory_items: list[MemoryItem]) -> list[str]:
        """Add multiple memory items in a batch operation."""
        results = []
        for item in memory_items:
            try:
                memory_id = await self.add(item)
                results.append(memory_id)
            except Exception:
                logger.exception("Error adding memory item in batch")
                # Continue with other items
                results.append(str(uuid.uuid4()))  # Generate placeholder ID
        return results

    async def delete_many(self, memory_ids: list[str]) -> int:
        """Delete multiple memory items in a batch operation."""
        deleted_count = 0
        for memory_id in memory_ids:
            try:
                if await self.delete(memory_id):
                    deleted_count += 1
            except Exception:
                logger.exception("Error deleting memory item %s in batch", memory_id)
                # Continue with other items
        return deleted_count

    # ==========================================
    # Query and Filtering Operations
    # ==========================================

    async def get_all(
        self,
        filters: MemoryFilter | None = None,
        limit: int | None = None,
        offset: int | None = None,
        sort_by: str | None = None,
        sort_order: str = "desc",
    ) -> list[MemoryItem]:
        """Retrieve multiple memory items with optional filtering and pagination."""
        try:
            # Get all memory mappings
            all_mappings = self._get_all_memory_mappings()

            # Reconstruct memory items
            items = []
            for memory_id, mapping in all_mappings.items():
                item = self._reconstruct_memory_item(memory_id, mapping)
                if item:
                    items.append(item)

            # Apply filters
            if filters:
                items = self._apply_filters(items, filters)

            # Apply sorting
            if sort_by:
                reverse = sort_order.lower() == "desc"
                items.sort(key=lambda x: getattr(x, sort_by, None) or 0, reverse=reverse)

            # Apply pagination
            if offset:
                items = items[offset:]
            if limit:
                items = items[:limit]
        except Exception:
            logger.exception("Error retrieving memory items")
            return []
        else:
            return items

    async def count(self, filters: MemoryFilter | None = None) -> int:
        """Count memory items matching the given filters."""
        try:
            items = await self.get_all(filters=filters)
            return len(items)
        except Exception:
            logger.exception("Error counting memory items")
            return 0

    # ==========================================
    # Search Operations
    # ==========================================

    async def search(
        self,
        query: str,
        limit: int = 10,
        threshold: float = 0.7,
        memory_types: list[str] | None = None,
        filters: MemoryFilter | None = None,
    ) -> list[SearchResult]:
        """Perform semantic search across memory items."""
        try:
            # Get all items first
            all_items = await self.get_all(filters=filters)

            # Filter by memory types if specified
            if memory_types:
                all_items = [item for item in all_items if item.memory_type in memory_types]

            # If embeddings are enabled, use similarity search
            if self.enable_embeddings and self.llm_client:
                # This is a simplified implementation
                # In practice, you'd use the embedding system from MemU
                results = []
                for item in all_items:
                    # Simple text similarity scoring (can be improved with actual embeddings)
                    score = self._calculate_similarity(query, item.content)
                    if score >= threshold:
                        results.append(
                            SearchResult(
                                memory_item=item,
                                relevance_score=score,
                                search_metadata={"search_type": "text_similarity"},
                            )
                        )

                # Sort by relevance score
                results.sort(key=lambda x: x.relevance_score, reverse=True)
                return results[:limit]
            # Fallback to simple text search
            results = []
            for item in all_items:
                if query.lower() in item.content.lower():
                    results.append(
                        SearchResult(
                            memory_item=item,
                            relevance_score=0.8,  # Fixed score for text match
                            search_metadata={"search_type": "text_match"},
                        )
                    )

            return results[:limit]

        except Exception:
            logger.exception("Error searching memory items")
            return []

    async def similarity_search(
        self,
        reference_items: list[MemoryItem],
        limit: int = 10,
        threshold: float = 0.7,
        filters: MemoryFilter | None = None,
    ) -> list[SearchResult]:
        """Find memory items similar to a list of reference items."""
        try:
            if not reference_items:
                return []

            # Use the first reference item as the primary query
            primary_item = reference_items[0]

            # Perform search using the content of the reference item
            return await self.search(
                query=primary_item.content,
                limit=limit,
                threshold=threshold,
                filters=filters,
            )

        except Exception:
            logger.exception("Error in similarity search")
            return []

    # ==========================================
    # Memory Management Operations
    # ==========================================

    async def get_stats(self, filters: MemoryFilter | None = None) -> MemoryStats:
        """Get statistics about the memory store."""
        try:
            items = await self.get_all(filters=filters)

            if not items:
                return MemoryStats(
                    total_items=0,
                    items_by_type={},
                    items_by_user={},
                    average_importance=0.0,
                )

            # Calculate statistics
            items_by_type = {}
            items_by_user = {}
            total_importance = 0.0
            oldest_date = None
            newest_date = None

            for item in items:
                # Count by type
                items_by_type[item.memory_type] = items_by_type.get(item.memory_type, 0) + 1

                # Count by user
                user = item.user_id or "unknown"
                items_by_user[user] = items_by_user.get(user, 0) + 1

                # Accumulate importance
                total_importance += item.importance

                # Track dates
                if oldest_date is None or item.created_at < oldest_date:
                    oldest_date = item.created_at
                if newest_date is None or item.created_at > newest_date:
                    newest_date = item.created_at

            # Calculate storage size (approximate)
            storage_size = sum(len(item.content.encode("utf-8")) for item in items)

            return MemoryStats(
                total_items=len(items),
                items_by_type=items_by_type,
                items_by_user=items_by_user,
                oldest_item_date=oldest_date,
                newest_item_date=newest_date,
                average_importance=total_importance / len(items),
                storage_size_bytes=storage_size,
            )

        except Exception:
            logger.exception("Error getting memory stats")
            return MemoryStats(
                total_items=0,
                items_by_type={},
                items_by_user={},
                average_importance=0.0,
            )

    async def cleanup_old_memories(
        self,
        older_than: datetime,
        memory_types: list[str] | None = None,
        *,
        preserve_important: bool = True,
        dry_run: bool = True,
    ) -> int:
        """Clean up old memory items based on age and criteria."""
        try:
            # Get all items
            items = await self.get_all()

            # Find items to delete
            items_to_delete = []
            for item in items:
                # Check age
                if item.created_at >= older_than:
                    continue

                # Check type filter
                if memory_types and item.memory_type not in memory_types:
                    continue

                # Check importance preservation
                if preserve_important and item.importance > 0.8:  # noqa: PLR2004
                    continue

                items_to_delete.append(item)

            if dry_run:
                return len(items_to_delete)
            # Actually delete items
            deleted_count = 0
            for item in items_to_delete:
                if await self.delete(item.id):
                    deleted_count += 1
        except Exception:
            logger.exception("Error cleaning up old memories")
            return 0
        else:
            return deleted_count

    # ==========================================
    # Helper Methods
    # ==========================================

    def _memory_item_to_content(self, memory_item: MemoryItem) -> str:
        """Convert a MemoryItem to content format suitable for MemU."""
        # Create a simple conversation format
        content = memory_item.content

        # Format as conversation if not already formatted
        if not content.startswith(("USER:", "ASSISTANT:", "SYSTEM:")):
            content = f"USER: {content}"

        return content

    def _store_memory_mapping(
        self, memory_id: str, memory_item: MemoryItem, memory_items: list[Any]
    ) -> None:
        """Store mapping between memory ID and MemU storage."""
        mappings_file = self.memory_dir / f"{self.agent_id}_{self.user_id}_mappings.json"

        # Load existing mappings
        mappings = {}
        if mappings_file.exists():
            try:
                with mappings_file.open() as f:
                    mappings = json.load(f)
            except Exception:
                logger.warning("Error loading mappings", exc_info=True)

        # Store new mapping
        mappings[memory_id] = {
            "content": memory_item.content,
            "memory_type": memory_item.memory_type,
            "user_id": memory_item.user_id,
            "agent_id": memory_item.agent_id,
            "session_id": memory_item.session_id,
            "importance": memory_item.importance,
            "context": memory_item.context,
            "metadata": memory_item.metadata,
            "tags": memory_item.tags,
            "created_at": memory_item.created_at.isoformat(),
            "updated_at": (memory_item.updated_at.isoformat() if memory_item.updated_at else None),
            "version": memory_item.version,
            "memory_items": memory_items,  # MemU-specific data
        }

        # Save mappings
        try:
            mappings_file.parent.mkdir(parents=True, exist_ok=True)
            with mappings_file.open("w") as f:
                json.dump(mappings, f, indent=2)
        except Exception:
            logger.exception("Error saving mappings")

    def _get_memory_mapping(self, memory_id: str) -> dict[str, Any] | None:
        """Get mapping data for a memory ID."""
        mappings_file = self.memory_dir / f"{self.agent_id}_{self.user_id}_mappings.json"

        if not mappings_file.exists():
            return None

        try:
            with mappings_file.open() as f:
                mappings = json.load(f)
            return mappings.get(memory_id)
        except Exception:
            logger.exception("Error loading mapping for %s", memory_id)
            return None

    def _get_all_memory_mappings(self) -> dict[str, dict[str, Any]]:
        """Get all memory mappings."""
        mappings_file = self.memory_dir / f"{self.agent_id}_{self.user_id}_mappings.json"

        if not mappings_file.exists():
            return {}

        try:
            with mappings_file.open() as f:
                return json.load(f)
        except Exception:
            logger.exception("Error loading all mappings")
            return {}

    def _remove_memory_mapping(self, memory_id: str) -> bool:
        """Remove a memory mapping."""
        mappings_file = self.memory_dir / f"{self.agent_id}_{self.user_id}_mappings.json"

        if not mappings_file.exists():
            return False

        try:
            with mappings_file.open() as f:
                mappings = json.load(f)

            if memory_id in mappings:
                del mappings[memory_id]

                with mappings_file.open("w") as f:
                    json.dump(mappings, f, indent=2)
                return True
        except Exception:
            logger.exception("Error removing mapping for %s", memory_id)
            return False
        else:
            return False

    def _reconstruct_memory_item(
        self, memory_id: str, mapping: dict[str, Any]
    ) -> MemoryItem | None:
        """Reconstruct a MemoryItem from mapping data."""
        try:
            return MemoryItem(
                id=memory_id,
                content=mapping.get("content", ""),
                memory_type=mapping.get("memory_type", "message"),
                user_id=mapping.get("user_id"),
                agent_id=mapping.get("agent_id"),
                session_id=mapping.get("session_id"),
                importance=mapping.get("importance", 0.5),
                context=mapping.get("context", {}),
                metadata=mapping.get("metadata", {}),
                tags=mapping.get("tags", []),
                created_at=datetime.fromisoformat(mapping["created_at"]),
                updated_at=(
                    datetime.fromisoformat(mapping["updated_at"])
                    if mapping.get("updated_at")
                    else None
                ),
                version=mapping.get("version", 1),
            )
        except Exception:
            logger.exception("Error reconstructing memory item %s", memory_id)
            return None

    def _apply_filters(self, items: list[MemoryItem], filters: MemoryFilter) -> list[MemoryItem]:
        """Apply filters to a list of memory items."""
        filtered_items = items

        if filters.user_id:
            filtered_items = [item for item in filtered_items if item.user_id == filters.user_id]

        if filters.agent_id:
            filtered_items = [item for item in filtered_items if item.agent_id == filters.agent_id]

        if filters.session_id:
            filtered_items = [
                item for item in filtered_items if item.session_id == filters.session_id
            ]

        if filters.memory_type:
            filtered_items = [
                item for item in filtered_items if item.memory_type == filters.memory_type
            ]

        if filters.tags:
            filtered_items = [
                item for item in filtered_items if all(tag in item.tags for tag in filters.tags)
            ]

        if filters.date_from:
            filtered_items = [
                item for item in filtered_items if item.created_at >= filters.date_from
            ]

        if filters.date_to:
            filtered_items = [item for item in filtered_items if item.created_at <= filters.date_to]

        if filters.min_importance is not None:
            filtered_items = [
                item for item in filtered_items if item.importance >= filters.min_importance
            ]

        # Apply metadata filters
        for key, value in filters.metadata_filters.items():
            filtered_items = [item for item in filtered_items if item.metadata.get(key) == value]

        return filtered_items

    def _calculate_similarity(self, query: str, content: str) -> float:
        """Calculate simple text similarity between query and content."""
        # Simple implementation - can be improved with actual similarity algorithms
        query_words = set(query.lower().split())
        content_words = set(content.lower().split())

        if not query_words:
            return 0.0

        intersection = query_words.intersection(content_words)
        union = query_words.union(content_words)

        if not union:
            return 0.0

        return len(intersection) / len(union)
