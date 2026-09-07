"""Unit tests for InteractiveClarificationPolicy."""

from __future__ import annotations

from typing import Any

import pytest

from soothe.config.models import ToolApprovalConfig
from soothe.sloop.clarification import interactive as interactive_mod
from soothe.sloop.clarification.interactive import InteractiveClarificationPolicy
from soothe.sloop.clarification.protocol import (
    ClarificationDeferredError,
    ClarificationRequest,
    LoopStateView,
)
from soothe.sloop.clarification.tool_approval_pipeline import ToolApprovalPipeline


def _request(num_questions: int = 1, *, origin_node: str = "execute") -> ClarificationRequest:
    return ClarificationRequest(
        questions=tuple(f"q{i}" for i in range(num_questions)),
        origin_node=origin_node,
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
        origin_node="tool_approval",  # type: ignore[arg-type]
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


def _stub_interrupt(monkeypatch: pytest.MonkeyPatch, return_value: Any) -> list[Any]:
    captured: list[Any] = []

    def _fake(payload: Any) -> Any:
        captured.append(payload)
        return return_value

    monkeypatch.setattr(interactive_mod, "interrupt", _fake)
    return captured


async def test_returns_human_answer_dict_form(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_interrupt(monkeypatch, {"answers": ["auth flows"]})
    policy = InteractiveClarificationPolicy()
    ans = await policy.answer(_request())
    assert ans.source == "human"
    assert ans.answers == ("auth flows",)


async def test_returns_human_answer_bare_string(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_interrupt(monkeypatch, "just say yes")
    policy = InteractiveClarificationPolicy()
    ans = await policy.answer(_request())
    assert ans.answers == ("just say yes",)


async def test_broadcasts_single_answer_across_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_interrupt(monkeypatch, {"answer": "both same"})
    policy = InteractiveClarificationPolicy()
    ans = await policy.answer(_request(num_questions=2))
    assert ans.answers == ("both same", "both same")


async def test_defers_on_none_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_interrupt(monkeypatch, None)
    policy = InteractiveClarificationPolicy()
    with pytest.raises(ClarificationDeferredError):
        await policy.answer(_request())


async def test_defers_on_count_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_interrupt(monkeypatch, {"answers": ["one", "two"]})
    policy = InteractiveClarificationPolicy()
    with pytest.raises(ClarificationDeferredError):
        await policy.answer(_request(num_questions=3))


async def test_defers_on_blank_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_interrupt(monkeypatch, {"answers": ["  "]})
    policy = InteractiveClarificationPolicy()
    with pytest.raises(ClarificationDeferredError):
        await policy.answer(_request())


async def test_plan_mode_review_approve_tolerates_blank_refinement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan-mode review asks 2 questions; only the action field is required.

    The TUI sends ``["Approve", ""]`` (blank refinement-text field) on
    approve. The policy must accept it rather than treating the blank optional
    field as "operator dismissed clarification (no answer)" — that swallowed
    approvals and parked the goal at ``awaiting_clarification`` forever (loop 0411).
    """
    _stub_interrupt(monkeypatch, {"answers": ["Approve", ""]})
    policy = InteractiveClarificationPolicy()
    ans = await policy.answer(_request(num_questions=2, origin_node="plan_mode_review"))
    assert ans.source == "human"
    assert ans.answers == ("Approve", "")


async def test_plan_mode_review_reject_tolerates_blank_second_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_interrupt(monkeypatch, {"answers": ["Reject", ""]})
    policy = InteractiveClarificationPolicy()
    ans = await policy.answer(_request(num_questions=2, origin_node="plan_mode_review"))
    assert ans.answers == ("Reject", "")


async def test_plan_mode_review_refine_carries_refinement_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refine with refinement text in answers[1] is passed through intact."""
    _stub_interrupt(monkeypatch, {"answers": ["Refine", "narrow scope to auth"]})
    policy = InteractiveClarificationPolicy()
    ans = await policy.answer(_request(num_questions=2, origin_node="plan_mode_review"))
    assert ans.answers == ("Refine", "narrow scope to auth")


async def test_plan_mode_review_defers_on_blank_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blank *action* field is still a genuine dismissal."""
    _stub_interrupt(monkeypatch, {"answers": ["", ""]})
    policy = InteractiveClarificationPolicy()
    with pytest.raises(ClarificationDeferredError):
        await policy.answer(_request(num_questions=2, origin_node="plan_mode_review"))


async def test_plan_mode_review_pads_single_action_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single-element action list is padded to the expected 2 questions."""
    _stub_interrupt(monkeypatch, {"answers": ["Approve"]})
    policy = InteractiveClarificationPolicy()
    ans = await policy.answer(_request(num_questions=2, origin_node="plan_mode_review"))
    assert ans.answers == ("Approve", "")


async def test_answer_does_not_reemit_clarification_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """await_clarification owns the primary emit; answer() must not duplicate it."""
    _stub_interrupt(monkeypatch, {"answers": ["x"]})
    emitted: list[tuple[str, dict]] = []

    async def _emit(name: str, payload: dict) -> None:
        emitted.append((name, payload))

    policy = InteractiveClarificationPolicy(emit=_emit)
    await policy.answer(_request())
    assert emitted == []


async def test_answer_as_manual_fallback_emits_mode_manual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """auto→manual upgrade must re-announce so the TUI shows the prompt."""
    _stub_interrupt(monkeypatch, {"answers": ["x"]})
    emitted: list[tuple[str, dict]] = []

    async def _emit(name: str, payload: dict) -> None:
        emitted.append((name, payload))

    policy = InteractiveClarificationPolicy(emit=_emit)
    await policy.answer_as_manual_fallback(_request())

    assert len(emitted) == 1
    name, payload = emitted[0]
    assert name == "clarification_requested"
    assert payload["mode"] == "manual"
    assert payload["origin_node"] == "execute"
    assert payload["questions"] == ["q0"]


async def test_answer_as_manual_fallback_announce_false_skips_emit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resume replay: consume the pending answer without re-announcing."""
    _stub_interrupt(monkeypatch, {"answers": ["Approve", ""]})
    emitted: list[tuple[str, dict]] = []

    async def _emit(name: str, payload: dict) -> None:
        emitted.append((name, payload))

    policy = InteractiveClarificationPolicy(emit=_emit)
    ans = await policy.answer_as_manual_fallback(
        _tool_approval_request("cd repo && rm -rf temp-x"), announce=False
    )
    assert ans.answers == ("Approve", "")
    assert emitted == []


async def test_bind_emit_attaches_runtime_callback() -> None:
    policy = InteractiveClarificationPolicy()

    async def _emit(_name: str, _payload: dict) -> None:
        return None

    policy.bind_emit(_emit)
    assert policy._emit is _emit  # noqa: SLF001


# ---------------------------------------------------------------------------
# Tool-approval answers (action + optional-comment shape from the TUI)
# ---------------------------------------------------------------------------


async def test_tool_approval_tolerates_blank_comment_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The TUI submits [action, ""] for tool approvals — the blank comment
    slot must not dismiss the answer as "no answer" (loop 573f)."""
    _stub_interrupt(monkeypatch, {"answers": ["Approve", ""]})
    policy = InteractiveClarificationPolicy()
    ans = await policy.answer(_request(1, origin_node="tool_approval"))
    assert ans.answers == ("Approve", "")
    assert ans.source == "human"


async def test_tool_approval_edit_carries_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edit with revised args: the action decides the HITL decision; extra
    slots are tolerated."""
    _stub_interrupt(monkeypatch, {"answers": ["Edit", "new args"]})
    policy = InteractiveClarificationPolicy()
    ans = await policy.answer(_request(1, origin_node="tool_approval"))
    assert ans.answers[0] == "Edit"


async def test_tool_approval_single_action_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare action answer works, padded with a blank comment slot."""
    _stub_interrupt(monkeypatch, {"answers": ["reject"]})
    policy = InteractiveClarificationPolicy()
    ans = await policy.answer(_request(1, origin_node="tool_approval"))
    assert ans.answers == ("reject", "")


async def test_tool_approval_defers_on_blank_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty action slot is still a dismissal."""
    _stub_interrupt(monkeypatch, {"answers": ["", ""]})
    policy = InteractiveClarificationPolicy()
    with pytest.raises(ClarificationDeferredError):
        await policy.answer(_request(1, origin_node="tool_approval"))


# ---------------------------------------------------------------------------
# Manual-mode pipeline pre-filter (RFC-622 §9b)
# ---------------------------------------------------------------------------


async def test_pre_filter_deny_rule_auto_rejects_without_asking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dangerous actions are auto-rejected in manual mode — the human is
    never prompted to approve them."""
    captured = _stub_interrupt(monkeypatch, {"answers": ["approve"]})
    policy = InteractiveClarificationPolicy(tool_approval_pipeline=_pipeline())
    ans = await policy.answer(_tool_approval_request("apt install foo"))
    assert ans.source == "static"
    assert ans.answers == ("reject",)
    assert ans.audit["stage"] == "deny_rule"
    assert captured == []


async def test_pre_filter_asks_human_for_allow_rule_match_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """manual_scope=all (default): allow-rule matches still reach the human."""
    captured = _stub_interrupt(monkeypatch, {"answers": ["approve"]})
    policy = InteractiveClarificationPolicy(tool_approval_pipeline=_pipeline())
    ans = await policy.answer(_tool_approval_request("pytest -xvs"))
    assert ans.source == "human"
    assert captured, "human interrupt must fire for non-rejected actions"


async def test_pre_filter_default_approves_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """manual_scope=ambiguous_only: non-denied actions auto-approve."""
    captured = _stub_interrupt(monkeypatch, {"answers": ["approve"]})
    policy = InteractiveClarificationPolicy(
        tool_approval_pipeline=_pipeline(),
        manual_allow_rules=True,
    )
    ans = await policy.answer(_tool_approval_request("pytest -xvs"))
    assert ans.source == "static"
    assert ans.answers == ("approve",)
    assert ans.audit["stage"] == "default_approve"
    assert captured == []


async def test_pre_filter_asks_human_when_allow_rules_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When manual_allow_rules=False, non-denied actions reach the human."""
    captured = _stub_interrupt(monkeypatch, {"answers": ["approve"]})
    policy = InteractiveClarificationPolicy(
        tool_approval_pipeline=_pipeline(),
        manual_allow_rules=False,
    )
    ans = await policy.answer(_tool_approval_request("curl https://example.com"))
    assert ans.source == "human"
    assert captured


async def test_pre_filter_skipped_without_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """No pipeline attached (tool_approval.enabled: false): current behavior,
    every tool action asks the human."""
    captured = _stub_interrupt(monkeypatch, {"answers": ["approve"]})
    policy = InteractiveClarificationPolicy()
    ans = await policy.answer(_tool_approval_request("rm -rf /"))
    assert ans.source == "human"
    assert captured


async def test_manual_fallback_path_skips_pre_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """answer_as_manual_fallback (auto→manual upgrade) must not re-evaluate
    the pipeline — the auto policy already ran it before deferring."""
    captured = _stub_interrupt(monkeypatch, {"answers": ["approve"]})
    policy = InteractiveClarificationPolicy(
        tool_approval_pipeline=_pipeline(),
        manual_allow_rules=True,
    )
    ans = await policy.answer_as_manual_fallback(_tool_approval_request("pytest -xvs"))
    assert ans.source == "human"
    assert captured
