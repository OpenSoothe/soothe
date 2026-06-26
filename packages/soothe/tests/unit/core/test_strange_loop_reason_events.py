"""Tests for StrangeLoop plan reason event forwarding (RFC-604 / IG-329)."""

from __future__ import annotations

from soothe.runner._runner_strange_loop import (
    _is_displayable_assessment_reasoning,
    _is_displayable_plan_next_action,
    _should_emit_loop_reason_event,
)


def test_should_emit_loop_reason_event_for_plan_generate_next_action() -> None:
    assert _should_emit_loop_reason_event(
        assessment_reasoning="",
        plan_reasoning="",
        next_action="I will read the log file first.",
    )


def test_should_not_emit_loop_reason_event_for_boilerplate_next_action() -> None:
    assert not _should_emit_loop_reason_event(
        assessment_reasoning="",
        plan_reasoning="",
        next_action="Goal achieved successfully",
    )
    assert not _should_emit_loop_reason_event(
        assessment_reasoning="",
        plan_reasoning="",
        next_action="Goal progress sufficient for completion",
    )


def test_should_emit_loop_reason_event_for_assessment_or_legacy_plan_reasoning() -> None:
    assert _should_emit_loop_reason_event(
        assessment_reasoning="Progress is medium.",
        plan_reasoning="",
        next_action="",
    )
    assert _should_emit_loop_reason_event(
        assessment_reasoning="",
        plan_reasoning="Keep executing remaining steps.",
        next_action="",
    )


def test_is_displayable_plan_next_action() -> None:
    assert _is_displayable_plan_next_action("I'll grep the adapter next.")
    assert not _is_displayable_plan_next_action("")
    assert not _is_displayable_plan_next_action("Goal achieved successfully")


def test_is_displayable_assessment_reasoning_rejects_fresh_loop_placeholder() -> None:
    assert not _is_displayable_assessment_reasoning(
        "Fresh-loop bypass: no prior execution to assess."
    )
    assert _is_displayable_assessment_reasoning("Evidence shows two steps completed.")
