"""Agent-loop plan decision event is forwarded to clients."""

from __future__ import annotations

from soothe.foundation.events import StrangeLoopPlanDecisionEvent


def test_strange_loop_plan_decision_event_to_dict() -> None:
    ev = StrangeLoopPlanDecisionEvent(
        iteration=2,
        steps=[
            {"id": "WAA-01", "description": "Explore codebase"},
            {
                "id": "WAA-02",
                "description": "Summarize findings",
                "dependencies": ["WAA-01"],
            },
        ],
        execution_mode="dependency",
    )
    d = ev.to_dict()
    assert d["type"] == "soothe.cognition.strange_loop.plan.decision"
    assert d["iteration"] == 2
    assert d["execution_mode"] == "dependency"
    assert len(d["steps"]) == 2
    assert d["steps"][0]["id"] == "WAA-01"
    assert d["steps"][1]["dependencies"] == ["WAA-01"]
