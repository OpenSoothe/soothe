"""Context Engine — unified context management for goals, steps, and projection (RFC-624)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from soothe.context.ledger import LedgerManager
from soothe.context.models import (
    GoalNode,
    GoalStepDAG,
    GoalStepDAGSnapshot,
    StepDAG,
    StepExecution,
    StepNode,
)
from soothe.context.projection import ContextBundle, ProjectionConfig, ProjectionEngine
from soothe.context.semantic import SemanticLoader

logger = logging.getLogger(__name__)

EngineEvent = Literal[
    "goal_created",
    "goal_activated",
    "goal_completed",
    "goal_failed",
    "goal_suspended",
    "goal_cancelled",
    "goal_blocked",
    "goal_unblocked",
    "step_completed",
    "step_failed",
    "step_skipped",
]

_MESSAGE_TYPES: dict[str, type[BaseMessage]] = {
    "AIMessage": AIMessage,
    "HumanMessage": HumanMessage,
    "SystemMessage": SystemMessage,
    "ToolMessage": ToolMessage,
    "AIMessageChunk": AIMessageChunk,
    "LoopAIMessage": AIMessage,
    "LoopHumanMessage": HumanMessage,
}


def _reconstruct_message(type_name: str, data: dict[str, Any]) -> BaseMessage | None:
    """Reconstruct a BaseMessage from a serialized dict."""
    cls = _MESSAGE_TYPES.get(type_name)
    if cls is None:
        logger.warning("Unknown message type %s, skipping", type_name)
        return None
    try:
        return cls.model_validate(data)
    except Exception:
        content = data.get("content", "")
        logger.warning("Failed to reconstruct %s, using content-only fallback", type_name)
        return cls(content=content)


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
        self._callbacks: dict[str, list[Callable]] = {}

    # ── Callback mechanism ────────────────────────────────────────

    def on(self, event: EngineEvent, callback: Callable) -> None:
        """Register a callback for an event."""
        self._callbacks.setdefault(event, []).append(callback)

    def off(self, event: EngineEvent, callback: Callable) -> None:
        """Unregister a callback for an event."""
        callbacks = self._callbacks.get(event, [])
        if callback in callbacks:
            callbacks.remove(callback)

    def _fire(self, event: EngineEvent, *args: Any) -> None:
        """Fire all callbacks for an event, catching errors."""
        for cb in self._callbacks.get(event, []):
            try:
                cb(*args)
            except Exception:
                logger.warning("Callback error for event %s", event, exc_info=True)

    # ── Public read API ──────────────────────────────────────────

    def get_dag_snapshot(self) -> GoalStepDAGSnapshot:
        """Return a serializable snapshot of the full GoalStepDAG."""
        return self._dag.snapshot()

    def get_step_dag(self, goal_id: str) -> StepDAG | None:
        """Return the StepDAG for a goal (None if goal not found)."""
        goal = self._dag.get_goal(goal_id)
        return goal.steps if goal else None

    def get_ledger_entries(
        self, phases: list[str] | None = None
    ) -> list[tuple[BaseMessage, str | None]]:
        """Return (message, phase) tuples, optionally filtered by phase."""
        return self._ledger.entries(phases)

    def get_all_goals(self) -> list[GoalNode]:
        """Return all goals in the DAG."""
        return list(self._dag.goals.values())

    def get_goal_lineage(self, goal_id: str) -> list[str]:
        """Return chain of goal descriptions from root to this goal."""
        return self._dag.goal_lineage(goal_id)

    def get_goal_sync(self, goal_id: str) -> GoalNode | None:
        """Synchronous goal lookup (in-memory, no I/O)."""
        return self._dag.get_goal(goal_id)

    @property
    def ledger(self) -> LedgerManager:
        """Access the underlying LedgerManager for sync operations."""
        return self._ledger

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
        self._fire("goal_created", goal.id)
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
        self._fire("goal_activated", goal_id)

    async def complete_goal(self, goal_id: str) -> None:
        self._dag.complete_goal(goal_id)
        logger.info("Completed goal %s", goal_id)
        self._fire("goal_completed", goal_id)

    async def fail_goal(self, goal_id: str, error: str) -> None:
        self._dag.fail_goal(goal_id, error)
        logger.info("Failed goal %s: %s", goal_id, error)
        self._fire("goal_failed", goal_id, error)

    async def suspend_goal(self, goal_id: str, reason: str) -> None:
        self._dag.suspend_goal(goal_id, reason)
        logger.info("Suspended goal %s: %s", goal_id, reason)
        self._fire("goal_suspended", goal_id, reason)

    async def cancel_goal(self, goal_id: str) -> None:
        """Transition goal to cancelled (terminal state)."""
        self._dag.cancel_goal(goal_id)
        logger.info("Cancelled goal %s", goal_id)
        self._fire("goal_cancelled", goal_id)

    async def block_goal(self, goal_id: str) -> None:
        """Transition goal to blocked."""
        self._dag.block_goal(goal_id)
        logger.info("Blocked goal %s", goal_id)
        self._fire("goal_blocked", goal_id)

    async def unblock_goal(self, goal_id: str) -> None:
        """Transition goal from blocked back to pending."""
        self._dag.unblock_goal(goal_id)
        logger.info("Unblocked goal %s", goal_id)
        self._fire("goal_unblocked", goal_id)

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
        self._fire("step_completed", goal_id, step_id)

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
        self._fire("step_failed", goal_id, step_id)

    async def skip_step(self, goal_id: str, step_id: str) -> None:
        """Skip a pending step."""
        goal = self._dag.get_goal(goal_id)
        if goal is None:
            return
        goal.steps.mark_skipped(step_id)
        goal.updated_at = datetime.now(UTC)
        logger.info("Skipped step %s in goal %s", step_id, goal_id)
        self._fire("step_skipped", goal_id, step_id)

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
        """Persist current DAG and ledger state with full message fidelity."""
        try:
            await self._persistence.save_dag(self._dag)
            ledger_data: list[dict[str, Any]] = []
            for msg, phase in self._ledger.entries():
                dump = msg.model_dump()
                dump["_phase"] = phase
                dump["_msg_type"] = type(msg).__name__
                ledger_data.append(dump)
            await self._persistence.save_ledger(ledger_data)
        except Exception:
            logger.warning("Persistence save failed", exc_info=True)

    async def load(self) -> bool:
        """Load persisted state. Returns True if DAG was loaded.

        Handles both new format (full BaseMessage dump with _msg_type/_phase)
        and legacy format (type + content + phase only).
        """
        try:
            dag = await self._persistence.load_dag()
            if dag is not None:
                self._dag = dag
            ledger_data = await self._persistence.load_ledger()
            if ledger_data:
                self._ledger.clear()
                for entry_data in ledger_data:
                    # New format: has _msg_type key
                    if "_msg_type" in entry_data:
                        msg_type_name = entry_data.pop("_msg_type")
                        phase = entry_data.pop("_phase", None)
                        msg = _reconstruct_message(msg_type_name, entry_data)
                        if msg is not None:
                            self._ledger.record_message(msg, phase or "")
                    else:
                        # Legacy format: type + content + phase
                        msg_type = entry_data.get("type", "HumanMessage")
                        content = entry_data.get("content", "")
                        phase = entry_data.get("phase")
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
