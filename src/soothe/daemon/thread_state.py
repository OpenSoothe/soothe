"""Per-thread state for daemon isolation (IG-110).

Replaces scattered daemon-level ``_thread_logger``, ``_draft_thread_id``,
and ``_thread_workspaces`` with explicit per-thread records so concurrent
clients do not overwrite each other's state.  Per-thread ``input_history``
is also managed via this registry.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ThreadState:
    """Mutable state for a single durability thread (or draft)."""

    thread_id: str
    workspace: Path | None = None
    thread_logger: Any = None  # ThreadLogger | None
    input_history: Any = None  # InputHistory | None
    is_draft: bool = False
    query_running: bool = False
    query_task: asyncio.Task | None = None


class ThreadStateRegistry:
    """Registry of per-thread state keyed by ``thread_id``.

    Also tracks which thread_id a client last created or resumed for helpers
    that need client-scoped lookups (optional; primary routing uses thread_id).
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._by_thread: dict[str, ThreadState] = {}
        self._client_active_thread: dict[str, str] = {}

    def get(self, thread_id: str) -> ThreadState | None:
        """Return state for *thread_id* if registered."""
        return self._by_thread.get(thread_id)

    def ensure(self, thread_id: str, *, is_draft: bool = False) -> ThreadState:
        """Get or create ``ThreadState`` for *thread_id*."""
        existing = self._by_thread.get(thread_id)
        if existing is not None:
            return existing
        st = ThreadState(thread_id=thread_id, is_draft=is_draft)
        self._by_thread[thread_id] = st
        return st

    def remove(self, thread_id: str) -> None:
        """Drop state for a thread (e.g. after archive/delete)."""
        self._by_thread.pop(thread_id, None)
        for cid, tid in list(self._client_active_thread.items()):
            if tid == thread_id:
                self._client_active_thread.pop(cid, None)

    def set_client_thread(self, client_id: str, thread_id: str) -> None:
        """Record the thread a client last bound to (new_thread / resume)."""
        self._client_active_thread[client_id] = thread_id

    def get_client_thread(self, client_id: str) -> str | None:
        """Return last bound thread_id for *client_id*, if any."""
        return self._client_active_thread.get(client_id)

    def set_workspace(self, thread_id: str, workspace: Path) -> None:
        """Attach resolved workspace path to a thread."""
        st = self.ensure(thread_id)
        st.workspace = workspace

    def get_workspace(self, thread_id: str) -> Path | None:
        """Return workspace for *thread_id*."""
        st = self.get(thread_id)
        return st.workspace if st else None

    def set_input_history(self, thread_id: str, input_history: Any) -> None:
        """Attach an InputHistory instance to a thread."""
        st = self.ensure(thread_id)
        st.input_history = input_history

    def get_input_history(self, thread_id: str) -> Any | None:
        """Return InputHistory for *thread_id*, if registered."""
        st = self.get(thread_id)
        return st.input_history if st else None

    def all_thread_ids(self) -> list[str]:
        """List all registered thread IDs."""
        return list(self._by_thread.keys())
