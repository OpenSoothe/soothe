"""Tests for graph-entry intent classification routing."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from soothe.foundation.sloop.intention import IntentClassification
from soothe.foundation.sloop.orchestrator.nodes.init_or_resume import node_init_or_resume


@pytest.mark.asyncio
async def test_init_or_resume_routes_fast_path_for_trivial_greeting() -> None:
    """Trivial intake (including greetings) should terminate graph before iteration gate."""
    emitted: list[tuple[str, object]] = []

    async def _emit(event_type: str, event_data: object) -> None:
        emitted.append((event_type, event_data))

    intent = IntentClassification(
        intake_label="trivial",
        goal_description="hello",
        task_complexity="minimal",
    )
    loop_state = SimpleNamespace(
        intent=intent,
        goal="hello",
        thread_id="t1",
        routing_classification=None,
    )
    ctx = SimpleNamespace(
        loop_state=loop_state,
        intent_classifier=None,
        preferred_subagent=None,
        state_manager=SimpleNamespace(loop_id="L1"),
        emit=_emit,
        ce=None,
        ce_goal_id=None,
        continue_loop_mode=False,
        recovery_valid_resume=False,
        scratch=SimpleNamespace(plan_result=None, plan_assessment=None),
    )

    result = await node_init_or_resume(ctx, {})

    assert result["intent_route"] == "fast_path"
    assert any(t == "intent_classified" for t, _ in emitted)
    assert any(t == "intent_fast_path" for t, _ in emitted)
    payload = next(data for t, data in emitted if t == "intent_fast_path")
    assert payload["fast_path_kind"] == "trivial"
