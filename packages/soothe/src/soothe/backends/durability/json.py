"""JsonDurability -- file-backed thread metadata durability."""

from __future__ import annotations

import logging
from pathlib import Path

from soothe.backends.durability.base import BasePersistStoreDurability
from soothe.backends.persistence import create_persist_store

logger = logging.getLogger(__name__)


class JsonDurability(BasePersistStoreDurability):
    """DurabilityProtocol implementation using JSON file storage.

    Uses JsonPersistStore for persistence with multi-file format:
        - thread:{id}.json - individual thread metadata
        - state:{id}.json - individual thread state
        - thread_index.json - list of all thread IDs
    """

    def __init__(self, persist_dir: str) -> None:
        """Initialize the durability backend with a JSON persistence directory.

        Args:
            persist_dir: Directory for JSON persistence files.
        """
        path = Path(persist_dir).expanduser().resolve()

        # Ensure directory exists
        path.mkdir(parents=True, exist_ok=True)

        # Create PersistStore
        persist_store = create_persist_store(str(path), backend="json")
        if persist_store is None:
            msg = f"Failed to create JSON persist store at {path}"
            raise ValueError(msg)

        super().__init__(persist_store)
