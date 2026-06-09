"""Agent-loop plan decision event is forwarded to clients."""

from __future__ import annotations

from soothe.foundation.events import AgenticPlanDecisionEvent


def test_agentic_plan_decision_event_to_dict() -> None:
    ev = AgenticPlanDecisionEvent(
        iteration=2,
        steps=[
            {"id": "WAA-01", "description": "Explore codebase"},
            {"id": "WAA-02", "description": "Summarize findings"},
        ],
        execution_mode="dependency",
    )
    d = ev.to_dict()
    assert d["type"] == "soothe.cognition.agent_loop.plan.decision"
    assert d["iteration"] == 2
    assert d["execution_mode"] == "dependency"
    assert len(d["steps"]) == 2
    assert d["steps"][0]["id"] == "WAA-01"
