"""ClarificationRequestedEvent carries planner review extras."""

from __future__ import annotations

from soothe.sloop.clarification.events import (
    ClarificationDeferredEvent,
    ClarificationRequestedEvent,
)


def test_clarification_requested_event_forwards_plan_payload() -> None:
    ev = ClarificationRequestedEvent(
        questions=["Action for this plan: Approve or Reject"],
        origin_node="plan_mode_review",
        mode="manual",
        plan_path="/ws/.soothe/plans/demo.md",
        plan_markdown="# Plan\n\nDo the thing.\n",
    )
    payload = ev.to_dict()
    assert payload["plan_path"] == "/ws/.soothe/plans/demo.md"
    assert payload["plan_markdown"].startswith("# Plan")
    assert payload["origin_node"] == "plan_mode_review"


def test_clarification_requested_event_forwards_step_id() -> None:
    ev = ClarificationRequestedEvent(
        questions=["Approve edit_file?"],
        origin_node="tool_approval",
        mode="manual",
        step_id="step-01",
    )
    payload = ev.to_dict()
    assert payload["step_id"] == "step-01"
    assert payload["origin_node"] == "tool_approval"


def test_clarification_deferred_event_carries_defer_kind() -> None:
    ev = ClarificationDeferredEvent(
        reason="veritas low confidence",
        question_summary="What aspect?",
        questions=["What aspect?"],
        defer_kind="low_confidence",
    )
    payload = ev.to_dict()
    assert payload["defer_kind"] == "low_confidence"
    assert payload["questions"] == ["What aspect?"]
    assert payload["reason"] == "veritas low confidence"
