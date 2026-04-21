"""Tests for GoalEngine (RFC-0007)."""

import pytest

from soothe.cognition import Goal, GoalEngine


class TestGoalModel:
    """Unit tests for the Goal model."""

    def test_goal_defaults(self) -> None:
        goal = Goal(description="Test goal")
        assert goal.status == "pending"
        assert goal.priority == 50
        assert goal.parent_id is None
        assert goal.retry_count == 0
        assert goal.max_retries == 2
        assert len(goal.id) == 8

    def test_goal_custom_fields(self) -> None:
        goal = Goal(description="Custom", priority=90, parent_id="abc", max_retries=5)
        assert goal.priority == 90
        assert goal.parent_id == "abc"
        assert goal.max_retries == 5


class TestGoalEngine:
    """Unit tests for GoalEngine."""

    @pytest.mark.asyncio
    async def test_create_goal(self) -> None:
        engine = GoalEngine()
        goal = await engine.create_goal("Test goal", priority=70)
        assert goal.description == "Test goal"
        assert goal.priority == 70
        assert goal.status == "pending"

    @pytest.mark.asyncio
    async def test_next_goal_empty(self) -> None:
        engine = GoalEngine()
        assert await engine.next_goal() is None

    @pytest.mark.asyncio
    async def test_next_goal_priority_order(self) -> None:
        engine = GoalEngine()
        await engine.create_goal("Low priority", priority=10)
        await engine.create_goal("High priority", priority=90)
        await engine.create_goal("Medium priority", priority=50)

        goal = await engine.next_goal()
        assert goal is not None
        assert goal.description == "High priority"
        assert goal.status == "active"

    @pytest.mark.asyncio
    async def test_next_goal_skips_completed(self) -> None:
        engine = GoalEngine()
        g1 = await engine.create_goal("First", priority=90)
        await engine.create_goal("Second", priority=50)
        await engine.complete_goal(g1.id)

        goal = await engine.next_goal()
        assert goal is not None
        assert goal.description == "Second"

    @pytest.mark.asyncio
    async def test_complete_goal(self) -> None:
        engine = GoalEngine()
        g = await engine.create_goal("To complete")
        completed = await engine.complete_goal(g.id)
        assert completed.status == "completed"

    @pytest.mark.asyncio
    async def test_complete_goal_not_found(self) -> None:
        engine = GoalEngine()
        with pytest.raises(KeyError):
            await engine.complete_goal("nonexistent")

    @pytest.mark.asyncio
    async def test_fail_goal_with_retry(self) -> None:
        engine = GoalEngine(max_retries=2)
        g = await engine.create_goal("Retryable")

        # RFC-200: fail_goal now returns BackoffDecision | None
        result = await engine.fail_goal(g.id, error="first failure")
        assert result is None  # No backoff decision applied (backward compatibility)
        # Check goal status from engine
        assert g.status == "pending"
        assert g.retry_count == 1

        result = await engine.fail_goal(g.id, error="second failure")
        assert result is None
        assert g.status == "pending"
        assert g.retry_count == 2

        result = await engine.fail_goal(g.id, error="third failure")
        assert result is None  # Permanent failure, no backoff
        assert g.status == "failed"
        assert g.retry_count == 2

    @pytest.mark.asyncio
    async def test_fail_goal_no_retry(self) -> None:
        engine = GoalEngine()
        g = await engine.create_goal("No retry")
        result = await engine.fail_goal(g.id, error="fail", allow_retry=False)
        assert result is None  # No backoff decision
        assert g.status == "failed"

    @pytest.mark.asyncio
    async def test_list_goals_all(self) -> None:
        engine = GoalEngine()
        await engine.create_goal("A")
        await engine.create_goal("B")
        goals = await engine.list_goals()
        assert len(goals) == 2

    @pytest.mark.asyncio
    async def test_list_goals_by_status(self) -> None:
        engine = GoalEngine()
        g1 = await engine.create_goal("A")
        await engine.create_goal("B")
        await engine.complete_goal(g1.id)

        pending = await engine.list_goals("pending")
        assert len(pending) == 1
        completed = await engine.list_goals("completed")
        assert len(completed) == 1

    @pytest.mark.asyncio
    async def test_get_goal(self) -> None:
        engine = GoalEngine()
        g = await engine.create_goal("Find me")
        found = await engine.get_goal(g.id)
        assert found is not None
        assert found.description == "Find me"
        assert await engine.get_goal("nonexistent") is None

    @pytest.mark.asyncio
    async def test_snapshot_and_restore(self) -> None:
        engine = GoalEngine()
        await engine.create_goal("Goal A", priority=80)
        g2 = await engine.create_goal("Goal B", priority=20)
        await engine.complete_goal(g2.id)

        snapshot = engine.snapshot()
        assert len(snapshot) == 2

        new_engine = GoalEngine()
        new_engine.restore_from_snapshot(snapshot)
        goals = await new_engine.list_goals()
        assert len(goals) == 2

        completed = await new_engine.list_goals("completed")
        assert len(completed) == 1
        assert completed[0].description == "Goal B"

    @pytest.mark.asyncio
    async def test_parent_child_goals(self) -> None:
        engine = GoalEngine()
        parent = await engine.create_goal("Parent goal", priority=80)
        child = await engine.create_goal("Child goal", priority=60, parent_id=parent.id)
        assert child.parent_id == parent.id


