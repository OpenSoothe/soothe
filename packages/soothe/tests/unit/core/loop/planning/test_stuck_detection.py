"""Tests for IG-454 planner stuck-loop detection."""

from __future__ import annotations

from soothe.sloop.cognition.planner import _detect_stuck_loop
from soothe.sloop.state.schemas import LoopState, StepExecutionRecord


def test_detect_stuck_loop_repeated_actions() -> None:
    state = LoopState(goal="g", thread_id="t")
    state.action_history = ["read README.md"] * 3

    reason = _detect_stuck_loop(state)

    assert reason is not None
    assert "Repeated identical action" in reason


def test_detect_stuck_loop_consecutive_failures() -> None:
    state = LoopState(goal="g", thread_id="t")
    state._step_results_cache = [
        StepExecutionRecord(
            step_id="s1",
            success=False,
            error="Error: File not found",
            duration_ms=1,
            thread_id="t",
        ),
        StepExecutionRecord(
            step_id="s2",
            success=False,
            error="Error: Permission denied",
            duration_ms=1,
            thread_id="t",
        ),
        StepExecutionRecord(
            step_id="s3",
            success=False,
            error="Error: Timeout",
            duration_ms=1,
            thread_id="t",
        ),
    ]

    reason = _detect_stuck_loop(state)

    assert reason is not None
    assert reason.startswith("Consecutive step failures:")
    assert "File not found" in reason
