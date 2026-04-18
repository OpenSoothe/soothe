"""Agent-loop step events include step_id for TUI correlation."""

from __future__ import annotations

from soothe.core.event_catalog import AgenticStepCompletedEvent, AgenticStepStartedEvent


def test_agentic_step_started_includes_step_id_in_dict() -> None:
    ev = AgenticStepStartedEvent(step_id="s-1", description="Do work")
    d = ev.to_dict()
    assert d["type"] == "soothe.cognition.agent_loop.step.started"
    assert d["step_id"] == "s-1"
    assert d["description"] == "Do work"


def test_agentic_step_completed_includes_step_id_in_dict() -> None:
    ev = AgenticStepCompletedEvent(
        step_id="s-1",
        success=True,
        summary="Done",
        duration_ms=1000,
        tool_call_count=2,
    )
    d = ev.to_dict()
    assert d["type"] == "soothe.cognition.agent_loop.step.completed"
    assert d["step_id"] == "s-1"
    assert d["success"] is True
    assert d["tool_call_count"] == 2
