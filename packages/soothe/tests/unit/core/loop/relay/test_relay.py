"""Integration tests for the InterruptRelay lifecycle (capture → park → resume → consume)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from soothe.sloop.clarification.origins import (
    ORIGIN_EXECUTE,
    ORIGIN_PLAN_MODE_REVIEW,
    ORIGIN_TOOL_APPROVAL,
)
from soothe.sloop.clarification.protocol import (
    ClarificationAnswer,
    ClarificationDeferredError,
    ClarificationRequest,
    LoopStateView,
)
from soothe.sloop.relay import InterruptRelay, RelayConfig
from soothe.sloop.relay.errors import RelayQueueFullError
from soothe.sloop.relay.store import SqliteClarificationStore
from soothe.sloop.relay.types import (
    projection_from_state,
    projection_to_state,
)

# ── Test fixtures ───────────────────────────────────────────────────────────


def _view(goal_id: str = "g1") -> LoopStateView:
    return LoopStateView(
        goal_id=goal_id,
        goal_description="test goal",
        user_request="build the auth module",
        iteration=1,
        intent_classification="agentic",
        plan_summary="step 1: write auth",
        recent_step_outputs=("output1",),
        workspace_summary="src/",
        active_skills=(),
        active_mcp_servers=(),
    )


def _ask_user_interrupt() -> dict[str, Any]:
    return {
        "type": "ask_user",
        "questions": [
            {
                "question": "Which auth provider?",
                "header": "Auth",
                "options": [
                    {"label": "OAuth2", "description": "OAuth 2.0"},
                    {"label": "SAML", "description": "SAML SSO"},
                ],
            }
        ],
    }


def _tool_approval_interrupt() -> dict[str, Any]:
    return {
        "action_requests": [
            {
                "name": "edit_file",
                "args": {"file_path": "/workspace/src/auth.py"},
            }
        ]
    }


@dataclass
class MockGoal:
    status: str = "active"


class MockCE:
    """Minimal CE mock for relay tests."""

    def __init__(self, goal_status: str = "active") -> None:
        self._goals: dict[str, MockGoal] = {}

    def set_goal_status(self, goal_id: str, status: str) -> None:
        self._goals[goal_id] = MockGoal(status=status)

    def get_goal(self, goal_id: str) -> MockGoal | None:
        return self._goals.get(goal_id)

    async def mark_awaiting_clarification(
        self, goal_id: str, pending: dict[str, Any] | None, *, reason: str = ""
    ) -> None:
        self._goals[goal_id] = MockGoal(status="awaiting_clarification")

    async def answer_clarification(self, goal_id: str, answers: list[str]) -> None:
        self._goals[goal_id] = MockGoal(status="pending")


class MockEmit:
    """Collects emitted events for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))


class ManualPolicy:
    """Interactive policy mock — returns defer=True with defer_kind='manual'."""

    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer:
        return ClarificationAnswer(
            answers=(),
            source="human",
            defer=True,
            audit={"defer_kind": "manual", "reason": "awaiting human"},
        )


class AutoPolicy:
    """Auto policy mock — resolves inline with a veritas answer."""

    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer:
        return ClarificationAnswer(
            answers=("OAuth2",),
            source="veritas",
            confidence=0.85,
            defer=False,
        )


class DeferringPolicy:
    """Auto policy mock — always defers."""

    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer:
        raise ClarificationDeferredError("low confidence", request, kind="low_confidence")


class RetryPolicy:
    """Auto policy mock — returns retry sentinel (veritas failure)."""

    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer:
        n = len(request.questions) or 1
        return ClarificationAnswer(
            answers=tuple("(retry)" for _ in range(n)),
            source="retry",
            confidence=0.0,
            defer=False,
        )


@pytest.fixture
async def relay() -> InterruptRelay:
    store = SqliteClarificationStore("loop-1", db_path=Path(":memory:"))
    r = InterruptRelay(
        store=store,
        config=RelayConfig(max_pending_per_goal=10, max_consecutive_retries=5),
    )
    yield r  # type: ignore[misc]
    await store.close()


# ── Capture tests ──────────────────────────────────────────────────────────


