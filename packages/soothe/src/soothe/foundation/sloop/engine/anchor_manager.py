"""Checkpoint anchor manager for iteration synchronization.

Captures checkpoint anchors at iteration boundaries (start/end) to enable
precise rewinding and checkpoint tree management.

RFC-218: StrangeLoop Checkpoint Tree Architecture
IG-055: Backend-agnostic persistence with config-driven backend selection
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.foundation.sloop.state.persistence.manager import (
    StrangeLoopCheckpointPersistenceManager,
)

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class CheckpointAnchorManager:
    """Manager for iteration checkpoint anchor capture."""

    def __init__(
        self,
        loop_id: str,
        config: SootheConfig | None = None,
        *,
        persistence_manager: StrangeLoopCheckpointPersistenceManager | None = None,
    ) -> None:
        """Initialize anchor manager.

        Args:
            loop_id: StrangeLoop identifier.
            config: SootheConfig for backend selection. If None, defaults to SQLite.
            persistence_manager: Optional pre-built manager (shared pool mode).
        """
        self.loop_id = loop_id
        if persistence_manager is not None:
            self.persistence_manager = persistence_manager
        else:
            self.persistence_manager = StrangeLoopCheckpointPersistenceManager(config=config)

    @classmethod
    async def create(
        cls, loop_id: str, config: SootheConfig | None = None
    ) -> CheckpointAnchorManager:
        """Build an anchor manager using the process-wide checkpoint pool when on PostgreSQL."""
        if config is not None and config.persistence.default_backend == "postgresql":
            manager = await StrangeLoopCheckpointPersistenceManager.for_shared_checkpoint_pool(
                config
            )
            return cls(loop_id, config, persistence_manager=manager)
        return cls(loop_id, config)

    async def capture_iteration_start_anchor(
        self,
        iteration: int,
        thread_id: str,
        checkpointer: BaseCheckpointSaver | None,
    ) -> None:
        """Capture iteration start anchor before Plan phase.

        Args:
            iteration: Current iteration number.
            thread_id: Current thread ID.
            checkpointer: LangGraph checkpointer instance, or ``None`` to skip.
        """
        if checkpointer is None:
            logger.debug(
                "No checkpointer available, skipping iter_start anchor for thread=%s iter=%d",
                thread_id,
                iteration,
            )
            return

        # Get current CoreAgent checkpoint
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint_tuple = await checkpointer.aget_tuple(config)

        if not checkpoint_tuple:
            log = logger.debug if iteration == 0 else logger.warning
            log(
                "No checkpoint found for thread=%s iteration=%d, skipping anchor capture",
                thread_id,
                iteration,
            )
            return

        checkpoint_id = checkpoint_tuple.config["configurable"]["checkpoint_id"]
        checkpoint_ns = checkpoint_tuple.config["configurable"].get("checkpoint_ns", "")

        # Save anchor to persistence
        await self.persistence_manager.save_checkpoint_anchor(
            loop_id=self.loop_id,
            iteration=iteration,
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            anchor_type="iteration_start",
            checkpoint_ns=checkpoint_ns,
        )

        logger.debug(
            "Captured iter_start anchor: loop=%s iter=%d thread=%s checkpoint=%s",
            self.loop_id,
            iteration,
            thread_id,
            checkpoint_id,
        )

    async def capture_iteration_end_anchor(
        self,
        iteration: int,
        thread_id: str,
        checkpointer: BaseCheckpointSaver | None,
        execution_summary: dict[str, Any] | None = None,
    ) -> None:
        """Capture iteration end anchor after successful Execute phase.

        Args:
            iteration: Current iteration number.
            thread_id: Current thread ID.
            checkpointer: LangGraph checkpointer instance, or ``None`` to skip.
            execution_summary: Execution summary (status, tools, reasoning).
        """
        if checkpointer is None:
            logger.debug(
                "No checkpointer available, skipping iter_end anchor for thread=%s iter=%d",
                thread_id,
                iteration,
            )
            return

        # Get latest CoreAgent checkpoint
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint_tuple = await checkpointer.aget_tuple(config)

        if not checkpoint_tuple:
            log = logger.debug if iteration == 0 else logger.warning
            log(
                "No checkpoint found for thread=%s iteration=%d, skipping anchor capture",
                thread_id,
                iteration,
            )
            return

        checkpoint_id = checkpoint_tuple.config["configurable"]["checkpoint_id"]
        checkpoint_ns = checkpoint_tuple.config["configurable"].get("checkpoint_ns", "")

        # Save anchor with execution summary
        await self.persistence_manager.save_checkpoint_anchor(
            loop_id=self.loop_id,
            iteration=iteration,
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            anchor_type="iteration_end",
            checkpoint_ns=checkpoint_ns,
            execution_summary=execution_summary,
        )

        logger.debug(
            "Captured iter_end anchor: loop=%s iter=%d thread=%s checkpoint=%s status=%s",
            self.loop_id,
            iteration,
            thread_id,
            checkpoint_id,
            execution_summary.get("status") if execution_summary else "unknown",
        )

    async def close(self) -> None:
        """Close persistence manager backend pools (IG-404: prevent pool exhaustion).

        Must be called when anchor manager is no longer needed to release database connections.
        """
        await self.persistence_manager.close()
        logger.debug("Closed anchor manager persistence pool for loop %s", self.loop_id)


__all__ = ["CheckpointAnchorManager"]
