"""Tests for ProjectionEngine (soothe.context.projection)."""

import pytest

from soothe.context.ledger import LedgerManager
from soothe.context.models import GoalNode, GoalStepDAG, StepExecution, StepNode
from soothe.context.projection import ContextBundle, ProjectionConfig, ProjectionEngine
from soothe.context.semantic import SemanticLoader


def _make_dag_with_goal(**goal_kwargs) -> tuple[GoalStepDAG, GoalNode]:
    dag = GoalStepDAG()
    goal = GoalNode(description="Test goal", **goal_kwargs)
    dag.add_goal(goal)
    return dag, goal


class TestProjectionEngineNoGoal:
    @pytest.mark.asyncio
    async def test_project_empty_dag(self) -> None:
        engine = ProjectionEngine()
        dag = GoalStepDAG()
        ledger = LedgerManager()
        semantic = SemanticLoader()
        bundle = await engine.project(dag, ledger, semantic)
        assert bundle.active_goal is None
        assert bundle.goal_lineage == ""
        assert bundle.step_lineage == ""
        assert bundle.prior_goals == []


class TestProjectionEngineWithGoal:
    @pytest.mark.asyncio
    async def test_project_with_active_goal(self) -> None:
        engine = ProjectionEngine()
        dag, goal = _make_dag_with_goal(status="active")
        goal.steps.add_step(StepNode(id="S1", description="Step 1"))
        goal.steps.add_step(StepNode(id="S2", description="Step 2"))
        goal.steps.mark_completed("S1", StepExecution())

        ledger = LedgerManager()
        semantic = SemanticLoader()
        bundle = await engine.project(dag, ledger, semantic)

        assert bundle.active_goal is goal
        assert bundle.goal_lineage != "" or goal.description == ""
        assert bundle.prior_goals == []

    @pytest.mark.asyncio
    async def test_project_specific_goal_id(self) -> None:
        engine = ProjectionEngine()
        dag, goal = _make_dag_with_goal()
        other = GoalNode(description="Other")
        dag.add_goal(other)

        ledger = LedgerManager()
        semantic = SemanticLoader()
        bundle = await engine.project(dag, ledger, semantic, goal_id=other.id)
        assert bundle.active_goal is other


class TestProjectionLineage:
    @pytest.mark.asyncio
    async def test_goal_lineage_in_bundle(self) -> None:
        engine = ProjectionEngine()
        dag = GoalStepDAG()
        root = GoalNode(description="Root goal")
        dag.add_goal(root)
        child = GoalNode(description="Child goal", parent_id=root.id, status="active")
        dag.add_goal(child)

        ledger = LedgerManager()
        semantic = SemanticLoader()
        bundle = await engine.project(dag, ledger, semantic, goal_id=child.id)
        assert "Root goal" in bundle.goal_lineage
        assert "Child goal" in bundle.goal_lineage


class TestProjectionPriorGoals:
    @pytest.mark.asyncio
    async def test_prior_goals_from_completed(self) -> None:
        """Completed goals appear in prior_goals."""
        engine = ProjectionEngine()
        dag = GoalStepDAG()
        g1 = GoalNode(description="A", status="completed")
        g2 = GoalNode(description="B", status="active")
        dag.add_goal(g1)
        dag.add_goal(g2)

        ledger = LedgerManager()
        semantic = SemanticLoader()
        bundle = await engine.project(dag, ledger, semantic)
        assert len(bundle.prior_goals) == 1
        assert bundle.prior_goals[0].goal_id == g1.id


class TestContextBundle:
    def test_default_values(self) -> None:
        bundle = ContextBundle()
        assert bundle.active_goal is None
        assert bundle.goal_lineage == ""
        assert bundle.step_lineage == ""
        assert bundle.prior_goals == []


class TestProjectionLineageTruncation:
    @pytest.mark.asyncio
    async def test_lineage_truncated(self) -> None:
        """Lineage is truncated to max_lineage_chars."""
        cfg = ProjectionConfig(max_lineage_chars=10)
        engine = ProjectionEngine(cfg)
        dag = GoalStepDAG()
        root = GoalNode(description="Root goal with a long name")
        dag.add_goal(root)
        child = GoalNode(
            description="Child goal also with a long name",
            parent_id=root.id,
            status="active",
        )
        dag.add_goal(child)

        ledger = LedgerManager()
        semantic = SemanticLoader()
        bundle = await engine.project(dag, ledger, semantic, goal_id=child.id)
        assert len(bundle.goal_lineage) <= 10
