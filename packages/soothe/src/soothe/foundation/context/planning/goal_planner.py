"""Goal-level planning subengine for ContextEngine (RFC-624 Phase 3c).

Provides goal decomposition, multi-goal orchestration, and reflection-driven
goal creation. Phase 1 implements the structure with stub decomposition;
Phase 2 adds LLM-driven decomposition.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.foundation.context.models import GoalNode, GoalStepDAG
from soothe.foundation.context.planning.models import (
    DecompositionRequest,
    DecompositionResult,
    OrchestrationStrategy,
    SubGoalSpec,
)

logger = logging.getLogger(__name__)


class GoalPlanningSubengine:
    """Manages goal-level planning: decomposition, orchestration, and lifecycle.

    Provides three capabilities not present in the current architecture:
    1. LLM-driven goal decomposition (complex objective → sub-goal DAG)
    2. Multi-goal orchestration strategy
    3. Reflection-driven goal creation

    Eventually replaces GoalEngine in AutopilotService, but during
    migration, both can coexist.
    """

    def __init__(self, dag: GoalStepDAG) -> None:
        self._dag = dag

    # --- Goal decomposition ---

    async def decompose_goal(
        self,
        request: DecompositionRequest,
    ) -> DecompositionResult:
        """Decompose a complex goal into subgoals.

        Phase 1: Returns empty decomposition (stub).
        Phase 2: LLM-driven decomposition implementation.
        """
        logger.info(
            "GoalPlanningSubengine.decompose_goal: stub called for goal %s",
            request.goal_id,
        )
        return DecompositionResult(subgoals=[], reasoning="Not yet implemented")

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

    # --- Orchestration ---

    def compute_orchestration_strategy(
        self,
        root_goal_id: str | None = None,
    ) -> OrchestrationStrategy:
        """Compute orchestration strategy from the current goal DAG.

        Analyzes dependency structure, priorities, and conflicts
        to determine optimal execution order and concurrency.
        """
        goals = list(self._dag.goals.values())
        if not goals:
            return OrchestrationStrategy()

        # Analyze dependency graph
        dep_graph: dict[str, list[str]] = {}
        for g in goals:
            if g.depends_on:
                dep_graph[g.id] = list(g.depends_on)

        # Determine concurrency mode from structure
        has_parallel = any(not g.depends_on for g in goals if g.status == "pending")
        has_sequential = any(g.depends_on for g in goals)

        if has_parallel and has_sequential:
            mode = "mixed"
        elif has_parallel:
            mode = "parallel"
        else:
            mode = "sequential"

        return OrchestrationStrategy(
            concurrency_mode=mode,
            dependency_graph=dep_graph,
        )

    def suggest_goal_adjustments(
        self,
        goal_id: str,
    ) -> list[dict[str, Any]]:
        """Suggest priority/dependency adjustments based on execution evidence.

        Called after step outcomes to dynamically reprioritize goals.
        Phase 1: Returns empty list (stub).
        """
        return []

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