class TestCapture:
    async def test_capture_ask_user(self, relay: InterruptRelay) -> None:
        handle = await relay.capture(
            interrupt_value=_ask_user_interrupt(),
            interrupt_id="iid-1",
            thread_id="thread-1",
            step_id="step-1",
            step_description="write auth",
            loop_id="loop-1",
            goal_id="g1",
            loop_state=_view(),
            origin_node=ORIGIN_EXECUTE,
            policy_mode="manual",
        )
        assert handle is not None
        assert handle.origin == ORIGIN_EXECUTE
        assert handle.core_agent_thread_id == "thread-1"
        assert handle.request.origin_interrupt_id == "iid-1"

    async def test_capture_tool_approval(self, relay: InterruptRelay) -> None:
        handle = await relay.capture(
            interrupt_value=_tool_approval_interrupt(),
            interrupt_id="iid-2",
            thread_id="thread-1",
            step_id="step-1",
            step_description="write auth",
            loop_id="loop-1",
            goal_id="g1",
            loop_state=_view(),
            origin_node=ORIGIN_TOOL_APPROVAL,
            policy_mode="auto",
        )
        assert handle is not None
        assert handle.origin == ORIGIN_TOOL_APPROVAL
        assert "action_requests" in handle.request.metadata

    async def test_capture_unmanaged_returns_none(self, relay: InterruptRelay) -> None:
        handle = await relay.capture(
            interrupt_value={"type": "unknown", "data": "foo"},
            interrupt_id="iid-x",
            thread_id="thread-1",
            step_id="step-1",
            step_description="step",
            loop_id="loop-1",
            goal_id="g1",
            loop_state=_view(),
            origin_node=ORIGIN_EXECUTE,
            policy_mode="manual",
        )
        assert handle is None

    async def test_capture_queue_full_raises(self, relay: InterruptRelay) -> None:
        for i in range(10):
            handle = await relay.capture(
                interrupt_value=_ask_user_interrupt(),
                interrupt_id=f"iid-{i}",
                thread_id=f"thread-{i}",
                step_id=f"step-{i}",
                step_description="step",
                loop_id="loop-1",
                goal_id="g1",
                loop_state=_view(),
                origin_node=ORIGIN_EXECUTE,
                policy_mode="manual",
            )
            assert handle is not None
        with pytest.raises(RelayQueueFullError, match="queue full"):
            await relay.capture(
                interrupt_value=_ask_user_interrupt(),
                interrupt_id="iid-overflow",
                thread_id="thread-x",
                step_id="step-x",
                step_description="step",
                loop_id="loop-1",
                goal_id="g1",
                loop_state=_view(),
                origin_node=ORIGIN_EXECUTE,
                policy_mode="manual",
            )


# ── Park tests ─────────────────────────────────────────────────────────────


class TestPark:
    async def test_park_manual_returns_awaiting_human(self, relay: InterruptRelay) -> None:
        handle = await relay.capture(
            interrupt_value=_ask_user_interrupt(),
            interrupt_id="iid-1",
            thread_id="thread-1",
            step_id="step-1",
            step_description="step",
            loop_id="loop-1",
            goal_id="g1",
            loop_state=_view(),
            origin_node=ORIGIN_EXECUTE,
            policy_mode="manual",
        )
        assert handle is not None
        ce = MockCE()
        emit = MockEmit()
        outcome = await relay.park(handle, policy=ManualPolicy(), ce=ce, emit=emit)
        assert outcome.kind == "awaiting_human"
        assert outcome.relay_id == handle.relay_id
        # Row should be parked
        row = await relay.store.get(handle.relay_id)
        assert row is not None
        assert row.status == "parked"
        assert row.defer_kind == "manual"
        # CE goal should be awaiting_clarification
        goal = ce.get_goal("g1")
        assert goal is not None
        assert goal.status == "awaiting_clarification"
        # Should have emitted clarification_requested
        event_types = [e[0] for e in emit.events]
        assert "clarification_requested" in event_types

    async def test_park_auto_resolves_inline(self, relay: InterruptRelay) -> None:
        handle = await relay.capture(
            interrupt_value=_ask_user_interrupt(),
            interrupt_id="iid-1",
            thread_id="thread-1",
            step_id="step-1",
            step_description="step",
            loop_id="loop-1",
            goal_id="g1",
            loop_state=_view(),
            origin_node=ORIGIN_EXECUTE,
            policy_mode="auto",
        )
        assert handle is not None
        emit = MockEmit()
        outcome = await relay.park(handle, policy=AutoPolicy(), emit=emit)
        assert outcome.kind == "answered"
        assert outcome.answer is not None
        assert outcome.answer.source == "veritas"
        assert outcome.answer.answers == ("OAuth2",)
        # Row should be answered
        row = await relay.store.get(handle.relay_id)
        assert row is not None
        assert row.status == "answered"
        assert row.answer_source == "veritas"

    async def test_park_auto_defer(self, relay: InterruptRelay) -> None:
        handle = await relay.capture(
            interrupt_value=_ask_user_interrupt(),
            interrupt_id="iid-1",
            thread_id="thread-1",
            step_id="step-1",
            step_description="step",
            loop_id="loop-1",
            goal_id="g1",
            loop_state=_view(),
            origin_node=ORIGIN_EXECUTE,
            policy_mode="auto",
        )
        assert handle is not None
        ce = MockCE()
        outcome = await relay.park(handle, policy=DeferringPolicy(), ce=ce)
        assert outcome.kind == "deferred"
        assert outcome.defer_kind == "low_confidence"
        # CE goal should be awaiting_clarification
        goal = ce.get_goal("g1")
        assert goal is not None
        assert goal.status == "awaiting_clarification"

    async def test_park_no_policy_defers(self, relay: InterruptRelay) -> None:
        handle = await relay.capture(
            interrupt_value=_ask_user_interrupt(),
            interrupt_id="iid-1",
            thread_id="thread-1",
            step_id="step-1",
            step_description="step",
            loop_id="loop-1",
            goal_id="g1",
            loop_state=_view(),
            origin_node=ORIGIN_EXECUTE,
            policy_mode="manual",
        )
        assert handle is not None
        outcome = await relay.park(handle, policy=None)
        assert outcome.kind == "deferred"


