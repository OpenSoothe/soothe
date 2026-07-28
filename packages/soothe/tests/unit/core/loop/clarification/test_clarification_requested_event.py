"""ClarificationRequestedEvent carries planner review extras."""

from __future__ import annotations

from soothe.sloop.clarification.events import ClarificationRequestedEvent


def test_clarification_requested_event_forwards_plan_payload() -> None:
    ev = ClarificationRequestedEvent(
        questions=["Action for this plan: Approve, Reject, or More comments"],
        origin_node="planner_subagent_review",
        mode="manual",
        plan_path="/ws/.soothe/plans/demo.md",
        plan_markdown="# Plan\n\nDo the thing.\n",
    )
    payload = ev.to_dict()
    assert payload["plan_path"] == "/ws/.soothe/plans/demo.md"
    assert payload["plan_markdown"].startswith("# Plan")
    assert payload["origin_node"] == "planner_subagent_review"
