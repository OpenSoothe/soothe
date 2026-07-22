"""Archive storage for finalized StrangeLoop checkpoints (IG-500).

Provides persistent storage for archived loops, preserving goal history and
metrics for knowledge transfer via /recall.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from soothe.sloop.checkpoints.directory_manager import (
    PersistenceDirectoryManager,
)

if TYPE_CHECKING:
    from soothe.sloop.state.checkpoint import StrangeLoopCheckpoint

logger = logging.getLogger(__name__)


class GoalSummary(BaseModel):
    """Summary of a goal for archive index."""

    goal_id: str
    goal_text: str = Field(..., max_length=200)
    final_report_preview: str = Field(default="", max_length=500)


class ArchiveMetadata(BaseModel):
    """Lightweight archive index entry."""

    loop_id: str
    archived_at: datetime
    reason: Literal["user_clear", "finalized", "expired"]

    # Summary for /recall search
    goal_count: int
    goals_completed: int
    total_tokens_used: int
    total_duration_ms: int

    # Goal summaries for semantic search
    goal_summaries: list[GoalSummary] = Field(default_factory=list)


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

    async def list_archived_loops(
        self,
        *,
        limit: int = 50,
        after: datetime | None = None,
    ) -> list[ArchiveMetadata]:
        """List archived loops for /recall queries.

        Args:
            limit: Maximum number of archives to return
            after: Only return archives after this datetime

        Returns:
            List of archive metadata, sorted by archived_at descending
        """
        archives: list[ArchiveMetadata] = []

        def _load_archives() -> list[ArchiveMetadata]:
            loaded: list[ArchiveMetadata] = []
            if not self._base_path.exists():
                return loaded

            for loop_dir in self._base_path.iterdir():
                if not loop_dir.is_dir():
                    continue

                metadata_file = loop_dir / "metadata.json"
                if not metadata_file.exists():
                    continue

                try:
                    with open(metadata_file, encoding="utf-8") as f:
                        data = json.load(f)
                    meta = ArchiveMetadata(**data)

                    # Filter by date if specified
                    if after is not None and meta.archived_at <= after:
                        continue

                    loaded.append(meta)
                except Exception as e:
                    logger.warning(
                        "Failed to load metadata from %s: %s",
                        metadata_file,
                        e,
                    )
                    continue

            # Sort by archived_at descending
            loaded.sort(key=lambda m: m.archived_at, reverse=True)
            return loaded[:limit]

        import asyncio

        archives = await asyncio.to_thread(_load_archives)
        return archives
