"""Tests for the relay channel projection / hydration (IG-775).

Covers the single reentrancy boundary: ``LoopPhaseScratch`` projection into
the ``relay_state`` graph channel and its inverse hydration on a fresh worker
(Rule 15 — fixes the "scratch is not serialized by LangGraph" fragility).
"""

from __future__ import annotations

from soothe.sloop.clarification.origins import ORIGIN_TOOL_APPROVAL
from soothe.sloop.clarification.protocol import ClarificationRequest, LoopStateView
from soothe.sloop.orchestrator.runtime_context import LoopPhaseScratch
from soothe.sloop.relay.channel import (
    ScratchProjection,
    build_relay_state_update,
    hydrate_inbox,
    hydrate_scratch_from_relay_state,
    project_inbox,
    project_scratch,
)
from soothe.sloop.relay.inbox import RelayInbox
from soothe.sloop.relay.ticket import ResumeTicket


def _view() -> LoopStateView:
    return LoopStateView(
        goal_id="g",
        goal_description="",
        user_request="",
        iteration=0,
        intent_classification=None,
        plan_summary=None,
        recent_step_outputs=(),
        workspace_summary=None,
        active_skills=(),
        active_mcp_servers=(),
    )


def _request(iid: str = "iii-1") -> ClarificationRequest:
    return ClarificationRequest(
        questions=("Approve?",),
        origin_node=ORIGIN_TOOL_APPROVAL,
        origin_interrupt_id=iid,
        loop_state=_view(),
    )


class TestScratchProjectionRoundTrip:
    def test_project_then_hydrate_restores_fields(self) -> None:
        scratch = LoopPhaseScratch(
            plan_draft_path="/tmp/plan.md",
            plan_draft_markdown="# Plan body",
            plan_review_comments="make it shorter",
            plan_rejected=False,
        )
        update = build_relay_state_update(
            inbox=RelayInbox(),
            scratch=scratch,
            active_origin="plan_mode_review",
            answer=None,
            audit=[],
        )
        assert update["relay_state"]["scratch"]["plan_draft_path"] == "/tmp/plan.md"
        assert update["relay_state"]["scratch"]["plan_draft_markdown"] == "# Plan body"

        fresh = LoopPhaseScratch()
        hydrate_scratch_from_relay_state(fresh, update["relay_state"])
        assert fresh.plan_draft_path == "/tmp/plan.md"
        assert fresh.plan_draft_markdown == "# Plan body"
        assert fresh.plan_review_comments == "make it shorter"

    def test_hydrate_is_idempotent_does_not_clobber(self) -> None:
        scratch = LoopPhaseScratch(plan_draft_path="/tmp/old.md")
        projection = ScratchProjection(plan_draft_path="/tmp/new.md")
        from soothe.sloop.relay.channel import hydrate_scratch

        hydrate_scratch(scratch, projection)
        assert scratch.plan_draft_path == "/tmp/old.md"

    def test_project_skips_ephemeral_fields(self) -> None:
        scratch = LoopPhaseScratch(iteration_perf_start=123.45, step_results=[1, 2])
        projection = project_scratch(scratch)
        assert not hasattr(projection, "iteration_perf_start")
        assert not hasattr(projection, "step_results")

    def test_plan_rejected_round_trips(self) -> None:
        scratch = LoopPhaseScratch(plan_rejected=True)
        update = build_relay_state_update(
            inbox=RelayInbox(),
            scratch=scratch,
            active_origin=None,
            answer=None,
            audit=[],
        )
        fresh = LoopPhaseScratch()
        hydrate_scratch_from_relay_state(fresh, update["relay_state"])
        assert fresh.plan_rejected is True


class TestInboxSerializeHydrate:
    def test_round_trip_preserves_entries(self) -> None:
        inbox = RelayInbox()
        inbox.enqueue(
            _request("iii-1"),
            resume_ticket=ResumeTicket(thread_id="t1", step_id="s1"),
            step_id="s1",
        )
        inbox.enqueue(
            _request("iii-2"),
            resume_ticket=ResumeTicket(thread_id="t2", step_id="s2"),
            step_id="s2",
        )
        serialized = project_inbox(inbox)
        assert len(serialized) == 2
        assert serialized[0]["resume_ticket"]["thread_id"] == "t1"

        restored = hydrate_inbox({"inbox": serialized})
        assert len(restored) == 2
        assert restored.head.origin_interrupt_id == "iii-1"
        assert restored.head_ticket.thread_id == "t1"

    def test_hydrate_empty_state_returns_empty_inbox(self) -> None:
        assert len(hydrate_inbox(None)) == 0
        assert len(hydrate_inbox({})) == 0
        assert len(hydrate_inbox({"inbox": "not-a-list"})) == 0

    def test_hydrate_skips_malformed_entries(self) -> None:
        bad = {"inbox": [{"no_request": {}}, {"request": {}, "resume_ticket": {}}]}
        restored = hydrate_inbox(bad)
        assert len(restored) == 0

    def test_hydrate_skips_entry_without_thread_id(self) -> None:
        from soothe.sloop.clarification.protocol import request_to_state

        req = _request("iii-1")
        bad = {"inbox": [{"request": request_to_state(req), "resume_ticket": {"thread_id": None}}]}
        restored = hydrate_inbox(bad)
        assert len(restored) == 0