class TestReadyGoals:
    """Tests for ready_goals (DAG-aware scheduling)."""

    @pytest.mark.asyncio
    async def test_ready_goals_empty(self) -> None:
        engine = GoalEngine()
        ready = await engine.ready_goals()
        assert ready == []

    @pytest.mark.asyncio
    async def test_ready_goals_no_deps(self) -> None:
        engine = GoalEngine()
        g = await engine.create_goal("No deps")
        ready = await engine.ready_goals()
        assert len(ready) == 1
        assert ready[0].id == g.id

    @pytest.mark.asyncio
    async def test_ready_goals_waits_for_dep(self) -> None:
        engine = GoalEngine()
        g_a = await engine.create_goal("A")
        g_b = await engine.create_goal("B")
        g_b.depends_on = [g_a.id]

        ready = await engine.ready_goals()
        assert len(ready) == 1
        assert ready[0].id == g_a.id

        await engine.complete_goal(g_a.id)
        ready = await engine.ready_goals()
        assert len(ready) == 1
        assert ready[0].id == g_b.id

    @pytest.mark.asyncio
    async def test_ready_goals_limit(self) -> None:
        engine = GoalEngine()
        await engine.create_goal("A")
        await engine.create_goal("B")
        await engine.create_goal("C")
        ready = await engine.ready_goals(limit=2)
        assert len(ready) == 2

    @pytest.mark.asyncio
    async def test_ready_goals_sorted_by_priority(self) -> None:
        engine = GoalEngine()
        await engine.create_goal("Low", priority=10)
        await engine.create_goal("High", priority=90)
        await engine.create_goal("Mid", priority=50)
        ready = await engine.ready_goals(limit=3)
        assert len(ready) == 3
        assert ready[0].description == "High"
        assert ready[1].description == "Mid"
        assert ready[2].description == "Low"

    @pytest.mark.asyncio
    async def test_ready_goals_activates_pending(self) -> None:
        engine = GoalEngine()
        g = await engine.create_goal("Pending")
        assert g.status == "pending"
        ready = await engine.ready_goals()
        assert len(ready) == 1
        assert ready[0].status == "active"


class TestIsComplete:
    """Tests for is_complete."""

    def test_is_complete_empty(self) -> None:
        engine = GoalEngine()
        assert engine.is_complete() is True

    @pytest.mark.asyncio
    async def test_is_complete_all_terminal(self) -> None:
        engine = GoalEngine()
        g1 = await engine.create_goal("A")
        g2 = await engine.create_goal("B")
        await engine.complete_goal(g1.id)
        await engine.fail_goal(g2.id, allow_retry=False)
        assert engine.is_complete() is True

    @pytest.mark.asyncio
    async def test_is_complete_pending(self) -> None:
        engine = GoalEngine()
        await engine.create_goal("Pending")
        assert engine.is_complete() is False


class TestNextGoalDelegation:
    """Tests for next_goal delegating to ready_goals."""

    @pytest.mark.asyncio
    async def test_next_goal_delegates(self) -> None:
        engine = GoalEngine()
        await engine.create_goal("A", priority=50)
        await engine.create_goal("B", priority=90)
        next_g = await engine.next_goal()
        ready = await engine.ready_goals(limit=1)
        assert next_g is not None
        assert len(ready) == 1
        assert next_g.id == ready[0].id


class TestGoalFields:
    """Tests for Goal model fields (depends_on, report)."""

    def test_goal_depends_on_default(self) -> None:
        goal = Goal(description="Test")
        assert goal.depends_on == []

    def test_goal_report_field(self) -> None:
        goal = Goal(description="Test")
        assert goal.report is None
