"""Wire-contract tests for agentic loop control events."""

from __future__ import annotations

from soothe.core.events import AgenticLoopCompletedEvent


def test_agentic_loop_completed_event_has_no_goal_completion_message_field() -> None:
    ev = AgenticLoopCompletedEvent(
        thread_id="t-1",
        status="done",
        goal_progress=1.0,
        evidence_summary="ev",
    )
    d = ev.to_dict()
    assert d["type"] == "soothe.cognition.agent_loop.completed"
    assert "goal_completion_message" not in d


def test_agentic_loop_completed_event_none_when_unset() -> None:
    ev = AgenticLoopCompletedEvent(
        thread_id="t-3",
        status="done",
        goal_progress=1.0,
        evidence_summary="ev",
    )
    d = ev.to_dict()
    assert "goal_completion_message" not in d
