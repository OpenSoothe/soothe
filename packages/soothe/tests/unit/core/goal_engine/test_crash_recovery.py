"""Tests for RFC-222 H4 crash recovery in GoalEngine."""

from __future__ import annotations

import pytest

from soothe.core.goal_engine import GoalEngine


class TestRecoverActiveGoals:
    """recover_active_goals resets stranded ``active`` goals on daemon start."""

    @pytest.mark.asyncio
    async def test_no_active_goals_returns_empty(self) -> None:
        engine = GoalEngine()
        await engine.create_goal("g1")
        recovered = engine.recover_active_goals()
        assert recovered == []

    @pytest.mark.asyncio
    async def test_resets_active_to_pending(self) -> None:
        engine = GoalEngine()
        goal = await engine.create_goal("active goal")
        # Simulate a goal that was mid-flight when the previous daemon died.
        goal.status = "active"
        goal.assigned_loop_id = "autopilot__w007"

        recovered = engine.recover_active_goals()

        assert recovered == [goal.id]
        assert goal.status == "pending"
        assert goal.assigned_loop_id is None
        assert goal.attempts_after_crash == 1

    @pytest.mark.asyncio
    async def test_increments_attempts_after_crash_each_cycle(self) -> None:
        engine = GoalEngine()
        goal = await engine.create_goal("repeatedly stranded")
        for expected_attempts in (1, 2, 3):
            goal.status = "active"
            goal.assigned_loop_id = f"autopilot__w{expected_attempts:03d}"
            engine.recover_active_goals()
            assert goal.attempts_after_crash == expected_attempts
            assert goal.status == "pending"

    @pytest.mark.asyncio
    async def test_does_not_touch_terminal_goals(self) -> None:
        engine = GoalEngine()
        completed = await engine.create_goal("done")
        completed.status = "completed"
        failed = await engine.create_goal("dead")
        failed.status = "failed"
        pending = await engine.create_goal("waiting")
        # pending stays pending

        recovered = engine.recover_active_goals()

        assert recovered == []
        assert completed.status == "completed"
        assert failed.status == "failed"
        assert pending.status == "pending"
