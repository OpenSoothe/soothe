"""Tests for structural plan keep gates (IG-671)."""

from __future__ import annotations

from soothe.sloop.cognition.structural_keep import (
    KEEP_NEXT_ACTION,
    build_keep_plan_result,
    note_structural_keep,
    remaining_plan_step_count,
    reset_structural_keep_streak,
    structural_keep_block_reason,
)
from soothe.sloop.state.schemas import (
    AgentDecision,
    LoopState,
    StepAction,
    StepExecutionRecord,
)


def _state_with_remaining(*, success: bool = True, streak: int = 0) -> LoopState:
    state = LoopState(
        goal="ship feature",
        thread_id="t1",
        iteration=1,
        current_decision=AgentDecision(
            type="execute_steps",
            steps=[
                StepAction(id="01", description="First"),
                StepAction(id="02", description="Second"),
            ],
            execution_mode="parallel",
        ),
        structural_keep_streak=streak,
    )
    state.add_step_result(
        StepExecutionRecord(step_id="01", success=success, duration_ms=10, thread_id="t1")
    )
    return state


def test_structural_keep_allows_healthy_mid_loop() -> None:
    state = _state_with_remaining()
    assert structural_keep_block_reason(state, enabled=True, max_streak=3) is None


def test_structural_keep_blocks_failed_last_step() -> None:
    state = _state_with_remaining(success=False)
    assert structural_keep_block_reason(state, enabled=True, max_streak=3) == "last_step_failed"


def test_structural_keep_blocks_streak_cap() -> None:
    state = _state_with_remaining(streak=3)
    assert structural_keep_block_reason(state, enabled=True, max_streak=3) == "streak_cap:3>=3"


def test_structural_keep_blocks_iter0() -> None:
    state = _state_with_remaining()
    state.iteration = 0
    assert structural_keep_block_reason(state, enabled=True, max_streak=3) == "iter0"


def test_build_keep_plan_result() -> None:
    state = _state_with_remaining()
    result = build_keep_plan_result(state)
    assert result.plan_action == "keep"
    assert result.status == "continue"
    assert result.decision is None
    assert result.next_action == KEEP_NEXT_ACTION
    assert remaining_plan_step_count(state) == 1


def test_note_and_reset_streak() -> None:
    state = _state_with_remaining()
    assert note_structural_keep(state) == 1
    assert state.structural_keep_streak == 1
    assert note_structural_keep(state) == 2
    reset_structural_keep_streak(state)
    assert state.structural_keep_streak == 0
