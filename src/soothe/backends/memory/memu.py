"""MemoryProtocol implementation using MemU package."""

from __future__ import annotations

import logging
import math
import uuid
from typing import Any

try:
    from memu.app.service import MemoryService
    from memu.app.settings import (
        DatabaseConfig,
        LLMConfig,
        LLMProfilesConfig,
        MemorizeConfig,
        RetrieveConfig,
        UserConfig,
    )

    MEMU_AVAILABLE = True
except ImportError:
    MEMU_AVAILABLE = False
    MemoryService = None  # type: ignore[misc]
    DatabaseConfig = None  # type: ignore[misc]
    LLMConfig = None  # type: ignore[misc]
    LLMProfilesConfig = None  # type: ignore[misc]
    MemorizeConfig = None  # type: ignore[misc]
    RetrieveConfig = None  # type: ignore[misc]
    UserConfig = None  # type: ignore[misc]

from soothe.protocols.memory import MemoryItem as SootheMemoryItem, MemoryProtocol

logger = logging.getLogger(__name__)


def _patch_memu_1_5_0() -> None:
    """Patch MemU 1.5.0 bug: missing resource_id in _patch_create_memory_item.

    MemU 1.5.0's CRUDMixin._patch_create_memory_item() doesn't pass the required
    `resource_id` parameter to repository.create_item(). This monkey patch fixes it.
    Also patches _model_dump_without_embeddings to handle dict objects.
    """
    if not MEMU_AVAILABLE:
        return

    try:
        from memu.app.crud import CRUDMixin
        from memu.app.service import MemoryService

        async def patched_patch_create(self: CRUDMixin, state: dict[str, Any], step_context: Any) -> dict[str, Any]:
            """Patched version that includes resource_id parameter."""
            memory_payload = state["memory_payload"]
            ctx = state["ctx"]
            store = state["store"]
            user = state["user"]
            propagate = state["propagate"]
            category_memory_updates: dict[str, tuple[Any, Any]] = {}

            embed_payload = [memory_payload["content"]]
            content_embedding = (await self._get_step_embedding_client(step_context).embed(embed_payload))[0]

            # Generate a resource_id if not present (this is the fix)
            resource_id = str(uuid.uuid4())

            item = store.memory_item_repo.create_item(
                resource_id=resource_id,  # Add missing parameter
                memory_type=memory_payload["type"],
                summary=memory_payload["content"],
                embedding=content_embedding,
                user_data=dict(user or {}),
            )
            cat_names = memory_payload["categories"]
            mapped_cat_ids = self._map_category_names_to_ids(cat_names, ctx)
            for cid in mapped_cat_ids:
                store.category_item_repo.link_item_category(item.id, cid, user_data=dict(user or {}))
                if propagate:
                    category_memory_updates[cid] = (None, memory_payload["content"])

            state["memory_item"] = self._model_dump_without_embeddings(item)
            state["category_memory_updates"] = category_memory_updates
            state["category_updates"] = category_memory_updates  # Required by persist_index step

            response = {
                "memory_item": state["memory_item"],
            }
            state["response"] = response
            return state

        def patched_model_dump_without_embeddings(_self: Any, obj: Any) -> dict[str, Any]:
            """Patched version that handles both Pydantic models and dicts."""
            if isinstance(obj, dict):
                # Already a dict, just exclude embedding if present
                return {k: v for k, v in obj.items() if k != "embedding"}
            # Pydantic model, use model_dump
            return obj.model_dump(exclude={"embedding"})

        # Apply the patches
        CRUDMixin._patch_create_memory_item = patched_patch_create
        MemoryService._model_dump_without_embeddings = patched_model_dump_without_embeddings
        logger.debug("Applied MemU 1.5.0 patches (resource_id and model_dump)")

    except Exception as e:
        logger.warning("Failed to apply MemU patch (may not be needed for newer versions): %s", e)


# Apply the patch when module loads
_patch_memu_1_5_0()


