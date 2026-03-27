"""JSON file persistence backend."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class JsonPersistStore:
    """PersistStore implementation using one JSON file per key.

    Files are stored as ``{persist_dir}/{key}.json``.
    """

    def __init__(self, persist_dir: str) -> None:
        """Initialize JsonPersistStore.

        Args:
            persist_dir: Directory for JSON files.
        """
        self._dir = Path(persist_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe_key = key.replace("/", "_").replace(":", "_")
        return self._dir / f"{safe_key}.json"

    def save(self, key: str, data: Any) -> None:
        """Persist data as a JSON file.

        Note: Persistence files are internal framework state (thread metadata, checkpoints),
        not user workspace files. They need to support overwrites, so we use direct file
        operations instead of FrameworkFilesystem (which is sandboxed and refuses overwrites).
        """
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, default=str))

    def load(self, key: str) -> Any | None:
        """Load data from a JSON file."""
        path = self._path(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to load JSON from %s", path)
            return None

    def delete(self, key: str) -> None:
        """Delete a JSON file."""
        path = self._path(key)
        path.unlink(missing_ok=True)

    def close(self) -> None:
        """No-op for JSON backend."""
