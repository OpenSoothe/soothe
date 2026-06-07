"""Goal lifecycle manager for autonomous iteration (RFC-0007, RFC-204, RFC-200)."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from soothe.core.goal_engine.backoff_reasoner import GoalBackoffReasoner
from soothe.core.goal_engine.file_lock_registry import FileLockRegistry
from soothe.core.goal_engine.models import (
    TERMINAL_STATES,
    BackoffDecision,
    EvidenceBundle,
    Goal,
    GoalStatus,
)
from soothe.protocols.planner import GoalDirective, GoalReport
from soothe.utils.text_preview import preview_first

logger = logging.getLogger(__name__)

# Number of parts expected from frontmatter split (before, yaml, after)
_FRONTMATTER_SPLIT_MIN = 3


class GoalEngine:
    """Priority-based goal lifecycle manager.

    Goals are stored in memory and persisted via DurabilityProtocol.
    Scheduling: highest priority first, oldest creation time as tiebreaker.

    RFC-200: Integrates GoalBackoffReasoner for LLM-driven backoff decisions.
    RFC-222: Owns a FileLockRegistry for multi-AL conflict tracking and
    optionally an InternalEventBus to emit goal-state-change events when
    running in autopilot mode. In solo mode the bus is left unset and event
    emission is a no-op (zero overhead).
    """

    def __init__(
        self,
        max_retries: int = 2,
        max_send_backs: int = 3,
        config: Any = None,  # SootheConfig type hint avoided for circular dependency
        *,
        internal_bus: Any = None,  # InternalEventBus | None — avoid circular import
        file_registry: FileLockRegistry | None = None,
    ) -> None:
        """Initialize the goal engine.

        Args:
            max_retries: Default max retries for new goals.
            max_send_backs: Default max consensus send-back rounds (RFC-204).
            config: Optional SootheConfig for backoff reasoning (RFC-200).
            internal_bus: Optional InternalEventBus for autopilot coordination
                (RFC-222). When None, state-change events are not emitted.
            file_registry: Optional pre-constructed FileLockRegistry. When None,
                a fresh registry is created (cheap, always present).
        """
        self._goals: dict[str, Goal] = {}
        self._max_retries = max_retries
        self._max_send_backs = max_send_backs
        # RFC-200: Optional backoff reasoner (initialized if config provided)
        self._backoff_reasoner: GoalBackoffReasoner | None = None
        if config:
            try:
                self._backoff_reasoner = GoalBackoffReasoner(config)
                logger.info("GoalBackoffReasoner initialized for LLM-driven backoff")
            except Exception:
                logger.warning("Failed to initialize GoalBackoffReasoner", exc_info=True)
        # RFC-222: File lock registry (always present) + optional event bus
        self._internal_bus = internal_bus
        self._file_registry: FileLockRegistry = file_registry or FileLockRegistry()
        # RFC-222 Q6: track in-flight backoff reasoner tasks so they aren't
        # garbage-collected while pending and so shutdown can drain them.
        self._backoff_tasks: set[asyncio.Task[Any]] = set()

    @property
    def file_registry(self) -> FileLockRegistry:
        """File lock registry for multi-AL conflict tracking (RFC-222)."""
        return self._file_registry

    @property
    def internal_bus(self) -> Any:
        """Optional InternalEventBus for autopilot coordination (RFC-222)."""
        return self._internal_bus

    async def _emit_state_change(
        self,
        goal: Goal,
        old_status: str | None,
        *,
        reason: str | None = None,
        loop_id: str | None = None,
    ) -> None:
        """Emit InternalGoalStateChangedEvent if a bus is wired (RFC-222).

        Args:
            goal: The goal whose status changed.
            old_status: Previous status string, or None for newly created goals.
            reason: Optional human-readable reason.
            loop_id: Optional loop_id associated with the transition.
        """
        if self._internal_bus is None:
            return
        from soothe.core.events.internal_events import InternalGoalStateChangedEvent

        await self._internal_bus.emit(
            InternalGoalStateChangedEvent(
                goal_id=goal.id,
                old_status=old_status or "none",
                new_status=goal.status,
                reason=reason,
                loop_id=loop_id or goal.assigned_loop_id,
            )
        )

    async def _release_locks_and_emit(self, goal_id: str) -> None:
        """Release all file locks for a goal and emit released events (RFC-222).

        Args:
            goal_id: Goal whose locks should be released.
        """
        released = self._file_registry.release_all_for_goal(goal_id)
        if not released or self._internal_bus is None:
            return
        from soothe.core.events.internal_events import InternalFileReleasedEvent

        for path in released:
            await self._internal_bus.emit(
                InternalFileReleasedEvent(goal_id=goal_id, file_path=path)
            )

    async def create_goal(
        self,
        description: str,
        *,
        priority: int = 50,
        parent_id: str | None = None,
        max_retries: int | None = None,
        max_send_backs: int | None = None,
        informs: list[str] | None = None,
        conflicts_with: list[str] | None = None,
        source_file: str | None = None,
        workspace: str | None = None,
        goal_id: str | None = None,
        depends_on: list[str] | None = None,
        _validate_depth: bool = True,
        _max_depth: int = 5,
    ) -> Goal:
        """Create a new goal with safety validation.

        Args:
            description: Human-readable goal text.
            priority: Scheduling priority (0-100).
            parent_id: Optional parent goal ID.
            max_retries: Override default max retries.
            max_send_backs: Override default max send-back rounds (RFC-204).
            informs: Soft dependency goal IDs (RFC-204).
            conflicts_with: Mutual exclusion goal IDs (RFC-204).
            source_file: Path to GOAL.md that defined this goal (RFC-204).
            workspace: Optional absolute workspace path for autopilot execution.
            goal_id: Override default ID generation (for file-discovered goals).
            depends_on: Hard dependency goal IDs (alternative to post-creation add).
            _validate_depth: Whether to validate goal depth.
            _max_depth: Maximum allowed goal depth.

        Returns:
            The created Goal.

        Raises:
            ValueError: If depth limit exceeded or parent not found.
        """
        # Validate parent exists
        if parent_id:
            parent = self._goals.get(parent_id)
            if not parent:
                msg = f"Parent goal {parent_id} not found"
                raise ValueError(msg)

            # Check depth limit
            if _validate_depth:
                depth = self._calculate_goal_depth(parent_id)
                if depth >= _max_depth:
                    msg = f"Goal depth limit ({_max_depth}) exceeded. Parent {parent_id} is at depth {depth}."
                    raise ValueError(msg)

        goal = Goal(
            description=description,
            priority=priority,
            parent_id=parent_id,
            max_retries=max_retries if max_retries is not None else self._max_retries,
            max_send_backs=max_send_backs if max_send_backs is not None else self._max_send_backs,
            informs=informs or [],
            conflicts_with=conflicts_with or [],
            source_file=source_file,
            workspace=workspace,
            depends_on=depends_on or [],
        )
        if goal_id:
            goal.id = goal_id
        self._goals[goal.id] = goal

        # Enhanced logging with parent context
        parent_context = ""
        if parent_id:
            parent = self._goals.get(parent_id)
            if parent:
                parent_context = f' | parent: "{parent.description}"'
        logger.info(
            'Created goal %s: "%s"%s (priority=%d)', goal.id, description, parent_context, priority
        )
        logger.debug(self._format_goal_dag())
        # RFC-222: Emit creation as a transition from "none" → "pending"
        await self._emit_state_change(goal, old_status=None, reason="created")
        return goal

    async def next_goal(self) -> Goal | None:
        """Return the highest-priority ready goal (backward-compatible).

        Delegates to ``ready_goals(1)`` for DAG-aware scheduling.

        Returns:
            Next goal to process, or None if no executable goals.
        """
        goals = await self.ready_goals(limit=1)
        return goals[0] if goals else None

    def _filter_ready_candidates(self, limit: int) -> list[Goal]:
        """Compute the prefix of goals eligible for activation (read-only).

        Shared by ``ready_goals`` (activating) and ``peek_ready_goals``
        (non-mutating). Filters by hard dependencies and conflicts_with,
        sorts by ``(priority DESC, created_at ASC)``, returns the first
        ``limit`` candidates.
        """
        ready: list[Goal] = []
        active_ids = {g.id for g in self._goals.values() if g.status == "active"}

        for goal in self._goals.values():
            # Only pending goals are candidates for dispatch.
            # Active goals are already being executed by a worker.
            if goal.status != "pending":
                continue

            # Hard dependencies: all must be terminal
            deps_met = all(
                (dep := self._goals.get(dep_id)) is not None and dep.status in TERMINAL_STATES
                for dep_id in goal.depends_on
            )
            if not deps_met:
                continue

            # RFC-204: Conflict check — defer if conflicting goal is active
            has_conflict = any(dep_id in active_ids for dep_id in goal.conflicts_with)
            if has_conflict:
                logger.debug("Goal %s deferred: conflict with active goal", goal.id)
                continue

            ready.append(goal)

        ready.sort(key=lambda g: (-g.priority, g.created_at))
        return ready[:limit]

    async def peek_ready_goals(self, limit: int = 1) -> list[Goal]:
        """Read-only variant of ``ready_goals`` (RFC-222).

        Returns the same candidates as ``ready_goals`` but does **not**
        mutate goal status and does **not** emit events. Use this for
        capacity planning (AutopilotService) where you may not be able to
        actually claim every returned goal.

        Args:
            limit: Max goals to return.

        Returns:
            List of ready candidates, with status unchanged.
        """
        return self._filter_ready_candidates(limit)

    async def claim_goal(self, goal_id: str, *, loop_id: str | None = None) -> Goal | None:
        """Atomically transition a specific goal to ``active`` (RFC-222).

        Used by ``AutopilotService`` after ``peek_ready_goals`` chose a
        candidate and a loop was assigned for it. Verifies the goal is
        still eligible (pending or active) and not blocked by a fresh
        conflict, then flips status and emits the transition.

        Args:
            goal_id: Goal to claim.
            loop_id: Optional loop_id to stamp on the goal.

        Returns:
            The Goal if successfully claimed, None if the goal vanished,
            became ineligible, or hit a conflict in the race window.
        """
        goal = self._goals.get(goal_id)
        if not goal or goal.status not in ("pending", "active"):
            return None
        # Re-check conflicts at claim time
        active_ids = {
            g.id for g in self._goals.values() if g.status == "active" and g.id != goal.id
        }
        if any(dep_id in active_ids for dep_id in goal.conflicts_with):
            logger.debug("Goal %s claim aborted: conflict appeared", goal_id)
            return None
        old = goal.status
        goal.status = "active"
        goal.updated_at = datetime.now(UTC)
        if loop_id:
            goal.assigned_loop_id = loop_id
        if old != "active":
            await self._emit_state_change(goal, old, reason="claimed", loop_id=loop_id)
        return goal

    async def ready_goals(self, limit: int = 1) -> list[Goal]:
        """Return goals whose dependencies are all completed (RFC-0009, RFC-204).

        Goals are eligible if they are ``pending`` and all goals in their
        ``depends_on`` list are in terminal states (completed or failed).
        Results are sorted by ``(priority DESC, created_at ASC)``.

        Conflict-aware: goals with ``conflicts_with`` pointing to an ``active``
        goal are deferred to prevent concurrent execution.

        **Side effect:** every returned goal is transitioned to ``active``.
        Use ``peek_ready_goals`` for a read-only query.

        Args:
            limit: Max goals to return.

        Returns:
            List of ready goals, activated to ``active`` status.
        """
        result = self._filter_ready_candidates(limit)

        # RFC-222: capture old statuses before mutating so we can emit transitions
        transitions: list[tuple[Goal, str]] = [(g, g.status) for g in result]

        for goal in result:
            goal.status = "active"
            goal.updated_at = datetime.now(UTC)

        # Log ready goals (RFC-0009 / IG-026) - Enhanced natural language format
        if result:
            goal_summaries = []
            for g in result:
                context = self._get_goal_context(g.id)
                goal_summaries.append(f'\n  → {g.id}: "{context}" (priority={g.priority})')
            logger.info("Ready goals: %d%s", len(result), "".join(goal_summaries))
        else:
            logger.debug("No ready goals (waiting for dependencies)")

        # RFC-222: emit per-goal state change + a single goals-ready event
        if result and self._internal_bus is not None:
            for goal, old in transitions:
                if old != "active":
                    await self._emit_state_change(goal, old, reason="ready_activated")
            from soothe.core.events.internal_events import InternalGoalsReadyEvent

            await self._internal_bus.emit(
                InternalGoalsReadyEvent(
                    goal_ids=[g.id for g in result],
                    count=len(result),
                )
            )

        return result

    def is_complete(self) -> bool:
        """Check if all goals are resolved (completed or failed).

        Returns:
            True if no pending, active, suspended, blocked, or validated goals remain.
        """
        if not self._goals:
            return True
        return all(g.status in TERMINAL_STATES for g in self._goals.values())

    async def validate_goal(self, goal_id: str) -> Goal:
        """RFC-204: Mark goal as validated (Layer 3 accepted completion).

        Args:
            goal_id: Goal to validate.

        Returns:
            The updated Goal.

        Raises:
            KeyError: If goal not found.
        """
        goal = self._goals.get(goal_id)
        if not goal:
            msg = f"Goal {goal_id} not found"
            raise KeyError(msg)
        old = goal.status
        goal.status = "validated"
        goal.updated_at = datetime.now(UTC)
        logger.info("Validated goal %s", goal_id)
        await self._emit_state_change(goal, old, reason="validated")
        return goal

    async def suspend_goal(self, goal_id: str, *, reason: str = "") -> Goal:
        """RFC-204: Suspend a goal due to send-back budget exhaustion.

        Args:
            goal_id: Goal to suspend.
            reason: Why the goal was suspended.

        Returns:
            The updated Goal.

        Raises:
            KeyError: If goal not found.
        """
        goal = self._goals.get(goal_id)
        if not goal:
            msg = f"Goal {goal_id} not found"
            raise KeyError(msg)
        old = goal.status
        goal.status = "suspended"
        goal.assigned_loop_id = None
        goal.updated_at = datetime.now(UTC)
        logger.warning("Suspended goal %s: %s", goal_id, reason)
        await self._emit_state_change(goal, old, reason=reason or "suspended")
        return goal

    async def mark_awaiting_clarification(
        self,
        goal_id: str,
        *,
        pending_clarification: dict[str, Any],
        reason: str = "",
    ) -> Goal:
        """RFC-622: pause a goal until an out-of-band clarification arrives.

        Args:
            goal_id: Goal to pause.
            pending_clarification: Serialized ``ClarificationRequest`` to persist
                on the goal so an operator can answer it later.
            reason: Audit string.

        Returns:
            The updated Goal.

        Raises:
            KeyError: If goal not found.
        """
        goal = self._goals.get(goal_id)
        if not goal:
            msg = f"Goal {goal_id} not found"
            raise KeyError(msg)
        old = goal.status
        goal.status = "awaiting_clarification"
        goal.pending_clarification = pending_clarification
        goal.assigned_loop_id = None
        goal.updated_at = datetime.now(UTC)
        logger.info(
            "[ClarificationRelay] goal %s -> awaiting_clarification: %s",
            goal_id,
            reason,
        )
        await self._emit_state_change(goal, old, reason=reason or "awaiting_clarification")
        return goal

    async def answer_clarification(
        self,
        goal_id: str,
        answers: list[str],
    ) -> Goal:
        """RFC-622: provide answers for a goal blocked on a clarification.

        Clears ``pending_clarification`` and transitions the goal back to
        ``pending`` so the scheduler picks it up on the next cycle. The
        loop on re-entry will consume the answers from the goal record.

        Args:
            goal_id: Goal currently in ``awaiting_clarification``.
            answers: One answer per question; the loop validates lengths.

        Returns:
            The updated Goal.

        Raises:
            KeyError: If goal not found.
            ValueError: If goal is not awaiting a clarification.
        """
        goal = self._goals.get(goal_id)
        if not goal:
            msg = f"Goal {goal_id} not found"
            raise KeyError(msg)
        if goal.status != "awaiting_clarification":
            msg = f"Goal {goal_id} is not awaiting a clarification (status={goal.status!r})"
            raise ValueError(msg)
        pending = goal.pending_clarification or {}
        pending["answers"] = list(answers)
        goal.pending_clarification = pending
        old = goal.status
        goal.status = "pending"
        goal.updated_at = datetime.now(UTC)
        logger.info(
            "[ClarificationRelay] goal %s clarification answered (%d answer(s))",
            goal_id,
            len(answers),
        )
        await self._emit_state_change(goal, old, reason="clarification_answered")
        return goal

    async def send_back_goal(self, goal_id: str, *, reason: str = "") -> Goal:
        """RFC-204: Return a goal to pending after consensus rejection.

        Increments ``send_back_count``. When the budget is exhausted the goal
        is suspended instead of re-queued.

        Args:
            goal_id: Goal to send back.
            reason: Consensus reasoning for the send-back.

        Returns:
            The updated Goal.

        Raises:
            KeyError: If goal not found.
        """
        goal = self._goals.get(goal_id)
        if not goal:
            msg = f"Goal {goal_id} not found"
            raise KeyError(msg)

        goal.send_back_count += 1
        if goal.send_back_count >= goal.max_send_backs:
            return await self.suspend_goal(
                goal_id,
                reason=reason or "send_back budget exhausted",
            )

        old = goal.status
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
        await self._emit_state_change(goal, old, reason=reason or "consensus_send_back")
        return goal

    async def block_goal(self, goal_id: str, *, reason: str = "") -> Goal:
        """RFC-204: Block a goal awaiting external input.

        Args:
            goal_id: Goal to block.
            reason: Why the goal was blocked.

        Returns:
            The updated Goal.

        Raises:
            KeyError: If goal not found.
        """
        goal = self._goals.get(goal_id)
        if not goal:
            msg = f"Goal {goal_id} not found"
            raise KeyError(msg)
        old = goal.status
        goal.status = "blocked"
        goal.updated_at = datetime.now(UTC)
        logger.warning("Blocked goal %s: %s", goal_id, reason)
        await self._emit_state_change(goal, old, reason=reason or "blocked")
        return goal

    async def reactivate_goal(self, goal_id: str) -> Goal:
        """RFC-204: Reactivate a suspended/blocked goal back to pending.

        Args:
            goal_id: Goal to reactivate.

        Returns:
            The updated Goal.

        Raises:
            KeyError: If goal not found.
        """
        goal = self._goals.get(goal_id)
        if not goal:
            msg = f"Goal {goal_id} not found"
            raise KeyError(msg)
        if goal.status not in ("suspended", "blocked"):
            msg = f"Goal {goal_id} is {goal.status}, not suspended/blocked"
            raise ValueError(msg)
        old = goal.status
        goal.status = "pending"
        goal.send_back_count = 0  # Reset send-back budget
        goal.updated_at = datetime.now(UTC)
        logger.info("Reactivated goal %s (was %s)", goal_id, old)
        await self._emit_state_change(goal, old, reason="reactivated")
        return goal

    async def check_reactivated_goals(self) -> list[Goal]:
        """RFC-204: Auto-reactivate goals whose dependencies are now resolved.

        After a goal completes, check if suspended or blocked goals now have
        their dependencies satisfied.

        Returns:
            List of reactivated goals.
        """
        reactivated: list[Goal] = []
        transitions: list[tuple[Goal, str]] = []
        for goal in self._goals.values():
            if goal.status not in ("suspended", "blocked"):
                continue
            deps_met = all(
                (dep := self._goals.get(dep_id)) is not None and dep.status in TERMINAL_STATES
                for dep_id in goal.depends_on
            )
            if deps_met:
                transitions.append((goal, goal.status))
                goal.status = "pending"
                goal.send_back_count = 0
                goal.updated_at = datetime.now(UTC)
                reactivated.append(goal)
                logger.info("Auto-reactivated goal %s (dependencies resolved)", goal.id)
        # RFC-222: emit transitions after mutations so observers see the new state
        for goal, old in transitions:
            await self._emit_state_change(goal, old, reason="deps_resolved")
        return reactivated

    async def absorb_guidance(
        self,
        goal_id: str,
        guidance_text: str,
        scope: str = "goal",
    ) -> bool:
        """Absorb user guidance from desktop LOR (RFC-228).

        Desktop sends guidance via job_guidance IPC. GoalEngine accumulates
        the guidance for use in next reasoning cycle. Guidance influences:
        - Goal priority adjustments
        - Constraint additions
        - Subgoal creation modifications
        - Execution behavior changes

        Args:
            goal_id: Target goal ID to receive guidance.
            guidance_text: User's guidance/instruction text.
            scope: "goal" for specific goal, "job" for root goal (full DAG).

        Returns:
            True if guidance was absorbed, False if goal not found.
        """
        goal = self._goals.get(goal_id)
        if goal is None:
            logger.warning("[Guidance] Goal %s not found for guidance absorption", goal_id)
            return False

        # Accumulate guidance for this goal
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

        # Emit event for observers (scheduler may re-evaluate)
        if self._internal_bus is not None:
            from soothe.core.events.internal_events import InternalGoalStateChangedEvent

            await self._internal_bus.emit(
                InternalGoalStateChangedEvent(
                    goal_id=goal_id,
                    old_status=goal.status,
                    new_status=goal.status,  # Status unchanged, but guidance added
                    reason="guidance_absorbed",
                )
            )

        return True

    async def complete_goal(self, goal_id: str) -> Goal:
        """Mark a goal as completed (IG-155: update source file).

        Args:
            goal_id: Goal to complete.

        Returns:
            The updated Goal.

        Raises:
            KeyError: If goal not found.
        """
        goal = self._goals.get(goal_id)
        if not goal:
            msg = f"Goal {goal_id} not found"
            raise KeyError(msg)

        # Calculate duration before updating timestamp
        duration = (datetime.now(UTC) - goal.created_at).total_seconds()

        old = goal.status
        goal.status = "completed"
        goal.updated_at = datetime.now(UTC)

        # IG-155: Update source file status if available
        if goal.source_file:
            try:
                from pathlib import Path

                from soothe.core.goal_engine.writer import update_goal_status

                update_goal_status(Path(goal.source_file), "completed")
                logger.debug("Updated goal file status for %s", goal_id)
            except Exception:
                logger.debug("Failed to update goal file status", exc_info=True)

        # Enhanced logging with parent context and duration
        parent_context = ""
        if goal.parent_id:
            parent = self._goals.get(goal.parent_id)
            if parent:
                parent_context = f' | parent: "{parent.description}"'
        logger.info(
            'Completed goal %s: "%s"%s (priority=%d, duration=%.1fs)',
            goal_id,
            goal.description,
            parent_context,
            goal.priority,
            duration,
        )
        logger.debug(self._format_goal_dag())
        # RFC-222: release file locks and emit transition
        await self._release_locks_and_emit(goal_id)
        await self._emit_state_change(goal, old, reason="completed")
        return goal

    async def cancel_goal(
        self,
        goal_id: str,
        *,
        reason: str = "user_cancelled",
    ) -> None:
        """Mark a goal as cancelled.

        Distinct from ``fail_goal``: no backoff reasoning, no retry logic.
        Used for intentional user or system cancellations.

        Args:
            goal_id: Goal to cancel.
            reason: Human-readable cancellation reason (stored in ``goal.error``).

        Raises:
            KeyError: If goal not found.
        """
        goal = self._goals.get(goal_id)
        if not goal:
            msg = f"Goal {goal_id} not found"
            raise KeyError(msg)

        old = goal.status
        goal.status = "cancelled"
        goal.error = reason
        goal.updated_at = datetime.now(UTC)

        if goal.source_file:
            try:
                from pathlib import Path

                from soothe.core.goal_engine.writer import update_goal_status

                update_goal_status(Path(goal.source_file), "cancelled", error=reason)
            except Exception:
                logger.debug("Failed to update goal file status", exc_info=True)

        logger.info(
            'Cancelled goal %s: "%s" — %s',
            goal_id,
            goal.description,
            reason,
        )
        logger.debug(self._format_goal_dag())
        await self._release_locks_and_emit(goal_id)
        await self._emit_state_change(goal, old, reason="cancelled")

    async def fail_goal(
        self,
        goal_id: str,
        *,
        evidence: EvidenceBundle | None = None,
        allow_retry: bool = True,
    ) -> BackoffDecision | None:
        """Mark a goal as failed with evidence, apply backoff reasoning.

        RFC-200 §14-22, §205-541: Receives EvidenceBundle from execution,
        applies GoalBackoffReasoner for LLM-driven DAG restructuring.

        If ``allow_retry`` and retries remain, resets to pending.
        Otherwise marks permanently failed.

        Args:
            goal_id: Goal to fail.
            evidence: EvidenceBundle from execution (RFC-200 contract).
            allow_retry: Whether to allow retry if retries remain.

        Returns:
            BackoffDecision if backoff reasoning applied, None if no retry.

        Raises:
            KeyError: If goal not found.
        """
        goal = self._goals.get(goal_id)
        if not goal:
            msg = f"Goal {goal_id} not found"
            raise KeyError(msg)

        if not evidence:
            logger.error("No EvidenceBundle provided for goal failure")
            return None

        old = goal.status

        # RFC-222 Q6: backoff reasoning runs as a fire-and-forget asyncio task
        # so the dispatch loop and direct fail_goal callers never block on the
        # LLM. The goal is transitioned now (retry-or-failed); the reasoner
        # may later restructure the DAG by transitioning a different goal to
        # ``pending`` with new directives.
        if self._backoff_reasoner and evidence:
            scheduled = self._spawn_backoff_task(goal_id, evidence)
            if scheduled:
                # Apply the immediate retry/failed transition, mirroring the
                # fallback path below, so callers see deterministic state
                # before the reasoner finishes.
                if allow_retry and goal.retry_count < goal.max_retries:
                    goal.retry_count += 1
                    goal.status = "pending"
                    goal.updated_at = datetime.now(UTC)
                    await self._release_locks_and_emit(goal_id)
                    await self._emit_state_change(goal, old, reason="retry")
                else:
                    goal.status = "failed"
                    goal.error = evidence.narrative
                    goal.updated_at = datetime.now(UTC)
                    await self._release_locks_and_emit(goal_id)
                    await self._emit_state_change(goal, old, reason="failed")
                return None  # decision not yet ready; emitted later by task

        # Fallback: Simple retry logic
        if allow_retry and goal.retry_count < goal.max_retries:
            goal.retry_count += 1
            goal.status = "pending"
            goal.updated_at = datetime.now(UTC)
            error_text = evidence.narrative
            logger.info(
                "Goal %s retry %d/%d: %s%s",
                goal_id,
                goal.retry_count,
                goal.max_retries,
                goal.description,
                f" - {error_text}" if error_text else "",
            )
            logger.debug(self._format_goal_dag())
            # RFC-222: release locks held by the failed attempt; emit retry transition
            await self._release_locks_and_emit(goal_id)
            await self._emit_state_change(goal, old, reason="retry")
            return None

        goal.status = "failed"
        goal.error = evidence.narrative  # IG-155: Store error message
        goal.updated_at = datetime.now(UTC)

        # IG-155: Update source file status if available
        if goal.source_file:
            try:
                from pathlib import Path

                from soothe.core.goal_engine.writer import update_goal_status

                error_text = evidence.narrative
                update_goal_status(Path(goal.source_file), "failed", error=error_text)
                logger.debug("Updated goal file status for failed %s", goal_id)
            except Exception:
                logger.debug("Failed to update goal file status", exc_info=True)

        # Enhanced logging with dependency context and status
        dep_context = ""
        if goal.depends_on:
            dep_descs = []
            for dep_id in goal.depends_on:
                dep = self._goals.get(dep_id)
                if dep:
                    dep_descs.append(f"{dep.description} ({dep.status})")
                else:
                    dep_descs.append(dep_id)
            dep_context = f" | depends_on: [{', '.join(dep_descs)}]"
        logger.warning(
            'Failed goal %s: "%s"%s (priority=%d, retries=%d/%d)%s',
            goal_id,
            goal.description,
            dep_context,
            goal.priority,
            goal.retry_count,
            goal.max_retries,
            f" - {goal.error}" if goal.error else "",
        )
        logger.debug(self._format_goal_dag())
        # RFC-222: release locks + emit permanent-failure transition
        await self._release_locks_and_emit(goal_id)
        await self._emit_state_change(goal, old, reason="failed")
        return None  # RFC-200: Return None for permanent failure (BackoffDecision | None)

    async def list_goals(self, status: GoalStatus | None = None) -> list[Goal]:
        """List goals, optionally filtered by status.

        Args:
            status: Filter by status, or None for all.

        Returns:
            List of matching goals.
        """
        if status:
            return [g for g in self._goals.values() if g.status == status]
        return list(self._goals.values())

    async def get_goal(self, goal_id: str) -> Goal | None:
        """Get a goal by ID.

        Args:
            goal_id: Goal ID to look up.

        Returns:
            The Goal, or None if not found.
        """
        return self._goals.get(goal_id)

    def _calculate_goal_depth(self, goal_id: str) -> int:
        """Calculate depth in goal hierarchy.

        Args:
            goal_id: Goal ID to calculate depth for.

        Returns:
            Depth value (0 = no parent, 1 = one parent, etc.).
        """
        max_depth_limit = 20  # Safety limit to prevent infinite loops
        depth = 0
        current_id = goal_id
        visited = set()

        while current_id:
            if current_id in visited:
                break  # Cycle detected
            visited.add(current_id)

            goal = self._goals.get(current_id)
            if not goal:
                break

            depth += 1
            current_id = goal.parent_id

            if depth > max_depth_limit:
                break

        return depth

    def _would_create_cycle(self, goal_id: str, new_deps: list[str]) -> bool:
        """Check if adding new_deps to goal_id would create a cycle using DFS.

        Args:
            goal_id: Target goal ID.
            new_deps: Proposed new dependencies.

        Returns:
            True if adding dependencies would create a cycle.
        """
        visited = set()

        def _dfs(current_id: str) -> bool:
            if current_id == goal_id:
                return True  # Cycle detected
            if current_id in visited:
                return False
            visited.add(current_id)

            current_goal = self._goals.get(current_id)
            if current_goal:
                return any(_dfs(dep_id) for dep_id in current_goal.depends_on)
            return False

        return any(_dfs(dep_id) for dep_id in new_deps)

    async def validate_dependency(self, goal_id: str, depends_on: list[str]) -> tuple[bool, str]:
        """Validate that adding dependencies won't create a cycle.

        Args:
            goal_id: Target goal ID.
            depends_on: Proposed new dependencies.

        Returns:
            Tuple of (is_valid, error_message).
        """
        # Check dependencies exist
        for dep_id in depends_on:
            if dep_id not in self._goals:
                return False, f"Dependency goal {dep_id} does not exist"

        # Check for self-dependency
        if goal_id in depends_on:
            msg = f"Goal {goal_id} cannot depend on itself"
            return False, msg

        # Check for cycles
        if self._would_create_cycle(goal_id, depends_on):
            return False, "Adding dependencies would create a cycle"

        return True, ""

    async def add_dependencies(self, goal_id: str, depends_on: list[str]) -> Goal:
        """Add dependencies to a goal with cycle validation.

        Args:
            goal_id: Target goal ID.
            depends_on: Dependencies to add.

        Returns:
            The updated Goal.

        Raises:
            ValueError: If dependencies would create a cycle.
            KeyError: If goal not found.
        """
        goal = self._goals.get(goal_id)
        if not goal:
            msg = f"Goal {goal_id} not found"
            raise KeyError(msg)

        is_valid, error = await self.validate_dependency(goal_id, depends_on)
        if not is_valid:
            raise ValueError(error)

        # Add new dependencies (avoid duplicates)
        existing = set(goal.depends_on)
        for dep_id in depends_on:
            if dep_id not in existing:
                goal.depends_on.append(dep_id)

        goal.updated_at = datetime.now(UTC)

        # Enhanced logging with dependency descriptions
        dep_descs = []
        for dep_id in depends_on:
            dep = self._goals.get(dep_id)
            if dep:
                dep_descs.append(f'{dep_id}: "{dep.description}"')
            else:
                dep_descs.append(dep_id)
        logger.info(
            'Added dependencies to goal %s "%s": [%s]',
            goal_id,
            goal.description,
            ", ".join(dep_descs),
        )
        logger.debug(self._format_goal_dag())
        return goal

    def _get_goal_context(self, goal_id: str) -> str:
        """Get natural language context for a goal.

        Args:
            goal_id: Goal ID to get context for.

        Returns:
            Context string with parent and dependency descriptions.
        """
        goal = self._goals.get(goal_id)
        if not goal:
            return goal_id

        context_parts = [goal.description]

        # Add parent context
        if goal.parent_id:
            parent = self._goals.get(goal.parent_id)
            if parent:
                context_parts.append(f"parent: {parent.description}")

        # Add dependency context
        if goal.depends_on:
            dep_descs = []
            for dep_id in goal.depends_on:
                dep = self._goals.get(dep_id)
                if dep:
                    dep_descs.append(dep.description)
                else:
                    dep_descs.append(dep_id)
            context_parts.append(f"depends_on: [{', '.join(dep_descs)}]")

        return " | ".join(context_parts)

    def _spawn_backoff_task(
        self,
        goal_id: str,
        evidence: EvidenceBundle,
    ) -> bool:
        """Schedule reason_backoff as a fire-and-forget task (RFC-222 Q6).

        Returns True on successful scheduling. Returns False when no event
        loop is running (e.g. legacy synchronous test contexts) so the caller
        can fall through to the inline backoff path.
        """
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            return False

        # Snapshot the goal map so the reasoner sees a consistent DAG even
        # if other coroutines mutate _goals while it runs.
        goals_snapshot = dict(self._goals)
        task = running_loop.create_task(self._run_backoff_task(goal_id, evidence, goals_snapshot))
        self._backoff_tasks.add(task)
        task.add_done_callback(self._backoff_tasks.discard)
        logger.debug(
            "Scheduled async backoff reasoner task for goal %s (%d in flight)",
            goal_id,
            len(self._backoff_tasks),
        )
        return True

    async def _run_backoff_task(
        self,
        goal_id: str,
        evidence: EvidenceBundle,
        goals_snapshot: dict[str, Goal],
    ) -> None:
        """Run reason_backoff and apply the decision asynchronously.

        Errors are logged and swallowed — the goal already transitioned to its
        immediate state in ``fail_goal``; the worst case is that no DAG
        restructuring happens.
        """
        if self._backoff_reasoner is None:
            return  # nothing to do (defensive)

        try:
            decision = await self._backoff_reasoner.reason_backoff(
                goal_id=goal_id,
                goals=goals_snapshot,
                failed_evidence=evidence,
            )
        except Exception:
            logger.warning(
                "Async backoff reasoning failed for goal %s; immediate transition stands",
                goal_id,
                exc_info=True,
            )
            return

        logger.info(
            "Async backoff decision for goal %s: backoff to %s — %s",
            goal_id,
            decision.backoff_to_goal_id,
            decision.reason,
        )

        try:
            await self._apply_backoff_decision(decision, goal_id)
        except Exception:
            logger.warning(
                "Failed to apply async backoff decision for goal %s",
                goal_id,
                exc_info=True,
            )
            return

        # Emit a separate ``backoff`` transition for observability after the
        # decision lands. The original ``retry``/``failed`` event already fired
        # synchronously inside fail_goal.
        failed_goal = self._goals.get(goal_id)
        if failed_goal is not None:
            try:
                await self._emit_state_change(failed_goal, failed_goal.status, reason="backoff")
            except Exception:
                logger.debug("emit_state_change raised after async backoff", exc_info=True)

    async def _apply_backoff_decision(
        self,
        decision: BackoffDecision,
        failed_goal_id: str,
    ) -> None:
        """Apply backoff decision to goal DAG.

        RFC-200: Resets backoff target goal to "pending" and applies new directives.

        Args:
            decision: BackoffDecision from GoalBackoffReasoner.
            failed_goal_id: ID of the goal that failed.
        """
        backoff_target = self._goals.get(decision.backoff_to_goal_id)
        if not backoff_target:
            logger.warning(
                "Backoff target %s not found in DAG",
                decision.backoff_to_goal_id,
            )
            return

        # Reset backoff target to pending
        backoff_target.status = "pending"
        backoff_target.updated_at = datetime.now(UTC)

        # Mark failed goal as failed (not retrying)
        failed_goal = self._goals.get(failed_goal_id)
        if failed_goal:
            failed_goal.status = "failed"
            failed_goal.error = decision.evidence_summary
            failed_goal.updated_at = datetime.now(UTC)

        logger.info(
            "Applied backoff: resetting goal %s to pending, marking %s as failed",
            decision.backoff_to_goal_id,
            failed_goal_id,
        )

        # Apply new directives if provided
        if decision.new_directives:
            logger.info(
                "Applying %d new directives from backoff decision",
                len(decision.new_directives),
            )
            # Apply directives from backoff decision (RFC-204 Group C)
            created = await self.apply_directives(decision.new_directives, failed_goal_id)
            logger.info("Backoff directives applied: created %d goals", len(created))

    async def apply_directives(
        self,
        directives: list[GoalDirective],
        source_goal_id: str,
    ) -> list[str]:
        """Apply goal directives from GoalCompletionChunk (RFC-204 Group C).

        Handles all six directive actions:
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
                if d.action == "create":
                    # Parent defaults to source goal if not specified
                    parent = d.parent_id or source_goal_id
                    priority = d.priority or 50
                    # Clamp priority to valid range
                    priority = max(0, min(100, priority))

                    new_goal = await self.create_goal(
                        description=d.description,
                        priority=priority,
                        parent_id=parent,
                        depends_on=list(d.depends_on) if d.depends_on else [],
                    )
                    created_ids.append(new_goal.id)
                    logger.info(
                        "Directive created goal %s (parent=%s, priority=%d): %s",
                        new_goal.id,
                        parent,
                        priority,
                        preview_first(d.description, 50),
                    )

                elif d.action == "adjust_priority":
                    goal = self._goals.get(d.goal_id)
                    if goal and d.priority is not None:
                        old_priority = goal.priority
                        goal.priority = max(0, min(100, d.priority))
                        goal.updated_at = datetime.now(UTC)
                        logger.info(
                            "Directive adjusted goal %s priority: %d → %d",
                            d.goal_id,
                            old_priority,
                            goal.priority,
                        )
                    elif not goal:
                        logger.warning(
                            "Directive adjust_priority: goal %s not found",
                            d.goal_id,
                        )

                elif d.action == "add_dependency":
                    goal = self._goals.get(d.goal_id)
                    if goal and d.depends_on:
                        for dep_id in d.depends_on:
                            if dep_id not in goal.depends_on:
                                goal.depends_on.append(dep_id)
                        goal.updated_at = datetime.now(UTC)
                        logger.info(
                            "Directive added dependencies to goal %s: %s",
                            d.goal_id,
                            d.depends_on,
                        )
                    elif not goal:
                        logger.warning(
                            "Directive add_dependency: goal %s not found",
                            d.goal_id,
                        )

                elif d.action == "fail":
                    if d.goal_id:
                        await self.fail_goal(
                            d.goal_id,
                            evidence=EvidenceBundle(
                                structured={"action": "directive_fail"},
                                narrative=d.rationale or "Directive-fail",
                                source="layer3_reflect",  # Directive comes from Layer 3 context
                            ),
                            allow_retry=False,
                        )
                        logger.info("Directive marked goal %s as failed", d.goal_id)
                    else:
                        logger.warning("Directive fail: no goal_id specified")

                elif d.action == "complete":
                    if d.goal_id:
                        await self.complete_goal(d.goal_id)
                        logger.info("Directive marked goal %s as completed", d.goal_id)
                    else:
                        logger.warning("Directive complete: no goal_id specified")

                elif d.action == "decompose":
                    # Future work — log and skip
                    logger.warning(
                        "Directive 'decompose' not implemented (goal %s): %s",
                        d.goal_id,
                        d.description,
                    )

            except Exception:
                logger.warning(
                    "Directive application failed (action=%s, goal_id=%s): %s",
                    d.action,
                    d.goal_id,
                    d.description,
                    exc_info=True,
                )

        return created_ids

    def _format_goal_dag(self) -> str:
        """Format the current goal DAG state for logging.

        Returns:
            Human-readable string representation of the goal DAG.
        """
        if not self._goals:
            return "Goal DAG: (empty)"

        lines = ["Goal DAG:"]
        for goal in sorted(self._goals.values(), key=lambda g: (-g.priority, g.created_at)):
            # Add parent description
            parent_str = ""
            if goal.parent_id:
                parent = self._goals.get(goal.parent_id)
                if parent:
                    parent_str = (
                        f' parent={goal.parent_id} "{preview_first(parent.description, 30)}"'
                    )
                else:
                    parent_str = f" parent={goal.parent_id}"

            # Add dependency descriptions
            deps_with_desc = []
            for dep_id in goal.depends_on:
                dep = self._goals.get(dep_id)
                if dep:
                    deps_with_desc.append(f'{dep_id} "{preview_first(dep.description, 30)}"')
                else:
                    deps_with_desc.append(dep_id)
            deps_str = f" depends_on=[{', '.join(deps_with_desc)}]" if goal.depends_on else ""

            lines.append(
                f"  [{goal.id}] {goal.status} priority={goal.priority}{parent_str}{deps_str}"
                f"\n      → {goal.description}"
            )
        return "\n".join(lines)

    def snapshot(self) -> list[dict[str, Any]]:
        """Serialize all goals to a list of dicts for persistence."""
        result = []
        for g in self._goals.values():
            goal_dict = g.model_dump(mode="json")
            # Serialize GoalReport to JSON string if present
            if g.report is not None:
                goal_dict["report"] = g.report.model_dump_json()
            result.append(goal_dict)
        return result

    def restore_from_snapshot(self, data: list[dict[str, Any]]) -> None:
        """Restore goals from a serialized snapshot.

        Args:
            data: List of goal dicts from ``snapshot()``.
        """
        self._goals.clear()
        for item in data:
            try:
                # Deserialize GoalReport from JSON string if present
                if "report" in item and isinstance(item["report"], str):
                    item["report"] = GoalReport.model_validate_json(item["report"])
                goal = Goal(**item)
                self._goals[goal.id] = goal
            except Exception:
                logger.debug("Skipping invalid goal record: %s", item, exc_info=True)
        logger.info("Restored %d goals", len(self._goals))
        logger.debug(self._format_goal_dag())

    def recover_active_goals(self) -> list[str]:
        """RFC-222 H4: reset goals stuck in ``active`` from a previous run.

        Called by the daemon after ``restore_from_snapshot`` on startup. Any
        goal still flagged ``active`` was mid-flight when the previous daemon
        process exited; the worker subprocess is gone, so the goal must be
        re-dispatched. Each recovered goal:

        - has ``assigned_loop_id`` cleared (the old worker is dead),
        - is flipped back to ``pending`` so the scheduler picks it up,
        - has ``attempts_after_crash`` incremented for visibility / audit,
        - logs a warning so operators see the recovery happened.

        Returns:
            IDs of goals that were reset. Empty list when nothing was active.
        """
        recovered: list[str] = []
        now = datetime.now(UTC)
        for goal in self._goals.values():
            if goal.status != "active":
                continue
            prev_loop = goal.assigned_loop_id
            goal.assigned_loop_id = None
            goal.attempts_after_crash += 1
            goal.status = "pending"
            goal.updated_at = now
            recovered.append(goal.id)
            logger.warning(
                "Crash recovery: reset goal %s (was active on loop=%s) → pending "
                "(attempts_after_crash=%d)",
                goal.id,
                prev_loop,
                goal.attempts_after_crash,
            )
        if recovered:
            logger.info("Crash recovery: reset %d active goals to pending", len(recovered))
        return recovered

    # ------------------------------------------------------------------
    # RFC-204: Goal File Discovery & Status Tracking
    # ------------------------------------------------------------------

    async def discover_goals_from_files(
        self,
        autopilot_dir: str | None = None,
    ) -> list[Goal]:
        """RFC-204: Discover goals from GOAL.md/GOALS.md files.

        Scans in priority order:
        1. `SOOTHE_HOME/autopilot/GOAL.md` — single goal mode
        2. `SOOTHE_HOME/autopilot/GOALS.md` — batch mode
        3. `SOOTHE_HOME/autopilot/goals/*/GOAL.md` — per-goal dirs

        Args:
            autopilot_dir: Override path. Defaults to $SOOTHE_HOME/autopilot.

        Returns:
            List of goals created from discovered files.
        """
        from soothe.config import SOOTHE_HOME

        base = Path(autopilot_dir or SOOTHE_HOME) / "autopilot"
        goals_dir = base / "goals"
        goals_created: list[Goal] = []

        # Priority 1: Root GOAL.md (single goal mode)
        single_goal_file = base / "GOAL.md"
        if single_goal_file.exists():
            goal_def = _parse_goal_file(single_goal_file)
            if goal_def:
                goal = await self._create_from_definition(
                    goal_def, source_file=str(single_goal_file)
                )
                goals_created.append(goal)
                return goals_created  # Single goal mode, skip other discovery

        # Priority 2: Root GOALS.md (batch mode)
        goals_batch_file = base / "GOALS.md"
        if goals_batch_file.exists():
            batch_defs = _parse_goals_batch_file(goals_batch_file)
            for gdef in batch_defs:
                goal = await self._create_from_definition(gdef, source_file=str(goals_batch_file))
                goals_created.append(goal)

        # Priority 3: goals/ subdirectory GOAL.md files
        if goals_dir.exists():
            for subdir in sorted(goals_dir.iterdir()):
                if subdir.is_dir():
                    gfile = subdir / "GOAL.md"
                    if gfile.exists():
                        goal_def = _parse_goal_file(gfile)
                        if goal_def:
                            goal = await self._create_from_definition(
                                goal_def, source_file=str(gfile)
                            )
                            goals_created.append(goal)

        if goals_created:
            logger.info("Discovered %d goals from files", len(goals_created))
        return goals_created

    async def update_goal_file_status(self, goal_id: str) -> None:
        """RFC-204: Update status in the source GOAL.md file.

        Updates the frontmatter status field to match the goal's current status.

        Args:
            goal_id: Goal whose file status should be updated.
        """
        goal = self._goals.get(goal_id)
        if not goal or not goal.source_file:
            return

        try:
            _update_frontmatter_status(goal.source_file, goal.status)
        except Exception:
            logger.debug("Failed to update goal file status for %s", goal_id, exc_info=True)

    async def append_goal_progress(self, goal_id: str, entry: str) -> None:
        """RFC-204: Append a progress entry to the goal's GOAL.md file.

        Finds or creates a ``## Progress`` section and appends a timestamped entry.

        Args:
            goal_id: Goal ID to update.
            entry: Progress entry text.
        """
        goal = self._goals.get(goal_id)
        if not goal or not goal.source_file:
            return

        source = Path(goal.source_file)
        if not source.exists():  # noqa: ASYNC240
            return

        try:
            from datetime import UTC, datetime

            content = source.read_text()  # noqa: ASYNC240
            timestamp = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
            progress_line = f"\n- [{timestamp}] {entry}"

            # Find or create ## Progress section
            if "## Progress" in content:
                # Append after the last ## section header within progress, or at end of file
                parts = content.split("## Progress", 1)
                section = parts[1]
                # Find next ## header after Progress
                next_header_idx = section.find("\n## ")
                if next_header_idx >= 0:
                    # Insert before the next section header
                    before = section[:next_header_idx]
                    after = section[next_header_idx:]
                    content = parts[0] + "## Progress" + before + progress_line + after
                else:
                    content += progress_line
            else:
                # Create Progress section at the end
                content += f"\n## Progress{progress_line}\n"

            source.write_text(content)  # noqa: ASYNC240
        except OSError:
            logger.debug("Failed to append progress for %s", goal_id, exc_info=True)

    # ------------------------------------------------------------------
    # Internal helpers for file discovery
    # ------------------------------------------------------------------

    async def _create_from_definition(
        self,
        goal_def: _GoalFileDefinition,
        *,
        source_file: str,
    ) -> Goal:
        """Create a goal from a parsed file definition."""
        return await self.create_goal(
            description=goal_def.description,
            priority=goal_def.priority,
            goal_id=goal_def.id,
            depends_on=goal_def.depends_on,
            informs=goal_def.informs,
            conflicts_with=goal_def.conflicts_with,
            source_file=source_file,
        )