class MemUMemory(MemoryProtocol):
    """MemoryProtocol implementation using MemU MemoryService.

    Requires the optional `memory` extra: `pip install soothe[memory]`
    """

    def __init__(
        self,
        *,
        llm_profiles: LLMProfilesConfig | dict | None = None,
        database_config: DatabaseConfig | dict | None = None,
        memorize_config: MemorizeConfig | dict | None = None,
        retrieve_config: RetrieveConfig | dict | None = None,
        user_config: UserConfig | dict | None = None,
    ) -> None:
        """Initialize MemU memory backend.

        Args:
            llm_profiles: LLM configuration profiles for MemU.
            database_config: Database storage configuration.
            memorize_config: Memorization workflow configuration.
            retrieve_config: Retrieval workflow configuration.
            user_config: User scope configuration.
        """
        if not MEMU_AVAILABLE:
            msg = "MemU is not installed. Install with: pip install soothe[memory] (requires Python 3.13+)"
            raise ImportError(msg)

        self._service = MemoryService(
            llm_profiles=llm_profiles,
            database_config=database_config,
            memorize_config=memorize_config,
            retrieve_config=retrieve_config,
            user_config=user_config,
        )

    async def remember(self, item: SootheMemoryItem) -> str:
        """Store a memory item using MemU's create_memory_item workflow.

        Args:
            item: The memory item to persist.

        Returns:
            The item's unique ID.
        """
        # Build user scope from source_thread
        user = {"user_id": item.source_thread} if item.source_thread else None

        # Use "knowledge" as default type, or infer from tags
        memory_type = "knowledge"
        if "profile" in item.tags:
            memory_type = "profile"
        elif "event" in item.tags:
            memory_type = "event"

        result = await self._service.create_memory_item(
            memory_type=memory_type,
            memory_content=item.content,
            memory_categories=item.tags,  # MemU will map to category IDs
            user=user,
            propagate=True,  # Update category summaries
        )

        memu_item = result["memory_item"]
        return memu_item["id"]

    async def recall(self, query: str, limit: int = 5) -> list[SootheMemoryItem]:
        """Retrieve items by semantic relevance using MemU's retrieve workflow.

        Args:
            query: The search query.
            limit: Maximum number of items to return.

        Returns:
            Matching items ordered by relevance.
        """
        result = await self._service.retrieve(
            queries=[{"role": "user", "content": query}],
            where=None,  # No user filtering
        )

        # Convert MemU MemoryItems -> Soothe MemoryItems
        soothe_items = []
        for memu_item in result.get("items", [])[:limit]:
            soothe_item = SootheMemoryItem(
                id=memu_item["id"],
                content=memu_item["summary"],
                source_thread=memu_item.get("user_id"),
                created_at=memu_item["created_at"],
                tags=[],  # Tags come from category membership
                importance=_compute_importance(memu_item),
                metadata=memu_item.get("extra", {}),
            )
            soothe_items.append(soothe_item)

        return soothe_items

    async def recall_by_tags(self, tags: list[str], limit: int = 10) -> list[SootheMemoryItem]:
        """Retrieve items matching all specified tags via category membership.

        Args:
            tags: Tags that items must match (AND logic).
            limit: Maximum number of items to return.

        Returns:
            Matching items ordered by importance.
        """
        # Query items by category membership
        result = await self._service.list_memory_items(
            where={"categories__has": tags}  # Filter by category names
        )

        # Convert and sort by importance
        soothe_items = []
        for memu_item in result.get("items", [])[:limit]:
            soothe_item = SootheMemoryItem(
                id=memu_item["id"],
                content=memu_item["summary"],
                source_thread=memu_item.get("user_id"),
                created_at=memu_item["created_at"],
                tags=tags,  # Return the queried tags
                importance=_compute_importance(memu_item),
                metadata=memu_item.get("extra", {}),
            )
            soothe_items.append(soothe_item)

        # Sort by importance (descending)
        soothe_items.sort(key=lambda x: x.importance, reverse=True)
        return soothe_items[:limit]

    async def forget(self, item_id: str) -> bool:
        """Remove a memory item using MemU's delete_memory_item workflow.

        Args:
            item_id: The item's unique ID.

        Returns:
            True if the item was found and removed.
        """
        try:
            await self._service.delete_memory_item(
                memory_id=item_id,
                user=None,
                propagate=True,  # Update category summaries
            )
        except Exception as e:
            logger.warning("Failed to delete memory item %s: %s", item_id, e)
            return False
        else:
            return True

    async def update(self, item_id: str, content: str) -> None:
        """Update an item's content using MemU's update_memory_item workflow.

        Args:
            item_id: The item's unique ID.
            content: New content to replace the existing content.

        Raises:
            KeyError: If no item with the given ID exists.
        """
        result = await self._service.update_memory_item(
            memory_id=item_id,
            memory_content=content,
            propagate=True,  # Update category summaries
        )

        if not result.get("memory_item"):
            msg = f"Memory item '{item_id}' not found"
            raise KeyError(msg)


def _compute_importance(memu_item: dict[str, Any]) -> float:
    """Compute importance score from MemU's reinforcement tracking.

    Args:
        memu_item: MemU memory item dict.

    Returns:
        Importance score from 0.0 to 1.0.
    """
    extra = memu_item.get("extra", {})
    reinforcement = extra.get("reinforcement_count", 0)
    # Use logarithmic scale: importance = min(1.0, log(reinforcement + 1) / log(10))
    # This maps 0 reinforcements → 0.0, 9 reinforcements → 1.0
    return min(1.0, math.log(reinforcement + 1) / math.log(10))
