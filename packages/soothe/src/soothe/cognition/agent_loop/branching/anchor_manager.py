"""Checkpoint anchor manager for iteration synchronization.

Captures checkpoint anchors at iteration boundaries (start/end) to enable
precise rewinding and checkpoint tree management.

RFC-611: AgentLoop Checkpoint Tree Architecture
IG-055: Backend-agnostic persistence with config-driven backend selection
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.cognition.agent_loop.state.persistence.manager import (
    AgentLoopCheckpointPersistenceManager,
)

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class CheckpointAnchorManager:
    """Manager for iteration checkpoint anchor capture."""

    def __init__(self, loop_id: str, config: SootheConfig | None = None) -> None:
        """Initialize anchor manager.

        Args:
            loop_id: AgentLoop identifier.
            config: SootheConfig for backend selection. If None, defaults to SQLite.
        """
        self.loop_id = loop_id
        self.persistence_manager = AgentLoopCheckpointPersistenceManager(config=config)

    async def capture_iteration_start_anchor(
        self,
        iteration: int,
        thread_id: str,
        checkpointer: BaseCheckpointSaver,
    ) -> None:
        """Capture iteration start anchor before Plan phase.

        Args:
            iteration: Current iteration number.
            thread_id: Current thread ID.
            checkpointer: LangGraph checkpointer instance.
        """
        # Get current CoreAgent checkpoint
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint_tuple = await checkpointer.aget_tuple(config)

        if not checkpoint_tuple:
            logger.warning(
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
        checkpointer: BaseCheckpointSaver,
        execution_summary: dict[str, Any] | None = None,
    ) -> None:
        """Capture iteration end anchor after successful Execute phase.

        Args:
            iteration: Current iteration number.
            thread_id: Current thread ID.
            checkpointer: LangGraph checkpointer instance.
            execution_summary: Execution summary (status, tools, reasoning).
        """
        # Get latest CoreAgent checkpoint
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint_tuple = await checkpointer.aget_tuple(config)

        if not checkpoint_tuple:
            logger.warning(
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


__all__ = ["CheckpointAnchorManager"]
