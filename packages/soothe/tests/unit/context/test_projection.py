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
        assert bundle.goal_progress == ""
        assert bundle.pending_steps == []


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
        assert "1/2 completed" in bundle.goal_progress
        assert len(bundle.completed_steps) == 1
        assert len(bundle.pending_steps) == 1

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

    @pytest.mark.asyncio
    async def test_project_failed_steps(self) -> None:
        engine = ProjectionEngine()
        dag, goal = _make_dag_with_goal(status="active")
        goal.steps.add_step(StepNode(id="S1", description="Fails"))
        goal.steps.mark_failed("S1", StepExecution(error="boom"))

        ledger = LedgerManager()
        semantic = SemanticLoader()
        bundle = await engine.project(dag, ledger, semantic)
        assert len(bundle.failed_steps) == 1


class TestProjectionConfigLimits:
    @pytest.mark.asyncio
    async def test_max_steps_per_goal(self) -> None:
        cfg = ProjectionConfig(max_steps_per_goal=2)
        engine = ProjectionEngine(cfg)
        dag, goal = _make_dag_with_goal(status="active")
        for i in range(5):
            goal.steps.add_step(StepNode(id=f"S{i}", description=f"Step {i}"))

        ledger = LedgerManager()
        semantic = SemanticLoader()
        bundle = await engine.project(dag, ledger, semantic)
        assert len(bundle.pending_steps) <= 2

    @pytest.mark.asyncio
    async def test_truncation_applies(self) -> None:
        cfg = ProjectionConfig(max_project_instructions_chars=10)
        engine = ProjectionEngine(cfg)
        dag = GoalStepDAG()
        ledger = LedgerManager()
        # Use a tmp_path with a long CLAUDE.md
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "CLAUDE.md").write_text("x" * 100, encoding="utf-8")
            semantic = SemanticLoader(workspace=Path(td))
            bundle = await engine.project(dag, ledger, semantic)
            assert len(bundle.project_instructions) <= 10


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


class TestProjectionDagSummary:
    @pytest.mark.asyncio
    async def test_dag_summary(self) -> None:
        engine = ProjectionEngine()
        dag = GoalStepDAG()
        g1 = GoalNode(description="A", status="active")
        g2 = GoalNode(description="B", status="completed")
        dag.add_goal(g1)
        dag.add_goal(g2)

        ledger = LedgerManager()
        semantic = SemanticLoader()
        bundle = await engine.project(dag, ledger, semantic)
        assert "2 total" in bundle.goal_dag_summary
        assert "1 active" in bundle.goal_dag_summary
        assert "1 completed" in bundle.goal_dag_summary


class TestContextBundle:
    def test_default_values(self) -> None:
        bundle = ContextBundle()
        assert bundle.active_goal is None
        assert bundle.goal_progress == ""
        assert bundle.pending_steps == []
        assert bundle.total_tokens_used == 0
