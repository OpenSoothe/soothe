"""Context Engine adapters bridging CE to existing AgentLoop interfaces (RFC-624 Phase 3).

Two adapter classes wrap `ContextEngine` to present identical interfaces to
existing code, ensuring 100% behavioral equivalence when the ContextEngine path
is enabled:

- `ContextEngineLedgerAdapter` → mirrors ledger writes to both `loop_messages` and `LedgerManager`
- `ContextEngineGoalContextAdapter` → satisfies `GoalContextManager` interface

Note: `ContextEnginePlanAdapter` has been replaced by `StepPlanManagerAdapter`
in `soothe.context.planning` (RFC-624 Phase 3c), which delegates to
`StepPlanningSubengine` instead of duplicating heuristic logic.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.context.engine import ContextEngine

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ContextEngineLedgerAdapter:
    """Mirrors ledger writes to both `LoopState.loop_messages` and `LedgerManager`.

    Every append to `loop_messages` is also recorded in `LedgerManager` with
    the correct phase tag. `project_loop_messages_for_plan()` continues to work
    on the native `loop_messages` list — the adapter doesn't change how the
    ledger is consumed by PromptBuilder.

    LedgerManager serves as the persistence/recovery path; `loop_messages`
    remains the real-time prompt path.
    """

    def __init__(self, context_engine: ContextEngine) -> None:
        self._ce = context_engine

    def record_message(
        self,
        message: Any,
        phase: str,
        loop_messages: list[Any],
    ) -> None:
        """Mirror a message to both loop_messages and LedgerManager.

        Args:
            message: The message to record.
            phase: Phase tag (e.g., "execute_step", "plan_assess", "plan_generate").
            loop_messages: The LoopState.loop_messages list to append to.
        """
        loop_messages.append(message)

        from langchain_core.messages import BaseMessage

        if isinstance(message, BaseMessage):
            self._ce.ledger.record_message(message, phase)


class ContextEngineGoalContextAdapter:
    """Wraps ContextEngine to provide the same interfaces as GoalContextManager.

    Reads goal history from the GoalStepDAG (via ContextEngine public API)
    instead of AgentLoopStateManager, producing identical XML blocks for plan
    context and execute briefings.

    Thread switch detection still uses state_manager (that concern is outside
    CE's scope), but completed goal data comes from the CE DAG.
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

        Reads completed goals from the CE GoalStepDAG. Falls back to
        state_manager if CE has no completed goals.
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

            # Primary: read from CE DAG
            all_goals = self._ce.get_all_goals()
            completed = [g for g in all_goals if g.status == "completed"][-actual_limit:]

            if not completed:
                # Fallback to state_manager if CE has no completed goals
                if self._state_manager is not None:
                    checkpoint = await self._state_manager.load()
                    if checkpoint and checkpoint.goal_history:
                        current_thread = checkpoint.current_thread_id
                        completed_goals = [
                            g
                            for g in checkpoint.goal_history
                            if g.thread_id == current_thread and g.status == "completed"
                        ][-actual_limit:]
                        if completed_goals:
                            context_blocks = []
                            for goal in completed_goals:
                                context_block = (
                                    f"<previous_goal>\n"
                                    f"Goal: {goal.goal_text}\n"
                                    f"Status: {goal.status}\n"
                                    f"Thread: {goal.thread_id}\n"
                                    f"Output:\n{goal.goal_completion}\n"
                                    f"</previous_goal>"
                                )
                                context_blocks.append(context_block)
                            return context_blocks
                return []

            context_blocks = []
            for goal in completed:
                step_summary = self._render_step_summary(goal)
                context_block = (
                    f"<previous_goal>\n"
                    f"Goal: {goal.description}\n"
                    f"Status: {goal.status}\n"
                    f"Output:\n{step_summary}\n"
                    f"</previous_goal>"
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
            # Thread switch detection still needs state_manager
            current_thread = ""
            if self._state_manager is not None:
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

            # Read completed goals from CE DAG
            all_goals = self._ce.get_all_goals()
            completed = [g for g in all_goals if g.status == "completed"][-actual_limit:]

            if not completed:
                # Fallback to state_manager if CE has no completed goals
                if self._state_manager is not None:
                    checkpoint = await self._state_manager.load()
                    if checkpoint and checkpoint.goal_history:
                        previous_goals = [
                            g for g in checkpoint.goal_history if g.status == "completed"
                        ][-actual_limit:]
                        if previous_goals:
                            from soothe.foundation.loop.engine.goal_context_manager import (
                                format_execute_briefing_from_goals,
                            )

                            return format_execute_briefing_from_goals(
                                previous_goals, current_thread
                            )
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
    """Format CE GoalNode objects as condensed Execute briefing.

    Parallel to ``format_execute_briefing_from_goals()`` but works with
    GoalNode objects instead of GoalExecutionRecord.
    """
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
