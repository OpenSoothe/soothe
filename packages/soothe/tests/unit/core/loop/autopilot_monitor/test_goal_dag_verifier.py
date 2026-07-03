"""Unit tests for GoalDAGVerifier (RFC-625)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from soothe.foundation.autopilot.monitor.goal_dag_verifier import GoalDAGVerifier
from soothe.foundation.autopilot.monitor.models import DagHealthReport, GoalPlacement
from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.models import GoalNode


@pytest.fixture
def mock_config() -> MagicMock:
    """Create mock SootheConfig."""
    cfg = MagicMock()
    cfg.agent = MagicMock()
    cfg.agent.autopilot = MagicMock()
    return cfg


@pytest.fixture
def mock_ce() -> ContextEngine:
    """Create mock ContextEngine with sample goals."""
    ce = MagicMock(spec=ContextEngine)
    ce._dag = MagicMock()
    ce._dag.goals = {}

    # Create sample goals with mocked steps
    goals = []
    for i, (id_, desc, status, priority, deps) in enumerate(
        [
            ("goal-1", "Active goal", "active", 50, []),
            ("goal-2", "Pending goal with deps", "pending", 40, ["goal-1"]),
            ("goal-3", "Orphaned pending goal", "pending", 30, ["missing-goal"]),
            ("goal-4", "Completed goal", "completed", 60, []),
        ]
    ):
        goal = MagicMock(spec=GoalNode)
        goal.id = id_
        goal.description = desc
        goal.status = status
        goal.priority = priority
        goal.depends_on = deps
        goal.steps = MagicMock()
        goal.steps.total_steps = 5 - i
        goal.steps.completed_steps = 2 - i
        goal.steps.failed_steps = 0
        goal.report = None  # GoalReport on completion (dict serialization)
        goal.findings = []  # Key findings from execution
        goal.total_duration_ms = 0
        goal.total_tokens_used = 0
        ce._dag.goals[id_] = goal
        goals.append(goal)

    def get_goals_by_status(status: str | None) -> list[GoalNode]:
        if status is None:
            return goals
        return [g for g in goals if g.status == status]

    def get_goal_sync(goal_id: str) -> GoalNode | None:
        return ce._dag.goals.get(goal_id)

    ce.get_goals_by_status = get_goals_by_status
    ce.get_goal_sync = get_goal_sync

    return ce


@pytest.fixture
def verifier(mock_ce: ContextEngine, mock_config: MagicMock) -> GoalDAGVerifier:
    """Create GoalDAGVerifier instance."""
    return GoalDAGVerifier(mock_ce, mock_config)


class TestGoalDAGVerifier:
    """Tests for GoalDAGVerifier class."""

    async def test_verify_dag_health_returns_report(self, verifier: GoalDAGVerifier) -> None:
        """verify_dag_health returns DagHealthReport."""
        report = await verifier.verify_dag_health()

        assert isinstance(report, DagHealthReport)
        assert report.reasoning != ""

    async def test_verify_dag_health_detects_orphaned_goals(
        self, verifier: GoalDAGVerifier
    ) -> None:
        """verify_dag_health suggests removal of orphaned goals."""
        report = await verifier.verify_dag_health()

        # Goal-3 depends on missing-goal, should be suggested for removal
        assert "goal-3" in report.suggest_remove

    async def test_verify_dag_post_completion_returns_analysis(
        self, verifier: GoalDAGVerifier
    ) -> None:
        """verify_dag_post_completion returns analysis dict."""
        result = await verifier.verify_dag_post_completion("goal-4")

        assert isinstance(result, dict)
        assert result.get("completed_goal_id") == "goal-4"

    async def test_verify_dag_post_completion_handles_missing_goal(
        self, verifier: GoalDAGVerifier
    ) -> None:
        """verify_dag_post_completion returns empty dict for missing goal."""
        result = await verifier.verify_dag_post_completion("nonexistent-goal")

        assert result == {}

    async def test_analyze_placement_returns_placement(self, verifier: GoalDAGVerifier) -> None:
        """analyze_placement returns GoalPlacement."""
        placement = await verifier.analyze_placement("New task description")

        assert isinstance(placement, GoalPlacement)
        assert placement.adjusted_priority > 0
        assert placement.reasoning != ""

    async def test_analyze_placement_adjusts_priority_by_load(
        self, verifier: GoalDAGVerifier
    ) -> None:
        """analyze_placement adjusts priority based on DAG load."""
        # With 2 pending + 1 active goals, priority should be adjusted
        placement = await verifier.analyze_placement("New task")

        # Load = 2 pending + 1 active = 3
        # Priority adjustment: max(20, 50 - load)
        assert placement.adjusted_priority == max(20, 50 - 3)

    def test_build_dag_snapshot(self, verifier: GoalDAGVerifier) -> None:
        """_build_dag_snapshot creates serializable snapshot."""
        snapshot = verifier._build_dag_snapshot()

        assert isinstance(snapshot, dict)
        assert "goals" in snapshot
        assert "total_goals" in snapshot
        assert snapshot["total_goals"] == 4

        # Check goal serialization
        for g in snapshot["goals"]:
            assert "id" in g
            assert "description" in g
            assert "status" in g
            assert "priority" in g
            assert "depends_on" in g
            assert "step_count" in g
            assert "completed_steps" in g


class TestDagHealthReport:
    """Tests for DagHealthReport model."""

    def test_default_values(self) -> None:
        """DagHealthReport has empty default values."""
        report = DagHealthReport()

        assert report.suggest_reset == []
        assert report.suggest_remove == []
        assert report.suggest_merge == []
        assert report.suggest_decompose == []
        assert report.suggest_priority_adjust == {}
        assert report.reasoning == ""
        assert report.errors == []

    def test_can_add_suggestions(self) -> None:
        """DagHealthReport can accumulate suggestions."""
        report = DagHealthReport()
        report.suggest_remove.append("goal-1")
        report.suggest_reset.append("goal-2")
        report.suggest_priority_adjust["goal-3"] = 80

        assert len(report.suggest_remove) == 1
        assert len(report.suggest_reset) == 1
        assert report.suggest_priority_adjust["goal-3"] == 80


class TestGoalPlacement:
    """Tests for GoalPlacement model."""

    def test_default_values(self) -> None:
        """GoalPlacement has sensible defaults."""
        placement = GoalPlacement()

        assert placement.adjusted_priority == 50
        assert placement.suggested_dependencies == []
        assert placement.merge_with is None
        assert placement.estimated_complexity == "moderate"
        assert placement.reasoning == ""

    def test_accepts_custom_values(self) -> None:
        """GoalPlacement accepts custom values."""
        placement = GoalPlacement(
            adjusted_priority=80,
            suggested_dependencies=["goal-1"],
            merge_with="goal-2",
            estimated_complexity="simple",
            reasoning="Test reasoning",
        )

        assert placement.adjusted_priority == 80
        assert placement.suggested_dependencies == ["goal-1"]
        assert placement.merge_with == "goal-2"
        assert placement.estimated_complexity == "simple"
        assert placement.reasoning == "Test reasoning"