# ── Submit + Resume tests ──────────────────────────────────────────────────


class TestSubmitAndResume:
    async def _capture_and_park_manual(self, relay: InterruptRelay) -> str:
        handle = await relay.capture(
            interrupt_value=_ask_user_interrupt(),
            interrupt_id="iid-1",
            thread_id="thread-1",
            step_id="step-1",
            step_description="step",
            loop_id="loop-1",
            goal_id="g1",
            loop_state=_view(),
            origin_node=ORIGIN_EXECUTE,
            policy_mode="manual",
        )
        assert handle is not None
        ce = MockCE()
        await relay.park(handle, policy=ManualPolicy(), ce=ce)
        return handle.relay_id

    async def test_submit_answer_ok(self, relay: InterruptRelay) -> None:
        relay_id = await self._capture_and_park_manual(relay)
        ce = MockCE()
        ce.set_goal_status("g1", "awaiting_clarification")
        result = await relay.submit_answer(
            relay_id=relay_id,
            answers=("OAuth2",),
            source="human",
            idempotency_key="key-1",
            ce=ce,
        )
        assert result.status == "ok"
        assert result.stored_answer is not None
        assert result.stored_answer.answers == ("OAuth2",)
        # CE goal should be unblocked
        goal = ce.get_goal("g1")
        assert goal is not None
        assert goal.status == "pending"

    async def test_submit_answer_idempotent(self, relay: InterruptRelay) -> None:
        relay_id = await self._capture_and_park_manual(relay)
        ce = MockCE()
        ce.set_goal_status("g1", "awaiting_clarification")
        await relay.submit_answer(
            relay_id=relay_id,
            answers=("OAuth2",),
            source="human",
            idempotency_key="key-1",
            ce=ce,
        )
        # Duplicate submit returns already_answered
        result2 = await relay.submit_answer(
            relay_id=relay_id,
            answers=("SAML",),
            source="human",
            idempotency_key="key-2",
            ce=ce,
        )
        assert result2.status == "already_answered"
        # The stored answer is the first one
        assert result2.stored_answer is not None
        assert result2.stored_answer.answers == ("OAuth2",)

    async def test_build_resume_directive_execute(self, relay: InterruptRelay) -> None:
        relay_id = await self._capture_and_park_manual(relay)
        ce = MockCE()
        ce.set_goal_status("g1", "awaiting_clarification")
        await relay.submit_answer(
            relay_id=relay_id,
            answers=("OAuth2",),
            source="human",
            ce=ce,
        )
        # CE should now be pending
        ce.set_goal_status("g1", "pending")
        directive = await relay.build_resume_directive(
            relay_id=relay_id,
            ce=ce,
        )
        assert directive.relay_id == relay_id
        assert directive.resume_station == "execute"
        assert directive.core_agent_resume is not None
        assert directive.core_agent_resume.thread_id == "thread-1"
        assert directive.core_agent_resume.resume_payload == {"iid-1": {"answers": ["OAuth2"]}}
        assert "pending_clarification_answer" in directive.graph_input
        assert directive.graph_input["resume_relay_id"] == relay_id

    async def test_build_resume_directive_plan_review(self, relay: InterruptRelay) -> None:
        handle = await relay.capture(
            interrupt_value=_ask_user_interrupt(),
            interrupt_id="plan-mode-review:1",
            thread_id=None,
            step_id=None,
            step_description=None,
            loop_id="loop-1",
            goal_id="g1",
            loop_state=_view(),
            origin_node=ORIGIN_PLAN_MODE_REVIEW,
            policy_mode="manual",
        )
        assert handle is not None
        ce = MockCE()
        await relay.park(handle, policy=ManualPolicy(), ce=ce)
        await relay.submit_answer(
            relay_id=handle.relay_id,
            answers=("approve",),
            source="human",
            ce=ce,
        )
        ce.set_goal_status("g1", "pending")
        directive = await relay.build_resume_directive(
            relay_id=handle.relay_id,
            ce=ce,
        )
        assert directive.resume_station == "plan_review"
        # plan_mode_review has no CoreAgent resume
        assert directive.core_agent_resume is None

    async def test_get_core_agent_resume(self, relay: InterruptRelay) -> None:
        relay_id = await self._capture_and_park_manual(relay)
        ce = MockCE()
        ce.set_goal_status("g1", "awaiting_clarification")
        await relay.submit_answer(
            relay_id=relay_id,
            answers=("OAuth2",),
            source="human",
            ce=ce,
        )
        spec = await relay.get_core_agent_resume(relay_id=relay_id)
        assert spec is not None
        assert spec.thread_id == "thread-1"
        assert spec.resume_payload == {"iid-1": {"answers": ["OAuth2"]}}

    async def test_consume(self, relay: InterruptRelay) -> None:
        relay_id = await self._capture_and_park_manual(relay)
        ce = MockCE()
        ce.set_goal_status("g1", "awaiting_clarification")
        await relay.submit_answer(
            relay_id=relay_id,
            answers=("OAuth2",),
            source="human",
            ce=ce,
        )
        await relay.consume(relay_id=relay_id)
        row = await relay.store.get(relay_id)
        assert row is not None
        assert row.status == "consumed"
        assert row.consumed_at is not None


