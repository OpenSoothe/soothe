"""Step success is fault-tolerant to recoverable tool errors."""

from __future__ import annotations

import pytest

from soothe.config import SootheConfig
from soothe.foundation.sloop.engine.executor import Executor
from soothe.foundation.sloop.engine.step_wave_types import step_had_tool_error
from soothe.foundation.sloop.state.schemas import LoopState, StepResult


@pytest.fixture
def executor() -> Executor:
    return Executor(object(), config=SootheConfig())


def test_step_had_tool_error_reads_outcome_flag() -> None:
    ok = StepResult(
        step_id="s1",
        success=True,
        outcome={"has_tool_error": True},
        duration_ms=1,
        thread_id="t",
    )
    clean = StepResult(
        step_id="s2",
        success=True,
        outcome={"type": "generic"},
        duration_ms=1,
        thread_id="t",
    )
    assert step_had_tool_error(ok) is True
    assert step_had_tool_error(clean) is False


def test_wave_metrics_count_tool_errors_on_successful_steps(executor: Executor) -> None:
    state = LoopState(goal="g", thread_id="t")
    step_results = [
        StepResult(
            step_id="s1",
            success=True,
            outcome={"has_tool_error": True},
            error="Error: Line offset 111 exceeds file length (111 lines)",
            duration_ms=100,
            thread_id="t",
            tool_call_count=3,
        ),
    ]

    executor._aggregate_wave_metrics(step_results, "done", [], state)

    assert state.last_wave_error_count == 1


def test_step_evidence_notes_tool_warning_when_step_succeeds() -> None:
    result = StepResult(
        step_id="PYH-01",
        success=True,
        outcome={"type": "generic", "has_tool_error": True},
        error="Error: Line offset 111 exceeds file length (111 lines)",
        duration_ms=169832,
        thread_id="t",
        tool_call_count=16,
    )

    evidence = result.to_evidence_string()

    assert "tool warning:" in evidence
    assert "Line offset 111" in evidence
