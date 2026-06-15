"""Goal scheduling for ContextEngine (RFC-624 Phase 3c).

Extracts scheduling logic from GoalEngine for use with ContextEngine's
GoalStepDAG. Provides ready-goal computation, atomic goal claiming,
and completion checking.
"""

from __future__ import annotations

import logging

from soothe.foundation.context.models import TERMINAL_STATES, GoalNode, GoalStepDAG

logger = logging.getLogger(__name__)


class GoalScheduler:
    """Goal scheduling extracted from GoalEngine for use with ContextEngine.

    Implements the same scheduling algorithm (priority DESC, created_at ASC,
    dependency satisfaction, conflict avoidance) but operates on GoalStepDAG
    instead of GoalEngine's internal _goals dict.
    """

    def __init__(self, dag: GoalStepDAG) -> None:
        self._dag = dag

    def peek_ready_goals(self, limit: int = 1) -> list[GoalNode]:
        """Compute ready goals (read-only, no status mutation, RFC-625).

        Delegates to GoalStepDAG.peek_ready_goals which implements:
        - Filter by status == "pending"
        - Check hard dependencies (all in TERMINAL_STATES)
        - Check conflicts_with (no active goal)
        - Sort by (-priority, created_at)
        """
        return self._dag.peek_ready_goals(limit=limit)

    def claim_goal(
        self,
        goal_id: str,
        *,
        loop_id: str | None = None,
    ) -> GoalNode | None:
        """Atomically transition a goal from pending to active.

        Delegates to GoalStepDAG.claim_goal which re-checks conflict
        constraints at claim time. Returns the GoalNode if claimed,
        None if ineligible.
        """
        return self._dag.claim_goal(goal_id, loop_id=loop_id)

    def is_complete(self) -> bool:
        """Check if all goals are in terminal states."""
        if not self._dag.goals:
            return True
        return all(g.status in TERMINAL_STATES for g in self._dag.goals.values())

    def check_reactivatable_goals(self) -> list[GoalNode]:
        """Find blocked/suspended goals whose deps are now resolved.

        Returns goals that could be transitioned back to pending.
        Does NOT perform the transition — caller decides.
        """
        reactivatable: list[GoalNode] = []
        for goal in self._dag.goals.values():
            if goal.status not in ("blocked", "suspended"):
                continue
            # Check if all hard dependencies are now terminal
            deps_met = all(
                (dep := self._dag.goals.get(dep_id)) is not None and dep.status in TERMINAL_STATES
                for dep_id in goal.depends_on
            )
            if deps_met:
                reactivatable.append(goal)
        return reactivatable
