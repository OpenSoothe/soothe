"""RocksDB persistence backend using rocksdict."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class RocksDBPersistStore:
    """PersistStore implementation using RocksDB via ``rocksdict``.

    All keys and values are stored as JSON-encoded strings in a single
    RocksDB database at ``persist_dir``.
    """

    def __init__(self, persist_dir: str) -> None:
        """Initialize RocksDBPersistStore.

        Args:
            persist_dir: Path to the RocksDB database directory.

        Raises:
            ImportError: If ``rocksdict`` is not installed.
        """
        try:
            from rocksdict import Rdict
        except ImportError as exc:
            msg = "rocksdict is required for RocksDB persistence: pip install soothe[rocksdb]"
            raise ImportError(msg) from exc

        self._db: Rdict = Rdict(persist_dir)

    def save(self, key: str, data: Any) -> None:
        """Persist data as a JSON string in RocksDB."""
        self._db[key] = json.dumps(data, default=str)

    def load(self, key: str) -> Any | None:
        """Load data from RocksDB."""
        try:
            raw = self._db[key]
        except KeyError:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to decode RocksDB value for key %s", key)
            return None

    def delete(self, key: str) -> None:
        """Delete a key from RocksDB."""
        try:
            del self._db[key]
        except KeyError:
            pass

    def close(self) -> None:
        """Close the RocksDB database."""
        self._db.close()