# ── Reconcile tests ────────────────────────────────────────────────────────


class TestReconcile:
    async def test_reconcile_ok(self, relay: InterruptRelay) -> None:
        handle = await relay.capture(
            interrupt_value=_ask_user_interrupt(),
            interrupt_id="iid-1",
            thread_id="thread-1",
            step_id="step-1",
            step_description="step",
            loop_id="loop-1",
            goal_id="g1",
            loop_state=_view(),
            origin_node=ORIGIN_EXECUTE,
            policy_mode="manual",
        )
        assert handle is not None
        ce = MockCE()
        await relay.park(handle, policy=ManualPolicy(), ce=ce)
        await relay.submit_answer(
            relay_id=handle.relay_id,
            answers=("OAuth2",),
            source="human",
            ce=ce,
        )
        ce.set_goal_status("g1", "pending")
        report = await relay.reconcile(relay_id=handle.relay_id, ce=ce)
        assert report.consistent is True
        assert report.relay_status == "answered"
        assert report.ce_goal_status == "pending"

    async def test_reconcile_ce_still_parked(self, relay: InterruptRelay) -> None:
        handle = await relay.capture(
            interrupt_value=_ask_user_interrupt(),
            interrupt_id="iid-1",
            thread_id="thread-1",
            step_id="step-1",
            step_description="step",
            loop_id="loop-1",
            goal_id="g1",
            loop_state=_view(),
            origin_node=ORIGIN_EXECUTE,
            policy_mode="manual",
        )
        assert handle is not None
        ce = MockCE()
        await relay.park(handle, policy=ManualPolicy(), ce=ce)
        await relay.submit_answer(
            relay_id=handle.relay_id,
            answers=("OAuth2",),
            source="human",
            ce=ce,
        )
        # Simulate CE goal stuck in awaiting_clarification (answer_clarification failed)
        ce.set_goal_status("g1", "awaiting_clarification")
        report = await relay.reconcile(relay_id=handle.relay_id, ce=ce)
        assert report.consistent is False
        assert "awaiting_clarification" in (report.conflict or "")

    async def test_reconcile_row_not_answered(self, relay: InterruptRelay) -> None:
        handle = await relay.capture(
            interrupt_value=_ask_user_interrupt(),
            interrupt_id="iid-1",
            thread_id="thread-1",
            step_id="step-1",
            step_description="step",
            loop_id="loop-1",
            goal_id="g1",
            loop_state=_view(),
            origin_node=ORIGIN_EXECUTE,
            policy_mode="manual",
        )
        assert handle is not None
        ce = MockCE()
        await relay.park(handle, policy=ManualPolicy(), ce=ce)
        # Row is "parked", not "answered"
        report = await relay.reconcile(relay_id=handle.relay_id, ce=ce)
        assert report.consistent is False
        assert "parked" in (report.conflict or "")

    async def test_reconcile_missing_row(self, relay: InterruptRelay) -> None:
        report = await relay.reconcile(relay_id="nonexistent")
        assert report.consistent is False
        assert "not found" in (report.conflict or "")


