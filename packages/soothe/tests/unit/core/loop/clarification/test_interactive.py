"""Unit tests for InteractiveClarificationPolicy."""

from __future__ import annotations

from typing import Any

import pytest

from soothe.sloop.clarification import interactive as interactive_mod
from soothe.sloop.clarification.interactive import InteractiveClarificationPolicy
from soothe.sloop.clarification.protocol import (
    ClarificationDeferredError,
    ClarificationRequest,
    LoopStateView,
)


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
    assert ans.answers == ("Approve",)
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
    """A bare action answer works unchanged."""
    _stub_interrupt(monkeypatch, {"answers": ["reject"]})
    policy = InteractiveClarificationPolicy()
    ans = await policy.answer(_request(1, origin_node="tool_approval"))
    assert ans.answers == ("reject",)


async def test_tool_approval_defers_on_blank_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty action slot is still a dismissal."""
    _stub_interrupt(monkeypatch, {"answers": ["", ""]})
    policy = InteractiveClarificationPolicy()
    with pytest.raises(ClarificationDeferredError):
        await policy.answer(_request(1, origin_node="tool_approval"))
