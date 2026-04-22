"""Smart retry manager for learning-based retry execution.

Manages smart retry workflow: rewind to root checkpoint, inject learning
insights, and retry execution with adjustments applied.

RFC-611: AgentLoop Checkpoint Tree Architecture
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.core.event_catalog import custom_event
from soothe.core.event_constants import BRANCH_RETRY_STARTED

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

logger = logging.getLogger(__name__)


class SmartRetryManager:
    """Manager for smart retry with learning injection."""

    def __init__(self, loop_id: str) -> None:
        """Initialize smart retry manager.

        Args:
            loop_id: AgentLoop identifier.
        """
        self.loop_id = loop_id

    async def execute_smart_retry(
        self,
        branch: dict[str, Any],
        checkpointer: BaseCheckpointSaver,
        retry_iteration: int,
    ) -> None:
        """Rewind to root checkpoint and retry with learning.

        Args:
            branch: Failed branch with learning insights.
            checkpointer: LangGraph checkpointer.
            retry_iteration: Retry iteration number.
        """
        thread_id = branch["thread_id"]
        root_checkpoint_id = branch["root_checkpoint_id"]

        # Step 1: Restore CoreAgent to root checkpoint
        await self._restore_coreagent_checkpoint(
            thread_id=thread_id,
            checkpoint_id=root_checkpoint_id,
            checkpointer=checkpointer,
        )

        logger.info(
            "Restored checkpoint for smart retry: branch=%s thread=%s checkpoint=%s",
            branch["branch_id"],
            thread_id,
            root_checkpoint_id,
        )

        # Step 2: Emit branch retry event
        yield custom_event(
            {
                "type": BRANCH_RETRY_STARTED,
                "branch_id": branch["branch_id"],
                "retry_iteration": retry_iteration,
                "learning_applied": branch.get("suggested_adjustments", []),
            }
        )

        logger.info(
            "Emitted branch retry event: branch=%s retry_iteration=%d",
            branch["branch_id"],
            retry_iteration,
        )

        # Note: Actual retry execution happens in AgentLoop's execute_plan_phase_with_context()
        # This manager only handles checkpoint restoration and event emission

    async def _restore_coreagent_checkpoint(
        self,
        thread_id: str,
        checkpoint_id: str,
        checkpointer: BaseCheckpointSaver,
    ) -> None:
        """Restore CoreAgent to specific checkpoint.

        Args:
            thread_id: Thread identifier.
            checkpoint_id: Target checkpoint ID.
            checkpointer: LangGraph checkpointer.
        """
        # LangGraph checkpoint restoration via aput()
        # Load checkpoint tuple and restore

        config = {"configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}}

        # Load checkpoint data
        checkpoint_tuple = await checkpointer.aget_tuple(config)

        if not checkpoint_tuple:
            logger.warning(
                "Checkpoint %s not found for thread %s, cannot restore",
                checkpoint_id,
                thread_id,
            )
            return

        # Restore checkpoint using aput() (creates new checkpoint from old state)
        await checkpointer.aput(
            config=config,
            checkpoint=checkpoint_tuple.checkpoint,
            metadata=checkpoint_tuple.metadata,
            new_versions={},  # No new versions (restoring existing)
        )

        logger.debug(
            "Restored checkpoint: thread=%s checkpoint=%s",
            thread_id,
            checkpoint_id,
        )

    def build_retry_context(
        self,
        branch: dict[str, Any],
    ) -> dict[str, Any]:
        """Build retry context for Plan phase injection.

        Args:
            branch: Failed branch with learning insights.

        Returns:
            Retry context dictionary for Plan phase.
        """
        return {
            "previous_failure": {
                "reason": branch.get("failure_reason", ""),
                "avoid_patterns": branch.get("avoid_patterns", []),
                "suggested_adjustments": branch.get("suggested_adjustments", []),
            },
            "retry_mode": True,
            "learning_applied": branch.get("suggested_adjustments", []),
            "branch_id": branch.get("branch_id", ""),
        }


__all__ = ["SmartRetryManager"]
