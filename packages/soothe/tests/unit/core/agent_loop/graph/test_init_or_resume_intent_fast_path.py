"""Tests for graph-entry intent classification routing."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from soothe.core.agent_loop.graph.nodes.init_or_resume import node_init_or_resume
from soothe.core.intention import IntentClassification


@pytest.mark.asyncio
async def test_init_or_resume_routes_fast_path_for_chitchat() -> None:
    """Chitchat intent should terminate graph before iteration gate."""
    emitted: list[tuple[str, object]] = []

    async def _emit(event_type: str, event_data: object) -> None:
        emitted.append((event_type, event_data))

    intent = IntentClassification(
        intent_type="chitchat",
        reuse_current_goal=False,
        goal_description=None,
        friendly_message=None,
        task_complexity="chitchat",
        chitchat_response="hello",
        quiz_response=None,
        reasoning="test",
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
        recent_messages_for_intent=None,
        active_goal_id_for_intent=None,
        active_goal_description_for_intent=None,
        state_manager=SimpleNamespace(loop_id="L1"),
        emit=_emit,
    )

    result = await node_init_or_resume(ctx, {})

    assert result["intent_route"] == "fast_path"
    assert any(t == "intent_classified" for t, _ in emitted)
    assert any(t == "intent_fast_path" for t, _ in emitted)
