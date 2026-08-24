"""Tests for the await_clarification graph node (RFC-622)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from soothe.sloop.clarification.protocol import (
    ClarificationAnswer,
    ClarificationDeferredError,
    ClarificationRequest,
    LoopStateView,
    request_to_state,
)
from soothe.sloop.stations.sidecars.await_user import (
    node_await_clarification,
)


@dataclass
class _StubStateManager:
    """Stub state manager with loop_id for goal_unblocked event emission."""

    loop_id: str = "test-loop-123"


@dataclass
class _StubCtx:
    policy: Any = None
    emitted: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    parks: list[tuple[dict[str, Any], str]] = field(default_factory=list)
    resolve_parked: bool = False
    resolve_answers: list[list[str]] = field(default_factory=list)
    state_manager: _StubStateManager = field(default_factory=_StubStateManager)
    scratch: Any = None
    clarification_resume_text: str | None = None
    clarification_resume_answers: list[str] | None = None

    @property
    def clarification_policy(self) -> Any:
        return self.policy

    async def emit(self, name: str, payload: dict[str, Any]) -> None:
        self.emitted.append((name, payload))

    async def park_for_clarification(self, pending: dict[str, Any], *, reason: str = "") -> None:
        self.parks.append((pending, reason))

    async def resolve_parked_clarification(self, answers: list[str]) -> bool:
        self.resolve_answers.append(list(answers))
        return self.resolve_parked


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

    def requires_manual(self, _origin_node: str) -> bool:
        return False

    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer:
        if self._raises is not None:
            raise self._raises
        return ClarificationAnswer(answers=("x",), source="veritas", confidence=0.9)


async def test_success_writes_answer_and_clears_pending() -> None:
    policy = _InteractivePolicyStub(ClarificationAnswer(answers=("auth flows",), source="human"))
    ctx = _StubCtx(policy=policy)
    state = _pending_state()

    result = await node_await_clarification(ctx, state)

    # ``pending_clarification`` survives the answer write so the
    # originating node can pair the request (carrying ``origin_interrupt_id``)
    # with the answer on re-entry. The originating node clears both channels.
    assert "pending_clarification" not in result
    assert result["pending_clarification_answer"]["answers"] == ["auth flows"]
    assert result["pending_clarification_answer"]["source"] == "human"
    names = [n for n, _ in ctx.emitted]
    # Short names — the runner dispatch wraps them into the
    # ``soothe.loop.clarification.*`` wire events before yielding.
    assert "clarification_requested" in names
    assert "clarification_answered" in names
    assert ctx.parks == []
    # Interactive first-shot (no CE park) must not emit a fake goal_unblocked.
    assert not any(n == "goal_unblocked" for n, _ in ctx.emitted)


async def test_success_emits_goal_unblocked_when_ce_park_resolved() -> None:
    policy = _InteractivePolicyStub(ClarificationAnswer(answers=("auth flows",), source="human"))
    ctx = _StubCtx(policy=policy, resolve_parked=True)

    await node_await_clarification(ctx, _pending_state())

    unblocked_payloads = [p for n, p in ctx.emitted if n == "goal_unblocked"]
    assert len(unblocked_payloads) == 1
    assert unblocked_payloads[0]["goal_id"] == "g"
    assert unblocked_payloads[0]["old_status"] == "awaiting_clarification"
    assert unblocked_payloads[0]["new_status"] == "pending"
    assert ctx.resolve_answers == [["auth flows"]]


async def test_deferred_parks_and_keeps_pending() -> None:
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
    policy = _AutoPolicyStub(
        raises=ClarificationDeferredError("low confidence", req, kind="low_confidence")
    )
    ctx = _StubCtx(policy=policy)

    result = await node_await_clarification(ctx, _pending_state())

    assert result["last_outcome"] == "deferred"
    # Keep graph pending (do not clear); only clear the answer channel.
    assert "pending_clarification" not in result
    assert result["pending_clarification_answer"] is None
    assert len(ctx.parks) == 1
    assert ctx.parks[0][1] == "low confidence"
    deferred_payloads = [p for n, p in ctx.emitted if n == "clarification_deferred"]
    assert len(deferred_payloads) == 1
    assert deferred_payloads[0]["defer_kind"] == "low_confidence"
    assert deferred_payloads[0]["reason"] == "low confidence"


async def test_answer_defer_true_parks() -> None:
    policy = _InteractivePolicyStub(ClarificationAnswer(answers=("x",), source="human", defer=True))
    ctx = _StubCtx(policy=policy)
    result = await node_await_clarification(ctx, _pending_state())
    assert result["last_outcome"] == "deferred"
    assert result["pending_clarification_answer"] is None
    assert len(ctx.parks) == 1
    assert any(n == "clarification_deferred" for n, _ in ctx.emitted)


@pytest.mark.parametrize(
    "kind",
    ["explicit", "low_confidence", "structured_output_failed", "answer_was_question"],
)
async def test_deferred_event_carries_defer_kind(kind: str) -> None:
    req = ClarificationRequest(
        questions=("Q?",),
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
    policy = _AutoPolicyStub(
        raises=ClarificationDeferredError("reason", req, kind=kind)  # type: ignore[arg-type]
    )
    ctx = _StubCtx(policy=policy)
    await node_await_clarification(ctx, _pending_state())
    payload = next(p for n, p in ctx.emitted if n == "clarification_deferred")
    assert payload["defer_kind"] == kind


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
    assert len(ctx.parks) == 1
    assert ctx.parks[0][1] == "no clarification policy configured"
    assert result["pending_clarification_answer"] is None
    assert "pending_clarification" not in result


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
    requested = [p for n, p in ctx.emitted if n == "clarification_requested"]
    assert len(requested) == 1
    assert requested[0]["mode"] == expected_mode


async def test_plan_mode_review_emit_includes_plan_payload() -> None:
    from soothe.sloop.clarification.origins import ORIGIN_PLAN_MODE_REVIEW
    from soothe.sloop.plans.plan_mode_review import _PLAN_MODE_REVIEW_QUESTIONS

    req = ClarificationRequest(
        questions=_PLAN_MODE_REVIEW_QUESTIONS,
        origin_node=ORIGIN_PLAN_MODE_REVIEW,
        origin_interrupt_id="plan-mode-review:abc",
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
    policy = _InteractivePolicyStub(ClarificationAnswer(answers=("Approve", ""), source="human"))
    ctx = _StubCtx(policy=policy)
    ctx.scratch = type(  # type: ignore[attr-defined]
        "Scratch",
        (),
        {
            "plan_draft_path": "/ws/.soothe/plans/demo.md",
            "plan_draft_markdown": "# Plan\n\nBody.\n",
        },
    )()
    await node_await_clarification(ctx, {"pending_clarification": request_to_state(req)})
    requested = [p for n, p in ctx.emitted if n == "clarification_requested"]
    assert len(requested) == 1
    assert requested[0]["plan_path"] == "/ws/.soothe/plans/demo.md"
    assert requested[0]["plan_markdown"].startswith("# Plan")
    assert requested[0]["questions"] == list(_PLAN_MODE_REVIEW_QUESTIONS)


def _plan_review_pending(
    *,
    plan_path: str = "/ws/.soothe/plans/demo.md",
    plan_markdown: str = "# Plan\n",
) -> dict[str, Any]:
    from soothe.sloop.clarification.origins import ORIGIN_PLAN_MODE_REVIEW
    from soothe.sloop.plans.plan_mode_review import _PLAN_MODE_REVIEW_QUESTIONS

    req = ClarificationRequest(
        questions=_PLAN_MODE_REVIEW_QUESTIONS,
        origin_node=ORIGIN_PLAN_MODE_REVIEW,
        origin_interrupt_id="plan-mode-review:abc",
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
    pending = request_to_state(req)
    pending["plan_path"] = plan_path
    pending["plan_markdown"] = plan_markdown
    return pending


async def test_resume_turn_skips_clarification_requested_reemit() -> None:
    """A plan-review resume must not remount an empty widget."""
    policy = _InteractivePolicyStub(ClarificationAnswer(answers=("Reject", ""), source="human"))
    ctx = _StubCtx(policy=policy, clarification_resume_answers=["Reject", ""])
    await node_await_clarification(ctx, {"pending_clarification": _plan_review_pending()})
    assert not any(n == "clarification_requested" for n, _ in ctx.emitted)
    assert any(n == "clarification_answered" for n, _ in ctx.emitted)
    # Sticky resume inputs must be consumed so a later park can re-announce.
    assert ctx.clarification_resume_answers is None
    assert ctx.clarification_resume_text is None


async def test_second_park_after_resume_reemits_clarification_requested() -> None:
    """Planner rewrite after Refine must remount plan review (loop 6580)."""
    first_policy = _InteractivePolicyStub(
        ClarificationAnswer(answers=("Refine", "Show unified mental model"), source="human")
    )
    ctx = _StubCtx(
        policy=first_policy,
        clarification_resume_answers=["Refine", "Show unified mental model"],
        clarification_resume_text="Plan review: Refine",
    )
    ctx.scratch = type(  # type: ignore[attr-defined]
        "Scratch",
        (),
        {
            "plan_draft_path": "/ws/.soothe/plans/v1.md",
            "plan_draft_markdown": "# Plan v1\n",
        },
    )()

    await node_await_clarification(
        ctx,
        {
            "pending_clarification": _plan_review_pending(
                plan_path="/ws/.soothe/plans/v1.md",
                plan_markdown="# Plan v1\n",
            )
        },
    )
    assert not any(n == "clarification_requested" for n, _ in ctx.emitted)
    assert ctx.clarification_resume_answers is None

    # Same graph turn: planner produced a new reviewable draft.
    ctx.emitted.clear()
    ctx.policy = _InteractivePolicyStub(
        ClarificationAnswer(answers=("Approve", ""), source="human")
    )
    ctx.scratch = type(  # type: ignore[attr-defined]
        "Scratch",
        (),
        {
            "plan_draft_path": "/ws/.soothe/plans/v2.md",
            "plan_draft_markdown": "# Plan v2\n\nUnified model.\n",
        },
    )()
    await node_await_clarification(
        ctx,
        {
            "pending_clarification": _plan_review_pending(
                plan_path="/ws/.soothe/plans/v2.md",
                plan_markdown="# Plan v2\n\nUnified model.\n",
            )
        },
    )
    requested = [p for n, p in ctx.emitted if n == "clarification_requested"]
    assert len(requested) == 1
    assert requested[0]["plan_path"] == "/ws/.soothe/plans/v2.md"
    assert "Unified model" in requested[0]["plan_markdown"]
    assert any(n == "clarification_answered" for n, _ in ctx.emitted)
