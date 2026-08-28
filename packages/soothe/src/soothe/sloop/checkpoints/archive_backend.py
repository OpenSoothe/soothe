"""Archive storage for finalized StrangeLoop checkpoints."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from soothe.sloop.checkpoints.directory_manager import (
    PersistenceDirectoryManager,
)

if TYPE_CHECKING:
    from soothe.sloop.state.checkpoint import StrangeLoopCheckpoint

logger = logging.getLogger(__name__)


class ArchiveBackend:
    """Archive storage for finalized loops.

    Layout:
        SOOTHE_HOME/data/archived_loops/
          {loop_id}/
            checkpoint_{timestamp}.json
            metadata.json  # Loop summary for /recall queries
    """

    def __init__(self, base_path: Path | None = None) -> None:
        """Initialize archive backend.

        Args:
            base_path: Optional base path for archives. Defaults to SOOTHE_HOME/data/archived_loops.
        """
        if base_path is None:
            self._base_path = PersistenceDirectoryManager.get_archived_loops_directory()
        else:
            self._base_path = base_path

        self._base_path.mkdir(parents=True, exist_ok=True)
        logger.debug("ArchiveBackend initialized at %s", self._base_path)

    async def archive_loop(
        self,
        checkpoint: StrangeLoopCheckpoint,
        *,
        reason: Literal["user_clear", "finalized", "expired"],
    ) -> str:
        """Archive loop checkpoint to disk.

        Args:
            checkpoint: Complete loop state to archive
            reason: Archival trigger reason

        Returns:
            Archive path (relative to SOOTHE_HOME)
        """
        loop_id = checkpoint.loop_id
        timestamp = datetime.now(UTC)
        timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")

        # Create archive directory for this loop
        loop_archive_dir = self._base_path / loop_id
        loop_archive_dir.mkdir(parents=True, exist_ok=True)

        # Save checkpoint
        checkpoint_file = loop_archive_dir / f"checkpoint_{timestamp_str}.json"
        checkpoint_data = checkpoint.model_dump(mode="json")

        def _write_checkpoint() -> None:
            with open(checkpoint_file, "w", encoding="utf-8") as f:
                json.dump(checkpoint_data, f, indent=2, default=str)

        # Run in thread pool for async compatibility
        import asyncio

        await asyncio.to_thread(_write_checkpoint)

        logger.info(
            "Archived loop %s checkpoint to %s (reason: %s)",
            loop_id,
            checkpoint_file,
            reason,
        )

        # Return relative path
        return str(checkpoint_file.relative_to(self._base_path.parent.parent))
