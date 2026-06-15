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
        execution_evidence: dict[str, Any],
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
        context_summary: str = "",
    ) -> list[GoalNode]:
        """LLM-driven reflection on a completed goal to identify follow-up goals.

        Uses the completed goal's context to determine if additional work
        is needed. Phase 1: Returns empty list (stub).
        """
        logger.info(
            "GoalPlanningSubengine.reflect_and_create_goals: stub for goal %s",
            completed_goal_id,
        )
        return []
