"""GoalIntakeHandler - new goal intake with placement analysis (RFC-625).

Handles:
- Workspace conflict check via WorkspaceReservation
- Placement analysis via GoalDAGVerifier
- Goal creation via ContextEngine
- Batch submission with dependency resolution
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.foundation.autopilot.monitor.goal_dag_verifier import GoalDAGVerifier
from soothe.foundation.autopilot.monitor.models import GoalIntakeResult
from soothe.foundation.context.engine import ContextEngine

if TYPE_CHECKING:
    from soothe.foundation.autopilot.service.workspace_reservation import WorkspaceReservation

logger = logging.getLogger(__name__)


class GoalIntakeHandler:
    """Handle new goal intake with placement analysis and conflict checking."""

    def __init__(
        self,
        ce: ContextEngine,
        verifier: GoalDAGVerifier,
        workspace_reservation: WorkspaceReservation | None = None,
    ) -> None:
        """Initialize handler.

        Args:
            ce: ContextEngine instance
            verifier: GoalDAGVerifier for placement analysis
            workspace_reservation: Optional WorkspaceReservation for conflict checks
        """
        self._ce = ce
        self._verifier = verifier
        self._reservation = workspace_reservation

    async def submit_goal(
        self,
        description: str,
        *,
        priority: int = 50,
        workspace: str | None = None,
        depends_on: list[str] | None = None,
        source: str = "user",
        **kwargs: Any,
    ) -> GoalIntakeResult:
        """Submit a new goal to the DAG.

        Args:
            description: Goal description
            priority: Initial priority (may be adjusted)
            workspace: Optional workspace constraint
            depends_on: Optional initial dependencies
            source: Goal origin ("user", "directive", "decomposition")

        Returns:
            GoalIntakeResult with status and goal_id
        """
        # Workspace conflict check
        if workspace and self._reservation:
            conflict = self._reservation.conflicts_with_active(workspace)
            if conflict:
                return GoalIntakeResult(
                    status="rejected",
                    reason=f"Workspace conflicts with active goal {conflict}",
                )

        # Placement analysis
        placement = await self._verifier.analyze_placement(description)
        final_deps = list(set(depends_on or []) | set(placement.suggested_dependencies))

        # Create via CE
        goal = await self._ce.create_goal(
            description,
            priority=placement.adjusted_priority,
            depends_on=final_deps,
            workspace=workspace,
            source=source,
            **kwargs,
        )

        logger.info("Created goal %s via intake handler", goal.id)

        return GoalIntakeResult(
            status="accepted",
            goal_id=goal.id,
            adjusted_priority=placement.adjusted_priority,
            suggested_dependencies=placement.suggested_dependencies,
        )

    async def submit_goals_batch(
        self,
        goals: list[dict[str, Any]],
    ) -> list[GoalIntakeResult]:
        """Submit multiple goals with dependency resolution.

        Args:
            goals: List of goal specs with description, priority, depends_on

        Returns:
            List of GoalIntakeResult for each goal
        """
        # Order by dependencies (simple topological sort)
        ordered = self._order_by_dependencies(goals)
        results: list[GoalIntakeResult] = []

        for spec in ordered:
            result = await self.submit_goal(
                spec.get("description", ""),
                priority=spec.get("priority", 50),
                workspace=spec.get("workspace"),
                depends_on=spec.get("depends_on"),
                source=spec.get("source", "user"),
            )
            results.append(result)

            # Mark dependents as skipped if this was rejected
            if result.status == "rejected":
                self._mark_dependents_skipped(spec.get("id", ""), goals, results)

        return results

    def _order_by_dependencies(self, goals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Order goals by dependencies (topological sort)."""
        # Simple implementation: goals with no deps first
        ordered: list[dict[str, Any]] = []
        remaining = list(goals)
        added_ids: set[str] = set()

        while remaining:
            for goal in remaining:
                goal_id = goal.get("id", "")
                deps = set(goal.get("depends_on", []))
                if not deps or deps.issubset(added_ids):
                    ordered.append(goal)
                    added_ids.add(goal_id)
                    remaining.remove(goal)
                    break
            else:
                # Circular dependency or unresolved - add remaining
                ordered.extend(remaining)
                break

        return ordered

    def _mark_dependents_skipped(
        self,
        failed_id: str,
        goals: list[dict[str, Any]],
        results: list[GoalIntakeResult],
    ) -> None:
        """Mark goals that depend on failed goal as skipped."""
        for goal in goals:
            if failed_id in goal.get("depends_on", []):
                # Find result for this goal and mark as skipped
                goal_id = goal.get("id", "")
                for r in results:
                    if r.goal_id == goal_id:
                        r.status = "skipped"
                        r.reason = f"Depends on rejected goal {failed_id}"

    async def cancel_goal(self, goal_id: str) -> bool:
        """Cancel a pending/active goal via CE.

        Args:
            goal_id: Goal to cancel

        Returns:
            True if cancelled, False if goal not found or in terminal state
        """
        goal = self._ce.get_goal_sync(goal_id)
        if goal is None:
            return False

        terminal = ("completed", "failed", "cancelled")
        if goal.status in terminal:
            return False

        await self._ce.cancel_goal(goal_id)

        if self._reservation:
            self._reservation.release(goal_id)

        logger.info("Cancelled goal %s", goal_id)
        return True
