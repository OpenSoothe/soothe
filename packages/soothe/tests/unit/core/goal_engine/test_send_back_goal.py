"""Tests for GoalEngine.send_back_goal (RFC-204)."""

from __future__ import annotations

import pytest

from soothe.foundation.autopilot.engine import GoalEngine


@pytest.mark.asyncio
async def test_send_back_increments_and_returns_pending() -> None:
    engine = GoalEngine(max_send_backs=3)
    goal = await engine.create_goal("write tests")
    await engine.claim_goal(goal.id, loop_id="loop-1")

    updated = await engine.send_back_goal(goal.id, reason="needs more detail")
    assert updated.status == "pending"
    assert updated.send_back_count == 1
    assert updated.assigned_loop_id is None


@pytest.mark.asyncio
async def test_send_back_budget_exhaustion_suspends() -> None:
    engine = GoalEngine(max_send_backs=2)
    goal = await engine.create_goal("deploy prod")
    await engine.claim_goal(goal.id, loop_id="loop-1")

    await engine.send_back_goal(goal.id, reason="round 1")
    await engine.claim_goal(goal.id, loop_id="loop-1")
    suspended = await engine.send_back_goal(goal.id, reason="round 2")

    assert suspended.status == "suspended"
    assert suspended.send_back_count == 2
