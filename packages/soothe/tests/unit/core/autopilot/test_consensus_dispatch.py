"""Tests for consensus wiring in AutopilotService dispatch completion (RFC-625)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.autopilot import AutopilotService
from soothe.autopilot.consensus import ConsensusVerdict
from soothe.config.models import AutopilotConfig
from soothe.context import ContextEngine
from soothe.events.internal_bus import InternalEventBus

from .fakes import IdleFakeFactory


def _mock_consensus_model(*, decision: str, reasoning: str) -> MagicMock:
    verdict = ConsensusVerdict(decision=decision, reasoning=reasoning)  # type: ignore[arg-type]
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=verdict.model_dump())
    mock_model = MagicMock()
    mock_model.with_structured_output = MagicMock(return_value=structured)
    return mock_model


@pytest.mark.asyncio
async def test_short_evidence_triggers_send_back() -> None:
    bus = InternalEventBus()
    ce = ContextEngine()
    svc = AutopilotService(
        ce=ce,
        config=AutopilotConfig(max_loops=1, max_parallel_goals=1),
        internal_bus=bus,
        consensus_model=_mock_consensus_model(
            decision="send_back",
            reasoning="Evidence is too short to verify completion.",
        ),
        runner_factory=IdleFakeFactory(),
    )
    goal = await svc.submit_task("short evidence test", max_send_backs=3)
    ce.claim_goal(goal.id, loop_id="w1")

    await svc._apply_consensus_and_finalize(goal.id, evidence_summary="too short")

    updated = await ce.get_goal(goal.id)
    assert updated is not None
    assert updated.status == "pending"
    assert updated.send_back_count == 1
