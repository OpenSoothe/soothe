"""Thread checkpoint forking for step inheritance (RFC-223).

This module provides ThreadForkManager which handles:
- Selecting fork source based on direct dependencies (singleton vs multi-dep)
- Executing checkpoint fork via LangGraph acopy_thread API
- Tracking step-to-thread and fork lineage mappings in LoopState

RFC-223: Singleton dependency steps fork from predecessor's checkpoint
to inherit full conversation history. Multi-dependency steps fork from
main thread and use message injection.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from soothe.core.loop.state.schemas import AgentDecision, LoopState, StepAction

logger = logging.getLogger(__name__)


class ThreadForkManager:
    """Manages thread checkpoint forking for step inheritance.

    RFC-223: Singleton dependency steps fork from predecessor's checkpoint
    to inherit full conversation history. Multi-dependency steps fork from
    main thread and use message injection.

    Args:
        checkpointer: LangGraph checkpointer for acopy_thread calls.
    """

    def __init__(self, checkpointer: BaseCheckpointSaver | None) -> None:
        """Initialize ThreadForkManager.

        Args:
            checkpointer: LangGraph checkpointer for acopy_thread calls.
        """
        self._checkpointer = checkpointer

    def select_fork_source(
        self,
        step: StepAction,
        decision: AgentDecision,
        state: LoopState,
    ) -> str:
        """Select source thread_id for checkpoint fork.

        Uses DIRECT dependencies only (not transitive closure):
        - No deps → main thread (loop_id)
        - Single dep → predecessor's step thread
        - Multiple deps → main thread (fallback)

        Args:
            step: Current step to execute.
            decision: Current decision with dependency information.
            state: Loop state with step_thread_ids mapping.

        Returns:
            Source thread_id to fork from.
        """
        # Use direct dependencies only (not transitive)
        # For chain A→B→C: C depends on B only → singleton, fork from B
        # For DAG A→C, B→C: C depends on [A, B] → multi-dep, fork from main
        direct_deps = step.dependencies or []

        # No direct dependencies → first step, fork from main
        if not direct_deps:
            return state.thread_id

        # Multiple direct dependencies → fork from main, use message injection
        if len(direct_deps) > 1:
            return state.thread_id

        # Singleton direct dependency → fork from predecessor's thread
        pred_step_id = direct_deps[0]
        pred_thread_id = state.step_thread_ids.get(pred_step_id)

        # Predecessor thread not tracked → fallback to main
        if not pred_thread_id:
            logger.debug(
                "Predecessor thread not found for step %s (dep: %s), using main thread",
                step.id,
                pred_step_id,
            )
            return state.thread_id

        return pred_thread_id

    async def fork_checkpoint(
        self,
        source_thread_id: str,
        target_thread_id: str,
    ) -> str:
        """Execute checkpoint fork from source to target thread.

        Calls LangGraph checkpointer.acopy_thread to copy full checkpoint
        history (messages, tool calls, artifacts) from source to target.

        Args:
            source_thread_id: Thread to copy checkpoint from.
            target_thread_id: Thread to copy checkpoint to.

        Returns:
            target_thread_id if successful, source_thread_id as fallback.
        """
        if not self._checkpointer:
            logger.debug("No checkpointer available, skipping fork")
            return source_thread_id

        try:
            await self._checkpointer.acopy_thread(source_thread_id, target_thread_id)
            logger.info(
                "Checkpoint forked: %s → %s",
                source_thread_id,
                target_thread_id,
            )
            return target_thread_id
        except Exception:
            logger.warning(
                "Checkpoint fork failed: %s → %s, proceeding without inheritance",
                source_thread_id,
                target_thread_id,
                exc_info=True,
            )
            return source_thread_id

    async def prepare_thread_for_step(
        self,
        step: StepAction,
        decision: AgentDecision,
        state: LoopState,
        main_thread_id: str,
    ) -> str:
        """Prepare thread for step execution (full preparation flow).

        Determines fork source, executes fork, and updates state mappings.

        Args:
            step: Step to execute.
            decision: Decision with dependency info.
            state: Loop state to update with mappings.
            main_thread_id: The loop's main thread_id (loop_id).

        Returns:
            Thread_id to use for CoreAgent stream.
        """
        # Determine source for fork
        source_thread_id = self.select_fork_source(step, decision, state)

        # Build target thread_id with __step_ prefix (RFC-223 naming)
        target_thread_id = f"{main_thread_id}__step_{step.id}"

        # Execute fork
        actual_thread_id = await self.fork_checkpoint(source_thread_id, target_thread_id)

        # Update state mappings
        state.step_thread_ids[step.id] = actual_thread_id
        state.thread_fork_sources[actual_thread_id] = source_thread_id

        logger.debug(
            "Thread prepared for step %s: source=%s target=%s actual=%s",
            step.id,
            source_thread_id,
            target_thread_id,
            actual_thread_id,
        )

        return actual_thread_id
