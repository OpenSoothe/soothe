"""Tests for IG-725: no evidence turns; trust StrangeLoop completion + Monitor path."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from soothe.config.models import AutopilotConfig
from soothe.context import ContextEngine
from soothe.events.internal_bus import InternalEventBus
from soothe.sloop.state.schemas import PlanResult

from soothe_autopilot import AutopilotService
from soothe_autopilot.dispatch.plan_contribution import synthesize_sloop_response
from soothe_autopilot.verify.consensus import (
    ConsensusResult,
    ConsensusVerdict,
)

from .fakes import IdleFakeFactory


def _mock_consensus_model(*, decision: str, reasoning: str) -> MagicMock:
    verdict = ConsensusVerdict(
        decision=decision,  # type: ignore[arg-type]
        reasoning=reasoning,
    )
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=verdict.model_dump())
    mock_model = MagicMock()
    mock_model.with_structured_output = MagicMock(return_value=structured)
    return mock_model


class TestSynthesizeResponse:
    def test_summary_preferred_by_default(self) -> None:
        pr = PlanResult(
            status="done",
            evidence_summary="Completed steps: a; b",
            full_output="Branch job/x/w1/auth\ncommits:\n abc feat auth",
        )
        assert synthesize_sloop_response(pr).startswith("Completed steps")


@pytest.mark.asyncio
async def test_proof_gap_send_back_uses_product_send_back_not_evidence_mission() -> None:
    bus = InternalEventBus()
    ce = ContextEngine()
    svc = AutopilotService(
        ce=ce,
        config=AutopilotConfig(max_loops=1, max_parallel_goals=1),
        internal_bus=bus,
        consensus_model=_mock_consensus_model(
            decision="send_back",
            reasoning="No branch or commit proof in the response.",
        ),
        runner_factory=IdleFakeFactory(),
    )
    goal = await svc.submit_task("maker auth slice", max_send_backs=3)
    ce.claim_goal(goal.id, loop_id="w1")

    with patch(
        "soothe_autopilot.verify.consensus.evaluate_goal_completion",
        new_callable=AsyncMock,
        return_value=ConsensusResult(
            "send_back",
            "No branch or commit proof in the response.",
        ),
    ):
        await svc._apply_consensus_and_finalize(
            goal.id,
            evidence_summary="too short",
            loop_id="autopilot__job__loop1",
        )

    updated = await ce.get_goal(goal.id)
    assert updated is not None
    assert updated.status == "pending"
    assert updated.send_back_count == 1
    assert "pending_mission" not in type(updated).model_fields


@pytest.mark.asyncio
async def test_accept_emits_goal_completed_for_monitor() -> None:
    bus = InternalEventBus()
    ce = ContextEngine()
    completed: list[str] = []

    async def _on_completed(event: object) -> None:
        gid = getattr(event, "goal_id", None)
        if gid:
            completed.append(str(gid))

    from soothe.events.internal_events import INTERNAL_GOAL_COMPLETED

    bus.subscribe(INTERNAL_GOAL_COMPLETED, _on_completed)

    svc = AutopilotService(
        ce=ce,
        config=AutopilotConfig(max_loops=1, max_parallel_goals=1),
        internal_bus=bus,
        consensus_model=_mock_consensus_model(decision="accept", reasoning="ok"),
        runner_factory=IdleFakeFactory(),
    )
    goal = await svc.submit_task("maker auth slice", max_send_backs=3)
    ce.claim_goal(goal.id, loop_id="w1")

    with patch(
        "soothe_autopilot.verify.consensus.evaluate_goal_completion",
        new_callable=AsyncMock,
        return_value=ConsensusResult("accept", "StrangeLoop completed"),
    ):
        await svc._apply_consensus_and_finalize(
            goal.id,
            evidence_summary="Implemented auth slice with commits",
            loop_id="w1",
        )

    updated = await ce.get_goal(goal.id)
    assert updated is not None
    assert updated.status == "completed"
    assert goal.id in completed


@pytest.mark.asyncio
async def test_implement_dispatch_defaults_intake_scope_null() -> None:
    bus = InternalEventBus()
    ce = ContextEngine()
    svc = AutopilotService(
        ce=ce,
        config=AutopilotConfig(max_loops=1, max_parallel_goals=1),
        internal_bus=bus,
        consensus_model=_mock_consensus_model(decision="accept", reasoning="ok"),
        runner_factory=IdleFakeFactory(),
    )
    goal = await svc.submit_task("implement feature", max_send_backs=3)

    captured: dict[str, object] = {}

    class _Worker:
        loop_id = "autopilot__x__y"

        def __init__(self) -> None:
            self.active_task = None

    def _fake_create_task(coro: object) -> MagicMock:
        frame = getattr(coro, "cr_frame", None)
        if frame is not None:
            captured["request"] = frame.f_locals.get("request")
        getattr(coro, "close", lambda: None)()
        return MagicMock()

    with patch("asyncio.create_task", side_effect=_fake_create_task):
        await svc._dispatch_to_worker(goal, _Worker())

    req = captured["request"]
    assert req is not None
    assert getattr(req, "intake_scope", "MISSING") is None
    job = getattr(req, "autopilot_job")
    assert job.goal_description == goal.description
    assert not hasattr(job, "mission")


@pytest.mark.asyncio
async def test_implement_dispatch_simple_intake_scope_forced() -> None:
    bus = InternalEventBus()
    ce = ContextEngine()
    svc = AutopilotService(
        ce=ce,
        config=AutopilotConfig(max_loops=1, max_parallel_goals=1, intake_scope="simple"),
        internal_bus=bus,
        consensus_model=_mock_consensus_model(decision="accept", reasoning="ok"),
        runner_factory=IdleFakeFactory(),
    )
    goal = await svc.submit_task("implement feature", max_send_backs=3)

    captured: dict[str, object] = {}

    class _Worker:
        loop_id = "autopilot__x__y"

        def __init__(self) -> None:
            self.active_task = None

    def _fake_create_task(coro: object) -> MagicMock:
        frame = getattr(coro, "cr_frame", None)
        if frame is not None:
            captured["request"] = frame.f_locals.get("request")
        getattr(coro, "close", lambda: None)()
        return MagicMock()

    with patch("asyncio.create_task", side_effect=_fake_create_task):
        await svc._dispatch_to_worker(goal, _Worker())

    req = captured["request"]
    assert req is not None
    assert getattr(req, "intake_scope", "MISSING") == "simple"


@pytest.mark.asyncio
async def test_goal_intake_scope_overrides_config() -> None:
    """Per-goal intake_scope wins over AutopilotConfig.intake_scope."""
    bus = InternalEventBus()
    ce = ContextEngine()
    svc = AutopilotService(
        ce=ce,
        config=AutopilotConfig(max_loops=1, max_parallel_goals=1, intake_scope="simple"),
        internal_bus=bus,
        consensus_model=_mock_consensus_model(decision="accept", reasoning="ok"),
        runner_factory=IdleFakeFactory(),
    )
    goal = await svc.submit_task("verify wave plan", max_send_backs=3)
    goal.intake_scope = "trivial"

    captured: dict[str, object] = {}

    class _Worker:
        loop_id = "autopilot__x__y"

        def __init__(self) -> None:
            self.active_task = None

    def _fake_create_task(coro: object) -> MagicMock:
        frame = getattr(coro, "cr_frame", None)
        if frame is not None:
            captured["request"] = frame.f_locals.get("request")
        getattr(coro, "close", lambda: None)()
        return MagicMock()

    with patch("asyncio.create_task", side_effect=_fake_create_task):
        await svc._dispatch_to_worker(goal, _Worker())

    req = captured["request"]
    assert req is not None
    assert getattr(req, "intake_scope", "MISSING") == "trivial"
