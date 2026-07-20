"""Directory manager for CoreAgent thread isolation."""

from __future__ import annotations

from pathlib import Path

THREADS_DATA_DIR = "data/threads"
"""Directory for CoreAgent thread runtime data."""


class PersistenceDirectoryManager:
    """Manager for isolated CoreAgent persistence directories."""

    @staticmethod
    def ensure_directories_exist() -> None:
        """Create thread data directories if they don't exist."""
        from soothe_nano.config import SOOTHE_HOME

        threads_dir = Path(SOOTHE_HOME).expanduser() / THREADS_DATA_DIR
        threads_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def get_thread_directory(thread_id: str) -> Path:
        """Get CoreAgent thread directory path."""
        from soothe_nano.config import SOOTHE_HOME

        return Path(SOOTHE_HOME).expanduser() / THREADS_DATA_DIR / thread_id

    @staticmethod
    def get_thread_checkpoint_path(thread_id: str) -> Path:
        """Get CoreAgent thread checkpoint database path."""
        return PersistenceDirectoryManager.get_thread_directory(thread_id) / "checkpoint.db"

    @staticmethod
    def get_thread_artifacts_dir(thread_id: str) -> Path:
        """Get CoreAgent thread artifacts directory."""
        return PersistenceDirectoryManager.get_thread_directory(thread_id) / "artifacts"


__all__ = [
    "PersistenceDirectoryManager",
    "THREADS_DATA_DIR",
]
