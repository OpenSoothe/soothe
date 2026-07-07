"""Per-checkpoint state for daemon isolation (IG-110, IG-408).

Registry keys are LangGraph / durability **checkpoint ids** (historically called
``thread_id`` in code). **Client routing** uses **``loop_id``**; this module maps
checkpoint ↔ loop via ``set_thread_loop`` / ``get_thread_loop``.

RFC-307: Identity context (user_id, aksk_id) is stored here for workspace isolation.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class ThreadState:
    """Mutable state for a single LangGraph checkpoint row (or draft).

    RFC-307: user_id and aksk_id populated by IdentityMiddleware for
    workspace isolation based on authenticated identity.
    """

    thread_id: str
    workspace: Path | None = None
    thread_logger: Any = None  # ThreadLogger | None
    is_draft: bool = False
    query_running: bool = False
    query_task: asyncio.Task | None = None
    last_activity: datetime | None = None
    # Identity context (RFC-307)
    user_id: str | None = None
    """Authenticated user_id from JWT token or external identity mapping."""
    aksk_id: str | None = None
    """AKSK ID that issued the token (for audit tracking)."""


class ThreadStateRegistry:
    """Registry of per-checkpoint state keyed by LangGraph ``thread_id``.

    **Loop-first routing** uses ``loop_id`` on the wire; use ``get_thread_loop`` to
    resolve checkpoint → loop.
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._by_thread: dict[str, ThreadState] = {}
        self._thread_loop: dict[str, str] = {}
        self._lock = threading.Lock()

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
        with self._lock:
            existing = self._by_thread.get(thread_id)
            if existing is not None:
                return existing
            st = ThreadState(thread_id=thread_id, is_draft=is_draft)
            self._by_thread[thread_id] = st
            return st

    def remove(self, thread_id: str) -> None:
        """Drop state for a thread (e.g. after archive/delete)."""
        self._by_thread.pop(thread_id, None)
        self._thread_loop.pop(thread_id, None)

    def set_thread_loop(self, thread_id: str, loop_id: str | None) -> None:
        """Associate a durability thread with an StrangeLoop id (IG-300)."""
        if loop_id and str(loop_id).strip():
            self._thread_loop[thread_id] = str(loop_id).strip()
        else:
            self._thread_loop.pop(thread_id, None)

    def get_thread_loop(self, thread_id: str) -> str | None:
        """Return StrangeLoop id bound to *thread_id*, if any."""
        return self._thread_loop.get(thread_id)

    def bind_loop(self, thread_id: str, loop_id: str) -> None:
        """Bind thread to loop (create or update mapping) (IG-500).

        Used by /clear command to update thread binding after creating new loop.

        Args:
            thread_id: Thread identifier.
            loop_id: Loop identifier to bind.
        """
        if loop_id and str(loop_id).strip():
            self._thread_loop[thread_id] = str(loop_id).strip()

    def unbind_loop(self, thread_id: str, loop_id: str) -> None:
        """Remove thread → loop binding (IG-500).

        Used by /clear command to remove old loop binding before creating new loop.

        Args:
            thread_id: Thread identifier.
            loop_id: Loop identifier to unbind.

        Note:
            Only removes binding if it matches the provided loop_id.
            Does not remove thread state or other associations.
        """
        current_binding = self._thread_loop.get(thread_id)
        if current_binding == loop_id:
            self._thread_loop.pop(thread_id, None)

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
        return removed

    # -----------------------------------------------------------------------
    # Identity Context (RFC-307)
    # -----------------------------------------------------------------------

    def set_user_id(
        self,
        thread_id: str,
        user_id: str | None,
        aksk_id: str | None = None,
    ) -> None:
        """Set user context from IdentityMiddleware.

        RFC-307 §Middleware Integration: user_id populated for workspace isolation.

        Args:
            thread_id: Thread identifier.
            user_id: Authenticated user_id (from JWT or external mapping).
            aksk_id: Optional AKSK ID for audit tracking.
        """
        st = self.ensure(thread_id)
        st.user_id = user_id
        st.aksk_id = aksk_id

    def get_user_id(self, thread_id: str) -> str | None:
        """Return user_id for *thread_id*.

        RFC-307 §Middleware Integration.

        Args:
            thread_id: Thread identifier.

        Returns:
            user_id if set, None otherwise.
        """
        st = self.get(thread_id)
        return st.user_id if st else None

    def get_aksk_id(self, thread_id: str) -> str | None:
        """Return aksk_id for *thread_id*.

        RFC-307 §Middleware Integration.

        Args:
            thread_id: Thread identifier.

        Returns:
            aksk_id if set, None otherwise.
        """
        st = self.get(thread_id)
        return st.aksk_id if st else None
