"""Tests for the clarification lifecycle on GoalEngine (RFC-622)."""

from __future__ import annotations

import pytest

from soothe.foundation.autopilot.engine import GoalEngine


@pytest.mark.asyncio
async def test_mark_awaiting_clarification_persists_pending_payload() -> None:
    engine = GoalEngine()
    goal = await engine.create_goal("refine auth module")

    payload = {
        "questions": ["What aspect?"],
        "origin_node": "execute",
        "origin_interrupt_id": "iX",
        "loop_state": {},
    }
    updated = await engine.mark_awaiting_clarification(
        goal.id, pending_clarification=payload, reason="veritas defer"
    )

    assert updated.status == "awaiting_clarification"
    assert updated.pending_clarification == payload
    assert updated.assigned_loop_id is None


@pytest.mark.asyncio
async def test_awaiting_clarification_excluded_from_ready_goals() -> None:
    engine = GoalEngine()
    g1 = await engine.create_goal("g1")
    g2 = await engine.create_goal("g2")

    await engine.mark_awaiting_clarification(g1.id, pending_clarification={"questions": ["q"]})

    ready = await engine.peek_ready_goals(limit=10)
    ready_ids = {g.id for g in ready}
    assert g1.id not in ready_ids
    assert g2.id in ready_ids


@pytest.mark.asyncio
async def test_answer_clarification_restores_pending_status() -> None:
    engine = GoalEngine()
    goal = await engine.create_goal("g")
    await engine.mark_awaiting_clarification(goal.id, pending_clarification={"questions": ["q"]})

    updated = await engine.answer_clarification(goal.id, ["my answer"])

    assert updated.status == "pending"
    assert updated.pending_clarification is not None
    assert updated.pending_clarification["answers"] == ["my answer"]


@pytest.mark.asyncio
async def test_answer_clarification_rejects_goal_in_other_status() -> None:
    engine = GoalEngine()
    goal = await engine.create_goal("g")

    with pytest.raises(ValueError, match="not awaiting"):
        await engine.answer_clarification(goal.id, ["x"])


@pytest.mark.asyncio
async def test_answer_clarification_missing_goal_raises_key_error() -> None:
    engine = GoalEngine()
    with pytest.raises(KeyError):
        await engine.answer_clarification("nope", ["x"])
