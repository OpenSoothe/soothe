"""Directory manager for isolated persistence directories.

Ensures thread/loop isolation:
- data/threads/ (CoreAgent Layer 1)
- data/loops/ (AgentLoop Layer 2)

RFC-409: AgentLoop Persistence Backend Architecture
"""

from __future__ import annotations

from pathlib import Path

# SOOTHE_HOME will be imported at runtime to allow test mocking
SOOTHE_HOME = None  # Will be set in methods

THREADS_DATA_DIR = "data/threads"
"""Directory for CoreAgent thread runtime data (Layer 1)."""

LOOPS_DATA_DIR = "data/loops"
"""Directory for AgentLoop checkpoint data (Layer 2)."""


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
    def get_thread_checkpoint_path(thread_id: str) -> Path:
        """Get CoreAgent thread checkpoint database path.

        Returns:
            Path to thread's checkpoint.db (managed by LangGraph).
        """
        # No need to import SOOTHE_HOME here - uses get_thread_directory
        return PersistenceDirectoryManager.get_thread_directory(thread_id) / "checkpoint.db"

    @staticmethod
    def get_thread_artifacts_dir(thread_id: str) -> Path:
        """Get CoreAgent thread artifacts directory.

        Returns:
            Path to thread's artifacts/ directory.
        """
        # No need to import SOOTHE_HOME here - uses get_thread_directory
        return PersistenceDirectoryManager.get_thread_directory(thread_id) / "artifacts"

    @staticmethod
    def get_loops_directory() -> Path:
        """Get AgentLoop loops base directory path.

        Returns:
            Path to data/loops/ directory.
        """
        from soothe.config import SOOTHE_HOME

        return Path(SOOTHE_HOME).expanduser() / LOOPS_DATA_DIR

    @staticmethod
    def get_loop_directory(loop_id: str) -> Path:
        """Get AgentLoop loop directory path.

        Args:
            loop_id: Loop identifier.

        Returns:
            Path to loop's data directory.
        """
        from soothe.config import SOOTHE_HOME

        return Path(SOOTHE_HOME).expanduser() / LOOPS_DATA_DIR / loop_id

    @staticmethod
    def get_goal_directory(loop_id: str, goal_id: str) -> Path:
        """Get AgentLoop goal directory path.

        Args:
            loop_id: Loop identifier.
            goal_id: Goal identifier.

        Returns:
            Path to goal's directory: data/loops/{loop_id}/goals/{goal_id}/
        """
        from soothe.config import SOOTHE_HOME

        return Path(SOOTHE_HOME).expanduser() / LOOPS_DATA_DIR / loop_id / "goals" / goal_id

    @staticmethod
    def get_step_directory(loop_id: str, goal_id: str, step_id: str) -> Path:
        """Get AgentLoop step directory path.

        Args:
            loop_id: Loop identifier.
            goal_id: Goal identifier.
            step_id: Step identifier.

        Returns:
            Path to step's directory: data/loops/{loop_id}/goals/{goal_id}/steps/{step_id}/
        """
        from soothe.config import SOOTHE_HOME

        return (
            Path(SOOTHE_HOME).expanduser()
            / LOOPS_DATA_DIR
            / loop_id
            / "goals"
            / goal_id
            / "steps"
            / step_id
        )

    @staticmethod
    def get_loop_checkpoint_path() -> Path:
        """Get AgentLoop global checkpoint database path (IG-055: unified SQLite).

        Returns:
            Path to shared soothe_checkpoints.db (managed by AgentLoop + LangGraph).
            Table: agentloop_checkpoints (separate from LangGraph checkpoint tables).
        """
        from soothe_sdk.client.config import SOOTHE_DATA_DIR

        return Path(SOOTHE_DATA_DIR) / "soothe_checkpoints.db"

    @staticmethod
    def get_loop_metadata_path(loop_id: str) -> Path:
        """Get AgentLoop loop metadata.json path.

        Returns:
            Path to loop's metadata.json (human-readable quick access).
        """
        # No need to import SOOTHE_HOME here - uses get_loop_directory
        return PersistenceDirectoryManager.get_loop_directory(loop_id) / "metadata.json"

    @staticmethod
    def get_loop_working_memory_dir(loop_id: str) -> Path:
        """Get AgentLoop working memory spill directory.

        Returns:
            Path to loop's working_memory/ directory.
        """
        # No need to import SOOTHE_HOME here - uses get_loop_directory
        return PersistenceDirectoryManager.get_loop_directory(loop_id) / "working_memory"


__all__ = [
    "PersistenceDirectoryManager",
    "THREADS_DATA_DIR",
    "LOOPS_DATA_DIR",
]
