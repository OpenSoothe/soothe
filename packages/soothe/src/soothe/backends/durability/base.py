"""Base class for durability backends using AsyncPersistStore (IG-258 Phase 2: async methods)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from soothe.backends.persistence import AsyncPersistStore
from soothe.core.runner._types import _generate_thread_id
from soothe.protocols.durability import ThreadFilter, ThreadInfo, ThreadMetadata


class BasePersistStoreDurability:
    """Base implementation of DurabilityProtocol using AsyncPersistStore.

    Provides thread lifecycle management.  State persistence (checkpoints,
    artifacts) is handled by ``RunArtifactStore`` (RFC-0010).
    Subclasses only need to provide an AsyncPersistStore instance.

    IG-258 Phase 2: All PersistStore methods are now async.
    """

    def __init__(self, persist_store: AsyncPersistStore) -> None:
        """Initialize durability backend with an AsyncPersistStore.

        Args:
            persist_store: The async persistence backend to use.
        """
        self._store = persist_store
        self._thread_index_key = "thread_index"

    async def create_thread(
        self,
        metadata: ThreadMetadata,
        thread_id: str | None = None,
    ) -> ThreadInfo:
        """Create a new thread with metadata.

        Args:
            metadata: Thread metadata.
            thread_id: Optional thread ID. If not provided, a new UUID is generated.
                       Use this to persist a draft thread with its existing ID.

        Returns:
            ThreadInfo for the created thread.
        """
        now = datetime.now(tz=UTC)
        info = ThreadInfo(
            thread_id=thread_id or _generate_thread_id(),
            status="active",
            created_at=now,
            updated_at=now,
            metadata=metadata,
        )
        await self._store.save(f"thread:{info.thread_id}", info.model_dump(mode="json"))
        await self._update_thread_index(info.thread_id, action="add")
        return info

    async def resume_thread(self, thread_id: str) -> ThreadInfo:
        """Resume a suspended thread.

        Supports prefix matching for thread IDs. If the provided thread_id
        is a prefix that matches one or more threads, the first match is resumed.

        Args:
            thread_id: Full thread ID or prefix.

        Returns:
            ThreadInfo for the resumed thread.

        Raises:
            KeyError: If thread not found.
        """
        # First try exact match
        data = await self._store.load(f"thread:{thread_id}")
        if data is not None:
            info = ThreadInfo.model_validate(data)
            info = info.model_copy(update={"status": "active", "updated_at": datetime.now(tz=UTC)})
            await self._store.save(f"thread:{thread_id}", info.model_dump(mode="json"))
            return info

        # Try prefix matching
        matching_threads = await self._find_threads_by_prefix(thread_id)
        if len(matching_threads) == 0:
            msg = f"Thread '{thread_id}' not found"
            raise KeyError(msg)

        # Return the first match (sorted by updated_at descending for consistency)
        matching_threads.sort(key=lambda t: t.updated_at, reverse=True)
        matched_thread = matching_threads[0]
        data = await self._store.load(f"thread:{matched_thread.thread_id}")
        if data is None:
            msg = f"Thread '{thread_id}' not found"
            raise KeyError(msg)

        info = ThreadInfo.model_validate(data)
        info = info.model_copy(update={"status": "active", "updated_at": datetime.now(tz=UTC)})
        await self._store.save(f"thread:{matched_thread.thread_id}", info.model_dump(mode="json"))
        return info

    async def suspend_thread(self, thread_id: str) -> None:
        """Suspend an active thread."""
        data = await self._store.load(f"thread:{thread_id}")
        if data is None:
            return

        info = ThreadInfo.model_validate(data)
        info = info.model_copy(update={"status": "suspended", "updated_at": datetime.now(tz=UTC)})
        await self._store.save(f"thread:{thread_id}", info.model_dump(mode="json"))

    async def archive_thread(self, thread_id: str) -> None:
        """Archive a thread."""
        data = await self._store.load(f"thread:{thread_id}")
        if data is None:
            return

        info = ThreadInfo.model_validate(data)
        info = info.model_copy(update={"status": "archived", "updated_at": datetime.now(tz=UTC)})
        await self._store.save(f"thread:{thread_id}", info.model_dump(mode="json"))

    async def get_thread(self, thread_id: str) -> ThreadInfo | None:
        """Load thread information without changing lifecycle status."""
        data = await self._store.load(f"thread:{thread_id}")
        if data is None:
            return None
        return ThreadInfo.model_validate(data)

    async def update_thread_metadata(
        self,
        thread_id: str,
        metadata: dict[str, Any] | ThreadMetadata,
    ) -> None:
        """Update thread metadata (partial update).

        Merges the provided metadata with existing metadata.
        Only updates fields that are present in the new metadata.

        Args:
            thread_id: Thread ID to update.
            metadata: New metadata to merge. Can be dict or ThreadMetadata.

        Raises:
            KeyError: If thread not found.
        """
        data = await self._store.load(f"thread:{thread_id}")
        if data is None:
            msg = f"Thread '{thread_id}' not found"
            raise KeyError(msg)

        info = ThreadInfo.model_validate(data)

        # Convert to dict if ThreadMetadata
        new_metadata = metadata.model_dump() if isinstance(metadata, ThreadMetadata) else metadata

        # Merge with existing metadata
        existing = info.metadata.model_dump()
        existing.update(new_metadata)

        # Update thread info
        info = info.model_copy(
            update={
                "metadata": ThreadMetadata(**existing),
                "updated_at": datetime.now(tz=UTC),
            }
        )
        await self._store.save(f"thread:{thread_id}", info.model_dump(mode="json"))

    async def list_threads(
        self,
        thread_filter: ThreadFilter | None = None,
    ) -> list[ThreadInfo]:
        """List threads matching a filter."""
        # Load thread index
        index_data = await self._store.load(self._thread_index_key)
        thread_ids: list[str] = index_data if isinstance(index_data, list) else []

        # Load all threads
        results: list[ThreadInfo] = []
        for tid in thread_ids:
            data = await self._store.load(f"thread:{tid}")
            if data:
                results.append(ThreadInfo.model_validate(data))

        # Apply filters
        if thread_filter is None:
            return results

        if thread_filter.status:
            results = [t for t in results if t.status == thread_filter.status]
        if thread_filter.tags:
            tag_set = set(thread_filter.tags)
            results = [t for t in results if tag_set.issubset(set(t.metadata.tags))]
        if thread_filter.created_after:
            results = [t for t in results if t.created_at >= thread_filter.created_after]
        if thread_filter.created_before:
            results = [t for t in results if t.created_at <= thread_filter.created_before]

        return results

    async def _update_thread_index(self, thread_id: str, action: str = "add") -> None:
        """Update the thread index for list_threads() (async, IG-258 Phase 2).

        Args:
            thread_id: Thread ID to add/remove from index.
            action: "add" or "remove".
        """
        index_data = await self._store.load(self._thread_index_key)
        thread_ids: set[str] = set(index_data) if isinstance(index_data, list) else set()

        if action == "add":
            thread_ids.add(thread_id)
        elif action == "remove":
            thread_ids.discard(thread_id)

        await self._store.save(self._thread_index_key, list(thread_ids))

    async def _find_threads_by_prefix(self, prefix: str) -> list[ThreadInfo]:
        """Find threads whose IDs start with the given prefix (async, IG-258 Phase 2).

        Args:
            prefix: Thread ID prefix to search for.

        Returns:
            List of ThreadInfo objects matching the prefix.
        """
        # Load thread index
        index_data = await self._store.load(self._thread_index_key)
        thread_ids: list[str] = index_data if isinstance(index_data, list) else []

        # Find threads starting with prefix
        matching = []
        for tid in thread_ids:
            if tid.startswith(prefix):
                data = await self._store.load(f"thread:{tid}")
                if data:
                    matching.append(ThreadInfo.model_validate(data))

        return matching
