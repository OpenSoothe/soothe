"""Tests for IG-724 engine-driven trivial evidence turns."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.autopilot import AutopilotService
from soothe.autopilot.dispatch.plan_contribution import synthesize_sloop_response
from soothe.autopilot.verify.consensus import (
    ConsensusResult,
    ConsensusVerdict,
    _build_consensus_prompt,
    evaluate_goal_completion,
)
from soothe.config.models import AutopilotConfig
from soothe.context import ContextEngine
from soothe.events.internal_bus import InternalEventBus
from soothe.sloop.state.schemas import PlanResult

from .fakes import IdleFakeFactory


def _mock_consensus_model(
    *,
    decision: str,
    reasoning: str,
    evidence_follow_up: bool = False,
) -> MagicMock:
    verdict = ConsensusVerdict(
        decision=decision,  # type: ignore[arg-type]
        reasoning=reasoning,
        evidence_follow_up=evidence_follow_up,
    )
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=verdict.model_dump())
    mock_model = MagicMock()
    mock_model.with_structured_output = MagicMock(return_value=structured)
    return mock_model


class TestSynthesizePreferFullOutput:
    def test_prefer_full_output_over_thin_summary(self) -> None:
        pr = PlanResult(
            status="done",
            evidence_summary="Completed steps: a; b",
            full_output="Branch job/x/w1/auth\ncommits:\n abc feat auth",
        )
        assert "Branch job" in synthesize_sloop_response(pr, prefer_full_output=True)
        assert synthesize_sloop_response(pr, prefer_full_output=False).startswith("Completed steps")

    def test_wire_does_not_clip_long_full_output(self) -> None:
        proof = "PROOF_MARKER_TAIL commits: abc def"
        pr = PlanResult(
            status="done",
            evidence_summary="",
            full_output=("x" * 3000) + "\n" + proof,
        )
        wire = synthesize_sloop_response(pr, prefer_full_output=True)
        assert proof in wire
        assert len(wire) > 2048


class TestConsensusEvidenceFollowUp:
    def test_prompt_mentions_evidence_follow_up(self) -> None:
        prompt = _build_consensus_prompt("Goal", "thin", "")
        assert "evidence_follow_up" in prompt

    @pytest.mark.asyncio
    async def test_evidence_follow_up_only_on_send_back(self) -> None:
        mock_model = MagicMock()
        with patch(
            "soothe_nano.utils.llm.structured.invoke_structured_chat_typed",
            new_callable=AsyncMock,
            return_value=ConsensusVerdict(
                decision="accept",
                reasoning="ok",
                evidence_follow_up=True,
            ),
        ):
            result = await evaluate_goal_completion(
                goal_description="Goal",
                response_text="done",
                model=mock_model,
            )
        assert result.decision == "accept"
        assert result.evidence_follow_up is False

    @pytest.mark.asyncio
    async def test_send_back_with_evidence_follow_up(self) -> None:
        mock_model = MagicMock()
        with patch(
            "soothe_nano.utils.llm.structured.invoke_structured_chat_typed",
            new_callable=AsyncMock,
            return_value=ConsensusVerdict(
                decision="send_back",
                reasoning="Need git log proof",
                evidence_follow_up=True,
            ),
        ):
            result = await evaluate_goal_completion(
                goal_description="Implement auth",
                response_text="7 steps",
                model=mock_model,
            )
        assert result == ConsensusResult("send_back", "Need git log proof", True)


@pytest.mark.asyncio
async def test_consensus_queues_evidence_turn_instead_of_send_back() -> None:
    bus = InternalEventBus()
    ce = ContextEngine()
    svc = AutopilotService(
        ce=ce,
        config=AutopilotConfig(max_loops=1, max_parallel_goals=1),
        internal_bus=bus,
        consensus_model=_mock_consensus_model(
            decision="send_back",
            reasoning="No branch or commit proof in the response.",
            evidence_follow_up=True,
        ),
        runner_factory=IdleFakeFactory(),
    )
    goal = await svc.submit_task("maker auth slice", max_send_backs=3)
    ce.claim_goal(goal.id, loop_id="w1")

    with patch(
        "soothe.autopilot.verify.consensus.evaluate_goal_completion",
        new_callable=AsyncMock,
        return_value=ConsensusResult(
            "send_back",
            "No branch or commit proof in the response.",
            True,
        ),
    ):
        await svc._apply_consensus_and_finalize(
            goal.id,
            evidence_summary="too short",
            loop_id="autopilot__job__loop1",
            mission="implement",
        )

    updated = await ce.get_goal(goal.id)
    assert updated is not None
    assert updated.status == "pending"
    assert updated.send_back_count == 0
    assert updated.evidence_turn_count == 1
    assert updated.pending_mission == "collect_evidence"
    assert updated.stashed_implement_response == "too short"
    assert updated.evidence_prefer_loop_id == "autopilot__job__loop1"


@pytest.mark.asyncio
async def test_implement_dispatch_does_not_force_trivial() -> None:
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
    assert goal.pending_mission is None

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
    assert getattr(req, "autopilot_job").mission == "implement"


@pytest.mark.asyncio
async def test_evidence_dispatch_sets_trivial_intake() -> None:
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
    goal.pending_mission = "collect_evidence"
    goal.evidence_turn_count = 1
    goal.branch_id = "job/abcd/w1/auth"
    goal.workspace = "/repo/.soothe/worktrees/w1-auth"
    goal.stashed_implement_response = "thin"
    goal.guidance_accumulated = [
        {
            "text": "Evidence turn requested: Need git proof",
            "source": "consensus_evidence_follow_up",
        }
    ]

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
    assert getattr(req, "intake_scope") == "trivial"
    assert "max_iterations" not in getattr(req, "__dataclass_fields__", {})
    assert getattr(req, "client_workspace") == "/repo/.soothe/worktrees/w1-auth"
    job = getattr(req, "autopilot_job")
    assert job.mission == "collect_evidence"
    assert "Do NOT modify product code" in job.goal_description
    assert "job/abcd/w1/auth" in job.goal_description
    assert "/repo/.soothe/worktrees/w1-auth" in job.goal_description
    assert "git worktree" in job.goal_description
    assert "parent job" in job.goal_description


def test_evidence_mission_brief_worktree_vs_plain_workspace() -> None:
    from soothe.autopilot.service import _evidence_mission_brief
    from soothe.context.models import GoalNode

    wt = GoalNode(
        id="g1",
        description="maker auth",
        branch_id="job/abcd/w1/auth",
        workspace="/repo/.soothe/worktrees/w1-auth",
    )
    brief_wt = _evidence_mission_brief(wt)
    assert "Maker workspace" in brief_wt
    assert "git worktree" in brief_wt

    plain = GoalNode(
        id="g2",
        description="maker auth",
        branch_id="job/abcd/w1/auth",
        workspace="/repo",
    )
    brief_plain = _evidence_mission_brief(plain)
    assert "Maker workspace" in brief_plain
    assert "git worktree" not in brief_plain
    assert "sibling checkout" in brief_plain
