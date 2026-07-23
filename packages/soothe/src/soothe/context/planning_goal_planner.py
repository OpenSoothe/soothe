"""Goal-level planning subengine for ContextEngine.

Provides goal decomposition helpers, multi-goal orchestration, and
reflection-driven goal creation. LLM-driven decomposition is wired
through the AutopilotMonitor verifier path (apply_llm_subgoals).
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.context.models import GoalNode, GoalStepDAG
from soothe.context.planning_models import (
    DecompositionResult,
    SubGoalSpec,
)

logger = logging.getLogger(__name__)


class GoalPlanningSubengine:
    """Manages goal-level planning: decomposition helpers, orchestration, and lifecycle.

    Provides goal creation from LLM decomposition payloads, multi-goal
    orchestration strategy computation, and reflection-driven follow-up
    goal creation. LLM decomposition results flow in from the
    AutopilotMonitor verifier; this subengine materializes them in the DAG.
    """

    def __init__(self, dag: GoalStepDAG) -> None:
        self._dag = dag

    # --- Goal decomposition ---

    def create_subgoals(
        self,
        parent_id: str,
        result: DecompositionResult,
    ) -> list[GoalNode]:
        """Create GoalNodes in the DAG from a decomposition result.

        Validates depth limits and creates child goals with proper
        parent_id, depends_on, and priority fields.
        """
        created: list[GoalNode] = []
        id_map: dict[str, str] = {}  # spec index → actual goal ID

        for i, spec in enumerate(result.subgoals):
            # Resolve depends_on: spec references → actual goal IDs
            resolved_deps = [id_map[ref] for ref in spec.depends_on if ref in id_map]

            child = GoalNode(
                description=spec.description,
                priority=spec.priority,
                parent_id=parent_id,
                depends_on=resolved_deps,
                conflicts_with=spec.conflicts_with,
                informs=spec.informs,
                source="decomposition",
            )

            try:
                self._dag.add_goal(child)
                id_map[str(i)] = child.id
                created.append(child)
                logger.info(
                    "GoalPlanningSubengine: created subgoal %s (%s) under %s",
                    child.id,
                    spec.description[:50],
                    parent_id,
                )
            except ValueError:
                logger.warning(
                    "GoalPlanningSubengine: depth limit exceeded for subgoal %d under %s",
                    i,
                    parent_id,
                )
                break

        return created

    def apply_llm_subgoals(
        self,
        parent_id: str,
        subgoals: list[dict[str, Any]],
        *,
        max_subgoals: int = 5,
        reasoning: str = "",
    ) -> list[GoalNode]:
        """Create child goals from LLM decomposition payloads (AutopilotMonitor / verifier).

        Args:
            parent_id: Parent goal to attach subgoals under.
            subgoals: List of dicts with description, priority, depends_on keys.
            max_subgoals: Upper bound on children created.
            reasoning: Optional decomposition rationale for logging.

        Returns:
            Created GoalNode instances.
        """
        specs: list[SubGoalSpec] = []
        for sg in subgoals[:max_subgoals]:
            description = (sg.get("description") or "").strip()
            if not description:
                continue
            raw_deps = sg.get("depends_on") or []
            specs.append(
                SubGoalSpec(
                    description=description,
                    priority=int(sg.get("priority", 50)),
                    depends_on=[str(d) for d in raw_deps],
                )
            )
        if not specs:
            return []
        result = DecompositionResult(
            subgoals=specs,
            reasoning=reasoning or "LLM decomposition",
        )
        return self.create_subgoals(parent_id, result)

    def create_follow_up_goals(
        self,
        new_goals: list[dict[str, Any]],
        *,
        parent_id: str | None = None,
        source: str = "reflection",
    ) -> list[GoalNode]:
        """Create follow-up goals from post-completion LLM suggestions.

        Args:
            new_goals: Dicts with description, priority, depends_on.
            parent_id: Optional parent goal for lineage.
            source: Goal source tag.

        Returns:
            Created GoalNode instances.
        """
        created: list[GoalNode] = []
        for ng in new_goals:
            description = (ng.get("description") or "").strip()
            if not description:
                continue
            child = GoalNode(
                description=description,
                priority=int(ng.get("priority", 50)),
                parent_id=parent_id,
                depends_on=[str(d) for d in (ng.get("depends_on") or [])],
                source=source,
            )
            try:
                self._dag.add_goal(child)
                created.append(child)
                logger.info(
                    "GoalPlanningSubengine: follow-up goal %s under %s",
                    child.id,
                    parent_id or "root",
                )
            except ValueError:
                logger.warning(
                    "GoalPlanningSubengine: depth limit exceeded for follow-up under %s",
                    parent_id,
                )
                break
        return created

    # --- Reflection-driven goal creation ---

    async def reflect_and_create_goals(
        self,
        completed_goal_id: str,
        *,
        new_goals: list[dict[str, Any]] | None = None,
    ) -> list[GoalNode]:
        """Create follow-up goals after a goal completes.

        When ``new_goals`` is provided (from post-completion verification),
        materializes them in the DAG. Callers may also invoke
        :meth:`create_follow_up_goals` directly.

        Args:
            completed_goal_id: ID of the completed parent goal.
            new_goals: Optional LLM-suggested follow-up goal specs.

        Returns:
            Created GoalNode instances (empty when no suggestions).
        """
        if not new_goals:
            logger.debug(
                "GoalPlanningSubengine.reflect_and_create_goals: no suggestions for %s",
                completed_goal_id,
            )
            return []
        return self.create_follow_up_goals(
            new_goals,
            parent_id=completed_goal_id,
            source="reflection",
        )
