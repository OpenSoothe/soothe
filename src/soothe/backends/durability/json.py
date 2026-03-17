"""JsonDurability -- file-backed thread metadata durability."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from soothe.backends.durability.base import BasePersistStoreDurability
from soothe.backends.persistence import create_persist_store

logger = logging.getLogger(__name__)


class JsonDurability(BasePersistStoreDurability):
    """DurabilityProtocol implementation using JSON file storage.

    Uses JsonPersistStore for persistence with automatic migration from
    legacy single-file format (threads.json) to new multi-file format.

    Legacy format (threads.json):
        {"threads": {...}, "state": {...}}

    New format (multiple files):
        - thread:{id}.json - individual thread metadata
        - state:{id}.json - individual thread state
        - thread_index.json - list of all thread IDs
    """

    def __init__(self, persist_dir: str) -> None:
        """Initialize the durability backend with a JSON persistence directory.

        Args:
            persist_dir: Directory for JSON persistence files.
                        If a .json file path is provided, uses its parent directory
                        and migrates legacy format if needed.
        """
        path = Path(persist_dir).expanduser().resolve()

        # Handle legacy usage where a .json file path was passed
        if path.suffix == ".json":
            self._migrate_legacy_format(path)
            persist_dir = str(path.parent)
        else:
            # Ensure directory exists
            path.mkdir(parents=True, exist_ok=True)
            persist_dir = str(path)

        # Create PersistStore
        persist_store = create_persist_store(persist_dir, backend="json")
        if persist_store is None:
            raise ValueError(f"Failed to create JSON persist store at {persist_dir}")

        super().__init__(persist_store)

    def _migrate_legacy_format(self, legacy_path: Path) -> None:
        """Migrate from legacy single-file format to new multi-file format.

        This migration is idempotent and safe to run multiple times.
        Creates backup of legacy file as threads.json.legacy.

        Args:
            legacy_path: Path to the legacy threads.json file.
        """
        # Check if legacy file exists
        if not legacy_path.exists():
            return

        # Check if already migrated (thread_index.json exists)
        index_path = legacy_path.parent / "thread_index.json"
        if index_path.exists():
            logger.debug("Already migrated from legacy format, skipping")
            return

        # Load legacy data
        try:
            raw = legacy_path.read_text(encoding="utf-8").strip()
            if not raw:
                return

            data = json.loads(raw)
            threads = data.get("threads", {})
            states = data.get("state", {})

            # Create PersistStore for migration
            store = create_persist_store(str(legacy_path.parent), backend="json")
            if store is None:
                logger.warning("Failed to create store for migration, skipping")
                return

            # Migrate threads
            thread_ids = []
            for tid, thread_data in threads.items():
                store.save(f"thread:{tid}", thread_data)
                thread_ids.append(tid)

            # Migrate states
            for tid, state_data in states.items():
                store.save(f"state:{tid}", state_data)

            # Create thread index
            store.save("thread_index", thread_ids)

            # Backup legacy file
            backup_path = legacy_path.with_suffix(".json.legacy")
            legacy_path.rename(backup_path)
            logger.info(
                "Migrated %d threads from legacy format to %s",
                len(thread_ids),
                legacy_path.parent,
            )

        except (json.JSONDecodeError, OSError, ValueError):
            logger.warning(
                "Failed to migrate legacy format from %s, starting fresh",
                legacy_path,
                exc_info=True,
            )
