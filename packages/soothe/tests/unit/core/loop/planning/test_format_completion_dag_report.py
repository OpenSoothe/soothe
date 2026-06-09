"""Tests for PlanManager.format_completion_dag_report (goal-end DAG log text)."""

from __future__ import annotations

from soothe.foundation.loop.planning.manager import PlanManager
from soothe.foundation.loop.state.schemas import (
    AgentDecision,
    PlanResult,
    StepAction,
    StepResult,
)


def test_format_completion_dag_report_empty() -> None:
    pm = PlanManager(goal="example")
    assert pm.format_completion_dag_report() == ""


def test_format_completion_dag_report_lists_steps_and_stats() -> None:
    pm = PlanManager(goal="ship feature")
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="KFA-01", description="Design API", dependencies=None),
            StepAction(id="KFA-02", description="Implement handler", dependencies=["KFA-01"]),
        ],
        execution_mode="dependency",
    )
    pm.ingest_plan(
        PlanResult(status="done", goal_progress="complete", decision=decision),
        "KFA",
        3,
    )
    pm.record_step_outcomes(
        [
            StepResult(
                step_id="KFA-01",
                success=True,
                outcome={"type": "generic"},
                error=None,
                duration_ms=10,
                thread_id="t1",
            ),
            StepResult(
                step_id="KFA-02",
                success=True,
                outcome={"type": "generic"},
                error=None,
                duration_ms=20,
                thread_id="t1",
            ),
        ]
    )
    text = pm.format_completion_dag_report()
    assert "KFA-01" in text
    assert "KFA-02" in text
    assert "Depends on: KFA-01" in text
    assert "COMPLETED" in text
    assert "Planned steps (nodes): 2" in text
    assert "Design API" in text
