"""GoalDAGVerifier - LLM-driven DAG verification coordinator (RFC-625).

Coordinates:
1. Background health verification (periodic)
2. Post-completion verification (event-triggered)
3. Placement analysis for new goal intake

Uses DagVerificationReasoner for structured LLM calls.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.autopilot.monitor_models import (
    DagHealthReport,
    DecomposeSuggestion,
    GoalPlacement,
    MergeSuggestion,
)
from soothe.autopilot.verifier_reasoner import (
    CompletionVerificationContext,
    DagSnapshot,
    DagVerificationReasoner,
    GoalPlacementContext,
)
from soothe.context.engine import ContextEngine

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class GoalDAGVerifier:
    """LLM-driven goal DAG verification and restructuring suggestions.

    Uses DagVerificationReasoner for structured LLM calls. Falls back to
    heuristics when LLM fails or is disabled.

    Args:
        ce: ContextEngine instance for goal access.
        config: SootheConfig for LLM model access.

    Attributes:
        _reasoner: DagVerificationReasoner for LLM calls.
    """

    def __init__(self, ce: ContextEngine, config: SootheConfig) -> None:
        """Initialize verifier with ContextEngine and config.

        Args:
            ce: ContextEngine instance
            config: SootheConfig for LLM model access
        """
        self._ce = ce
        self._config = config
        self._reasoner = DagVerificationReasoner(config)

    async def verify_dag_health(self) -> DagHealthReport:
        """LLM-driven periodic background verification.

        Process:
          1. Gather full DAG snapshot (goals, statuses, step progress)
          2. Call DagVerificationReasoner.verify_health() for LLM analysis
          3. Parse LLM response into structured DagHealthReport
          4. Report includes: reset, remove, merge, decompose suggestions

        Falls back to heuristics on LLM failure.

        Returns:
            DagHealthReport with restructuring suggestions.
        """
        goals = self._ce.get_goals_by_status(None)
        snapshot = DagSnapshot.from_goals(goals)

        try:
            response = await self._reasoner.verify_health(snapshot)
            return self._convert_health_response(response)
        except Exception:
            logger.exception("LLM health verification failed, using heuristics")
            return self._heuristic_health_check(goals)

    def _convert_health_response(self, response: Any) -> DagHealthReport:
        """Convert DagHealthResponse to DagHealthReport.

        Args:
            response: DagHealthResponse from LLM.

        Returns:
            DagHealthReport for monitor consumption.
        """
        report = DagHealthReport(
            suggest_reset=response.reset_goals,
            suggest_remove=response.remove_goals,
            suggest_priority_adjust=response.priority_adjustments,
            reasoning=response.reasoning,
        )

        # Convert merge suggestions
        for merge in response.merge_goals:
            report.suggest_merge.append(
                MergeSuggestion(
                    goal_ids=merge.goal_ids,
                    merged_description=merge.merged_description,
                )
            )

        # Convert decompose suggestions
        for decomp in response.decompose_goals:
            report.suggest_decompose.append(
                DecomposeSuggestion(
                    goal_id=decomp.goal_id,
                    subgoals=decomp.subgoals,
                )
            )

        return report

    def _heuristic_health_check(self, goals: list[Any]) -> DagHealthReport:
        """Fallback heuristic health check.

        Args:
            goals: List of all goals in DAG.

        Returns:
            DagHealthReport with heuristic suggestions.
        """
        report = DagHealthReport(reasoning="Heuristic-based verification (LLM fallback)")

        pending = [g for g in goals if g.status == "pending"]
        for goal in pending:
            # Check for orphaned goals (deps not satisfied)
            deps_met = all(
                self._ce.get_goal_sync(dep) is not None
                and self._ce.get_goal_sync(dep).status in ("completed", "failed", "cancelled")
                for dep in goal.depends_on
            )
            if goal.depends_on and not deps_met:
                report.suggest_remove.append(goal.id)

        return report

    async def verify_dag_post_completion(self, completed_goal_id: str) -> dict[str, Any]:
        """LLM-driven analysis after goal completion.

        Process:
          1. Gather completed goal + its steps + outcomes
          2. Gather pending goals that may be affected
          3. Call DagVerificationReasoner.verify_post_completion()
          4. Parse into structured response

        Falls back to heuristics on LLM failure.

        Args:
            completed_goal_id: ID of the completed goal.

        Returns:
            Dict with new goals, redundant goals, ready goals, decomposition.
        """
        completed = self._ce.get_goal_sync(completed_goal_id)
        if not completed:
            return {}

        pending = self._ce.get_goals_by_status("pending")
        active = self._ce.get_goals_by_status("active")

        context = CompletionVerificationContext.from_goal(completed, pending, active)

        try:
            response = await self._reasoner.verify_post_completion(context)
            return {
                "completed_goal_id": completed_goal_id,
                "new_goals": [
                    {
                        "description": ng.description,
                        "priority": ng.priority,
                        "depends_on": list(ng.depends_on),
                    }
                    for ng in response.new_goals
                ],
                "redundant_goals": response.redundant_goals,
                "ready_goals": response.ready_goals,
                "decomposition": (
                    {
                        "goal_id": response.decomposition.goal_id,
                        "subgoals": response.decomposition.subgoals,
                    }
                    if response.decomposition
                    else None
                ),
                "reasoning": response.reasoning,
            }
        except Exception:
            logger.exception("LLM post-completion analysis failed, using heuristics")
            return {
                "completed_goal_id": completed_goal_id,
                "pending_count": len(pending),
                "reasoning": "Heuristic-based analysis (LLM fallback)",
            }

    async def analyze_placement(self, description: str) -> GoalPlacement:
        """LLM-driven placement analysis for new goal.

        Process:
          1. Gather current DAG state (active, pending, recently completed)
          2. Call DagVerificationReasoner.analyze_placement()
          3. Parse into GoalPlacement

        Falls back to load-based heuristic on LLM failure.

        Args:
            description: Goal description to analyze.

        Returns:
            GoalPlacement with priority, dependencies, merge suggestion.
        """
        goals = self._ce.get_goals_by_status(None)
        context = GoalPlacementContext.from_description(description, goals)

        try:
            response = await self._reasoner.analyze_placement(context)
            return GoalPlacement(
                adjusted_priority=response.priority,
                suggested_dependencies=list(response.depends_on),
                suggested_informs=list(response.informs),
                merge_with=response.merge_with,
                estimated_complexity=response.complexity,
                reasoning=response.reasoning,
            )
        except Exception:
            logger.exception("LLM placement analysis failed, using heuristics")
            # Fallback heuristic
            active = self._ce.get_goals_by_status("active")
            pending = self._ce.get_goals_by_status("pending")
            load = len(active) + len(pending)
            return GoalPlacement(
                adjusted_priority=max(20, 50 - load),
                reasoning=f"Priority adjusted based on DAG load ({load} goals) (LLM fallback)",
            )

    def _build_dag_snapshot(self) -> dict[str, Any]:
        """Build serializable DAG snapshot for LLM context."""
        goals = self._ce.get_goals_by_status(None)
        return {
            "goals": [
                {
                    "id": g.id,
                    "description": g.description,
                    "status": g.status,
                    "priority": g.priority,
                    "depends_on": g.depends_on,
                    "step_count": g.steps.total_steps,
                    "completed_steps": g.steps.completed_steps,
                }
                for g in goals
            ],
            "total_goals": len(goals),
        }

    async def apply_health_report(self, report: DagHealthReport) -> None:
        """Apply DAG health verification suggestions via ContextEngine planning APIs.

        Args:
            report: Structured health report from :meth:`verify_dag_health`.
        """
        goal_planner = self._ce.planning.goal

        for decomp in report.suggest_decompose:
            goal_planner.apply_llm_subgoals(decomp.goal_id, decomp.subgoals)

        for goal_id in report.suggest_remove:
            try:
                await self._ce.cancel_goal(goal_id, reason="dag_health_verification")
            except Exception:
                logger.warning(
                    "Failed to cancel goal %s from health report", goal_id, exc_info=True
                )

        for goal_id in report.suggest_reset:
            goal = self._ce.get_goal_sync(goal_id)
            if goal is None:
                continue
            if goal.status in ("blocked", "suspended"):
                try:
                    await self._ce.reactivate_goal(goal_id)
                except Exception:
                    logger.warning("Failed to reactivate goal %s", goal_id, exc_info=True)

        for goal_id, priority in report.suggest_priority_adjust.items():
            goal = self._ce.get_goal_sync(goal_id)
            if goal is not None:
                goal.priority = max(0, min(100, int(priority)))

        for merge in report.suggest_merge:
            logger.info(
                "Merge suggestion (not auto-applied): goals=%s desc=%s",
                merge.goal_ids,
                merge.merged_description[:80],
            )

    async def apply_post_completion(self, result: dict[str, Any]) -> None:
        """Apply post-completion verification suggestions to the CE DAG.

        Args:
            result: Dict returned by :meth:`verify_dag_post_completion`.
        """
        if not result:
            return

        completed_id = result.get("completed_goal_id") or ""
        goal_planner = self._ce.planning.goal

        new_goals = result.get("new_goals") or []
        if new_goals:
            await goal_planner.reflect_and_create_goals(
                completed_id,
                new_goals=new_goals,
            )

        decomp = result.get("decomposition")
        if decomp and decomp.get("goal_id"):
            goal_planner.apply_llm_subgoals(
                decomp["goal_id"],
                decomp.get("subgoals") or [],
                reasoning=result.get("reasoning", ""),
            )

        for redundant_id in result.get("redundant_goals") or []:
            try:
                await self._ce.cancel_goal(redundant_id, reason="post_completion_redundant")
            except Exception:
                logger.warning(
                    "Failed to cancel redundant goal %s",
                    redundant_id,
                    exc_info=True,
                )
