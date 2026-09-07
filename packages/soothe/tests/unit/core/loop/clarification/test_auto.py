"""Unit tests for AutoClarificationPolicy (RFC-622, RFC-623, IG-768)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from soothe.config.models import ToolApprovalConfig
from soothe.sloop.clarification.auto import AutoClarificationPolicy
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
from soothe.sloop.clarification.tool_approval_pipeline import ToolApprovalPipeline
from soothe.subagents.veritas.schemas import VeritasAnswerSchema


def _request(*, origin_node: str = ORIGIN_EXECUTE) -> ClarificationRequest:
    return ClarificationRequest(
        questions=("What aspect to refine?",),
        origin_node=origin_node,  # type: ignore[arg-type]
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


def _tool_approval_request(command: str) -> ClarificationRequest:
    return ClarificationRequest(
        questions=("Approve run_command?",),
        origin_node=ORIGIN_TOOL_APPROVAL,  # type: ignore[arg-type]
        origin_interrupt_id="iTA",
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
        metadata={"action_requests": [{"name": "run_command", "args": {"command": command}}]},
    )


def _pipeline() -> ToolApprovalPipeline:
    return ToolApprovalPipeline(ToolApprovalConfig())


def _veritas_returning(schema: VeritasAnswerSchema):
    async def _fn(_req: ClarificationRequest) -> VeritasAnswerSchema:
        return schema

    return _fn


class _RecordingFallback:
    """Stand-in ClarificationPolicy that records invocations."""

    def __init__(self, answer: ClarificationAnswer) -> None:
        self._answer = answer
        self.calls: list[ClarificationRequest] = []

    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer:
        self.calls.append(request)
        return self._answer


class _AnnounceFallback:
    """Fallback that tracks answer vs answer_as_manual_fallback calls."""

    def __init__(self, answer: ClarificationAnswer | None = None) -> None:
        self._answer = answer or ClarificationAnswer(
            answers=("operator says X",), source="human", confidence=None
        )
        self.answer_calls = 0
        self.upgrade_calls = 0
        self.upgrade_announces: list[bool] = []

    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer:
        self.answer_calls += 1
        return self._answer

    async def answer_as_manual_fallback(
        self, request: ClarificationRequest, *, announce: bool = True
    ) -> ClarificationAnswer:
        self.upgrade_calls += 1
        self.upgrade_announces.append(announce)
        return self._answer


# ---- success path (unchanged) ----


@pytest.mark.asyncio
async def test_high_confidence_returns_answer() -> None:
    policy = AutoClarificationPolicy(
        _veritas_returning(
            VeritasAnswerSchema(
                answers=["auth flows"],
                confidence=0.9,
                defer=False,
                rationale="user said refine auth",
            )
        )
    )
    ans = await policy.answer(_request())
    assert ans.source == "veritas"
    assert ans.answers == ("auth flows",)
    assert ans.confidence == pytest.approx(0.9)
    assert ans.audit == {"rationale": "user said refine auth"}


# ---- TUI: all veritas failures degrade to manual (IG-768) ----


@pytest.mark.asyncio
async def test_structured_output_failed_delegates_to_fallback() -> None:
    fallback_answer = ClarificationAnswer(
        answers=("operator says auth",), source="human", confidence=None
    )
    fallback = _RecordingFallback(fallback_answer)
    policy = AutoClarificationPolicy(
        _veritas_returning(
            VeritasAnswerSchema(
                answers=[],
                confidence=0.0,
                defer=True,
                rationale="structured_output_failed: provider error",
            )
        ),
        interactive_fallback=fallback,
    )
    request = _request()
    ans = await policy.answer(request)
    assert ans is fallback_answer
    assert fallback.calls == [request]


@pytest.mark.asyncio
async def test_structured_output_failed_uses_manual_fallback_announce() -> None:
    """Interactive fallback must use answer_as_manual_fallback (auto→manual)."""
    fallback = _AnnounceFallback()
    policy = AutoClarificationPolicy(
        _veritas_returning(
            VeritasAnswerSchema(
                answers=[],
                confidence=0.0,
                defer=True,
                rationale="structured_output_failed: provider error",
            )
        ),
        interactive_fallback=fallback,  # type: ignore[arg-type]
    )
    ans = await policy.answer(_request())
    assert ans is fallback._answer  # noqa: SLF001
    assert fallback.upgrade_calls == 1
    assert fallback.answer_calls == 0


@pytest.mark.asyncio
async def test_low_confidence_degrades_to_fallback_when_enabled() -> None:
    """With degrade_to_manual_on_failure=True, low-confidence routes to interactive fallback."""
    fallback = _AnnounceFallback()
    policy = AutoClarificationPolicy(
        _veritas_returning(VeritasAnswerSchema(answers=["guess"], confidence=0.2, defer=False)),
        interactive_fallback=fallback,  # type: ignore[arg-type]
    )
    ans = await policy.answer(_request())
    assert ans is fallback._answer  # noqa: SLF001
    assert fallback.upgrade_calls == 1
    assert fallback.answer_calls == 0


@pytest.mark.asyncio
async def test_explicit_defer_degrades_to_fallback_when_enabled() -> None:
    """IG-768: explicit defer now also degrades to manual when a fallback is wired."""
    fallback = _AnnounceFallback()
    policy = AutoClarificationPolicy(
        _veritas_returning(
            VeritasAnswerSchema(
                answers=[], confidence=0.0, defer=True, rationale="real uncertainty"
            )
        ),
        interactive_fallback=fallback,  # type: ignore[arg-type]
    )
    ans = await policy.answer(_request())
    assert ans is fallback._answer  # noqa: SLF001
    assert fallback.upgrade_calls == 1
    assert fallback.answer_calls == 0


@pytest.mark.asyncio
async def test_answer_was_question_degrades_to_fallback_when_enabled() -> None:
    """IG-768: answer_was_question now also degrades to manual when a fallback is wired."""
    fallback = _AnnounceFallback()
    policy = AutoClarificationPolicy(
        _veritas_returning(
            VeritasAnswerSchema(
                answers=[],
                confidence=0.0,
                defer=True,
                rationale="answer_was_question",
            )
        ),
        interactive_fallback=fallback,  # type: ignore[arg-type]
    )
    ans = await policy.answer(_request())
    assert ans is fallback._answer  # noqa: SLF001
    assert fallback.upgrade_calls == 1
    assert fallback.answer_calls == 0


@pytest.mark.asyncio
async def test_empty_answers_degrades_to_fallback_when_enabled() -> None:
    """IG-768: empty veritas answers also degrade to manual when a fallback is wired."""
    fallback = _AnnounceFallback()
    policy = AutoClarificationPolicy(
        _veritas_returning(
            VeritasAnswerSchema(answers=["  "], confidence=0.95, defer=False, rationale="blank")
        ),
        interactive_fallback=fallback,  # type: ignore[arg-type]
    )
    ans = await policy.answer(_request())
    assert ans is fallback._answer  # noqa: SLF001
    assert fallback.upgrade_calls == 1
    assert fallback.answer_calls == 0


# ---- TUI: opt-out of degrade (hard defer on non-structured failures) ----


@pytest.mark.asyncio
async def test_low_confidence_hard_defers_when_degrade_disabled() -> None:
    """With degrade_to_manual_on_failure=False, low-confidence hard-defers."""
    fallback_answer = ClarificationAnswer(answers=("x",), source="human", confidence=None)
    fallback = _RecordingFallback(fallback_answer)
    policy = AutoClarificationPolicy(
        _veritas_returning(VeritasAnswerSchema(answers=["guess"], confidence=0.2, defer=False)),
        interactive_fallback=fallback,
        degrade_to_manual_on_failure=False,
    )
    with pytest.raises(ClarificationDeferredError) as exc_info:
        await policy.answer(_request())
    assert exc_info.value.kind == "low_confidence"
    assert fallback.calls == []


@pytest.mark.asyncio
async def test_explicit_defer_hard_defers_when_degrade_disabled() -> None:
    """With degrade_to_manual_on_failure=False, explicit defer hard-defers."""
    fallback_answer = ClarificationAnswer(answers=("x",), source="human", confidence=None)
    fallback = _RecordingFallback(fallback_answer)
    policy = AutoClarificationPolicy(
        _veritas_returning(
            VeritasAnswerSchema(
                answers=[], confidence=0.0, defer=True, rationale="real uncertainty"
            )
        ),
        interactive_fallback=fallback,
        degrade_to_manual_on_failure=False,
    )
    with pytest.raises(ClarificationDeferredError) as exc_info:
        await policy.answer(_request())
    assert exc_info.value.kind == "explicit"
    assert fallback.calls == []


# ---- autopilot: veritas failure → retry (IG-768) ----


@pytest.mark.asyncio
async def test_autopilot_retry_on_low_confidence() -> None:
    """Headless (no fallback): low confidence returns a retry answer."""
    policy = AutoClarificationPolicy(
        _veritas_returning(VeritasAnswerSchema(answers=["guess"], confidence=0.2, defer=False)),
        # No interactive_fallback — simulates autopilot.
    )
    ans = await policy.answer(_request())
    assert ans.source == "retry"
    assert ans.answers == ("(retry)",)
    assert ans.confidence == 0.0
    assert ans.audit["reason"] == "veritas failed; autopilot retry"


@pytest.mark.asyncio
async def test_autopilot_retry_on_explicit_defer() -> None:
    """Headless: explicit defer returns a retry answer."""
    policy = AutoClarificationPolicy(
        _veritas_returning(
            VeritasAnswerSchema(
                answers=[], confidence=0.0, defer=True, rationale="real uncertainty"
            )
        ),
    )
    ans = await policy.answer(_request())
    assert ans.source == "retry"
    assert ans.answers == ("(retry)",)


@pytest.mark.asyncio
async def test_autopilot_retry_on_structured_output_failed() -> None:
    """Headless: structured output failure returns a retry answer."""
    policy = AutoClarificationPolicy(
        _veritas_returning(
            VeritasAnswerSchema(
                answers=[],
                confidence=0.0,
                defer=True,
                rationale="structured_output_failed: validation error",
            )
        ),
    )
    ans = await policy.answer(_request())
    assert ans.source == "retry"
    assert ans.answers == ("(retry)",)


@pytest.mark.asyncio
async def test_autopilot_retry_on_answer_was_question() -> None:
    """Headless: answer_was_question returns a retry answer."""
    policy = AutoClarificationPolicy(
        _veritas_returning(
            VeritasAnswerSchema(
                answers=[],
                confidence=0.0,
                defer=True,
                rationale="answer_was_question",
            )
        ),
    )
    ans = await policy.answer(_request())
    assert ans.source == "retry"
    assert ans.answers == ("(retry)",)


@pytest.mark.asyncio
async def test_autopilot_retry_on_empty_answers() -> None:
    """Headless: empty veritas answers return a retry answer."""
    policy = AutoClarificationPolicy(
        _veritas_returning(
            VeritasAnswerSchema(answers=["  "], confidence=0.95, defer=False, rationale="blank")
        ),
    )
    ans = await policy.answer(_request())
    assert ans.source == "retry"
    assert ans.answers == ("(retry)",)


@pytest.mark.asyncio
async def test_autopilot_retry_multi_question() -> None:
    """Retry answer has one sentinel per question."""
    request = ClarificationRequest(
        questions=("Q1?", "Q2?"),
        origin_node=ORIGIN_EXECUTE,
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
    policy = AutoClarificationPolicy(
        _veritas_returning(VeritasAnswerSchema(answers=["guess"], confidence=0.1, defer=False)),
    )
    ans = await policy.answer(request)
    assert ans.source == "retry"
    assert len(ans.answers) == 2
    assert all(a == "(retry)" for a in ans.answers)


# ---- autopilot: opt-out of retry (legacy hard defer) ----


@pytest.mark.asyncio
async def test_autopilot_hard_defer_when_retry_disabled() -> None:
    """With autopilot_retry_on_fail=False, veritas failures hard-defer (legacy)."""
    policy = AutoClarificationPolicy(
        _veritas_returning(VeritasAnswerSchema(answers=["guess"], confidence=0.2, defer=False)),
        autopilot_retry_on_fail=False,
    )
    with pytest.raises(ClarificationDeferredError) as exc_info:
        await policy.answer(_request())
    assert exc_info.value.kind == "low_confidence"


# ---- TUI + autopilot precedence ----


@pytest.mark.asyncio
async def test_tui_fallback_takes_precedence_over_autopilot_retry() -> None:
    """When both fallback and retry are available, TUI fallback wins."""
    fallback = _AnnounceFallback()
    policy = AutoClarificationPolicy(
        _veritas_returning(VeritasAnswerSchema(answers=["guess"], confidence=0.2, defer=False)),
        interactive_fallback=fallback,  # type: ignore[arg-type]
        autopilot_retry_on_fail=True,
    )
    ans = await policy.answer(_request())
    assert fallback.upgrade_calls == 1
    assert ans.source == "human"


# ---- properties ----


def test_degrade_to_manual_on_failure_property() -> None:
    policy = AutoClarificationPolicy(
        _veritas_returning(VeritasAnswerSchema(answers=["x"], confidence=0.9, defer=False)),
    )
    assert policy.degrade_to_manual_on_failure is True

    policy2 = AutoClarificationPolicy(
        _veritas_returning(VeritasAnswerSchema(answers=["x"], confidence=0.9, defer=False)),
        degrade_to_manual_on_failure=False,
    )
    assert policy2.degrade_to_manual_on_failure is False


def test_autopilot_retry_on_fail_property() -> None:
    policy = AutoClarificationPolicy(
        _veritas_returning(VeritasAnswerSchema(answers=["x"], confidence=0.9, defer=False)),
    )
    assert policy.autopilot_retry_on_fail is True

    policy2 = AutoClarificationPolicy(
        _veritas_returning(VeritasAnswerSchema(answers=["x"], confidence=0.9, defer=False)),
        autopilot_retry_on_fail=False,
    )
    assert policy2.autopilot_retry_on_fail is False


# ---- force_manual_origins (unchanged) ----


@pytest.mark.asyncio
async def test_force_manual_origin_uses_fallback_and_skips_veritas() -> None:
    calls: list[ClarificationRequest] = []

    async def _veritas(_req: ClarificationRequest) -> VeritasAnswerSchema:
        calls.append(_req)
        return VeritasAnswerSchema(answers=["approved"], confidence=0.99, defer=False)

    fallback_answer = ClarificationAnswer(answers=("Approve", ""), source="human")
    fallback = _RecordingFallback(fallback_answer)
    policy = AutoClarificationPolicy(
        _veritas,
        interactive_fallback=fallback,
        force_manual_origins=(ORIGIN_PLAN_MODE_REVIEW,),
    )
    request = _request(origin_node=ORIGIN_PLAN_MODE_REVIEW)
    ans = await policy.answer(request)
    assert ans is fallback_answer
    assert fallback.calls == [request]
    assert calls == []


@pytest.mark.asyncio
async def test_force_manual_origin_defers_without_fallback() -> None:
    """IG-768: force-manual origin without fallback now retries (autopilot default).
    Use autopilot_retry_on_fail=False to get the legacy hard defer."""

    async def _veritas(_req: ClarificationRequest) -> VeritasAnswerSchema:
        raise AssertionError("veritas must not run for force-manual origins")

    policy = AutoClarificationPolicy(
        _veritas,
        force_manual_origins=(ORIGIN_PLAN_MODE_REVIEW,),
        autopilot_retry_on_fail=False,
    )
    request = _request(origin_node=ORIGIN_PLAN_MODE_REVIEW)
    with pytest.raises(ClarificationDeferredError) as exc_info:
        await policy.answer(request)
    assert "manual confirmation" in exc_info.value.reason
    assert exc_info.value.kind == "explicit"


@pytest.mark.asyncio
async def test_force_manual_origin_autopilot_retry_without_fallback() -> None:
    """IG-768: force-manual origin in autopilot returns retry instead of hard defer."""

    async def _veritas(_req: ClarificationRequest) -> VeritasAnswerSchema:
        raise AssertionError("veritas must not run for force-manual origins")

    policy = AutoClarificationPolicy(
        _veritas,
        force_manual_origins=(ORIGIN_PLAN_MODE_REVIEW,),
        autopilot_retry_on_fail=True,
    )
    request = _request(origin_node=ORIGIN_PLAN_MODE_REVIEW)
    ans = await policy.answer(request)
    assert ans.source == "retry"
    assert ans.answers == ("(retry)",)


@pytest.mark.asyncio
async def test_force_manual_does_not_affect_other_origins() -> None:
    policy = AutoClarificationPolicy(
        _veritas_returning(
            VeritasAnswerSchema(answers=["auth"], confidence=0.9, defer=False, rationale="ok")
        ),
        force_manual_origins=(ORIGIN_PLAN_MODE_REVIEW,),
    )
    ans = await policy.answer(_request(origin_node=ORIGIN_EXECUTE))
    assert ans.source == "veritas"
    assert ans.answers == ("auth",)


# ---- tool_approval pipeline × force_manual_origins ordering (§9b) ----


@pytest.mark.asyncio
async def test_tool_approval_default_approve_without_force_manual() -> None:
    """Plain auto mode: non-denied actions are default-approved via the pipeline."""

    async def _veritas(_req: ClarificationRequest) -> VeritasAnswerSchema:
        raise AssertionError("veritas must not run for default-approved actions")

    policy = AutoClarificationPolicy(_veritas, tool_approval_pipeline=_pipeline())
    ans = await policy.answer(_tool_approval_request("pytest -xvs"))
    assert ans.source == "static"
    assert ans.answers == ("approve",)
    assert ans.audit["stage"] == "default_approve"


@pytest.mark.asyncio
async def test_force_manual_tool_approval_deny_rule_still_auto_rejects() -> None:
    """Deny/safety stages are a safety property: they run even for
    force-manual origins — dangerous actions are auto-rejected, not asked."""

    async def _veritas(_req: ClarificationRequest) -> VeritasAnswerSchema:
        raise AssertionError("veritas must not run for force-manual origins")

    fallback = _RecordingFallback(ClarificationAnswer(answers=("Approve", ""), source="human"))
    policy = AutoClarificationPolicy(
        _veritas,
        interactive_fallback=fallback,
        force_manual_origins=(ORIGIN_TOOL_APPROVAL,),
        tool_approval_pipeline=_pipeline(),
    )
    ans = await policy.answer(_tool_approval_request("apt install foo"))
    assert ans.source == "static"
    assert ans.answers == ("reject",)
    assert ans.audit["stage"] == "deny_rule"
    assert fallback.calls == []


@pytest.mark.asyncio
async def test_force_manual_tool_approval_allow_rule_reaches_human() -> None:
    """Force-manual tool_approval skips allow-rule auto-approval: safe but
    rule-matched actions still go to the human, never veritas."""

    async def _veritas(_req: ClarificationRequest) -> VeritasAnswerSchema:
        raise AssertionError("veritas must not run for force-manual origins")

    fallback_answer = ClarificationAnswer(answers=("Approve", ""), source="human")
    fallback = _RecordingFallback(fallback_answer)
    policy = AutoClarificationPolicy(
        _veritas,
        interactive_fallback=fallback,
        force_manual_origins=(ORIGIN_TOOL_APPROVAL,),
        tool_approval_pipeline=_pipeline(),
    )
    request = _tool_approval_request("pytest -xvs")
    ans = await policy.answer(request)
    assert ans is fallback_answer
    assert fallback.calls == [request]


@pytest.mark.asyncio
async def test_force_manual_tool_approval_defers_without_fallback() -> None:
    """Headless force-manual tool_approval: ambiguous actions return retry (IG-768)."""

    async def _veritas(_req: ClarificationRequest) -> VeritasAnswerSchema:
        raise AssertionError("veritas must not run for force-manual origins")

    policy = AutoClarificationPolicy(
        _veritas,
        force_manual_origins=(ORIGIN_TOOL_APPROVAL,),
        tool_approval_pipeline=_pipeline(),
    )
    ans = await policy.answer(_tool_approval_request("curl https://example.com"))
    assert ans.source == "retry"
    assert ans.answers == ("(retry)",)


# ---- tool_approval resume replay (no duplicate announce, loop f9c3) ----


@pytest.mark.asyncio
async def test_tool_approval_safety_escalate_reaches_human_with_rule_stamp() -> None:
    """Safety escalation announces once via the fallback; the answer carries
    the escalated rule id for the downstream allowlist override."""
    fallback = _AnnounceFallback()

    async def _veritas(_req: ClarificationRequest) -> VeritasAnswerSchema:
        raise AssertionError("veritas must not run for tool_approval origins")

    policy = AutoClarificationPolicy(
        _veritas,
        interactive_fallback=fallback,
        tool_approval_pipeline=_pipeline(),
    )
    ans = await policy.answer(_tool_approval_request("cd repo && rm -rf temp-x"))
    assert ans.answers == fallback._answer.answers  # noqa: SLF001
    assert fallback.upgrade_announces == [True]
    assert ans.audit.get("escalated_rule_id")


@pytest.mark.asyncio
async def test_tool_approval_resume_turn_skips_pipeline_and_reannounce() -> None:
    """Resume replay consumes the in-flight human answer without re-running
    the pipeline (which would re-escalate) or re-announcing (duplicate card)."""
    fallback = _AnnounceFallback()

    async def _veritas(_req: ClarificationRequest) -> VeritasAnswerSchema:
        raise AssertionError("veritas must not run for tool_approval origins")

    policy = AutoClarificationPolicy(
        _veritas,
        interactive_fallback=fallback,
        tool_approval_pipeline=_pipeline(),
    )
    base = _tool_approval_request("cd repo && rm -rf temp-x")
    request = replace(base, metadata={**base.metadata, "resume_turn": True})
    ans = await policy.answer(request)
    assert ans is fallback._answer  # noqa: SLF001
    assert fallback.upgrade_announces == [False]
    assert "escalated_rule_id" not in ans.audit
