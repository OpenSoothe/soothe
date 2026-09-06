"""Tests for the LoopRelay orchestrator (IG-775).

Covers the full interrupt → park → resume lifecycle: capture from a
``GraphInterrupt``, origin-aware routing, resume command building (live
``interrupt()`` + orphan goto), per-thread lock concurrency, stale-head
detection, answer record/consume, and the typed ``RelayError`` outcomes.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from langgraph.errors import GraphInterrupt

from soothe.sloop.clarification.detector import ClarificationDetector
from soothe.sloop.clarification.origins import ORIGIN_EXECUTE, ORIGIN_TOOL_APPROVAL
from soothe.sloop.clarification.protocol import (
    ClarificationAnswer,
    LoopStateView,
)
from soothe.sloop.orchestrator.runtime_context import LoopPhaseScratch
from soothe.sloop.relay import (
    LoopRelay,
    RelayResumeMismatchError,
    RelayStaleInterruptError,
)
from soothe.sloop.relay.ticket import ResumeTicket


def _view() -> LoopStateView:
    return LoopStateView(
        goal_id="g",
        goal_description="do the thing",
        user_request="do the thing",
        iteration=1,
        intent_classification=None,
        plan_summary=None,
        recent_step_outputs=(),
        workspace_summary=None,
        active_skills=(),
        active_mcp_servers=(),
    )


def _ask_user_interrupt(iid: str = "iAU1") -> dict[str, Any]:
    return {iid: {"type": "ask_user", "questions": ["What next?"]}}


def _tool_approval_interrupt(iid: str = "iTA1") -> dict[str, Any]:
    return {iid: {"action_requests": [{"name": "edit_file", "args": {"file_path": "/tmp/x"}}]}}


def _make_relay() -> LoopRelay:
    events: list[tuple[str, Any]] = []

    async def emit(event_type: str, event_data: Any) -> None:
        events.append((event_type, event_data))

    relay = LoopRelay(loop_id="loop-1", emit=emit)
    return relay, events  # type: ignore[return-value]


class _RecordingRelay(tuple):
    """Helper so test bodies read relay + events from one make_relay() call."""


@pytest.fixture
def relay_and_events():
    return _make_relay()


def _capture(
    relay: LoopRelay,
    interrupts: dict[str, Any],
    *,
    origin: str = ORIGIN_EXECUTE,
    thread_id: str = "loop-1__a3f7c",
    step_id: str = "step-1",
) -> Any:
    return relay.capture_interrupt(
        exc=GraphInterrupt(interrupts),  # type: ignore[arg-type]
        origin=origin,
        ticket=ResumeTicket(thread_id=thread_id, step_id=step_id, step_description="desc"),
        step_id=step_id,
        detector=ClarificationDetector(),
        loop_state_view=_view(),
        scratch=LoopPhaseScratch(),
    )


class TestCaptureInterrupt:
    @pytest.mark.asyncio
    async def test_captures_ask_user_and_halts_step(self, relay_and_events) -> None:
        relay, events = relay_and_events
        outcome = await _capture(relay, _ask_user_interrupt())
        assert outcome.halt_step is True
        assert outcome.error is None
        assert "relay_state" in outcome.channel_update
        assert len(relay.inbox) == 1
        assert relay.active_origin == ORIGIN_EXECUTE
        assert events and events[0][0] == "soothe.cognition.relay.captured"

    @pytest.mark.asyncio
    async def test_captures_tool_approval_origin(self, relay_and_events) -> None:
        relay, _ = relay_and_events
        outcome = await _capture(relay, _tool_approval_interrupt())
        assert outcome.halt_step is True
        assert relay.inbox.head.origin_node == ORIGIN_TOOL_APPROVAL

    @pytest.mark.asyncio
    async def test_non_clarification_interrupt_does_not_halt(self, relay_and_events) -> None:
        relay, _ = relay_and_events
        outcome = await _capture(relay, {"iX": {"type": "other", "foo": "bar"}})
        assert outcome.halt_step is False
        assert len(relay.inbox) == 0

    @pytest.mark.asyncio
    async def test_empty_interrupt_args_returns_no_halt(self, relay_and_events) -> None:
        relay, _ = relay_and_events
        outcome = await relay.capture_interrupt(
            exc=GraphInterrupt(()),  # type: ignore[arg-type]
            origin=ORIGIN_EXECUTE,
            ticket=ResumeTicket(thread_id="t"),
            step_id="s",
            detector=ClarificationDetector(),
            loop_state_view=_view(),
            scratch=LoopPhaseScratch(),
        )
        assert outcome.halt_step is False
        assert outcome.error is None

    @pytest.mark.asyncio
    async def test_malformed_interrupt_raises_no_error_but_no_halt(self, relay_and_events) -> None:
        relay, _ = relay_and_events

        class BadExcError(Exception):
            pass

        outcome = await relay.capture_interrupt(
            exc=BadExcError("not a GraphInterrupt"),  # type: ignore[arg-type]
            origin=ORIGIN_EXECUTE,
            ticket=ResumeTicket(thread_id="t"),
            step_id="s",
            detector=ClarificationDetector(),
            loop_state_view=_view(),
            scratch=LoopPhaseScratch(),
        )
        assert outcome.halt_step is False


class TestRouteCaptured:
    @pytest.mark.asyncio
    async def test_execute_routes_to_execute(self, relay_and_events) -> None:
        relay, _ = relay_and_events
        await _capture(relay, _ask_user_interrupt())
        decision = relay.route_captured()
        assert decision.resume_node == "execute"
        assert decision.pause_mode == "interactive"

    @pytest.mark.asyncio
    async def test_tool_approval_routes_to_execute(self, relay_and_events) -> None:
        relay, _ = relay_and_events
        await _capture(relay, _tool_approval_interrupt())
        decision = relay.route_captured()
        assert decision.resume_node == "execute"

    @pytest.mark.asyncio
    async def test_empty_inbox_routes_nowhere(self, relay_and_events) -> None:
        relay, _ = relay_and_events
        decision = relay.route_captured()
        assert decision.resume_node is None


class TestBuildResumeCommand:
    @pytest.mark.asyncio
    async def test_live_interrupt_resume(self, relay_and_events) -> None:
        relay, _ = relay_and_events
        await _capture(relay, _ask_user_interrupt())
        snapshot = SimpleNamespace(
            interrupts=(object(),),
            tasks=(),
            values={"relay_state": {"inbox": [{}], "answer": None}},
        )
        cmd = await relay.build_resume_command(
            answers=["do X"],
            snapshot=snapshot,
            relay_state={"inbox": [{}], "answer": None, "parked_head_ticket_id": "loop-1__a3f7c"},
        )
        assert cmd is not None
        assert cmd.resume == {"answers": ["do X"]}

    @pytest.mark.asyncio
    async def test_no_pending_returns_none(self, relay_and_events) -> None:
        relay, _ = relay_and_events
        snapshot = SimpleNamespace(interrupts=(), tasks=(), values={})
        cmd = await relay.build_resume_command(answers=["x"], snapshot=snapshot, relay_state=None)
        assert cmd is None

    @pytest.mark.asyncio
    async def test_stale_head_raises(self, relay_and_events) -> None:
        relay, _ = relay_and_events
        await _capture(relay, _ask_user_interrupt())  # head ticket = loop-1__a3f7c
        snapshot = SimpleNamespace(
            interrupts=(object(),),
            tasks=(),
            values={"relay_state": {"inbox": [{}], "answer": None}},
        )
        with pytest.raises(RelayStaleInterruptError):
            await relay.build_resume_command(
                answers=["x"],
                snapshot=snapshot,
                relay_state={
                    "inbox": [{}],
                    "answer": None,
                    "parked_head_ticket_id": "different-thread",
                },
            )


class TestResumeSlot:
    @pytest.mark.asyncio
    async def test_per_thread_lock_serializes(self, relay_and_events) -> None:
        relay, _ = relay_and_events
        held: list[int] = []

        async def hold(slot: str, delay: float) -> None:
            async with relay.resume_slot(slot):
                held.append(1)
                await asyncio.sleep(delay)

        await asyncio.gather(hold("t1", 0.05), hold("t1", 0.01), hold("t2", 0.01))
        assert held == [1, 1, 1]

    @pytest.mark.asyncio
    async def test_parallel_across_threads(self, relay_and_events) -> None:
        relay, _ = relay_and_events
        order: list[str] = []

        async def hold(slot: str, label: str) -> None:
            async with relay.resume_slot(slot):
                order.append(label)

        await asyncio.gather(hold("t1", "a"), hold("t2", "b"))
        assert set(order) == {"a", "b"}


class TestAnswerLifecycle:
    @pytest.mark.asyncio
    async def test_record_then_consume(self, relay_and_events) -> None:
        relay, _ = relay_and_events
        await _capture(relay, _ask_user_interrupt())
        answer = ClarificationAnswer(answers=("do X",), source="human")
        update = relay.record_answer(answer=answer, scratch=LoopPhaseScratch())
        assert update["relay_state"]["answer"]["answers"] == ["do X"]

        consumed = relay.consume_answer(update["relay_state"])
        assert consumed is not None
        request, ans, ticket = consumed
        assert request.origin_interrupt_id == "iAU1"
        assert ans.answers == ("do X",)
        assert ticket.thread_id == "loop-1__a3f7c"
        assert len(relay.inbox) == 0

    @pytest.mark.asyncio
    async def test_consume_empty_returns_none(self, relay_and_events) -> None:
        relay, _ = relay_and_events
        assert relay.consume_answer(None) is None
        assert relay.consume_answer({}) is None
        assert relay.consume_answer({"answer": None}) is None

    @pytest.mark.asyncio
    async def test_build_core_agent_resume_payload(self, relay_and_events) -> None:
        relay, _ = relay_and_events
        await _capture(relay, _ask_user_interrupt())
        request = relay.inbox.head
        answer = ClarificationAnswer(answers=("do X",), source="human")
        payload = relay.build_core_agent_resume_payload(request=request, answer=answer)
        assert payload == {"iAU1": {"answers": ["do X"]}}

    @pytest.mark.asyncio
    async def test_mismatch_on_empty_answer_for_ask_user(self, relay_and_events) -> None:
        relay, _ = relay_and_events
        await _capture(relay, _ask_user_interrupt())
        request = relay.inbox.head
        answer = ClarificationAnswer(answers=(), source="human")
        with pytest.raises(RelayResumeMismatchError):
            relay.build_core_agent_resume_payload(request=request, answer=answer)


class TestProjectAndHydrate:
    @pytest.mark.asyncio
    async def test_project_then_hydrate_round_trip(self, relay_and_events) -> None:
        relay, _ = relay_and_events
        await _capture(relay, _ask_user_interrupt())
        scratch = LoopPhaseScratch(plan_draft_path="/tmp/p.md")
        update = relay.project_to_channels(scratch=scratch, mark_parked_head=True)
        assert update["relay_state"]["parked_head_ticket_id"] == "loop-1__a3f7c"

        fresh = LoopRelay(loop_id="loop-1", emit=relay._emit)
        fresh.hydrate_from_channels(update["relay_state"], scratch=LoopPhaseScratch())
        assert len(fresh.inbox) == 1
        assert fresh.inbox.head_ticket.thread_id == "loop-1__a3f7c"
        assert fresh._parked_head_ticket_id == "loop-1__a3f7c"

    @pytest.mark.asyncio
    async def test_snapshot_view(self, relay_and_events) -> None:
        relay, _ = relay_and_events
        await _capture(relay, _ask_user_interrupt())
        snap = relay.snapshot()
        assert snap.inbox_len == 1
        assert snap.head_ticket_id == "loop-1__a3f7c"
        assert snap.active_origin == ORIGIN_EXECUTE
