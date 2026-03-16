"""JsonDurability -- file-backed thread metadata durability."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from soothe.protocols.durability import ThreadFilter, ThreadInfo, ThreadMetadata


class JsonDurability:
    """DurabilityProtocol implementation using JSON file storage.

    Stores thread metadata in a single threads.json file.
    Simple, file-based persistence for development/testing.

    NOT related to LangGraph checkpointer - this is for thread
    lifecycle metadata only.
    """

    def __init__(self, metadata_path: str) -> None:
        """Initialize the durability backend with a JSON metadata file.

        Args:
            metadata_path: Path to the JSON file for storing thread metadata.
        """
        self._path = Path(metadata_path).expanduser().resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._threads: dict[str, ThreadInfo] = {}
        self._state: dict[str, Any] = {}
        self._load()

    async def create_thread(self, metadata: ThreadMetadata) -> ThreadInfo:
        """Create a new thread and persist metadata."""
        now = datetime.now(tz=UTC)
        info = ThreadInfo(
            thread_id=str(uuid4()),
            status="active",
            created_at=now,
            updated_at=now,
            metadata=metadata,
        )
        self._threads[info.thread_id] = info
        self._save()
        return info

    async def resume_thread(self, thread_id: str) -> ThreadInfo:
        """Resume a suspended thread."""
        info = self._threads.get(thread_id)
        if info is None:
            msg = f"Thread '{thread_id}' not found"
            raise KeyError(msg)
        info = info.model_copy(update={"status": "active", "updated_at": datetime.now(tz=UTC)})
        self._threads[thread_id] = info
        self._save()
        return info

    async def suspend_thread(self, thread_id: str) -> None:
        """Suspend an active thread."""
        info = self._threads.get(thread_id)
        if info is None:
            return
        self._threads[thread_id] = info.model_copy(update={"status": "suspended", "updated_at": datetime.now(tz=UTC)})
        self._save()

    async def archive_thread(self, thread_id: str) -> None:
        """Archive a thread."""
        info = self._threads.get(thread_id)
        if info is None:
            return
        self._threads[thread_id] = info.model_copy(update={"status": "archived", "updated_at": datetime.now(tz=UTC)})
        self._save()

    async def list_threads(
        self,
        thread_filter: ThreadFilter | None = None,
    ) -> list[ThreadInfo]:
        """List threads matching a filter."""
        results = list(self._threads.values())
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
        self._state[thread_id] = state
        self._save()

    async def load_state(self, thread_id: str) -> Any | None:
        """Load persisted state for a thread."""
        return self._state.get(thread_id)

    def _save(self) -> None:
        payload = {
            "threads": {tid: info.model_dump(mode="json") for tid, info in self._threads.items()},
            "state": self._state,
        }
        self._path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if not self._path.exists():
            return
        raw = self._path.read_text(encoding="utf-8").strip()
        if not raw:
            return
        data = json.loads(raw)
        threads = data.get("threads", {})
        self._threads = {tid: ThreadInfo.model_validate(item) for tid, item in threads.items()}
        self._state = data.get("state", {})
