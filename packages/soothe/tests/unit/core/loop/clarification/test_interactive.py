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


def _request(num_questions: int = 1) -> ClarificationRequest:
    return ClarificationRequest(
        questions=tuple(f"q{i}" for i in range(num_questions)),
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
