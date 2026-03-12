"""InMemoryDurability -- lightweight in-memory thread lifecycle management."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from soothe.protocols.durability import ThreadFilter, ThreadInfo, ThreadMetadata

logger = logging.getLogger(__name__)


class InMemoryDurability:
    """DurabilityProtocol implementation using in-memory storage.

    Suitable for development and testing. Production deployments should use
    a persistent backend (e.g., LangGraphDurability with Checkpointer).
    """

    def __init__(self) -> None:
        """Initialize with empty thread registry."""
        self._threads: dict[str, ThreadInfo] = {}
        self._state: dict[str, Any] = {}

    async def create_thread(self, metadata: ThreadMetadata) -> ThreadInfo:
        """Create a new thread."""
        now = datetime.now(tz=UTC)
        info = ThreadInfo(
            thread_id=str(uuid4()),
            status="active",
            created_at=now,
            updated_at=now,
            metadata=metadata,
        )
        self._threads[info.thread_id] = info
        return info

    async def resume_thread(self, thread_id: str) -> ThreadInfo:
        """Resume a suspended thread."""
        info = self._threads.get(thread_id)
        if info is None:
            msg = f"Thread '{thread_id}' not found"
            raise KeyError(msg)
        info = info.model_copy(update={"status": "active", "updated_at": datetime.now(tz=UTC)})
        self._threads[thread_id] = info
        return info

    async def suspend_thread(self, thread_id: str) -> None:
        """Suspend an active thread."""
        info = self._threads.get(thread_id)
        if info is None:
            return
        self._threads[thread_id] = info.model_copy(update={"status": "suspended", "updated_at": datetime.now(tz=UTC)})

    async def archive_thread(self, thread_id: str) -> None:
        """Archive a thread."""
        info = self._threads.get(thread_id)
        if info is None:
            return
        self._threads[thread_id] = info.model_copy(update={"status": "archived", "updated_at": datetime.now(tz=UTC)})

    async def list_threads(
        self,
        filter: ThreadFilter | None = None,  # noqa: A002
    ) -> list[ThreadInfo]:
        """List threads matching a filter."""
        results = list(self._threads.values())
        if filter is None:
            return results
        if filter.status:
            results = [t for t in results if t.status == filter.status]
        if filter.tags:
            tag_set = set(filter.tags)
            results = [t for t in results if tag_set.issubset(set(t.metadata.tags))]
        if filter.created_after:
            results = [t for t in results if t.created_at >= filter.created_after]
        if filter.created_before:
            results = [t for t in results if t.created_at <= filter.created_before]
        return results

    async def save_state(self, thread_id: str, state: Any) -> None:
        """Persist state for a thread (in memory)."""
        self._state[thread_id] = state

    async def load_state(self, thread_id: str) -> Any | None:
        """Load persisted state for a thread."""
        return self._state.get(thread_id)