# ─-- Circuit breaker tests ───────────────────────────────────────────────


class TestCircuitBreaker:
    async def test_retry_circuit_breaker(self, relay: InterruptRelay) -> None:
        """The circuit breaker trips after max_consecutive_retries park() calls.

        Each park() call with a retry policy stores the retry answer and
        the goal accumulates retry rows. After the cap, park() returns
        deferred with defer_kind="retry_limit".
        """
        for i in range(5):
            handle = await relay.capture(
                interrupt_value=_ask_user_interrupt(),
                interrupt_id=f"iid-{i}",
                thread_id=f"thread-{i}",
                step_id=f"step-{i}",
                step_description="step",
                loop_id="loop-1",
                goal_id="g1",
                loop_state=_view(),
                origin_node=ORIGIN_EXECUTE,
                policy_mode="auto",
            )
            assert handle is not None
            outcome = await relay.park(handle, policy=RetryPolicy())
            # First 5 should be answered (retry sentinel stored)
            assert outcome.kind == "answered", (
                f"iteration {i}: expected answered, got {outcome.kind}"
            )

        # 6th capture+park should trip the circuit breaker
        handle = await relay.capture(
            interrupt_value=_ask_user_interrupt(),
            interrupt_id="iid-5",
            thread_id="thread-5",
            step_id="step-5",
            step_description="step",
            loop_id="loop-1",
            goal_id="g1",
            loop_state=_view(),
            origin_node=ORIGIN_EXECUTE,
            policy_mode="auto",
        )
        assert handle is not None
        outcome = await relay.park(handle, policy=RetryPolicy())
        assert outcome.kind == "deferred"
        assert outcome.defer_kind == "retry_limit"
        # Row should be failed
        row = await relay.store.get(handle.relay_id)
        assert row is not None
        assert row.status == "failed"


# ── Projection tests ──────────────────────────────────────────────────────


class TestProjection:
    async def test_project_for_graph(self, relay: InterruptRelay) -> None:
        handle = await relay.capture(
            interrupt_value=_ask_user_interrupt(),
            interrupt_id="iid-1",
            thread_id="thread-1",
            step_id="step-1",
            step_description="step",
            loop_id="loop-1",
            goal_id="g1",
            loop_state=_view(),
            origin_node=ORIGIN_EXECUTE,
            policy_mode="manual",
        )
        assert handle is not None
        projection = relay.project_for_graph(handle)
        assert projection.resume_relay_id == handle.relay_id
        assert projection.last_clarification_origin == ORIGIN_EXECUTE
        assert "questions" in projection.pending_clarification

    async def test_projection_round_trip(self, relay: InterruptRelay) -> None:
        handle = await relay.capture(
            interrupt_value=_ask_user_interrupt(),
            interrupt_id="iid-1",
            thread_id="thread-1",
            step_id="step-1",
            step_description="step",
            loop_id="loop-1",
            goal_id="g1",
            loop_state=_view(),
            origin_node=ORIGIN_EXECUTE,
            policy_mode="manual",
        )
        assert handle is not None
        projection = relay.project_for_graph(handle)
        state = projection_to_state(projection)
        restored = projection_from_state(state)
        assert restored is not None
        assert restored.resume_relay_id == projection.resume_relay_id
        assert restored.last_clarification_origin == projection.last_clarification_origin

    async def test_projection_from_empty_state(self) -> None:
        assert projection_from_state({}) is None
        assert projection_from_state({"pending_clarification": None}) is None
