"""Per-resolved-path lock registry for serializing file edits.

Provides both async (``asyncio.Lock``) and sync (``threading.RLock``) lock
pools keyed by ``os.path.realpath``. A meta-lock guards lazy lock creation
so that concurrent tasks/threads requesting a lock for the same path do not
create duplicate entries.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

__all__ = ["FileEditLockRegistry"]


class FileEditLockRegistry:
    """Registry of per-resolved-path locks for serializing file edits.

    Maintains two independent lock pools:

    * **Async pool** – ``asyncio.Lock`` instances, used by async filesystem
      methods (``awrite``, ``aedit``, ``aedit_lines``, …).
    * **Sync pool** – ``threading.RLock`` instances (reentrant), used by sync
      filesystem methods (``edit``, ``edit_lines``, ``apply_diff``).

    Each pool is protected by its own meta-lock so that lazy lock creation
    is race-free: when multiple tasks or threads simultaneously request a
    lock for a path that has no entry yet, exactly one lock is created and
    shared by all callers.

    Lock keys are canonicalised via ``os.path.realpath`` so that symlinks
    and relative paths collapse to the same underlying inode.
    """

    def __init__(self) -> None:
        """Initialise empty lock pools and meta-locks."""
        # Async pool
        self._async_locks: dict[str, asyncio.Lock] = {}
        self._async_meta_lock = asyncio.Lock()

        # Sync pool (reentrant locks allow nested same-path acquisition)
        self._sync_locks: dict[str, threading.RLock] = {}
        self._sync_meta_lock = threading.Lock()

    @staticmethod
    def _resolve_key(path: str | Path) -> str:
        """Canonicalise *path* to a real-path string key.

        Args:
            path: Filesystem path (string or ``Path``).

        Returns:
            ``os.path.realpath`` result — resolves symlinks and
            normalises the path so that different references to the same
            file share a single lock.
        """
        return os.path.realpath(str(path))

    async def _get_async_lock(self, key: str) -> asyncio.Lock:
        """Return (creating if necessary) the async lock for *key*.

        The meta-lock is held only during dict lookup/insertion, not while
        the caller waits on the per-path lock, so that unrelated paths are
        never blocked.
        """
        async with self._async_meta_lock:
            lock = self._async_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._async_locks[key] = lock
            return lock

    def _get_sync_lock(self, key: str) -> threading.RLock:
        """Return (creating if necessary) the sync lock for *key*.

        The meta-lock is held only during dict lookup/insertion.
        """
        with self._sync_meta_lock:
            lock = self._sync_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._sync_locks[key] = lock
            return lock

    @asynccontextmanager
    async def acquire(self, path: str | Path) -> AsyncIterator[None]:
        """Acquire the async edit lock for *path*.

        Usage::

            async with registry.acquire(resolved_path):
                ...  # read-modify-write critical section

        Args:
            path: Filesystem path (resolved or relative).

        Yields:
            None — the lock is held for the duration of the ``async with``
            block.
        """
        key = self._resolve_key(path)
        lock = await self._get_async_lock(key)
        async with lock:
            yield

    @contextmanager
    def acquire_sync(self, path: str | Path) -> Iterator[None]:
        """Acquire the sync edit lock for *path*.

        Usage::

            with registry.acquire_sync(resolved_path):
                ...  # read-modify-write critical section

        Uses a reentrant lock (``threading.RLock``) so that nested
        same-path acquisitions from the same thread do not deadlock.

        Args:
            path: Filesystem path (resolved or relative).

        Yields:
            None — the lock is held for the duration of the ``with`` block.
        """
        key = self._resolve_key(path)
        lock = self._get_sync_lock(key)
        with lock:
            yield
