"""Goal scheduling for ContextEngine."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from soothe.context.models import TERMINAL_STATES, GoalNode, GoalStepDAG

if TYPE_CHECKING:
    from soothe.context.planning_goal_planner import GoalPlanningSubengine
    from soothe.context.planning_step_planner import StepPlanningSubengine

logger = logging.getLogger(__name__)


class GoalScheduler:
    """Goal scheduling for ContextEngine, operating on GoalStepDAG."""

    def __init__(self, dag: GoalStepDAG) -> None:
        self._dag = dag

    def peek_ready_goals(self, limit: int = 1) -> list[GoalNode]:
        """Compute ready goals without mutating status (read-only)."""
        return self._dag.peek_ready_goals(limit=limit)

    def claim_goal(
        self,
        goal_id: str,
        *,
        loop_id: str | None = None,
    ) -> GoalNode | None:
        """Atomically transition a goal from pending to active."""
        return self._dag.claim_goal(goal_id, loop_id=loop_id)

    def is_complete(self) -> bool:
        """Check if all goals are in terminal states."""
        if not self._dag.goals:
            return True
        return all(g.status in TERMINAL_STATES for g in self._dag.goals.values())

    def check_reactivatable_goals(self) -> list[GoalNode]:
        """Find blocked/suspended goals whose dependencies are now resolved."""
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


@dataclass
class PlanningFacade:
    """Unified access point for ContextEngine's planning capabilities."""

    step: StepPlanningSubengine
    goal: GoalPlanningSubengine
    scheduler: GoalScheduler
