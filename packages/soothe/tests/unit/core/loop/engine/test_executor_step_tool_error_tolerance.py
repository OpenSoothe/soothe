"""Step success is fault-tolerant to recoverable tool errors."""

from __future__ import annotations

import pytest

from soothe.config import SootheConfig
from soothe.sloop.engine.executor import Executor
from soothe.sloop.engine.step_wave_types import all_tool_outcomes_failed
from soothe.sloop.state.schemas import LoopState, StepExecutionRecord


@pytest.fixture
def executor() -> Executor:
    return Executor(object(), config=SootheConfig())


def test_all_tool_outcomes_failed_requires_nonempty_outcomes() -> None:
    assert all_tool_outcomes_failed([]) is False
    assert all_tool_outcomes_failed([{"has_error": True}]) is True
    assert all_tool_outcomes_failed([{"has_error": True}, {"has_error": False}]) is False


def test_wave_metrics_ignore_recoverable_tool_errors_on_successful_steps(
    executor: Executor,
) -> None:
    state = LoopState(goal="g", thread_id="t")
    step_results = [
        StepExecutionRecord(
            step_id="s1",
            success=True,
            outcome={"type": "generic"},
            error="Error: Line offset 111 exceeds file length (111 lines)",
            duration_ms=100,
            thread_id="t",
            tool_call_count=3,
        ),
    ]

    executor._aggregate_wave_metrics(step_results, "done", [], state)

    assert state.last_wave_error_count == 0


def test_wave_metrics_count_failed_steps(executor: Executor) -> None:
    state = LoopState(goal="g", thread_id="t")
    step_results = [
        StepExecutionRecord(
            step_id="s1",
            success=False,
            error="All tool calls failed",
            duration_ms=100,
            thread_id="t",
            tool_call_count=2,
        ),
    ]

    executor._aggregate_wave_metrics(step_results, "", [], state)

    assert state.last_wave_error_count == 1


def test_step_evidence_omits_recoverable_tool_warning() -> None:
    result = StepExecutionRecord(
        step_id="PYH-01",
        success=True,
        outcome={"type": "generic"},
        error="Error: Line offset 111 exceeds file length (111 lines)",
        duration_ms=169832,
        thread_id="t",
        tool_call_count=16,
    )

    evidence = result.to_evidence_string()

    assert "tool warning:" not in evidence
    assert "Line offset 111" not in evidence
