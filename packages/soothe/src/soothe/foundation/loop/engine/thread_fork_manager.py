"""Thread checkpoint forking for step inheritance (RFC-223).

This module provides ``ThreadForkManager`` which handles:

- Selecting fork source based on direct dependencies (singleton vs multi-dep)
- Sole-child optimization: when a step is the only dependent of its
  predecessor, reuse the predecessor's thread directly instead of forking
  (saves the cost of copying every checkpoint row when there's no
  parallel sibling that would race on the namespace).
- Executing checkpoint fork via the in-house ``copy_thread_via_public_api``
  helper (LangGraph's stock savers don't implement ``acopy_thread``; we
  do the copy via their public ``alist`` + ``aput`` surface).
- Tracking step-to-thread and fork lineage mappings in ``LoopState``.

RFC-223 strategy summary:

| Direct deps | Predecessor's other dependents | Action                     |
|-------------|--------------------------------|----------------------------|
| 0           | n/a                            | use main thread            |
| 1           | 0 (sole child)                 | reuse predecessor's thread |
| 1           | ≥1 (has siblings)              | fork from predecessor      |
| ≥2          | n/a                            | use main thread + inject   |
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe.foundation.loop.engine.checkpoint_copy import copy_thread_via_public_api

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from soothe.foundation.loop.state.schemas import AgentDecision, LoopState, StepAction

logger = logging.getLogger(__name__)


def _count_dependents(predecessor_id: str, decision: AgentDecision) -> int:
    """Count how many steps in ``decision`` directly depend on ``predecessor_id``.

    Used by the sole-child optimization: when only one step depends on a
    given predecessor, that step can reuse the predecessor's thread
    directly without forking, because no sibling will race on the namespace.
    """
    count = 0
    for s in getattr(decision, "steps", None) or []:
        deps = getattr(s, "dependencies", None) or []
        if predecessor_id in deps:
            count += 1
    return count


class ThreadForkManager:
    """Manages thread checkpoint forking for step inheritance (RFC-223).

    Args:
        checkpointer: LangGraph checkpointer used for the in-house copy.
            When ``None``, all forks degrade to "use source thread directly".
    """

    def __init__(self, checkpointer: BaseCheckpointSaver | None) -> None:
        """Initialize ThreadForkManager.

        Args:
            checkpointer: LangGraph checkpointer used for checkpoint copy.
        """
        self._checkpointer = checkpointer

    def select_fork_source(
        self,
        step: StepAction,
        decision: AgentDecision,
        state: LoopState,
    ) -> tuple[str, bool]:
        """Select the source thread for a step and whether to fork.

        Returns:
            ``(source_thread_id, should_fork)``.

            ``should_fork=True`` means "allocate a new ``__step_<id>``
            target thread and copy ``source_thread_id``'s checkpoints into
            it." Used for no-deps (fork from empty main → fresh isolated
            namespace), multi-deps (fork from main → fresh, plus message
            injection elsewhere), and singleton-with-siblings (fork from
            predecessor so siblings don't race on its namespace).

            ``should_fork=False`` means "reuse ``source_thread_id`` as-is"
            — currently triggered ONLY by the sole-child singleton
            optimization: a step that's the only dependent of its
            predecessor inherits the predecessor's thread directly with
            no copy cost.
        """
        direct_deps = step.dependencies or []

        # No direct dependencies → fresh isolated thread sourced from main.
        if not direct_deps:
            return state.thread_id, True

        # Multiple direct dependencies → fresh isolated thread sourced
        # from main; caller injects predecessor messages separately.
        if len(direct_deps) > 1:
            return state.thread_id, True

        # Singleton dependency.
        pred_step_id = direct_deps[0]
        pred_thread_id = state.step_thread_ids.get(pred_step_id)

        # Predecessor thread wasn't tracked → fall back to main + fork.
        if not pred_thread_id:
            logger.debug(
                "Predecessor thread not found for step %s (dep: %s), using main thread",
                step.id,
                pred_step_id,
            )
            return state.thread_id, True

        # Sole-child optimization: when this step is the only dependent of
        # its predecessor, REUSE the predecessor's thread directly. No
        # sibling will race on the namespace and we save the copy cost.
        if _count_dependents(pred_step_id, decision) <= 1:
            logger.debug(
                "Sole-child reuse: step %s reusing predecessor %s's thread (no fork)",
                step.id,
                pred_step_id,
            )
            return pred_thread_id, False

        # Has at least one sibling — fork to keep histories independent.
        return pred_thread_id, True

    async def fork_checkpoint(
        self,
        source_thread_id: str,
        target_thread_id: str,
    ) -> str:
        """Copy ``source_thread_id``'s checkpoints under ``target_thread_id``.

        Uses the in-house ``copy_thread_via_public_api`` helper because no
        LangGraph saver implements ``acopy_thread`` natively. On failure,
        return ``source_thread_id`` as a fallback so the step can still run.

        Args:
            source_thread_id: Thread to copy checkpoints from.
            target_thread_id: Thread to copy checkpoints to.

        Returns:
            ``target_thread_id`` on success; ``source_thread_id`` on failure.
        """
        if not self._checkpointer:
            logger.debug("No checkpointer available, skipping fork")
            return source_thread_id

        if source_thread_id == target_thread_id:
            return target_thread_id

        try:
            count = await copy_thread_via_public_api(
                self._checkpointer, source_thread_id, target_thread_id
            )
        except Exception:
            # Real failures (DB errors, serialization issues, etc.) — keep
            # WARN+traceback so they're visible. Caller falls back to source.
            logger.warning(
                "Checkpoint fork failed: %s → %s, proceeding without inheritance",
                source_thread_id,
                target_thread_id,
                exc_info=True,
            )
            return source_thread_id

        logger.debug(
            "Checkpoint forked: %s → %s (%d checkpoint(s) copied)",
            source_thread_id,
            target_thread_id,
            count,
        )
        return target_thread_id

    async def prepare_thread_for_step(
        self,
        step: StepAction,
        decision: AgentDecision,
        state: LoopState,
        main_thread_id: str,
    ) -> str:
        """Pick + execute the fork strategy for one step.

        Args:
            step: Step about to execute.
            decision: Current decision (used for sibling-count optimization).
            state: Loop state to update with mappings.
            main_thread_id: The loop's main thread_id (= loop_id).

        Returns:
            The thread_id the step's CoreAgent should run under.
        """
        source_thread_id, should_fork = self.select_fork_source(step, decision, state)

        if not should_fork:
            # Reusing source thread directly — no copy, no new namespace.
            actual_thread_id = source_thread_id
            state.step_thread_ids[step.id] = actual_thread_id
            state.thread_fork_sources[actual_thread_id] = source_thread_id
            logger.debug(
                "Thread prepared for step %s: reusing source thread %s (no fork)",
                step.id,
                actual_thread_id,
            )
            return actual_thread_id

        # Build target thread_id with __step_ prefix (RFC-223 naming)
        target_thread_id = f"{main_thread_id}__step_{step.id}"
        actual_thread_id = await self.fork_checkpoint(source_thread_id, target_thread_id)

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
