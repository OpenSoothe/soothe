"""Unit tests for GoalIntakeHandler (RFC-625)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.foundation.autopilot.monitor.goal_dag_verifier import GoalDAGVerifier
from soothe.foundation.autopilot.monitor.goal_intake_handler import GoalIntakeHandler
from soothe.foundation.autopilot.monitor.models import GoalIntakeResult, GoalPlacement
from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.models import GoalNode


@pytest.fixture
def mock_config() -> MagicMock:
    """Create mock SootheConfig."""
    cfg = MagicMock()
    cfg.agent = MagicMock()
    cfg.agent.autonomous = MagicMock()
    return cfg


@pytest.fixture
def mock_ce() -> ContextEngine:
    """Create mock ContextEngine."""
    ce = MagicMock(spec=ContextEngine)
    ce._dag = MagicMock()
    ce._dag.goals = {}

    existing_goal = MagicMock(spec=GoalNode)
    existing_goal.id = "goal-1"
    existing_goal.description = "Existing goal"
    existing_goal.status = "completed"
    existing_goal.priority = 50
    existing_goal.depends_on = []
    ce._dag.goals["goal-1"] = existing_goal

    def get_goal_sync(goal_id: str) -> GoalNode | None:
        return ce._dag.goals.get(goal_id)

    def cancel_goal(goal_id: str) -> None:
        if goal_id in ce._dag.goals:
            ce._dag.goals[goal_id].status = "cancelled"

    ce.get_goal_sync = get_goal_sync
    ce.cancel_goal = AsyncMock(side_effect=cancel_goal)

    created_goals = []

    async def create_goal(
        description: str,
        priority: int = 50,
        depends_on: list[str] | None = None,
        workspace: str | None = None,
        source: str = "user",
    ) -> GoalNode:
        goal = MagicMock(spec=GoalNode)
        goal.id = f"goal-{len(created_goals) + 2}"
        goal.description = description
        goal.status = "pending"
        goal.priority = priority
        goal.depends_on = depends_on or []
        goal.workspace = workspace
        created_goals.append(goal)
        ce._dag.goals[goal.id] = goal
        return goal

    ce.create_goal = AsyncMock(side_effect=create_goal)

    return ce


@pytest.fixture
def mock_verifier(mock_ce: ContextEngine, mock_config: MagicMock) -> GoalDAGVerifier:
    """Create mock GoalDAGVerifier."""
    verifier = MagicMock(spec=GoalDAGVerifier)
    verifier._ce = mock_ce
    verifier._config = mock_config

    async def analyze_placement(description: str) -> GoalPlacement:
        return GoalPlacement(
            adjusted_priority=60,
            suggested_dependencies=["goal-1"],
            reasoning="Test placement",
        )

    verifier.analyze_placement = AsyncMock(side_effect=analyze_placement)

    return verifier


@pytest.fixture
def mock_workspace_reservation() -> MagicMock:
    """Create mock WorkspaceReservation."""
    reservation = MagicMock()
    reservation.conflicts_with_active = MagicMock(return_value=None)
    reservation.release = MagicMock()
    return reservation


@pytest.fixture
def handler(
    mock_ce: ContextEngine,
    mock_verifier: GoalDAGVerifier,
    mock_workspace_reservation: MagicMock,
) -> GoalIntakeHandler:
    """Create GoalIntakeHandler instance."""
    return GoalIntakeHandler(mock_ce, mock_verifier, mock_workspace_reservation)


class TestGoalIntakeHandler:
    """Tests for GoalIntakeHandler class."""

    async def test_submit_goal_returns_accepted(self, handler: GoalIntakeHandler) -> None:
        """submit_goal returns accepted result."""
        result = await handler.submit_goal("New task description")

        assert result.status == "accepted"
        assert result.goal_id is not None
        assert result.adjusted_priority == 60

    async def test_submit_goal_merges_dependencies(
        self,
        handler: GoalIntakeHandler,
        mock_verifier: GoalDAGVerifier,
    ) -> None:
        """submit_goal merges user and suggested dependencies."""
        result = await handler.submit_goal(
            "New task",
            depends_on=["user-dep"],
        )

        assert result.suggested_dependencies == ["goal-1"]

    async def test_submit_goal_with_workspace(self, handler: GoalIntakeHandler) -> None:
        """submit_goal accepts workspace parameter."""
        result = await handler.submit_goal(
            "Workspace task",
            workspace="/path/to/workspace",
        )

        assert result.status == "accepted"

    async def test_submit_goal_rejected_on_workspace_conflict(
        self, handler: GoalIntakeHandler, mock_workspace_reservation: MagicMock
    ) -> None:
        """submit_goal rejects when workspace conflicts."""
        mock_workspace_reservation.conflicts_with_active = MagicMock(
            return_value="conflicting-goal-1"
        )

        result = await handler.submit_goal(
            "Conflict task",
            workspace="/shared/workspace",
        )

        assert result.status == "rejected"
        assert "conflicting-goal-1" in result.reason

    async def test_submit_goals_batch_processes_ordered(self, handler: GoalIntakeHandler) -> None:
        """submit_goals_batch processes goals in dependency order."""
        goals = [
            {"description": "Goal A", "id": "a", "depends_on": []},
            {"description": "Goal B", "id": "b", "depends_on": ["a"]},
            {"description": "Goal C", "id": "c", "depends_on": ["b"]},
        ]

        results = await handler.submit_goals_batch(goals)

        assert len(results) == 3
        assert all(r.status == "accepted" for r in results)

    async def test_submit_goals_batch_marks_dependents_skipped(
        self, handler: GoalIntakeHandler, mock_workspace_reservation: MagicMock
    ) -> None:
        """submit_goals_batch marks dependents as skipped when parent rejected."""
        mock_workspace_reservation.conflicts_with_active = MagicMock(return_value="conflict")

        goals = [
            {"description": "Conflict goal", "id": "a", "workspace": "/shared", "depends_on": []},
            {"description": "Dependent goal", "id": "b", "depends_on": ["a"]},
        ]

        results = await handler.submit_goals_batch(goals)

        assert results[0].status == "rejected"

    async def test_cancel_goal_returns_true_for_pending(
        self, handler: GoalIntakeHandler, mock_ce: ContextEngine
    ) -> None:
        """cancel_goal cancels pending goal."""
        pending_goal = MagicMock(spec=GoalNode)
        pending_goal.id = "test-goal"
        pending_goal.description = "Test"
        pending_goal.status = "pending"
        pending_goal.priority = 50
        pending_goal.depends_on = []
        mock_ce._dag.goals["test-goal"] = pending_goal

        result = await handler.cancel_goal("test-goal")

        assert result is True
        mock_ce.cancel_goal.assert_called_once()

    async def test_cancel_goal_returns_false_for_terminal(
        self, handler: GoalIntakeHandler, mock_ce: ContextEngine
    ) -> None:
        """cancel_goal returns false for completed/failed goals."""
        completed_goal = MagicMock(spec=GoalNode)
        completed_goal.id = "completed-goal"
        completed_goal.description = "Done"
        completed_goal.status = "completed"
        completed_goal.priority = 50
        completed_goal.depends_on = []
        mock_ce._dag.goals["completed-goal"] = completed_goal

        result = await handler.cancel_goal("completed-goal")

        assert result is False

    async def test_cancel_goal_returns_false_for_missing(self, handler: GoalIntakeHandler) -> None:
        """cancel_goal returns false for nonexistent goal."""
        result = await handler.cancel_goal("nonexistent-goal")

        assert result is False

    async def test_cancel_goal_releases_workspace_reservation(
        self,
        handler: GoalIntakeHandler,
        mock_ce: ContextEngine,
        mock_workspace_reservation: MagicMock,
    ) -> None:
        """cancel_goal releases workspace reservation."""
        pending_goal = MagicMock(spec=GoalNode)
        pending_goal.id = "test-goal"
        pending_goal.description = "Test"
        pending_goal.status = "pending"
        pending_goal.priority = 50
        pending_goal.depends_on = []
        mock_ce._dag.goals["test-goal"] = pending_goal

        await handler.cancel_goal("test-goal")

        mock_workspace_reservation.release.assert_called_once_with("test-goal")


class TestGoalIntakeResult:
    """Tests for GoalIntakeResult model."""

    def test_accepted_result(self) -> None:
        """GoalIntakeResult for accepted goal."""
        result = GoalIntakeResult(
            status="accepted",
            goal_id="goal-1",
            adjusted_priority=60,
            suggested_dependencies=["goal-0"],
        )

        assert result.status == "accepted"
        assert result.goal_id == "goal-1"
        assert result.reason is None

    def test_rejected_result(self) -> None:
        """GoalIntakeResult for rejected goal."""
        result = GoalIntakeResult(
            status="rejected",
            reason="Workspace conflict",
        )

        assert result.status == "rejected"
        assert result.goal_id is None
        assert result.reason == "Workspace conflict"

    def test_skipped_result(self) -> None:
        """GoalIntakeResult for skipped goal."""
        result = GoalIntakeResult(
            status="skipped",
            reason="Depends on rejected goal",
        )

        assert result.status == "skipped"
        assert result.reason == "Depends on rejected goal"


class TestDependencyOrdering:
    """Tests for _order_by_dependencies method."""

    def test_orders_no_deps_first(self, handler: GoalIntakeHandler) -> None:
        """Goals with no dependencies come first."""
        goals = [
            {"description": "A", "id": "a", "depends_on": ["b"]},
            {"description": "B", "id": "b", "depends_on": []},
        ]

        ordered = handler._order_by_dependencies(goals)

        assert ordered[0]["id"] == "b"
        assert ordered[1]["id"] == "a"

    def test_orders_chain_correctly(self, handler: GoalIntakeHandler) -> None:
        """Chain dependencies are ordered correctly."""
        goals = [
            {"description": "C", "id": "c", "depends_on": ["b"]},
            {"description": "A", "id": "a", "depends_on": []},
            {"description": "B", "id": "b", "depends_on": ["a"]},
        ]

        ordered = handler._order_by_dependencies(goals)

        assert ordered[0]["id"] == "a"
        assert ordered[1]["id"] == "b"
        assert ordered[2]["id"] == "c"

    def test_handles_circular_dependency(self, handler: GoalIntakeHandler) -> None:
        """Circular dependencies are handled gracefully."""
        goals = [
            {"description": "A", "id": "a", "depends_on": ["b"]},
            {"description": "B", "id": "b", "depends_on": ["a"]},
        ]

        ordered = handler._order_by_dependencies(goals)

        assert len(ordered) == 2