# ======================================================================
# RFC-204: Goal File Parsing Helpers
# ======================================================================


@dataclass
class _GoalFileDefinition:
    """Parsed definition of a goal from a markdown file."""

    id: str
    description: str
    priority: int = 50
    depends_on: list[str] = field(default_factory=list)
    informs: list[str] = field(default_factory=list)
    conflicts_with: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)


def _parse_goal_file(path: Path) -> _GoalFileDefinition | None:
    """Parse a single GOAL.md file.

    Expected format:
    ```
    ---
    id: my-goal
    priority: 80
    depends_on: [dep1, dep2]
    informs: [goal3]
    conflicts_with: [goal4]
    ---

    # Title → used as description

    ## Success Criteria
    - criterion 1
    - criterion 2
    ```
    """
    text = path.read_text()
    frontmatter, body = _split_frontmatter(text)
    if not frontmatter:
        return None

    import yaml

    fm = yaml.safe_load(frontmatter) or {}

    # Extract description from first heading
    description = ""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            description = stripped[2:].strip()
            break
    if not description:
        description = "Goal from " + path.name

    # Extract success criteria
    success_criteria = _extract_success_criteria(body)

    return _GoalFileDefinition(
        id=fm.get("id", path.stem),
        description=description,
        priority=int(fm.get("priority", 50)),
        depends_on=fm.get("depends_on", []),
        informs=fm.get("informs", []),
        conflicts_with=fm.get("conflicts_with", []),
        success_criteria=success_criteria,
    )


