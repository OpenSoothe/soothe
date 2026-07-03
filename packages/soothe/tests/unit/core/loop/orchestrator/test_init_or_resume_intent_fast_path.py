"""Tests for graph-entry intent classification routing."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from soothe.foundation.sloop.intention import IntentClassification
from soothe.foundation.sloop.orchestrator.nodes.init_or_resume import node_init_or_resume


@pytest.mark.asyncio
async def test_init_or_resume_routes_fast_path_for_quiz() -> None:
    """Quiz intent should terminate graph before iteration gate."""
    emitted: list[tuple[str, object]] = []

    async def _emit(event_type: str, event_data: object) -> None:
        emitted.append((event_type, event_data))

    intent = IntentClassification(
        intent_type="quiz",
        intake_label="quiz",
        goal_description=None,
        task_complexity="minimal",
        quiz_response="hello",
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
        continue_loop_mode=False,
        recovery_valid_resume=False,
        scratch=SimpleNamespace(plan_result=None, plan_assessment=None),
    )

    result = await node_init_or_resume(ctx, {})

    assert result["intent_route"] == "fast_path"
    assert any(t == "intent_classified" for t, _ in emitted)
    assert any(t == "intent_fast_path" for t, _ in emitted)
