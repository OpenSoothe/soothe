"""Global cross-thread input history stored in JSONL format."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from soothe.config import SOOTHE_HOME

logger = logging.getLogger(__name__)


class GlobalInputHistory:
    """Cross-thread global input history stored in JSONL format.

    Stores all user inputs from all threads in a single JSONL file at
    SOOTHE_HOME/history.jsonl. Provides deduplication, size limits, and
    cleanup for old entries.

    Args:
        history_file: Path to global history JSONL file.
            Defaults to SOOTHE_HOME/history.jsonl.
        max_size: Maximum number of entries to retain.
        dedup_window: Number of recent entries to check for duplicates.
    """

    def __init__(
        self,
        history_file: str | None = None,
        max_size: int = 5000,
        dedup_window: int = 10,
    ) -> None:
        """Initialize global input history.

        Args:
            history_file: Path to global history JSONL file.
            max_size: Maximum entries to retain.
            dedup_window: Recent entries to check for duplicates.
        """
        self.history_file = Path(history_file or Path(SOOTHE_HOME) / "history.jsonl").expanduser()
        self.max_size = max_size
        self.dedup_window = dedup_window
        self._index_counter: int = 0
        self._recent_cache: list[dict[str, Any]] = []
        self._load_index_and_cache()

    def _load_index_and_cache(self) -> None:
        """Load current index counter and recent cache from file.

        Reads last line of JSONL file to extract index counter.
        Loads last N entries (dedup_window) into in-memory cache.
        """
        if not self.history_file.exists():
            self._index_counter = 0
            self._recent_cache = []
            return

        # Read file to get last entry and populate cache
        entries = []
        try:
            with self.history_file.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        # Ensure entry is a dict (not a bare string or other type)
                        if isinstance(entry, dict):
                            entries.append(entry)
                        else:
                            logger.debug("Skipping non-dict history entry: %s", str(entry)[:50])
                    except json.JSONDecodeError:
                        logger.debug("Skipping malformed history line: %s", line[:50])
                        continue
        except OSError:
            logger.debug("Failed to read global history file", exc_info=True)
            self._index_counter = 0
            self._recent_cache = []
            return

        # Set index counter from last entry
        if entries:
            last_entry = entries[-1]
            last_index = last_entry.get("index", -1) if isinstance(last_entry, dict) else -1
            self._index_counter = last_index + 1
            # Cache last N entries for dedup
            self._recent_cache = entries[-self.dedup_window :]
        else:
            self._index_counter = 0
            self._recent_cache = []

    def add(
        self,
        text: str,
        thread_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add entry to global history with deduplication.

        Args:
            text: User input text (will be stripped).
            thread_id: Thread where input was submitted.
            metadata: Optional metadata dict (workspace, autonomous, subagent).
        """
        stripped = text.strip()
        if not stripped:
            return

        # Deduplication check against recent cache
        if self._dedup_check(stripped):
            logger.debug("Skipping duplicate input: %s", stripped[:50])
            return

        # Create entry
        entry = {
            "index": self._index_counter,
            "timestamp": datetime.now(UTC).isoformat(),
            "text": stripped,
            "thread_id": thread_id,
            "metadata": metadata or {},
        }

        # Write to file
        self._write_entry(entry)

        # Update counter and cache
        self._index_counter += 1
        self._recent_cache.append(entry)
        if len(self._recent_cache) > self.dedup_window:
            self._recent_cache = self._recent_cache[-self.dedup_window :]

    def _dedup_check(self, text: str) -> bool:
        """Check if text is in recent cache (duplicate).

        Args:
            text: Text to check for duplication.

        Returns:
            True if duplicate found, False otherwise.
        """
        for entry in self._recent_cache:
            # Skip non-dict entries in cache
            if isinstance(entry, dict) and entry.get("text") == text:
                return True
        return False

    def _write_entry(self, entry: dict[str, Any]) -> None:
        """Append entry to JSONL file with fsync.

        Args:
            entry: Entry dict to write.
        """
        try:
            # Ensure directory exists
            self.history_file.parent.mkdir(parents=True, exist_ok=True)

            # Append entry
            with self.history_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except OSError:
            logger.debug("Failed to write global history entry", exc_info=True)

    def get_recent(self, limit: int = 100) -> list[str]:
        """Get recent input texts (oldest first) for TUI navigation.

        Args:
            limit: Maximum number of entries to return.

        Returns:
            List of text strings, oldest first.
        """
        if not self.history_file.exists():
            return []

        entries = []
        try:
            with self.history_file.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        # Only include dict entries
                        if isinstance(entry, dict):
                            entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            logger.debug("Failed to read global history for recent", exc_info=True)
            return []

        # Return last N text strings (oldest first)
        recent = entries[-limit:] if limit > 0 else entries
        return [entry.get("text", "") for entry in recent if isinstance(entry, dict) and entry.get("text")]

    def get_entries(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent entries with full metadata.

        Args:
            limit: Maximum number of entries to return.

        Returns:
            List of entry dicts, oldest first.
        """
        if not self.history_file.exists():
            return []

        entries = []
        try:
            with self.history_file.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        # Only include dict entries
                        if isinstance(entry, dict):
                            entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            logger.debug("Failed to read global history entries", exc_info=True)
            return []

        return entries[-limit:] if limit > 0 else entries

    def cleanup_old_entries(self, retention_days: int = 90) -> int:
        """Remove entries older than retention period.

        Strategy:
        1. Read entire file, filter by timestamp
        2. Rewrite file with retained entries (preserve order)
        3. Reset index counter to last retained entry

        Args:
            retention_days: Days to retain before cleanup.

        Returns:
            Number of entries removed.
        """
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)

        if not self.history_file.exists():
            return 0

        # Read all entries
        retained = []
        removed = 0
        try:
            with self.history_file.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        # Ensure entry is a dict before accessing
                        if not isinstance(entry, dict):
                            logger.debug("Skipping non-dict history entry in cleanup")
                            continue
                        ts_str = entry.get("timestamp", "")
                        if ts_str:
                            ts = datetime.fromisoformat(ts_str)
                            if ts >= cutoff:
                                retained.append(entry)
                            else:
                                removed += 1
                    except (json.JSONDecodeError, ValueError):
                        # Keep malformed entries (conservative approach)
                        continue
        except OSError:
            logger.debug("Global history cleanup read failed", exc_info=True)
            return 0

        # Rewrite file with retained entries
        if removed > 0:
            try:
                # Ensure directory exists
                self.history_file.parent.mkdir(parents=True, exist_ok=True)

                with self.history_file.open("w", encoding="utf-8") as fh:
                    for entry in retained:
                        fh.write(json.dumps(entry, default=str) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())

                # Reset index counter
                if retained:
                    last_entry = retained[-1]
                    if isinstance(last_entry, dict):
                        self._index_counter = last_entry.get("index", 0) + 1
                    else:
                        self._index_counter = 0
                else:
                    self._index_counter = 0

                # Update cache
                self._recent_cache = retained[-self.dedup_window :]

                logger.info("Cleaned up %d old global history entries", removed)
            except OSError:
                logger.debug("Global history cleanup write failed", exc_info=True)

        return removed
