"""RocksDB-based durability backend for thread lifecycle and metadata."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from soothe.backends.persistence import create_persist_store
from soothe.protocols.durability import ThreadFilter, ThreadInfo, ThreadMetadata


class RocksDBDurability:
    """DurabilityProtocol implementation using RocksDB for persistence.

    Stores thread metadata and state in a RocksDB database for durability
    and performance. Uses key prefixes for organization:
    - "threads:{thread_id}" -> ThreadInfo JSON
    - "state:{thread_id}" -> arbitrary state JSON
    - "thread_index" -> list of all thread IDs (for list_threads())
    """

    def __init__(self, persist_dir: str) -> None:
        """Initialize RocksDB durability backend.

        Args:
            persist_dir: Directory for the RocksDB database.

        Raises:
            RuntimeError: If rocksdict package is not available.
            ValueError: If store creation fails.
        """
        try:
            self._store = create_persist_store(persist_dir, backend="rocksdb")
            if self._store is None:
                msg = f"Failed to create RocksDB store at {persist_dir}"
                raise ValueError(msg)
        except ImportError as e:
            raise RuntimeError(
                "RocksDB persistence requires 'rocksdict' package. Install with: pip install soothe[rocksdb]"
            ) from e

    async def create_thread(self, metadata: ThreadMetadata) -> ThreadInfo:
        """Create a new thread with metadata."""
        now = datetime.now(tz=UTC)
        info = ThreadInfo(
            thread_id=str(uuid4()),
            status="active",
            created_at=now,
            updated_at=now,
            metadata=metadata,
        )
        self._store.save(f"threads:{info.thread_id}", info.model_dump(mode="json"))
        self._update_thread_index(info.thread_id, action="add")
        return info

    async def resume_thread(self, thread_id: str) -> ThreadInfo:
        """Resume a suspended thread."""
        data = self._store.load(f"threads:{thread_id}")
        if data is None:
            msg = f"Thread '{thread_id}' not found"
            raise KeyError(msg)

        info = ThreadInfo.model_validate(data)
        info = info.model_copy(update={"status": "active", "updated_at": datetime.now(tz=UTC)})
        self._store.save(f"threads:{thread_id}", info.model_dump(mode="json"))
        return info

    async def suspend_thread(self, thread_id: str) -> None:
        """Suspend an active thread."""
        data = self._store.load(f"threads:{thread_id}")
        if data is None:
            return

        info = ThreadInfo.model_validate(data)
        info = info.model_copy(update={"status": "suspended", "updated_at": datetime.now(tz=UTC)})
        self._store.save(f"threads:{thread_id}", info.model_dump(mode="json"))

    async def archive_thread(self, thread_id: str) -> None:
        """Archive a thread."""
        data = self._store.load(f"threads:{thread_id}")
        if data is None:
            return

        info = ThreadInfo.model_validate(data)
        info = info.model_copy(update={"status": "archived", "updated_at": datetime.now(tz=UTC)})
        self._store.save(f"threads:{thread_id}", info.model_dump(mode="json"))

    async def list_threads(
        self,
        thread_filter: ThreadFilter | None = None,
    ) -> list[ThreadInfo]:
        """List threads matching a filter."""
        # Load thread index
        index_data = self._store.load("thread_index")
        thread_ids: list[str] = index_data if isinstance(index_data, list) else []

        # Load all threads
        results: list[ThreadInfo] = []
        for tid in thread_ids:
            data = self._store.load(f"threads:{tid}")
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

    async def save_state(self, thread_id: str, state: Any) -> None:
        """Persist arbitrary state for a thread."""
        self._store.save(f"state:{thread_id}", state)

    async def load_state(self, thread_id: str) -> Any | None:
        """Load persisted state for a thread."""
        return self._store.load(f"state:{thread_id}")

    def _update_thread_index(self, thread_id: str, action: str = "add") -> None:
        """Update the thread index for list_threads().

        Args:
            thread_id: Thread ID to add/remove from index.
            action: "add" or "remove".
        """
        index_data = self._store.load("thread_index")
        thread_ids: set[str] = set(index_data) if isinstance(index_data, list) else set()

        if action == "add":
            thread_ids.add(thread_id)
        elif action == "remove":
            thread_ids.discard(thread_id)

        self._store.save("thread_index", list(thread_ids))
