"""GoalDAGVerifier - LLM-driven DAG verification coordinator (RFC-625).

Coordinates:
1. Background health verification (periodic)
2. Post-completion verification (event-triggered)
3. Placement analysis for new goal intake

Uses DagVerificationReasoner for structured LLM calls.
IG-680: health remove guardrails, wire_dependencies, decompose budget.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from soothe.autopilot.evidence_grounding import workspace_has_deliverables
from soothe.autopilot.monitor_models import (
    DagHealthReport,
    DecomposeSuggestion,
    GoalPlacement,
    MergeSuggestion,
    WireDependencySuggestion,
)
from soothe.autopilot.verifier_reasoner import (
    CompletionVerificationContext,
    DagSnapshot,
    DagVerificationReasoner,
    GoalPlacementContext,
)
from soothe.context.engine import ContextEngine
from soothe.context.models import TERMINAL_STATES

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

# Max one health/post-completion decompose wave per parent within this window.
_DECOMPOSE_COOLDOWN_SECONDS = 300.0

CancelGoalFn = Callable[[str, str], Awaitable[Any]]


class GoalDAGVerifier:
    """LLM-driven goal DAG verification and restructuring suggestions.

    Uses DagVerificationReasoner for structured LLM calls. Falls back to
    heuristics when LLM fails or is disabled.

    Args:
        ce: ContextEngine instance for goal access.
        config: SootheConfig for LLM model access.
        cancel_goal: Optional AutopilotService.cancel_goal for cascading cancels.
    """

    def __init__(
        self,
        ce: ContextEngine,
        config: SootheConfig,
        *,
        cancel_goal: CancelGoalFn | None = None,
    ) -> None:
        """Initialize verifier with ContextEngine and config.

        Args:
            ce: ContextEngine instance
            config: SootheConfig for LLM model access
            cancel_goal: Optional async ``(goal_id, reason) -> ...`` cascade cancel
        """
        self._ce = ce
        self._config = config
        self._reasoner = DagVerificationReasoner(config)
        self._cancel_goal = cancel_goal
        self._decompose_at: dict[str, float] = {}

    def bind_cancel_goal(self, cancel_goal: CancelGoalFn) -> None:
        """Wire AutopilotService.cancel_goal for health removals that need cascade."""
        self._cancel_goal = cancel_goal

    async def verify_dag_health(self) -> DagHealthReport:
        """LLM-driven periodic background verification.

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
        """Convert DagHealthResponse to DagHealthReport."""
        report = DagHealthReport(
            suggest_reset=response.reset_goals,
            suggest_remove=response.remove_goals,
            suggest_priority_adjust=response.priority_adjustments,
            reasoning=response.reasoning,
        )

        for merge in response.merge_goals:
            report.suggest_merge.append(
                MergeSuggestion(
                    goal_ids=merge.goal_ids,
                    merged_description=merge.merged_description,
                )
            )

        for decomp in response.decompose_goals:
            report.suggest_decompose.append(
                DecomposeSuggestion(
                    goal_id=decomp.goal_id,
                    subgoals=decomp.subgoals,
                )
            )

        for wire in getattr(response, "wire_dependencies", None) or []:
            report.wire_dependencies.append(
                WireDependencySuggestion(
                    goal_id=wire.goal_id,
                    depends_on=list(wire.depends_on),
                )
            )

        return report

    def _job_root_id(self, goal_id: str) -> str | None:
        """Walk parents to the job root id (parent_id is None)."""
        goal = self._ce.get_goal_sync(goal_id)
        if goal is None:
            return None
        seen: set[str] = set()
        while goal is not None and goal.parent_id and goal.parent_id not in seen:
            seen.add(goal.id)
            parent = self._ce.get_goal_sync(goal.parent_id)
            if parent is None:
                break
            goal = parent
        return goal.id if goal is not None else None

    def _filter_wire_depends_on(self, goal_id: str, depends_on: list[str]) -> list[str] | None:
        """Drop child→job-root edges; return None if nothing remains to apply."""
        root_id = self._job_root_id(goal_id)
        if root_id is None:
            return list(depends_on)
        # Never wire a child to depend on its job root (deadlocks rail pipelines).
        filtered = [d for d in depends_on if d != root_id]
        dropped = len(depends_on) - len(filtered)
        if dropped:
            logger.info(
                "Health wire skipped child→job-root edge(s) for %s → %s",
                goal_id,
                root_id,
            )
        if not filtered and depends_on:
            return None
        return filtered

    def _heuristic_health_check(self, goals: list[Any]) -> DagHealthReport:
        """Fallback heuristic health check."""
        report = DagHealthReport(reasoning="Heuristic-based verification (LLM fallback)")

        pending = [g for g in goals if g.status == "pending"]
        for goal in pending:
            deps_met = all(
                self._ce.get_goal_sync(dep) is not None
                and self._ce.get_goal_sync(dep).status in ("completed", "failed", "cancelled")
                for dep in goal.depends_on
            )
            if goal.depends_on and not deps_met:
                # Suggest reset rather than remove for orphaned pending (safer).
                report.suggest_reset.append(goal.id)

        return report

    def may_auto_remove(self, goal_id: str) -> bool:
        """Return True if health may auto-remove this goal (IG-680 AH-1).

        Only cancelled/failed clutter with zero dependents and no non-terminal
        descendants. Job roots that are still non-terminal are never removable.
        """
        goal = self._ce.get_goal_sync(goal_id)
        if goal is None:
            return False

        if goal.status not in ("cancelled", "failed"):
            logger.info(
                "Health remove skipped for %s: status=%s (only cancelled/failed clutter)",
                goal_id,
                goal.status,
            )
            return False

        # Never strip a job root that still has live work under it.
        subtree = self._ce.collect_subtree_ids(goal_id)
        for gid in subtree:
            if gid == goal_id:
                continue
            child = self._ce.get_goal_sync(gid)
            if child is not None and child.status not in TERMINAL_STATES:
                logger.info(
                    "Health remove skipped for %s: non-terminal descendant %s",
                    goal_id,
                    gid,
                )
                return False

        dependents = self._ce.get_goal_dependents(goal_id)
        for dep_id in dependents:
            dep = self._ce.get_goal_sync(dep_id)
            if dep is not None and dep.status not in TERMINAL_STATES:
                logger.info(
                    "Health remove skipped for %s: non-terminal dependent %s",
                    goal_id,
                    dep_id,
                )
                return False

        return True

    def _decompose_allowed(self, parent_id: str) -> bool:
        """Enforce per-parent decompose cooldown (IG-680 AH-4)."""
        now = time.monotonic()
        last = self._decompose_at.get(parent_id)
        if last is not None and (now - last) < _DECOMPOSE_COOLDOWN_SECONDS:
            logger.info(
                "Decompose skipped for %s: cooldown %.0fs remaining",
                parent_id,
                _DECOMPOSE_COOLDOWN_SECONDS - (now - last),
            )
            return False
        return True

    def _mark_decomposed(self, parent_id: str) -> None:
        self._decompose_at[parent_id] = time.monotonic()

    async def verify_dag_post_completion(self, completed_goal_id: str) -> dict[str, Any]:
        """LLM-driven analysis after goal completion."""
        completed = self._ce.get_goal_sync(completed_goal_id)
        if not completed:
            return {}

        # Skip further decompose when workspace already shows deliverables.
        if workspace_has_deliverables(getattr(completed, "workspace", None)):
            logger.info(
                "Post-completion skip decompose for %s: workspace deliverables present",
                completed_goal_id,
            )
            return {
                "completed_goal_id": completed_goal_id,
                "new_goals": [],
                "redundant_goals": [],
                "ready_goals": [],
                "decomposition": None,
                "reasoning": "Workspace deliverable probe satisfied; no further decompose",
                "skip_decompose": True,
            }

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
        """LLM-driven placement analysis for new goal."""
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
            active = self._ce.get_goals_by_status("active")
            pending = self._ce.get_goals_by_status("pending")
            load = len(active) + len(pending)
            return GoalPlacement(
                adjusted_priority=max(20, 50 - load),
                reasoning=f"Priority adjusted based on DAG load ({load} goals) (LLM fallback)",
            )

    def _build_dag_snapshot(self) -> dict[str, Any]:
        """Build serializable DAG snapshot for LLM context / tests."""
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
        """Apply DAG health verification suggestions via ContextEngine planning APIs."""
        goal_planner = self._ce.planning.goal

        for wire in report.wire_dependencies:
            filtered = self._filter_wire_depends_on(wire.goal_id, list(wire.depends_on))
            if filtered is None:
                continue
            try:
                await self._ce.update_dependencies(wire.goal_id, filtered)
                logger.info(
                    "Health wired depends_on for %s → %s",
                    wire.goal_id,
                    filtered,
                )
            except Exception:
                logger.warning(
                    "Failed to wire dependencies for %s",
                    wire.goal_id,
                    exc_info=True,
                )

        for decomp in report.suggest_decompose:
            parent = self._ce.get_goal_sync(decomp.goal_id)
            if parent is not None and workspace_has_deliverables(
                getattr(parent, "workspace", None)
            ):
                logger.info(
                    "Health decompose skipped for %s: workspace deliverables present",
                    decomp.goal_id,
                )
                continue
            if not self._decompose_allowed(decomp.goal_id):
                continue
            created = goal_planner.apply_llm_subgoals(decomp.goal_id, decomp.subgoals)
            if created:
                self._mark_decomposed(decomp.goal_id)

        for goal_id in report.suggest_remove:
            if not self.may_auto_remove(goal_id):
                continue
            try:
                goal = self._ce.get_goal_sync(goal_id)
                if goal is None:
                    continue
                # Terminal clutter: prefer DAG remove; cascade cancel only if still open.
                if goal.status in TERMINAL_STATES:
                    removed = await self._ce.remove_goal(goal_id)
                    if not removed:
                        logger.info(
                            "Health remove of terminal %s deferred (dependents remain)",
                            goal_id,
                        )
                elif self._cancel_goal is not None:
                    await self._cancel_goal(goal_id, "dag_health_verification")
                else:
                    await self._ce.cancel_goal(goal_id, reason="dag_health_verification")
            except Exception:
                logger.warning(
                    "Failed to cancel/remove goal %s from health report",
                    goal_id,
                    exc_info=True,
                )

        for goal_id in report.suggest_reset:
            goal = self._ce.get_goal_sync(goal_id)
            if goal is None:
                continue
            if goal.status not in ("blocked", "suspended"):
                continue
            # IG-691: do not undo consensus send-back budget exhaustion.
            if goal.status == "suspended" and goal.send_back_count >= goal.max_send_backs:
                logger.info(
                    "Health reset skipped for %s: consensus send_back budget exhausted (%d/%d)",
                    goal_id,
                    goal.send_back_count,
                    goal.max_send_backs,
                )
                continue
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
        """Apply post-completion verification suggestions to the CE DAG."""
        if not result or result.get("skip_decompose"):
            return

        completed_id = result.get("completed_goal_id") or ""
        goal_planner = self._ce.planning.goal

        new_goals = result.get("new_goals") or []
        if new_goals:
            if completed_id and not self._decompose_allowed(completed_id):
                new_goals = []
            else:
                created = await goal_planner.reflect_and_create_goals(
                    completed_id,
                    new_goals=new_goals,
                )
                if created and completed_id:
                    self._mark_decomposed(completed_id)

        decomp = result.get("decomposition")
        if decomp and decomp.get("goal_id"):
            parent_id = decomp["goal_id"]
            parent = self._ce.get_goal_sync(parent_id)
            if parent is not None and workspace_has_deliverables(
                getattr(parent, "workspace", None)
            ):
                logger.info(
                    "Post-completion decompose skipped for %s: deliverables present",
                    parent_id,
                )
            elif self._decompose_allowed(parent_id):
                created = goal_planner.apply_llm_subgoals(
                    parent_id,
                    decomp.get("subgoals") or [],
                    reasoning=result.get("reasoning", ""),
                )
                if created:
                    self._mark_decomposed(parent_id)

        for redundant_id in result.get("redundant_goals") or []:
            if not self.may_auto_remove(redundant_id):
                # Only cancel if already cancelled/failed clutter path allows; otherwise skip.
                goal = self._ce.get_goal_sync(redundant_id)
                if goal is None or goal.status not in ("cancelled", "failed"):
                    logger.info(
                        "Post-completion redundant skip for %s (not removable clutter)",
                        redundant_id,
                    )
                    continue
            try:
                if self._cancel_goal is not None:
                    await self._cancel_goal(redundant_id, "post_completion_redundant")
                else:
                    await self._ce.cancel_goal(redundant_id, reason="post_completion_redundant")
            except Exception:
                logger.warning(
                    "Failed to cancel redundant goal %s",
                    redundant_id,
                    exc_info=True,
                )
