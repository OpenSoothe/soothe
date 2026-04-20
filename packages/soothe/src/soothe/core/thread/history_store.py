"""Thread history JSONL storage - single source of truth for metadata.

Provides fast TUI access via append-only JSONL format.
Replaces JsonPersistStore's per-thread JSON files for thread metadata.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ThreadHistoryStore:
    """Manages thread_history.jsonl for all thread metadata.

    Thread metadata is stored as append-only JSONL for:
    - Fast TUI loading (line-by-line read)
    - Simple daemon updates (append on create, rewrite on update/delete)
    - Atomic operations (single file write, no partial state)

    Each line contains complete thread metadata needed for TUI /threads display.
    """

    def __init__(self, history_path: Path) -> None:
        """Initialize ThreadHistoryStore.

        Args:
            history_path: Base directory for thread_history.jsonl (usually $SOOTHE_HOME).
        """
        self._path = history_path / "thread_history.jsonl"
        self._lock = asyncio.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def append_thread(self, info: dict[str, Any]) -> None:
        """Append new thread entry to history file.

        Args:
            info: Thread metadata dict with all ThreadInfo fields.
        """
        async with self._lock:
            # Append single line (atomic write)
            line = json.dumps(info, ensure_ascii=False) + "\n"
            await asyncio.to_thread(self._path.write_text, line, encoding="utf-8", append=True)
            logger.debug(
                "Appended thread %s to thread_history.jsonl",
                info.get("thread_id", "unknown"),
            )

    async def update_thread(self, thread_id: str, info: dict[str, Any]) -> None:
        """Update thread entry by rewriting entire file.

        Args:
            thread_id: Thread ID to update.
            info: Updated thread metadata dict.
        """
        async with self._lock:
            # Read all threads
            threads = await self._read_all_threads()

            # Update matching thread
            updated = False
            for i, thread in enumerate(threads):
                if thread.get("thread_id") == thread_id:
                    threads[i] = info
                    updated = True
                    break

            if not updated:
                logger.warning(
                    "Thread %s not found in history for update, appending instead",
                    thread_id,
                )
                threads.append(info)

            # Rewrite entire file
            await self._write_all_threads(threads)
            logger.debug("Updated thread %s in thread_history.jsonl", thread_id)

    async def remove_thread(self, thread_id: str) -> None:
        """Remove thread entry by rewriting file (skip matching ID).

        Args:
            thread_id: Thread ID to remove.
        """
        async with self._lock:
            # Read all threads
            threads = await self._read_all_threads()

            # Filter out removed thread
            filtered = [t for t in threads if t.get("thread_id") != thread_id]

            if len(filtered) == len(threads):
                logger.warning("Thread %s not found in history for removal", thread_id)
                return

            # Rewrite file without removed thread
            await self._write_all_threads(filtered)
            logger.debug("Removed thread %s from thread_history.jsonl", thread_id)

    async def list_threads(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Read all threads from JSONL (top N lines if limit).

        Args:
            limit: Maximum threads to return. None returns all.

        Returns:
            List of thread metadata dicts, sorted by updated_at (most recent first).
        """
        threads = await self._read_all_threads()

        # Sort by updated_at (most recent first)
        threads.sort(key=lambda t: t.get("updated_at", ""), reverse=True)

        # Apply limit
        if limit is not None and limit > 0:
            threads = threads[:limit]

        return threads

    async def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        """Get single thread by ID (scan file).

        Args:
            thread_id: Thread ID to retrieve.

        Returns:
            Thread metadata dict or None if not found.
        """
        threads = await self._read_all_threads()
        for thread in threads:
            if thread.get("thread_id") == thread_id:
                return thread
        return None

    async def cleanup_archived(self, days: int = 90) -> int:
        """Remove archived threads older than retention period.

        Args:
            days: Retention period in days. Archived threads older than this are removed.

        Returns:
            Number of threads removed.
        """
        async with self._lock:
            threads = await self._read_all_threads()

            cutoff = datetime.now() - timedelta(days=days)
            cutoff_iso = cutoff.isoformat()

            # Filter: keep non-archived or recent archived
            filtered = []
            removed_count = 0
            for thread in threads:
                status = thread.get("status", "")
                updated_at = thread.get("updated_at", "")

                # Keep if not archived OR if recently updated
                if status != "archived" or updated_at >= cutoff_iso:
                    filtered.append(thread)
                else:
                    removed_count += 1

            if removed_count == 0:
                return 0

            # Rewrite file
            await self._write_all_threads(filtered)
            logger.info(
                "Cleaned up %d archived threads older than %d days from thread_history.jsonl",
                removed_count,
                days,
            )
            return removed_count

    async def _read_all_threads(self) -> list[dict[str, Any]]:
        """Read all threads from JSONL file.

        Returns:
            List of thread metadata dicts.
        """
        if not self._path.exists():
            return []

        threads = []
        try:
            content = await asyncio.to_thread(self._path.read_text, encoding="utf-8")
            for line in content.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    thread = json.loads(line)
                    threads.append(thread)
                except json.JSONDecodeError:
                    logger.warning("Malformed JSON line in thread_history.jsonl: %s", line[:100])
                    # Skip malformed lines
                    continue
        except OSError:
            logger.exception("Failed to read thread_history.jsonl")
            return []

        return threads

    async def _write_all_threads(self, threads: list[dict[str, Any]]) -> None:
        """Write all threads to JSONL file (rewrite entire file).

        Args:
            threads: List of thread metadata dicts to write.
        """
        lines = [json.dumps(t, ensure_ascii=False) for t in threads]
        content = "\n".join(lines) + "\n" if lines else ""
        await asyncio.to_thread(self._path.write_text, content, encoding="utf-8")