def _parse_goals_batch_file(path: Path) -> list[_GoalFileDefinition]:
    """Parse a GOALS.md file with multiple goals.

    Expected format:
    ```
    ## Goal: Authentication System
    - id: auth
    - priority: 90
    - depends_on: []

    Description text becomes the goal description.

    ## Goal:API Integration
    - id: api
    - priority: 70
    - depends_on: [auth]
    ```
    """
    text = path.read_text()
    goals = []

    # Split on ## Goal: headings
    sections = re.split(r"## Goal:\s*", text)[1:]  # skip preamble

    for section in sections:
        lines = section.splitlines()
        # First line is the goal name
        name = lines[0].strip() if lines else ""

        # Parse key-value bullets
        metadata: dict[str, Any] = {}
        body_lines: list[str] = []
        for line in lines[1:]:
            stripped = line.strip()
            if stripped.startswith("- id:"):
                metadata["id"] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("- priority:"):
                metadata["priority"] = int(stripped.split(":", 1)[1].strip())
            elif stripped.startswith("- depends_on:"):
                raw = stripped.split(":", 1)[1].strip()
                metadata["depends_on"] = _parse_yaml_list(raw)
            elif stripped.startswith("- informs:"):
                raw = stripped.split(":", 1)[1].strip()
                metadata["informs"] = _parse_yaml_list(raw)
            elif stripped.startswith("- conflicts_with:"):
                raw = stripped.split(":", 1)[1].strip()
                metadata["conflicts_with"] = _parse_yaml_list(raw)
            else:
                body_lines.append(line)

        description = name
        if body_lines:
            desc_text = "\n".join(body_lines).strip()
            if desc_text:
                description = f"{name}: {desc_text}"

        goals.append(
            _GoalFileDefinition(
                id=metadata.get("id", name.lower().replace(" ", "-")),
                description=description,
                priority=metadata.get("priority", 50),
                depends_on=metadata.get("depends_on", []),
                informs=metadata.get("informs", []),
                conflicts_with=metadata.get("conflicts_with", []),
            )
        )

    return goals


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    """Split YAML frontmatter from body text."""
    if not text.startswith("---"):
        return None, text
    parts = text.split("---", 2)
    if len(parts) >= _FRONTMATTER_SPLIT_MIN:
        return parts[1].strip(), parts[2].strip()
    return None, text


def _extract_success_criteria(body: str) -> list[str]:
    """Extract checklist items from Success Criteria section."""
    criteria = []
    in_criteria = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("## Success Criteria"):
            in_criteria = True
            continue
        if in_criteria:
            if stripped.startswith("- "):
                criteria.append(stripped[2:].strip())
            elif stripped.startswith("##"):
                break
    return criteria


def _parse_yaml_list(raw: str) -> list[str]:
    """Parse a YAML list string like '[a, b]' or '[]'."""
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [x.strip().strip('"').strip("'") for x in inner.split(",") if x.strip()]
    return []


def _update_frontmatter_status(file_path: str, status: str) -> None:
    """Update the status field in YAML frontmatter of a markdown file."""
    path = Path(file_path)
    text = path.read_text()
    frontmatter, body = _split_frontmatter(text)
    if not frontmatter:
        return

    import yaml

    fm = yaml.safe_load(frontmatter) or {}
    fm["status"] = status

    # Re-serialize frontmatter
    new_fm = yaml.dump(fm, default_flow_style=False, sort_keys=False).strip()
    new_text = f"---\n{new_fm}\n---\n\n{body}\n"
    path.write_text(new_text)
