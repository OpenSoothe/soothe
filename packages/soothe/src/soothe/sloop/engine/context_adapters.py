"""Context Engine goal context provider.

Provides ``ContextEngineGoalContextAdapter``, which exposes completed-goal
history to the Plan phase.  Goal data is read directly from the CE
GoalStepDAG via the ``ContextEngine`` public API; thread-switch detection
remains delegated to ``state_manager`` (outside CE's scope).
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.context.engine import ContextEngine

logger = logging.getLogger(__name__)


class ContextEngineGoalContextAdapter:
    """Exposes completed-goal history from ContextEngine to the Plan phase.

    Goal data is read from the GoalStepDAG via the ContextEngine public API.
    Thread-switch detection is delegated to ``state_manager`` (outside CE's
    scope); completed-goal data comes from the CE DAG.
    """

    def __init__(
        self,
        context_engine: ContextEngine,
        state_manager: Any,
        config: Any = None,
    ) -> None:
        self._ce = context_engine
        self._state_manager = state_manager
        self._config = config

    async def get_plan_context(self, limit: int | None = None) -> list[str]:
        """Get previous goal summaries for Plan phase (XML blocks).

        Reads completed goals from the CE GoalStepDAG.
        """
        if self._config is not None and not getattr(self._config, "enabled", True):
            return []

        try:
            if limit is not None:
                actual_limit = limit
            elif self._config:
                actual_limit = getattr(self._config, "plan_limit", 10)
            else:
                actual_limit = 10

            all_goals = self._ce.get_all_goals()
            completed = [g for g in all_goals if g.status == "completed"][-actual_limit:]

            if not completed:
                return []

            context_blocks = []
            for goal in completed:
                step_summary = self._render_step_summary(goal)
                context_block = (
                    f"<PREVIOUS_GOAL>\n"
                    f"Goal: {goal.description}\n"
                    f"Status: {goal.status}\n"
                    f"Output:\n{step_summary}\n"
                    f"</PREVIOUS_GOAL>"
                )
                context_blocks.append(context_block)

            logger.info(
                "CE Plan context: %d previous goals from CE DAG",
                len(context_blocks),
            )
            return context_blocks

        except Exception as e:
            logger.warning("CE GoalContextAdapter: failed to load plan context: %s", e)
            return []

    async def get_execute_briefing(self, limit: int | None = None) -> str | None:
        """Get goal briefing for Execute phase (only on thread switch).

        Thread switch detection still uses state_manager. Completed goal
        data comes from the CE DAG.
        """
        if self._config is not None and not getattr(self._config, "enabled", True):
            return None

        try:
            # Thread switch detection needs state_manager
            current_thread = ""
            if self._state_manager is not None:
                checkpoint = self._state_manager.get_checkpoint()
                if checkpoint is None:
                    checkpoint = await self._state_manager.load()
                if not checkpoint:
                    return None
                if not checkpoint.thread_switch_pending:
                    logger.debug(
                        "CE GoalContextAdapter: execute briefing skipped (no thread switch)"
                    )
                    return None
                checkpoint.thread_switch_pending = False
                await self._state_manager.save(checkpoint)
                current_thread = checkpoint.current_thread_id

            actual_limit = (
                limit or getattr(self._config, "execute_limit", 10) if self._config else 10
            )

            all_goals = self._ce.get_all_goals()
            completed = [g for g in all_goals if g.status == "completed"][-actual_limit:]

            if not completed:
                logger.warning(
                    "CE GoalContextAdapter: thread switch but no completed goals for briefing"
                )
                return None

            return _format_execute_briefing_from_ce_goals(completed, current_thread)

        except Exception as e:
            logger.error("CE GoalContextAdapter: failed to generate execute briefing: %s", e)
            return None

    @staticmethod
    def _render_step_summary(goal: Any) -> str:
        """Build a text summary from a GoalNode's completed steps."""
        if not hasattr(goal, "steps") or not goal.steps.nodes:
            return ""
        parts = []
        for sid in sorted(goal.steps.nodes.keys()):
            node = goal.steps.nodes[sid]
            if node.status == "completed":
                desc = (node.description or "").strip().replace("\n", " ")
                execution = node.execution
                if execution and execution.error:
                    parts.append(f"  - {sid}: {desc} (error: {execution.error})")
                else:
                    parts.append(f"  - {sid}: {desc}")
        return "\n".join(parts) if parts else ""


def _format_execute_briefing_from_ce_goals(goals: list, current_thread: str) -> str:
    """Format CE GoalNode objects as condensed Execute briefing."""
    sections = ["## Previous Goal Context (Thread Switch Recovery)\n\n"]

    for i, goal in enumerate(goals, 1):
        step_summary = ContextEngineGoalContextAdapter._render_step_summary(goal)
        sections.append(
            f"**Goal {i}** ({goal.status}):\n"
            f"Query: {goal.description}\n"
            f"Steps completed:\n{step_summary}\n\n"
        )

    sections.append(
        f"**Current thread**: {current_thread} (new thread, no conversation history)\n"
        f"**Instruction**: Use previous goal context to inform step execution strategy.\n"
        f"Reference critical files discovered in prior work. Avoid re-exploring solved problems."
    )

    return "".join(sections)
