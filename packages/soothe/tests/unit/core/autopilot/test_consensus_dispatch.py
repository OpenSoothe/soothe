"""Tests for consensus wiring in AutopilotService dispatch completion."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from soothe.config.models import AutonomousConfig
from soothe.foundation.autopilot.service import AutopilotService
from soothe.foundation.events.internal_bus import InternalEventBus
from soothe.foundation.autopilot.engine import GoalEngine


def _mock_consensus_model(*, decision: str, reasoning: str) -> AsyncMock:
    mock_model = AsyncMock()
    mock_model.ainvoke.return_value.type = "ai"
    mock_model.ainvoke.return_value.content = f"DECISION: {decision}\nREASONING: {reasoning}"
    return mock_model


@pytest.mark.asyncio
async def test_short_evidence_triggers_send_back() -> None:
    bus = InternalEventBus()
    ge = GoalEngine(internal_bus=bus, max_send_backs=3)
    svc = AutopilotService(
        goal_engine=ge,
        config=AutonomousConfig(max_loops=1, max_parallel_goals=1),
        internal_bus=bus,
        consensus_model=_mock_consensus_model(
            decision="send_back",
            reasoning="Evidence is too short to verify completion.",
        ),
    )
    goal = await svc.submit_task("short evidence test")
    await ge.claim_goal(goal.id, loop_id="w1")

    await svc._apply_consensus_and_finalize(goal.id, evidence_summary="too short")

    updated = await ge.get_goal(goal.id)
    assert updated is not None
    assert updated.status == "pending"
    assert updated.send_back_count == 1
