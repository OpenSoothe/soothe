"""Failed branch manager for branch creation and management.

Creates failed branches on iteration failure detection, preserving
execution path for learning analysis and smart retry.

RFC-611: AgentLoop Checkpoint Tree Architecture
IG-055: Backend-agnostic persistence with config-driven backend selection
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from soothe.cognition.agent_loop.state.persistence.manager import (
    AgentLoopCheckpointPersistenceManager,
)

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class FailedBranchManager:
    """Manager for failed branch creation and management."""

    def __init__(self, loop_id: str, config: SootheConfig | None = None) -> None:
        """Initialize branch manager.

        Args:
            loop_id: AgentLoop identifier.
            config: SootheConfig for backend selection. If None, defaults to SQLite.
        """
        self.loop_id = loop_id
        self.persistence_manager = AgentLoopCheckpointPersistenceManager(config=config)

    async def detect_iteration_failure(
        self,
        iteration: int,
        thread_id: str,
        failure_reason: str,
        checkpointer: BaseCheckpointSaver,
    ) -> dict[str, Any]:
        """Detect iteration failure and create failed branch.

        Args:
            iteration: Iteration where failure occurred.
            thread_id: Thread where failure occurred.
            failure_reason: High-level failure reason.
            checkpointer: LangGraph checkpointer.

        Returns:
            Failed branch record (dict representation).
        """
        # Get current failure checkpoint
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint_tuple = await checkpointer.aget_tuple(config)

        if not checkpoint_tuple:
            logger.warning(
                "No checkpoint found for thread=%s iteration=%d, cannot create branch",
                thread_id,
                iteration,
            )
            return {}

        failure_checkpoint_id = checkpoint_tuple.config["configurable"]["checkpoint_id"]

        # Get root checkpoint (previous iteration's checkpoint)
        anchors = await self.persistence_manager.get_checkpoint_anchors_for_range(
            self.loop_id, iteration - 1, iteration - 1
        )

        root_checkpoint_id = "initial"
        if anchors:
            # Use previous iteration's end anchor as root
            prev_anchor = [a for a in anchors if a["anchor_type"] == "iteration_end"]
            if prev_anchor:
                root_checkpoint_id = prev_anchor[0]["checkpoint_id"]
            else:
                # Use start anchor if end anchor doesn't exist
                prev_anchor = [a for a in anchors if a["anchor_type"] == "iteration_start"]
                if prev_anchor:
                    root_checkpoint_id = prev_anchor[0]["checkpoint_id"]

        # Extract execution path (simplified: root → failure)
        execution_path = [root_checkpoint_id, failure_checkpoint_id]

        # Create failed branch
        branch_id = f"branch_{uuid.uuid4().hex[:8]}"

        await self.persistence_manager.save_failed_branch(
            branch_id=branch_id,
            loop_id=self.loop_id,
            iteration=iteration,
            thread_id=thread_id,
            root_checkpoint_id=root_checkpoint_id,
            failure_checkpoint_id=failure_checkpoint_id,
            failure_reason=failure_reason,
            execution_path=execution_path,
        )

        logger.info(
            "Created failed branch: branch=%s loop=%s iteration=%d thread=%s reason=%s",
            branch_id,
            self.loop_id,
            iteration,
            thread_id,
            failure_reason,
        )

        # Return branch dict
        return {
            "branch_id": branch_id,
            "loop_id": self.loop_id,
            "iteration": iteration,
            "thread_id": thread_id,
            "root_checkpoint_id": root_checkpoint_id,
            "failure_checkpoint_id": failure_checkpoint_id,
            "failure_reason": failure_reason,
            "execution_path": execution_path,
            "created_at": datetime.now(UTC),
            "analyzed_at": None,
            "avoid_patterns": [],
            "suggested_adjustments": [],
        }

    async def find_retry_iteration_after_branch(
        self,
        branch_id: str,
    ) -> int | None:
        """Find retry iteration after failed branch.

        Args:
            branch_id: Failed branch identifier.

        Returns:
            Retry iteration number if retry happened, None otherwise.
        """
        branches = await self.persistence_manager.get_failed_branches_for_loop(self.loop_id)

        branch = None
        for b in branches:
            if b["branch_id"] == branch_id:
                branch = b
                break

        if not branch:
            return None

        # Check if next iteration exists (would be retry)
        next_iteration = branch["iteration"] + 1
        next_anchors = await self.persistence_manager.get_checkpoint_anchors_for_range(
            self.loop_id, next_iteration, next_iteration
        )

        if next_anchors:
            return next_iteration

        return None


__all__ = ["FailedBranchManager"]
