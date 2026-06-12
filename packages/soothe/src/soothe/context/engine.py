"""Context Engine — unified context management for goals, steps, and projection (RFC-624)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage

from soothe.context.ledger import LedgerManager
from soothe.context.models import (
    GoalNode,
    GoalStepDAG,
    StepExecution,
    StepNode,
)
from soothe.context.projection import ContextBundle, ProjectionConfig, ProjectionEngine
from soothe.context.semantic import SemanticLoader

logger = logging.getLogger(__name__)


class ContextEngine:
    """Unified context management for goals, steps, ledger, and projection.

    Composes GoalStepDAG, LedgerManager, SemanticLoader, ProjectionEngine,
    and a pluggable persistence backend into a single interface.

    Args:
        persistence: Persistence backend (defaults to InMemoryContextPersistence).
        projection_config: Limits for bounded projection.
        soothe_home: Base directory for SemanticLoader and FileContextPersistence.
        workspace: Working directory for SemanticLoader file lookup.
    """

    def __init__(
        self,
        persistence: Any | None = None,
        projection_config: ProjectionConfig | None = None,
        soothe_home: Path | None = None,
        workspace: Path | None = None,
    ) -> None:
        from soothe.context.persistence.in_memory import InMemoryContextPersistence

        self._dag = GoalStepDAG()
        self._ledger = LedgerManager()
        self._semantic = SemanticLoader(soothe_home=soothe_home, workspace=workspace)
        self._projection = ProjectionEngine(projection_config)
        self._persistence = persistence or InMemoryContextPersistence()

    # ── Goal management ──────────────────────────────────────────

    async def create_goal(
        self,
        description: str,
        *,
        priority: int = 50,
        parent_id: str | None = None,
        depends_on: list[str] | None = None,
        generating_reasoning: str | None = None,
        source: str = "user",
        **kwargs: Any,
    ) -> GoalNode:
        """Create a new goal and add it to the DAG.

        Args:
            description: Human-readable goal text.
            priority: Scheduling priority (0-100).
            parent_id: Optional parent goal ID.
            depends_on: Hard dependency goal IDs.
            generating_reasoning: Reasoning that produced this goal.
            source: Origin of the goal.

        Returns:
            The created GoalNode.

        Raises:
            ValueError: If depth limit exceeded or parent not found.
        """
        goal = GoalNode(
            description=description,
            priority=priority,
            parent_id=parent_id,
            depends_on=depends_on or [],
            generating_reasoning=generating_reasoning,
            source=source,
            **kwargs,
        )
        self._dag.add_goal(goal)
        logger.info('Created goal %s: "%s" (priority=%d)', goal.id, description, priority)
        return goal

    async def get_goal(self, goal_id: str) -> GoalNode | None:
        return self._dag.get_goal(goal_id)

    async def list_goals(self, status: str | None = None) -> list[GoalNode]:
        if status:
            return [g for g in self._dag.goals.values() if g.status == status]
        return list(self._dag.goals.values())

    async def activate_goal(self, goal_id: str, loop_id: str | None = None) -> None:
        """Transition a goal from pending to active.

        Args:
            goal_id: Goal to activate.
            loop_id: Optional loop_id to assign.

        Raises:
            ValueError: If goal not found or not in pending state.
        """
        goal = self._dag.get_goal(goal_id)
        if goal is None:
            msg = f"Goal {goal_id} not found"
            raise ValueError(msg)
        if goal.status != "pending":
            msg = f"Goal {goal_id} is {goal.status}, expected pending"
            raise ValueError(msg)
        goal.status = "active"
        goal.assigned_loop_id = loop_id
        goal.updated_at = datetime.now(UTC)
        logger.info("Activated goal %s (loop_id=%s)", goal_id, loop_id)

    async def complete_goal(self, goal_id: str) -> None:
        self._dag.complete_goal(goal_id)
        logger.info("Completed goal %s", goal_id)

    async def fail_goal(self, goal_id: str, error: str) -> None:
        self._dag.fail_goal(goal_id, error)
        logger.info("Failed goal %s: %s", goal_id, error)

    async def suspend_goal(self, goal_id: str, reason: str) -> None:
        self._dag.suspend_goal(goal_id, reason)
        logger.info("Suspended goal %s: %s", goal_id, reason)

    # ── Step management ──────────────────────────────────────────

    async def add_step(self, goal_id: str, step: StepNode) -> None:
        goal = self._dag.get_goal(goal_id)
        if goal is None:
            msg = f"Goal {goal_id} not found"
            raise KeyError(msg)
        goal.steps.add_step(step)

    async def add_steps(
        self,
        goal_id: str,
        steps: list[StepNode],
        plan_iteration: int = 0,
    ) -> None:
        """Batch-add steps from a plan result."""
        goal = self._dag.get_goal(goal_id)
        if goal is None:
            msg = f"Goal {goal_id} not found"
            raise KeyError(msg)
        for step in steps:
            step.plan_iteration = plan_iteration
            goal.steps.add_step(step)

    async def complete_step(
        self,
        goal_id: str,
        step_id: str,
        execution: StepExecution,
    ) -> None:
        goal = self._dag.get_goal(goal_id)
        if goal is None:
            return
        goal.steps.mark_completed(step_id, execution)
        goal.total_tokens_used += execution.tokens_used
        goal.updated_at = datetime.now(UTC)
        self._ledger.record_step_result(
            step_id=step_id,
            description=goal.steps.nodes[step_id].description
            if step_id in goal.steps.nodes
            else step_id,
            output=None,
            error=None,
            success=True,
        )

    async def fail_step(
        self,
        goal_id: str,
        step_id: str,
        execution: StepExecution,
    ) -> None:
        goal = self._dag.get_goal(goal_id)
        if goal is None:
            return
        goal.steps.mark_failed(step_id, execution)
        goal.total_tokens_used += execution.tokens_used
        goal.updated_at = datetime.now(UTC)
        self._ledger.record_step_result(
            step_id=step_id,
            description=goal.steps.nodes[step_id].description
            if step_id in goal.steps.nodes
            else step_id,
            output=None,
            error=execution.error,
            success=False,
        )

    # ── Ledger management ────────────────────────────────────────

    async def record_message(self, message: BaseMessage, phase: str) -> None:
        self._ledger.record_message(message, phase)

    async def get_ledger(self, phases: list[str] | None = None) -> list[BaseMessage]:
        return self._ledger.get_messages(phases)

    # ── Projection ───────────────────────────────────────────────

    async def project(self, goal_id: str | None = None) -> ContextBundle:
        """Build a bounded ContextBundle for prompt template rendering."""
        return await self._projection.project(
            dag=self._dag,
            ledger=self._ledger,
            semantic=self._semantic,
            goal_id=goal_id,
        )

    # ── Persistence ──────────────────────────────────────────────

    async def save(self) -> None:
        """Persist current DAG and ledger state."""
        try:
            await self._persistence.save_dag(self._dag)
            # Serialize ledger entries for persistence
            ledger_data: list[dict[str, Any]] = []
            for entry in self._ledger._entries:
                msg = entry.message
                ledger_data.append(
                    {
                        "type": type(msg).__name__,
                        "content": getattr(msg, "content", ""),
                        "phase": entry.phase,
                    }
                )
            await self._persistence.save_ledger(ledger_data)
        except Exception:
            logger.warning("Persistence save failed", exc_info=True)

    async def load(self) -> bool:
        """Load persisted state. Returns True if DAG was loaded."""
        try:
            dag = await self._persistence.load_dag()
            if dag is not None:
                self._dag = dag
            ledger_data = await self._persistence.load_ledger()
            if ledger_data:
                from langchain_core.messages import AIMessage, HumanMessage

                self._ledger.clear()
                for entry in ledger_data:
                    msg_type = entry.get("type", "HumanMessage")
                    content = entry.get("content", "")
                    phase = entry.get("phase")
                    if msg_type == "AIMessage":
                        msg = AIMessage(content=content)
                    else:
                        msg = HumanMessage(content=content)
                    self._ledger.record_message(msg, phase or "")
            return dag is not None
        except Exception:
            logger.warning("Persistence load failed", exc_info=True)
            return False

    # ── Recovery ─────────────────────────────────────────────────

    async def recover(self) -> list[str]:
        """Reset goals stuck in 'active' to 'pending' after crash."""
        return self._dag.recover_active_goals()
