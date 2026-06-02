"""Tests for the await_clarification graph node (RFC-622)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from soothe.core.loop.clarification.protocol import (
    ClarificationAnswer,
    ClarificationDeferredError,
    ClarificationRequest,
    LoopStateView,
    request_to_state,
)
from soothe.core.loop.orchestrator.nodes.await_clarification import (
    node_await_clarification,
)


@dataclass
class _StubCtx:
    policy: Any = None
    emitted: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    status_marks: list[tuple[str, str]] = field(default_factory=list)

    @property
    def clarification_policy(self) -> Any:
        return self.policy

    async def emit(self, name: str, payload: dict[str, Any]) -> None:
        self.emitted.append((name, payload))

    async def mark_goal_status(self, status: str, reason: str = "") -> None:
        self.status_marks.append((status, reason))


def _pending_state() -> dict[str, Any]:
    req = ClarificationRequest(
        questions=("What aspect to refine?",),
        origin_node="execute",
        origin_interrupt_id="i1",
        loop_state=LoopStateView(
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
        ),
    )
    return {"pending_clarification": request_to_state(req)}


class _InteractivePolicyStub:
    def __init__(self, answer: ClarificationAnswer) -> None:
        self._answer = answer

    async def answer(self, _request: ClarificationRequest) -> ClarificationAnswer:
        return self._answer


class _AutoPolicyStub:
    def __init__(self, *, raises: ClarificationDeferredError | None = None) -> None:
        self._raises = raises

    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer:
        if self._raises is not None:
            raise self._raises
        return ClarificationAnswer(answers=("x",), source="veritas", confidence=0.9)


async def test_success_writes_answer_and_clears_pending() -> None:
    policy = _InteractivePolicyStub(ClarificationAnswer(answers=("auth flows",), source="human"))
    ctx = _StubCtx(policy=policy)
    state = _pending_state()

    result = await node_await_clarification(ctx, state)

    # IG-462: ``pending_clarification`` survives the answer write so the
    # originating node can pair the request (carrying ``origin_interrupt_id``)
    # with the answer on re-entry. The originating node clears both channels.
    assert "pending_clarification" not in result
    assert result["pending_clarification_answer"]["answers"] == ["auth flows"]
    assert result["pending_clarification_answer"]["source"] == "human"
    names = [n for n, _ in ctx.emitted]
    assert "soothe.loop.clarification.requested" in names
    assert "soothe.loop.clarification.answered" in names
    assert ctx.status_marks == []


async def test_deferred_marks_status_and_terminates() -> None:
    req = ClarificationRequest(
        questions=("What aspect to refine?",),
        origin_node="execute",
        origin_interrupt_id="i1",
        loop_state=LoopStateView(
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
        ),
    )
    policy = _AutoPolicyStub(raises=ClarificationDeferredError("low confidence", req))
    ctx = _StubCtx(policy=policy)

    result = await node_await_clarification(ctx, _pending_state())

    assert result["last_outcome"] == "deferred"
    assert result["pending_clarification"] is None
    assert ctx.status_marks == [("awaiting_clarification", "low confidence")]
    names = [n for n, _ in ctx.emitted]
    assert "soothe.loop.clarification.deferred" in names


async def test_no_pending_clarification_is_noop() -> None:
    ctx = _StubCtx(
        policy=_InteractivePolicyStub(ClarificationAnswer(answers=("x",), source="human"))
    )
    result = await node_await_clarification(ctx, {})
    assert result == {"pending_clarification": None}
    assert ctx.emitted == []


async def test_missing_policy_defers() -> None:
    ctx = _StubCtx(policy=None)
    result = await node_await_clarification(ctx, _pending_state())
    assert result["last_outcome"] == "deferred"
    assert ctx.status_marks[0][0] == "awaiting_clarification"


async def test_malformed_pending_returns_fatal() -> None:
    ctx = _StubCtx(
        policy=_InteractivePolicyStub(ClarificationAnswer(answers=("x",), source="human"))
    )
    result = await node_await_clarification(
        ctx, {"pending_clarification": {"origin_node": "garbage"}}
    )
    assert result["last_outcome"] == "fatal"


@pytest.mark.parametrize(
    "policy_factory,expected_mode",
    [
        (
            lambda: _InteractivePolicyStub(ClarificationAnswer(answers=("x",), source="human")),
            "manual",
        ),
        (lambda: _AutoPolicyStub(), "auto"),
    ],
)
async def test_mode_derived_from_policy_class(policy_factory: Any, expected_mode: str) -> None:
    ctx = _StubCtx(policy=policy_factory())
    await node_await_clarification(ctx, _pending_state())
    requested = [p for n, p in ctx.emitted if n == "soothe.loop.clarification.requested"]
    assert len(requested) == 1
    assert requested[0]["mode"] == expected_mode
