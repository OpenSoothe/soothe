"""Tests for GoalEngine (RFC-0007)."""

import pytest

from soothe.core.goal_engine import Goal, GoalEngine


class TestGoalModel:
    """Unit tests for the Goal model."""

    def test_goal_defaults(self):
        goal = Goal(description="Test goal")
        assert goal.status == "pending"
        assert goal.priority == 50
        assert goal.parent_id is None
        assert goal.retry_count == 0
        assert goal.max_retries == 2
        assert len(goal.id) == 8

    def test_goal_custom_fields(self):
        goal = Goal(description="Custom", priority=90, parent_id="abc", max_retries=5)
        assert goal.priority == 90
        assert goal.parent_id == "abc"
        assert goal.max_retries == 5


class TestGoalEngine:
    """Unit tests for GoalEngine."""

    @pytest.mark.asyncio
    async def test_create_goal(self):
        engine = GoalEngine()
        goal = await engine.create_goal("Test goal", priority=70)
        assert goal.description == "Test goal"
        assert goal.priority == 70
        assert goal.status == "pending"

    @pytest.mark.asyncio
    async def test_next_goal_empty(self):
        engine = GoalEngine()
        assert await engine.next_goal() is None

    @pytest.mark.asyncio
    async def test_next_goal_priority_order(self):
        engine = GoalEngine()
        await engine.create_goal("Low priority", priority=10)
        await engine.create_goal("High priority", priority=90)
        await engine.create_goal("Medium priority", priority=50)

        goal = await engine.next_goal()
        assert goal is not None
        assert goal.description == "High priority"
        assert goal.status == "active"

    @pytest.mark.asyncio
    async def test_next_goal_skips_completed(self):
        engine = GoalEngine()
        g1 = await engine.create_goal("First", priority=90)
        await engine.create_goal("Second", priority=50)
        await engine.complete_goal(g1.id)

        goal = await engine.next_goal()
        assert goal is not None
        assert goal.description == "Second"

    @pytest.mark.asyncio
    async def test_complete_goal(self):
        engine = GoalEngine()
        g = await engine.create_goal("To complete")
        completed = await engine.complete_goal(g.id)
        assert completed.status == "completed"

    @pytest.mark.asyncio
    async def test_complete_goal_not_found(self):
        engine = GoalEngine()
        with pytest.raises(KeyError):
            await engine.complete_goal("nonexistent")

    @pytest.mark.asyncio
    async def test_fail_goal_with_retry(self):
        engine = GoalEngine(max_retries=2)
        g = await engine.create_goal("Retryable")

        failed = await engine.fail_goal(g.id, error="first failure")
        assert failed.status == "pending"
        assert failed.retry_count == 1

        failed = await engine.fail_goal(g.id, error="second failure")
        assert failed.status == "pending"
        assert failed.retry_count == 2

        failed = await engine.fail_goal(g.id, error="third failure")
        assert failed.status == "failed"
        assert failed.retry_count == 2

    @pytest.mark.asyncio
    async def test_fail_goal_no_retry(self):
        engine = GoalEngine()
        g = await engine.create_goal("No retry")
        failed = await engine.fail_goal(g.id, error="fail", allow_retry=False)
        assert failed.status == "failed"

    @pytest.mark.asyncio
    async def test_list_goals_all(self):
        engine = GoalEngine()
        await engine.create_goal("A")
        await engine.create_goal("B")
        goals = await engine.list_goals()
        assert len(goals) == 2

    @pytest.mark.asyncio
    async def test_list_goals_by_status(self):
        engine = GoalEngine()
        g1 = await engine.create_goal("A")
        await engine.create_goal("B")
        await engine.complete_goal(g1.id)

        pending = await engine.list_goals("pending")
        assert len(pending) == 1
        completed = await engine.list_goals("completed")
        assert len(completed) == 1

    @pytest.mark.asyncio
    async def test_get_goal(self):
        engine = GoalEngine()
        g = await engine.create_goal("Find me")
        found = await engine.get_goal(g.id)
        assert found is not None
        assert found.description == "Find me"
        assert await engine.get_goal("nonexistent") is None

    @pytest.mark.asyncio
    async def test_snapshot_and_restore(self):
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
    async def test_parent_child_goals(self):
        engine = GoalEngine()
        parent = await engine.create_goal("Parent goal", priority=80)
        child = await engine.create_goal("Child goal", priority=60, parent_id=parent.id)
        assert child.parent_id == parent.id
