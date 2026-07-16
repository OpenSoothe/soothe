"""Context Engine — unified context management for goals, steps, and projection (RFC-624, RFC-625)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from soothe.foundation.context.ledger import LedgerManager
from soothe.foundation.context.models import (
    EpisodeSummary,
    EvidenceEntry,
    GoalNode,
    GoalStatus,
    GoalStepDAG,
    GoalStepDAGSnapshot,
    StepDAG,
    StepExecution,
    StepNode,
)
from soothe.foundation.context.projection import ContextBundle, ProjectionConfig, ProjectionEngine
from soothe.foundation.context.semantic import SemanticLoader

if TYPE_CHECKING:
    pass

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


def _normalize_ledger_entry(
    entry_data: dict[str, Any],
) -> tuple[str, dict[str, Any], str | None]:
    """Normalize persisted ledger rows to the current ``_msg_type`` wire shape.

    Pre-RFC-624 rows stored ``type``, ``content``, and ``phase`` only. They are
    upgraded on read so ``load()`` uses a single reconstruction path.
    """
    entry = dict(entry_data)
    if "_msg_type" in entry:
        msg_type_name = str(entry.pop("_msg_type"))
        phase = entry.pop("_phase", None)
        return msg_type_name, entry, phase

    msg_type_name = str(entry.pop("type", "HumanMessage"))
    phase = entry.pop("phase", None)
    content = entry.pop("content", "")
    return msg_type_name, {"content": content}, phase


class ContextEngine:
    """Unified context management for goals, steps, ledger, and projection.

    Composes GoalStepDAG, LedgerManager, SemanticLoader, ProjectionEngine,
    and a pluggable persistence backend into a single interface.

    Args:
        persistence: Persistence backend. Defaults to an in-memory SQLite
            instance suitable for tests; production code should supply an
            explicit backend (SQLite or pgsql).
        projection_config: Limits for bounded projection.
        soothe_home: Base directory for SemanticLoader and context persistence backends.
        workspace: Working directory for SemanticLoader file lookup.
    """

    def __init__(
        self,
        persistence: Any | None = None,
        projection_config: ProjectionConfig | None = None,
        soothe_home: Path | None = None,
        workspace: Path | None = None,
    ) -> None:
        if persistence is None:
            from soothe.foundation.context.persistence.sqlite_backend import (
                SqliteContextPersistence,
            )

            persistence = SqliteContextPersistence(loop_id="default", db_path=Path(":memory:"))

        self._dag = GoalStepDAG()
        # Preserve full ledger history for downstream LLM calls unless a caller
        # explicitly sets a positive cap on LedgerManager.
        self._ledger = LedgerManager(max_entries=0)
        self._semantic = SemanticLoader(soothe_home=soothe_home, workspace=workspace)
        self._projection = ProjectionEngine(projection_config)
        self._persistence = persistence
        self._callbacks: dict[str, list[Callable]] = {}
        self._save_dirty = False
        self.execute_ai_ledger_max_tokens: int = 0

        # Planning submodule (RFC-624 Phase 3c)
        from soothe.foundation.context.planning import (
            GoalPlanningSubengine,
            GoalScheduler,
            PlanningFacade,
            StepPlanningSubengine,
        )

        self._step_planner = StepPlanningSubengine(self._dag)
        self._goal_planner = GoalPlanningSubengine(self._dag)
        self._scheduler = GoalScheduler(self._dag)
        self._planning_facade = PlanningFacade(
            step=self._step_planner,
            goal=self._goal_planner,
            scheduler=self._scheduler,
        )

    def _rebind_planning_subengines(self) -> None:
        """Rebind planning sub-engines to the current DAG instance.

        Called after ``load()`` replaces ``self._dag`` with a persisted instance.
        The sub-engines hold a reference to the DAG at construction time;
        replacing ``self._dag`` without rebinding leaves them pointing to an
        orphan DAG that doesn't contain newly created goals.
        """
        from soothe.foundation.context.planning import (
            GoalPlanningSubengine,
            GoalScheduler,
            PlanningFacade,
            StepPlanningSubengine,
        )

        self._step_planner = StepPlanningSubengine(self._dag)
        self._goal_planner = GoalPlanningSubengine(self._dag)
        self._scheduler = GoalScheduler(self._dag)
        self._planning_facade = PlanningFacade(
            step=self._step_planner,
            goal=self._goal_planner,
            scheduler=self._scheduler,
        )
        logger.debug(
            "Rebound planning sub-engines to DAG (goals=%d)",
            len(self._dag.goals),
        )

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

    @property
    def planning(self):
        """Access the planning submodule (step, goal, scheduler)."""
        return self._planning_facade

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
        max_iterations: int = 0,
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
            max_iterations: Maximum loop iterations for this goal.

        Returns:
            The created GoalNode.

        Raises:
            ValueError: If depth limit exceeded or parent not found.
        """
        # Filter None values from kwargs to avoid validation errors on list fields
        filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}
        goal = GoalNode(
            description=description,
            priority=priority,
            parent_id=parent_id,
            depends_on=depends_on or [],
            generating_reasoning=generating_reasoning,
            source=source,
            max_iterations=max_iterations,
            **filtered_kwargs,
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

    async def fail_goal(
        self,
        goal_id: str,
        error: str | None = None,
        *,
        evidence: Any | None = None,
    ) -> None:
        """Transition goal to failed.

        Args:
            goal_id: Goal to fail.
            error: Error message string.
            evidence: Optional evidence bundle for structured failure info.
        """
        error_msg = error or (evidence.narrative if evidence else "unknown error")
        self._dag.fail_goal(goal_id, error_msg)
        logger.info("Failed goal %s: %s", goal_id, error_msg)
        self._fire("goal_failed", goal_id, error_msg)

    async def suspend_goal(self, goal_id: str, reason: str) -> None:
        self._dag.suspend_goal(goal_id, reason)
        logger.info("Suspended goal %s: %s", goal_id, reason)
        self._fire("goal_suspended", goal_id, reason)

    async def cancel_goal(self, goal_id: str, *, reason: str = "user_cancelled") -> None:
        """Transition goal to cancelled (terminal state).

        Args:
            goal_id: Goal to cancel.
            reason: Cancellation reason for logging/events.
        """
        self._dag.cancel_goal(goal_id)
        logger.info("Cancelled goal %s: %s", goal_id, reason)
        self._fire("goal_cancelled", goal_id, reason)

    def collect_subtree_ids(self, root_id: str) -> list[str]:
        """Return ``root_id`` and descendants (deepest-first). See GoalStepDAG."""
        return self._dag.collect_subtree_ids(root_id)

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

    async def finalize_goal(self, goal_id: str, *, status: str = "completed") -> None:
        """Finalize a goal: set terminal status and reset per-goal mutable state.

        Unlike ``complete_goal`` which only sets status, finalize also
        accumulates duration/tokens from steps and clears per-goal
        execution state while preserving the step DAG for projection.

        Args:
            goal_id: Goal to finalize.
            status: Terminal status (``"completed"`` or ``"failed"``).
        """
        goal = self._dag.get_goal(goal_id)
        if goal is None:
            return
        # Duration/tokens already accumulated incrementally in complete_step/fail_step
        goal.status = status
        goal.updated_at = datetime.now(UTC)
        logger.info("Finalized goal %s (status=%s)", goal_id, status)

    def record_action(self, goal_id: str, action: str) -> None:
        """Append an action description to the goal's action history."""
        goal = self._dag.get_goal(goal_id)
        if goal is not None:
            goal.action_history.append(action)

    def increment_iteration(self, goal_id: str) -> int:
        """Increment the iteration count for a goal (RFC-624 Phase 4 Step 4).

        Called by ``record_iteration`` after each iteration checkpoint is persisted.
        Returns the new iteration value.

        Args:
            goal_id: Goal whose iteration to increment.

        Returns:
            New iteration_count value (after increment).
        """
        goal = self._dag.get_goal(goal_id)
        if goal is None:
            logger.warning("increment_iteration called on missing goal %s", goal_id)
            return 0
        goal.iteration_count += 1
        goal.touch()
        return goal.iteration_count

    def record_evidence(
        self,
        goal_id: str,
        evidence_id: str,
        summary: str,
        kind: str = "tool",
    ) -> None:
        """Append an evidence entry to the goal's evidence ledger.

        Args:
            goal_id: Goal to update.
            evidence_id: Stable identifier for the evidence.
            summary: Compact summary text for prompts/validation.
            kind: Provenance classification ("tool", "bootstrap", "ledger").
        """
        goal = self._dag.get_goal(goal_id)
        if goal is None:
            logger.warning("record_evidence called on missing goal %s", goal_id)
            return
        entry = EvidenceEntry(evidence_id=evidence_id, summary=summary, kind=kind)
        goal.evidence_ledger.append(entry)
        goal.touch()

    def get_iteration(self, goal_id: str) -> int:
        """Get current iteration count for a goal.

        Args:
            goal_id: Goal to query.

        Returns:
            Current iteration_count, or 0 if goal not found.
        """
        goal = self._dag.get_goal(goal_id)
        return goal.iteration_count if goal is not None else 0

    def set_previous_plan(self, goal_id: str, plan: Any) -> None:
        """Store the previous plan result on the goal node."""
        goal = self._dag.get_goal(goal_id)
        if goal is not None:
            goal.previous_plan = (
                plan.model_dump(mode="json") if hasattr(plan, "model_dump") else plan
            )

    def set_last_assessment(
        self,
        goal_id: str,
        assessment: Any,
        *,
        iteration: int,
    ) -> None:
        """Overwrite per-goal assess audit snapshot (RFC-624, IG-557)."""
        goal = self._dag.get_goal(goal_id)
        if goal is not None:
            goal.last_assessment = (
                assessment.model_dump(mode="json")
                if hasattr(assessment, "model_dump")
                else assessment
            )
            goal.last_assessment_iteration = iteration
            goal.touch()

    def set_last_gap_analysis(
        self,
        goal_id: str,
        gap: Any,
        *,
        iteration: int,
    ) -> None:
        """Overwrite per-goal gap analysis audit snapshot (IG-557)."""
        goal = self._dag.get_goal(goal_id)
        if goal is not None:
            goal.last_gap_analysis = (
                gap.model_dump(mode="json") if hasattr(gap, "model_dump") else gap
            )
            goal.touch()
            _ = iteration

    # ── RFC-625: Monitor-required methods ────────────────────────────────

    async def remove_goal(self, goal_id: str) -> bool:
        """Remove a goal from the DAG. Validates no dependents.

        Returns True if removed, False if goal not found or has dependents.
        """
        return self._dag.remove_goal(goal_id)

    async def merge_goals(
        self, goal_ids: list[str], merged_description: str, merged_id: str | None = None
    ) -> GoalNode | None:
        """Merge multiple goals into a single consolidated goal.

        Preserves union of dependencies, informs, and findings.
        Returns new merged goal, or None if any goal not found.
        """
        return self._dag.merge_goals(goal_ids, merged_description, merged_id)

    def is_dag_complete(self) -> bool:
        """Check if all goals in DAG are in terminal states."""
        return self._dag.is_dag_complete()

    def get_goals_by_status(self, status: GoalStatus | None = None) -> list[GoalNode]:
        """Filter goals by status (None = all goals)."""
        return self._dag.get_goals_by_status(status)

    def get_goal_dependents(self, goal_id: str) -> list[str]:
        """Get all goal IDs that depend on this goal."""
        return self._dag.get_goal_dependents(goal_id)

    async def update_dependencies(self, goal_id: str, depends_on: list[str]) -> None:
        """Update goal dependencies (for mode switch flattening)."""
        self._dag.update_dependencies(goal_id, depends_on)

    # ── Episodic memory (RFC-625 dreaming) ────────────────────────────────

    _episodic_memory: list[EpisodeSummary] = []

    async def record_episodic_memory(self, episodes: list[EpisodeSummary]) -> None:
        """Store distilled episodic memory from dreaming."""
        self._episodic_memory.extend(episodes)
        logger.info("Recorded %d episodic memory entries", len(episodes))

    # ── Scheduler methods (RFC-222, RFC-625) ────────────────────────────────

    def peek_ready_goals(self, limit: int = 1) -> list[GoalNode]:
        """Return ready candidates without mutation (read-only).

        Delegates to GoalStepDAG.peek_ready_goals for scheduler
        capacity planning. Goals are eligible when:
        - status == "pending"
        - all dependencies in TERMINAL_STATES
        - no conflicts_with goals are active

        Args:
            limit: Max goals to return.

        Returns:
            List of ready GoalNodes, sorted by (-priority, created_at).
        """
        return self._scheduler.peek_ready_goals(limit)

    def claim_goal(self, goal_id: str, loop_id: str | None = None) -> GoalNode | None:
        """Atomically transition goal to active (dispatch claim).

        Used by AutopilotService after peek_ready_goals selected a
        candidate and a loop was assigned. Re-checks conflicts at
        claim time to prevent race conditions.

        Args:
            goal_id: Goal to claim.
            loop_id: Optional loop_id to stamp on the goal.

        Returns:
            GoalNode if claimed, None if ineligible or conflict appeared.
        """
        goal = self._scheduler.claim_goal(goal_id, loop_id=loop_id)
        if goal is not None:
            self._fire("goal_activated", goal_id)
        return goal

    # ── RFC-204 consensus methods ───────────────────────────────────────────

    async def send_back_goal(self, goal_id: str, reason: str = "") -> GoalNode:
        """Return goal to pending after consensus rejection.

        Increments send_back_count. When budget exhausted, suspends instead.

        Args:
            goal_id: Goal to send back.
            reason: Consensus reasoning for the send-back.

        Returns:
            The updated GoalNode.

        Raises:
            KeyError: If goal not found.
        """
        goal = self._dag.get_goal(goal_id)
        if goal is None:
            raise KeyError(f"Goal {goal_id} not found")

        goal.send_back_count += 1
        if goal.send_back_count >= goal.max_send_backs:
            await self.suspend_goal(goal_id, reason=reason or "send_back budget exhausted")
            return goal

        goal.status = "pending"
        goal.assigned_loop_id = None
        goal.updated_at = datetime.now(UTC)
        logger.info(
            "Sent goal %s back for rework (send_back %d/%d): %s",
            goal_id,
            goal.send_back_count,
            goal.max_send_backs,
            reason,
        )
        self._fire("goal_suspended", goal_id, reason)  # Use existing event
        return goal

    async def validate_goal(self, goal_id: str) -> GoalNode:
        """Mark goal as validated (Layer 3 accepted completion).

        Args:
            goal_id: Goal to validate.

        Returns:
            The updated GoalNode.

        Raises:
            KeyError: If goal not found.
        """
        goal = self._dag.get_goal(goal_id)
        if goal is None:
            raise KeyError(f"Goal {goal_id} not found")
        goal.status = "validated"
        goal.updated_at = datetime.now(UTC)
        logger.info("Validated goal %s", goal_id)
        self._fire("goal_completed", goal_id)  # validated is a completion form
        return goal

    async def reactivate_goal(self, goal_id: str) -> GoalNode:
        """Reactivate a suspended/blocked goal back to pending.

        Args:
            goal_id: Goal to reactivate.

        Returns:
            The updated GoalNode.

        Raises:
            KeyError: If goal not found.
            ValueError: If goal is not suspended/blocked.
        """
        goal = self._dag.get_goal(goal_id)
        if goal is None:
            raise KeyError(f"Goal {goal_id} not found")
        if goal.status not in ("suspended", "blocked"):
            raise ValueError(f"Goal {goal_id} is {goal.status}, not suspended/blocked")
        old = goal.status
        goal.status = "pending"
        goal.send_back_count = 0  # Reset send-back budget
        goal.updated_at = datetime.now(UTC)
        logger.info("Reactivated goal %s (was %s)", goal_id, old)
        self._fire("goal_unblocked", goal_id)
        return goal

    # ── RFC-204 Group C directives ──────────────────────────────────────────

    async def apply_directives(
        self,
        directives: list[Any],  # GoalDirective type
        source_goal_id: str,
    ) -> list[str]:
        """Apply goal directives from GoalCompletionChunk.

        Handles six directive actions:
        - create: Create new goal with parent_id defaulting to source_goal_id
        - adjust_priority: Update goal.priority (clamped to 0-100)
        - add_dependency: Extend goal.depends_on (deduplicated)
        - fail: Transition goal to failed state
        - complete: Transition goal to completed state
        - decompose: Log warning (future work)

        Args:
            directives: List of GoalDirective to apply.
            source_goal_id: Goal that emitted these directives (for parent_id default).

        Returns:
            List of newly created goal IDs.
        """
        created_ids: list[str] = []

        for d in directives:
            try:
                action = getattr(d, "action", None)
                if action == "create":
                    parent = getattr(d, "parent_id", None) or source_goal_id
                    priority = getattr(d, "priority", 50) or 50
                    priority = max(0, min(100, priority))

                    new_goal = await self.create_goal(
                        description=getattr(d, "description", ""),
                        priority=priority,
                        parent_id=parent,
                        depends_on=list(getattr(d, "depends_on", []) or []),
                    )
                    created_ids.append(new_goal.id)
                    logger.info(
                        "Directive created goal %s (parent=%s, priority=%d)",
                        new_goal.id,
                        parent,
                        priority,
                    )

                elif action == "adjust_priority":
                    goal_id = getattr(d, "goal_id", None)
                    if goal_id:
                        goal = self._dag.get_goal(goal_id)
                        if goal:
                            new_priority = max(
                                0, min(100, getattr(d, "priority", goal.priority) or goal.priority)
                            )
                            old_priority = goal.priority
                            goal.priority = new_priority
                            goal.updated_at = datetime.now(UTC)
                            logger.info(
                                "Directive adjusted goal %s priority: %d → %d",
                                goal_id,
                                old_priority,
                                new_priority,
                            )

                elif action == "add_dependency":
                    goal_id = getattr(d, "goal_id", None)
                    if goal_id:
                        goal = self._dag.get_goal(goal_id)
                        if goal:
                            new_deps = list(getattr(d, "depends_on", []) or [])
                            for dep_id in new_deps:
                                if dep_id not in goal.depends_on:
                                    goal.depends_on.append(dep_id)
                            goal.updated_at = datetime.now(UTC)
                            logger.info(
                                "Directive added dependencies to goal %s: %s",
                                goal_id,
                                new_deps,
                            )

                elif action == "fail":
                    goal_id = getattr(d, "goal_id", None)
                    if goal_id:
                        await self.fail_goal(
                            goal_id,
                            error=getattr(d, "rationale", "Directive-fail") or "Directive-fail",
                        )
                        logger.info("Directive marked goal %s as failed", goal_id)

                elif action == "complete":
                    goal_id = getattr(d, "goal_id", None)
                    if goal_id:
                        await self.complete_goal(goal_id)
                        logger.info("Directive marked goal %s as completed", goal_id)

                elif action == "decompose":
                    logger.warning(
                        "Directive 'decompose' not implemented (goal %s): %s",
                        getattr(d, "goal_id", ""),
                        getattr(d, "description", ""),
                    )

            except Exception:
                logger.warning(
                    "Directive application failed (action=%s): %s",
                    getattr(d, "action", ""),
                    exc_info=True,
                )

        return created_ids

    # ── RFC-622 clarification ───────────────────────────────────────────────

    async def mark_awaiting_clarification(
        self,
        goal_id: str,
        pending_clarification: dict[str, Any],
        reason: str = "",
    ) -> GoalNode:
        """Pause a goal until out-of-band clarification arrives.

        Args:
            goal_id: Goal to pause.
            pending_clarification: Serialized ClarificationRequest to persist.
            reason: Audit string.

        Returns:
            The updated GoalNode.

        Raises:
            KeyError: If goal not found.
        """
        goal = self._dag.get_goal(goal_id)
        if goal is None:
            raise KeyError(f"Goal {goal_id} not found")
        goal.status = "awaiting_clarification"
        goal.pending_clarification = pending_clarification
        goal.assigned_loop_id = None
        goal.updated_at = datetime.now(UTC)
        logger.info(
            "[ClarificationRelay] goal %s -> awaiting_clarification: %s",
            goal_id,
            reason,
        )
        self._fire("goal_blocked", goal_id)
        return goal

    async def answer_clarification(
        self,
        goal_id: str,
        answers: list[str],
    ) -> GoalNode:
        """Resume goal with clarification answers.

        Clears pending_clarification and transitions back to pending.

        Args:
            goal_id: Goal currently in awaiting_clarification.
            answers: Answers to consume on re-entry.

        Returns:
            The updated GoalNode.

        Raises:
            KeyError: If goal not found.
            ValueError: If goal not awaiting clarification.
        """
        goal = self._dag.get_goal(goal_id)
        if goal is None:
            raise KeyError(f"Goal {goal_id} not found")
        if goal.status != "awaiting_clarification":
            raise ValueError(
                f"Goal {goal_id} is not awaiting clarification (status={goal.status!r})"
            )
        pending = goal.pending_clarification or {}
        pending["answers"] = list(answers)
        goal.pending_clarification = pending
        goal.status = "pending"
        goal.updated_at = datetime.now(UTC)
        logger.info(
            "[ClarificationRelay] goal %s clarification answered (%d answers)",
            goal_id,
            len(answers),
        )
        self._fire("goal_unblocked", goal_id)
        return goal

    # ── RFC-228 guidance ─────────────────────────────────────────────────────

    def absorb_guidance(
        self,
        goal_id: str,
        guidance_text: str,
        scope: str = "goal",
    ) -> bool:
        """Absorb user guidance from desktop LOR.

        Accumulates guidance for use in next reasoning cycle.

        Args:
            goal_id: Target goal ID.
            guidance_text: User's guidance/instruction.
            scope: "goal" for specific, "job" for root (full DAG).

        Returns:
            True if absorbed, False if goal not found.
        """
        goal = self._dag.get_goal(goal_id)
        if goal is None:
            logger.warning("[Guidance] Goal %s not found", goal_id)
            return False

        guidance_entry = {
            "text": guidance_text,
            "timestamp": datetime.now(UTC).isoformat(),
            "scope": scope,
        }
        goal.guidance_accumulated.append(guidance_entry)
        goal.updated_at = datetime.now(UTC)
        logger.info(
            "[Guidance] Absorbed guidance for goal %s (scope=%s): %s",
            goal_id,
            scope,
            guidance_text[:50],
        )
        return True

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
        goal.total_duration_ms += execution.duration_ms
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
        goal.total_duration_ms += execution.duration_ms
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

    def defer_save(self) -> None:
        """Mark CE state dirty without writing to disk (coalesce until ``save``)."""
        self._save_dirty = True

    async def save(self) -> None:
        """Persist current DAG and ledger state with full message fidelity."""
        await self._persist_now()
        self._save_dirty = False

    def persistence_snapshot(self) -> tuple[Any, list[dict[str, Any]]]:
        """Return DAG and ledger payloads for unified goal-boundary persist."""
        ledger_data: list[dict[str, Any]] = []
        for msg, phase in self._ledger.entries():
            dump = msg.model_dump()
            dump["_phase"] = phase
            dump["_msg_type"] = type(msg).__name__
            ledger_data.append(dump)
        return self._dag, ledger_data

    async def _persist_now(self) -> None:
        """Write DAG and ledger to the persistence backend."""
        try:
            dag, ledger_data = self.persistence_snapshot()
            await self._persistence.save_dag(dag)
            await self._persistence.save_ledger(ledger_data)
        except Exception:
            logger.warning("Persistence save failed", exc_info=True)

    async def load(self) -> bool:
        """Load persisted state. Returns True if DAG was loaded."""
        try:
            dag = await self._persistence.load_dag()
            if dag is not None:
                self._dag = dag
                # Rebind planning sub-engines to the new DAG instance.
                # The sub-engines hold a reference to the old DAG at construction;
                # without rebinding, they would look up goals in an orphan DAG.
                self._rebind_planning_subengines()
            ledger_data = await self._persistence.load_ledger()
            if ledger_data:
                self._ledger.clear()
                for entry_data in ledger_data:
                    msg_type_name, payload, phase = _normalize_ledger_entry(entry_data)
                    msg = _reconstruct_message(msg_type_name, payload)
                    if msg is not None:
                        self._ledger.record_message(msg, phase or "")
            return dag is not None
        except Exception:
            logger.warning("Persistence load failed", exc_info=True)
            return False

    # ── Recovery ─────────────────────────────────────────────────

    async def recover(self) -> list[str]:
        """Reset goals stuck in 'active' to 'pending' after crash."""
        return self._dag.recover_active_goals()
