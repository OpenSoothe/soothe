"""Agent-loop step events include step_id for TUI correlation."""

from __future__ import annotations

from soothe.foundation.events import (
    AgenticStepCompletedEvent,
    AgenticStepQueuedEvent,
    AgenticStepStartedEvent,
)


def test_agentic_step_started_includes_step_id_in_dict() -> None:
    ev = AgenticStepStartedEvent(step_id="s-1", description="Do work")
    d = ev.to_dict()
    assert d["type"] == "soothe.cognition.agent_loop.step.started"
    assert d["step_id"] == "s-1"
    assert d["description"] == "Do work"


def test_agentic_step_queued_includes_step_id_in_dict() -> None:
    ev = AgenticStepQueuedEvent(step_id="s-2", description="Wait for slot")
    d = ev.to_dict()
    assert d["type"] == "soothe.cognition.agent_loop.step.queued"
    assert d["step_id"] == "s-2"
    assert d["description"] == "Wait for slot"


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
    # Default ``clarification=None`` is dropped by ``model_dump(exclude_none=True)``.
    assert "clarification" not in d


def test_agentic_step_completed_carries_clarification_when_set() -> None:
    ev = AgenticStepCompletedEvent(
        step_id="ASK-01",
        success=True,
        summary="Done",
        duration_ms=0,
        tool_call_count=0,
        clarification={
            "questions": ["Which output format?"],
            "answers": ["json"],
            "source": "veritas",
            "confidence": 0.9,
        },
    )
    d = ev.to_dict()
    assert d["clarification"]["questions"] == ["Which output format?"]
    assert d["clarification"]["answers"] == ["json"]
    assert d["clarification"]["source"] == "veritas"
    assert d["clarification"]["confidence"] == 0.9
