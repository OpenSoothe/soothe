"""Directory manager for isolated persistence directories."""

from __future__ import annotations

from pathlib import Path

# SOOTHE_HOME will be imported at runtime to allow test mocking
SOOTHE_HOME = None  # Will be set in methods

THREADS_DATA_DIR = "data/threads"
"""Directory for CoreAgent thread runtime data (Layer 1)."""

LOOPS_DATA_DIR = "data/loops"
"""Directory for StrangeLoop checkpoint data (Layer 2)."""

ARCHIVED_LOOPS_DATA_DIR = "data/archived_loops"
"""Directory for archived StrangeLoop checkpoints."""


class PersistenceDirectoryManager:
    """Manager for isolated persistence directories."""

    @staticmethod
    def ensure_directories_exist() -> None:
        """Create isolated data directories if they don't exist."""
        from soothe.config import SOOTHE_HOME

        threads_dir = Path(SOOTHE_HOME).expanduser() / THREADS_DATA_DIR
        loops_dir = Path(SOOTHE_HOME).expanduser() / LOOPS_DATA_DIR

        threads_dir.mkdir(parents=True, exist_ok=True)
        loops_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def get_thread_directory(thread_id: str) -> Path:
        """Get CoreAgent thread directory path.

        Args:
            thread_id: Thread identifier.

        Returns:
            Path to thread's data directory.
        """
        from soothe.config import SOOTHE_HOME

        return Path(SOOTHE_HOME).expanduser() / THREADS_DATA_DIR / thread_id

    @staticmethod
    def get_loops_directory() -> Path:
        """Get StrangeLoop loops base directory path.

        Returns:
            Path to data/loops/ directory.
        """
        from soothe.config import SOOTHE_HOME

        return Path(SOOTHE_HOME).expanduser() / LOOPS_DATA_DIR

    @staticmethod
    def get_loop_directory(loop_id: str) -> Path:
        """Get StrangeLoop loop directory path.

        Args:
            loop_id: Loop identifier.

        Returns:
            Path to loop's data directory.
        """
        from soothe.config import SOOTHE_HOME

        return Path(SOOTHE_HOME).expanduser() / LOOPS_DATA_DIR / loop_id

    @staticmethod
    def get_archived_loops_directory() -> Path:
        """Get archived StrangeLoop loops base directory path.

        Returns:
            Path to data/archived_loops/ directory.
        """
        from soothe.config import SOOTHE_HOME

        return Path(SOOTHE_HOME).expanduser() / ARCHIVED_LOOPS_DATA_DIR

    @staticmethod
    def get_loop_checkpoint_path() -> Path:
        """Get StrangeLoop global checkpoint database path (unified SQLite).

        Returns:
            Path to shared `databases/checkpoints.db` (StrangeLoop + LangGraph).
            Table: agentloop_checkpoints (separate from LangGraph checkpoint tables).
        """
        from soothe_sdk.paths import resolve_checkpoints_db_path

        return resolve_checkpoints_db_path()


__all__ = [
    "PersistenceDirectoryManager",
    "THREADS_DATA_DIR",
    "LOOPS_DATA_DIR",
]
