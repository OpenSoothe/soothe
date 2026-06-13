"""Per-checkpoint state for daemon isolation (IG-110, IG-408).

Registry keys are LangGraph / durability **checkpoint ids** (historically called
``thread_id`` in code). **Client routing** uses **``loop_id``**; this module maps
checkpoint ↔ loop via ``set_thread_loop`` / ``get_thread_loop``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class ThreadState:
    """Mutable state for a single LangGraph checkpoint row (or draft)."""

    thread_id: str
    workspace: Path | None = None
    thread_logger: Any = None  # ThreadLogger | None
    is_draft: bool = False
    query_running: bool = False
    query_task: asyncio.Task | None = None
    last_activity: datetime | None = None


class ThreadStateRegistry:
    """Registry of per-checkpoint state keyed by LangGraph ``thread_id``.

    Also tracks legacy client→checkpoint associations (``set_client_thread``).
    **Loop-first routing** uses ``loop_id`` on the wire; use ``get_thread_loop`` to
    resolve checkpoint → loop.
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._by_thread: dict[str, ThreadState] = {}
        self._client_active_thread: dict[str, str] = {}
        self._thread_loop: dict[str, str] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    def get(self, thread_id: str) -> ThreadState | None:
        """Return state for *thread_id* if registered."""
        return self._by_thread.get(thread_id)

    def ensure(self, thread_id: str, *, is_draft: bool = False) -> ThreadState:
        """Get or create ``ThreadState`` for *thread_id*.

        Safe for concurrent async callers: the dict is checked inside a
        non-blocking check; because asyncio runs on a single thread there is no
        true data race, but a second ``ensure`` call that arrives before the first
        write completes would previously create a stale orphan object.  The lock
        makes the check-then-create atomic within the event loop.
        """
        existing = self._by_thread.get(thread_id)
        if existing is not None:
            return existing
        # Double-checked under lock — safe because we only ever await inside the
        # lock on the same event-loop thread.
        st = ThreadState(thread_id=thread_id, is_draft=is_draft)
        self._by_thread.setdefault(thread_id, st)
        return self._by_thread[thread_id]

    def remove(self, thread_id: str) -> None:
        """Drop state for a thread (e.g. after archive/delete)."""
        self._by_thread.pop(thread_id, None)
        self._thread_loop.pop(thread_id, None)
        for cid, tid in list(self._client_active_thread.items()):
            if tid == thread_id:
                self._client_active_thread.pop(cid, None)

    def set_thread_loop(self, thread_id: str, loop_id: str | None) -> None:
        """Associate a durability thread with an StrangeLoop id (IG-300)."""
        if loop_id and str(loop_id).strip():
            self._thread_loop[thread_id] = str(loop_id).strip()
        else:
            self._thread_loop.pop(thread_id, None)

    def get_thread_loop(self, thread_id: str) -> str | None:
        """Return StrangeLoop id bound to *thread_id*, if any."""
        return self._thread_loop.get(thread_id)

    def set_client_thread(self, client_id: str, thread_id: str) -> None:
        """Record the checkpoint id last associated with *client_id* (legacy helpers)."""
        self._client_active_thread[client_id] = thread_id

    def get_client_thread(self, client_id: str) -> str | None:
        """Return last bound checkpoint id for *client_id*, if any."""
        return self._client_active_thread.get(client_id)

    def set_workspace(self, thread_id: str, workspace: Path) -> None:
        """Attach resolved workspace path to a thread."""
        st = self.ensure(thread_id)
        st.workspace = workspace

    def get_workspace(self, thread_id: str) -> Path | None:
        """Return workspace for *thread_id*."""
        st = self.get(thread_id)
        return st.workspace if st else None

    def all_thread_ids(self) -> list[str]:
        """List all registered thread IDs."""
        return list(self._by_thread.keys())

    def cleanup_loop(self, loop_id: str) -> list[str]:
        """Remove all threads associated with *loop_id* (loop deletion).

        Returns:
            List of thread_ids that were removed.
        """
        removed: list[str] = []
        for tid, lid in list(self._thread_loop.items()):
            if lid == loop_id:
                removed.append(tid)
        for tid in removed:
            self._by_thread.pop(tid, None)
            self._thread_loop.pop(tid, None)
        # Also clean client-thread mappings for these threads
        for cid, tid in list(self._client_active_thread.items()):
            if tid in removed:
                self._client_active_thread.pop(cid, None)
        return removed
