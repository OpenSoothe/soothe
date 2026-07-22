"""Tests for StrangeLoop plan reason event forwarding."""

from __future__ import annotations

from soothe.sloop.utils.loop_reason_display import (
    is_displayable_assessment_reasoning,
    is_displayable_plan_reasoning,
    should_emit_loop_reason_event,
)


def test_should_emit_loop_reason_event_for_plan_generate_reasoning() -> None:
    assert should_emit_loop_reason_event(
        assessment_reasoning="",
        plan_reasoning="I'll inspect the adapter module first.",
    )


def test_should_not_emit_loop_reason_event_without_reasoning() -> None:
    """Empty assess/plan reasoning must not surface a cognition card."""
    assert not should_emit_loop_reason_event(
        assessment_reasoning="",
        plan_reasoning="",
    )


def test_should_emit_loop_reason_event_for_assessment_or_plan_reasoning() -> None:
    assert should_emit_loop_reason_event(
        assessment_reasoning="Progress is medium.",
        plan_reasoning="",
    )
    assert should_emit_loop_reason_event(
        assessment_reasoning="",
        plan_reasoning="Keep executing remaining steps.",
    )


def test_is_displayable_assessment_reasoning_rejects_fresh_loop_placeholder() -> None:
    assert not is_displayable_assessment_reasoning(
        "Fresh-loop bypass: no prior execution to assess."
    )
    assert not is_displayable_assessment_reasoning(
        "Continue keyword: resume prior loop work from ledger context."
    )
    assert is_displayable_assessment_reasoning("Evidence shows two steps completed.")


def test_is_displayable_plan_reasoning_rejects_bootstrap_placeholder() -> None:
    assert not is_displayable_plan_reasoning(
        "Single execute wave from prior loop context and current goal."
    )
    assert is_displayable_plan_reasoning("I'll inspect the adapter module first.")


def test_should_not_emit_loop_reason_event_for_continue_keyword_bootstrap() -> None:
    assert not should_emit_loop_reason_event(
        assessment_reasoning="Loop-continuation bootstrap: initial planner call skipped.",
        plan_reasoning="Single execute wave grounded on prior goal completion report.",
    )
